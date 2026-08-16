"""Tests for issue #318 — a migration that reverses an earlier migration must
say why in its docstring.

Background (#299): `members.federation_number` was dropped by `b2c3d4e5f6a7`
(superseded by the `member_federations` table), then silently re-added one
revision later by `c3d4e5f6a7b8` with the docstring "readd federation_number to
members" and no rationale. The column sat orphaned in the schema for roughly
three months. The ORM↔migration drift guard added in #297
(`test_migrations.py::test_migrated_schema_matches_orm_metadata_exactly`) is
what eventually caught it — but that guard only catches divergence *from the
ORM*, and only long after the fact. This test catches the reversal itself, at
review time.

These tests are pure static analysis: the revision chain is parsed with
`ast`, never imported and never executed, and no database is touched. That
keeps them in the fast tier despite living alongside the Tier 2 tests in
`test_migrations.py`.

No Playwright / `test_e2e_*` stubs accompany this issue, for the same reason
`test_migrations.py` gives: every acceptance criterion is about the contents of
migration source files. None of it is observable through a browser, and a
browser stub would fake coverage rather than provide it.
"""

import ast
import os
import re

import pytest

# ---------------------------------------------------------------------------
# Grandfathered revisions
#
# Revisions that predate this convention and cannot now be edited without
# rewriting published migration history. Each entry must explain itself. New
# reversals do NOT belong here — add the rationale to the migration's docstring
# instead. This list must only ever shrink.
# ---------------------------------------------------------------------------

GRANDFATHERED_REVISIONS: dict[str, str] = {
    # The original offender, documented in full in issue #299. Re-added
    # `members.federation_number` one revision after `b2c3d4e5f6a7`
    # deliberately dropped it in favour of the `member_federations` table,
    # with no stated reason. Dropped again by `a5b6c7d8e9f0` (#297), whose
    # docstring is the worked example of what this convention asks for.
    "c3d4e5f6a7b8": "issue #299 — predates this convention; history is published",
}


def _alembic_script_directory():
    from alembic.script import ScriptDirectory

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ScriptDirectory(os.path.join(backend_dir, "alembic"))


def _ordered_revisions():
    """Every revision from base to head, in application order.

    `walk_revisions()` yields head-first; the chain is meaningful only when
    read the way it is applied, so it is reversed here.
    """
    script = _alembic_script_directory()
    return list(reversed(list(script.walk_revisions())))


# ---------------------------------------------------------------------------
# Static extraction of schema operations from a migration's upgrade()
# ---------------------------------------------------------------------------

# Alembic operation name -> (action, object kind). Only operations that create
# or destroy a schema object can constitute a reversal; `alter_column` and
# friends change one in place and are deliberately out of scope (see #318).
_OPERATIONS = {
    "add_column": ("add", "column"),
    "drop_column": ("drop", "column"),
    "create_table": ("add", "table"),
    "drop_table": ("drop", "table"),
    "create_index": ("add", "index"),
    "drop_index": ("drop", "index"),
    "create_unique_constraint": ("add", "constraint"),
    "create_foreign_key": ("add", "constraint"),
    "create_check_constraint": ("add", "constraint"),
    "drop_constraint": ("drop", "constraint"),
}


# Migrations do not always go through the `op.*` helpers: `b2c3d4e5f6a7` drops
# `members.federation_number` with raw SQL via `op.execute`, and that is the
# very drop the #299 defect reversed. A detector that only understood the
# helpers would be blind to the reference case, so literal SQL passed to
# `op.execute` is scanned too. Identifiers may be bare or double-quoted.
_IDENT = r'"?([A-Za-z_][A-Za-z0-9_]*)"?'
_SQL_PATTERNS = [
    (
        re.compile(
            rf"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?{_IDENT}\s+DROP\s+COLUMN"
            rf"\s+(?:IF\s+EXISTS\s+)?{_IDENT}",
            re.IGNORECASE,
        ),
        "drop",
        "column",
    ),
    (
        re.compile(
            rf"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?{_IDENT}\s+ADD\s+COLUMN"
            rf"\s+(?:IF\s+NOT\s+EXISTS\s+)?{_IDENT}",
            re.IGNORECASE,
        ),
        "add",
        "column",
    ),
    (
        re.compile(rf"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?{_IDENT}", re.IGNORECASE),
        "drop",
        "table",
    ),
    (
        re.compile(
            rf"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?{_IDENT}", re.IGNORECASE
        ),
        "add",
        "table",
    ),
]


def _sql_operations(sql: str) -> list[tuple[str, tuple[str, ...]]]:
    """Schema operations expressed as raw SQL inside `op.execute`."""
    operations = []
    for pattern, action, kind in _SQL_PATTERNS:
        for match in pattern.finditer(sql):
            if kind == "column":
                operations.append((action, ("column", match.group(1), match.group(2))))
            else:
                operations.append((action, ("table", match.group(1))))
    return operations


def _string_literal(node) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _column_name_from_arg(node) -> str | None:
    """Extract the column name from an `op.add_column` column argument.

    Accepts either a bare string or a `sa.Column("name", ...)` call, whose
    first positional argument is the name.
    """
    literal = _string_literal(node)
    if literal is not None:
        return literal
    if isinstance(node, ast.Call) and node.args:
        return _string_literal(node.args[0])
    return None


def _function_def(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _schema_operations(source: str) -> list[tuple[str, tuple[str, ...]]]:
    """Return the schema operations performed by `upgrade()`, in source order.

    Each entry is `(action, object_key)` where `action` is "add" or "drop" and
    `object_key` identifies the schema object, e.g.
    `("column", "members", "federation_number")` or `("table", "federations")`.

    `downgrade()` is ignored: a downgrade is expected to reverse its own
    upgrade, which is the whole point of it.
    """
    tree = ast.parse(source)
    upgrade = _function_def(tree, "upgrade")
    if upgrade is None:
        return []

    operations: list[tuple[str, tuple[str, ...]]] = []

    def visit(node, batch_table: str | None) -> None:
        # `with op.batch_alter_table("members") as batch_op:` binds a table for
        # everything in its body, where calls omit the table name.
        if isinstance(node, ast.With):
            table = batch_table
            for item in node.items:
                call = item.context_expr
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "batch_alter_table"
                    and call.args
                ):
                    table = _string_literal(call.args[0]) or table
            for child in node.body:
                visit(child, table)
            return

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "execute" and node.args:
                sql = _string_literal(node.args[0])
                if sql:
                    operations.extend(_sql_operations(sql))

            entry = _OPERATIONS.get(node.func.attr)
            if entry is not None:
                action, kind = entry
                key = _object_key(node, kind, batch_table)
                if key is not None:
                    operations.append((action, key))

        for child in ast.iter_child_nodes(node):
            visit(child, batch_table)

    def _object_key(node: ast.Call, kind: str, batch_table: str | None):
        args = node.args
        if kind == "column":
            if batch_table is not None:
                name = _column_name_from_arg(args[0]) if args else None
                table = batch_table
            else:
                table = _string_literal(args[0]) if args else None
                name = _column_name_from_arg(args[1]) if len(args) > 1 else None
            if table is None or name is None:
                return None
            return ("column", table, name)

        if kind == "table":
            name = _string_literal(args[0]) if args else None
            return ("table", name) if name else None

        # Indexes and constraints are named first, then their table.
        name = _string_literal(args[0]) if args else None
        if name is None:
            return None
        table = batch_table
        if table is None and len(args) > 1:
            table = _string_literal(args[1])
        return (kind, table or "?", name)

    for statement in upgrade.body:
        visit(statement, None)

    return operations


# ---------------------------------------------------------------------------
# Reversal detection
# ---------------------------------------------------------------------------

_OPPOSITE = {"add": "drop", "drop": "add"}


def _find_reversals():
    """Walk the chain in application order, returning every reversal found.

    A revision reverses an earlier one when it adds a schema object a prior
    revision dropped, or drops one a prior revision added.

    Each result is `(revision, object_key, prior_revision, action)`.
    """
    last_action: dict[tuple[str, ...], tuple[str, str]] = {}
    reversals = []

    for script in _ordered_revisions():
        with open(script.path, encoding="utf-8") as handle:
            source = handle.read()

        for action, key in _schema_operations(source):
            previous = last_action.get(key)
            if previous is not None:
                prior_action, prior_revision = previous
                if prior_action == _OPPOSITE[action]:
                    reversals.append((script.revision, key, prior_revision, action))
            last_action[key] = (action, script.revision)

    return reversals


# ---------------------------------------------------------------------------
# Docstring rationale
# ---------------------------------------------------------------------------

_HEADER_FIELD = re.compile(r"^(Revision ID|Revises|Create Date)\s*:", re.IGNORECASE)

# Prose shorter than this is not an explanation. Chosen to reject placeholders
# ("n/a", "see PR", "fixes bug") while accepting any real sentence.
_MIN_RATIONALE_CHARS = 30

# The prompt `script.py.mako` seeds new migrations with. Left unedited it is
# long enough to clear the length bar while explaining nothing, so it is
# rejected explicitly — otherwise the template would defeat the check it exists
# to support.
_TEMPLATE_PLACEHOLDER = "say why here: what changed, and what supersedes"


def _is_unedited_template_prompt(rationale: str) -> bool:
    return _TEMPLATE_PLACEHOLDER in rationale


def _rationale(source: str) -> str:
    """The docstring prose beyond the generated header block.

    The generated header is the summary line, the `Revision ID:` / `Revises:` /
    `Create Date:` fields, and blank lines. Anything else an author has written
    is the rationale.
    """
    docstring = ast.get_docstring(ast.parse(source)) or ""
    lines = docstring.splitlines()
    body = lines[1:] if lines else []  # drop the summary line
    prose = [
        line.strip()
        for line in body
        if line.strip() and not _HEADER_FIELD.match(line.strip())
    ]
    return " ".join(prose)


def _describe(key: tuple[str, ...]) -> str:
    if key[0] == "column":
        return f"column {key[1]}.{key[2]}"
    if key[0] == "table":
        return f"table {key[1]}"
    return f"{key[0]} {key[2]} on {key[1]}"


# ---------------------------------------------------------------------------
# AC1/AC2 — the chain is walked statically and reversals are identified.
# ---------------------------------------------------------------------------


def test_revision_chain_is_walkable_and_yields_schema_operations():
    """Guards the detector itself: if parsing silently broke, every other test
    here would vacuously pass."""
    revisions = _ordered_revisions()
    assert len(revisions) > 1, "expected a multi-revision chain to analyse"

    total_operations = 0
    for script in revisions:
        with open(script.path, encoding="utf-8") as handle:
            total_operations += len(_schema_operations(handle.read()))

    assert total_operations > 0, (
        "parsed no schema operations from any migration — the AST extraction "
        "has broken, and the reversal check below is not actually checking "
        "anything"
    )


def test_known_federation_number_reversal_is_detected():
    """The #299 defect is the reference case: `c3d4e5f6a7b8` re-added a column
    `b2c3d4e5f6a7` had dropped. If the detector cannot see that, it cannot see
    the next one either."""
    reversals = _find_reversals()

    matching = [
        (revision, prior)
        for revision, key, prior, _action in reversals
        if key == ("column", "members", "federation_number")
    ]

    assert ("c3d4e5f6a7b8", "b2c3d4e5f6a7") in matching, (
        "expected to detect c3d4e5f6a7b8 re-adding members.federation_number "
        f"after b2c3d4e5f6a7 dropped it; detected reversals of that column: "
        f"{matching!r}"
    )


# ---------------------------------------------------------------------------
# AC3/AC4/AC5 — every reversal must carry a rationale, with a named failure.
# ---------------------------------------------------------------------------


def test_every_reversing_migration_states_its_rationale():
    failures = []

    for revision, key, prior_revision, action in _find_reversals():
        if revision in GRANDFATHERED_REVISIONS:
            continue

        script = next(s for s in _ordered_revisions() if s.revision == revision)
        with open(script.path, encoding="utf-8") as handle:
            rationale = _rationale(handle.read())

        if len(rationale) < _MIN_RATIONALE_CHARS or _is_unedited_template_prompt(
            rationale
        ):
            verb = "re-adds" if action == "add" else "drops"
            detail = (
                "still carries the unedited prompt from script.py.mako"
                if _is_unedited_template_prompt(rationale)
                else "gives no rationale"
            )
            failures.append(
                f"  {revision} ({os.path.basename(script.path)}) {verb} "
                f"{_describe(key)}, reversing {prior_revision}, but its "
                f"docstring {detail}. Explain in the docstring why "
                f"the decision made in {prior_revision} is being reversed: "
                f"what changed, and what supersedes it."
            )

    assert not failures, (
        "migrations that reverse an earlier migration must justify themselves "
        "in their module docstring (issue #318):\n" + "\n".join(failures)
    )


def test_template_prompt_is_rejected_until_the_author_replaces_it():
    """AC6's prompt must not become a way to pass AC3 without writing anything.

    Reads the real template so the two cannot drift apart: if the wording in
    `script.py.mako` is reworded, this fails until `_TEMPLATE_PLACEHOLDER`
    is updated to match.
    """
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_path = os.path.join(backend_dir, "alembic", "script.py.mako")
    with open(template_path, encoding="utf-8") as handle:
        template = handle.read()

    assert _TEMPLATE_PLACEHOLDER in template, (
        "script.py.mako no longer contains the rationale prompt this test "
        "keys on — update _TEMPLATE_PLACEHOLDER to match the new wording"
    )

    # A migration generated from the template and never edited: long enough to
    # clear the length bar, but explaining nothing.
    generated = (
        '"""drop something\n\n'
        "Revision ID: aaaaaaaaaaaa\n"
        "Revises: bbbbbbbbbbbb\n"
        "Create Date: 2026-08-16\n\n"
        "Rationale: if this migration reverses an earlier one — adding back "
        "something a previous revision dropped, or dropping something a "
        "previous revision added — say why here: what changed, and what "
        "supersedes the earlier decision.\n"
        '"""\n'
    )
    rationale = _rationale(generated)

    assert len(rationale) >= _MIN_RATIONALE_CHARS, (
        "precondition: the unedited prompt is long enough to pass the length "
        "check, which is exactly why it needs rejecting separately"
    )
    assert _is_unedited_template_prompt(rationale)


@pytest.mark.parametrize("revision", sorted(GRANDFATHERED_REVISIONS))
def test_grandfathered_revisions_are_still_real_reversals(revision: str):
    """Stops the exemption list rotting into a place where revisions are parked.

    If a grandfathered revision no longer reads as a reversal — because the
    chain changed, or the detector did — its entry is dead and must be removed
    rather than left to silently exempt a revision id that may be reused in a
    future rebase.
    """
    reversing = {rev for rev, _key, _prior, _action in _find_reversals()}
    assert revision in reversing, (
        f"{revision} is grandfathered in GRANDFATHERED_REVISIONS but is no "
        f"longer detected as a reversal — remove its entry"
    )


def test_reference_migration_satisfies_the_rationale_requirement():
    """`a5b6c7d8e9f0` (#297) is cited in issue #318 as the worked example of a
    reversal that explains itself. It must keep passing on its own merits, not
    by exemption."""
    assert "a5b6c7d8e9f0" not in GRANDFATHERED_REVISIONS

    script = next(s for s in _ordered_revisions() if s.revision == "a5b6c7d8e9f0")
    with open(script.path, encoding="utf-8") as handle:
        rationale = _rationale(handle.read())

    assert len(rationale) >= _MIN_RATIONALE_CHARS, (
        "a5b6c7d8e9f0 is the reference example of a documented reversal but "
        f"its docstring rationale did not survive extraction: {rationale!r}"
    )
