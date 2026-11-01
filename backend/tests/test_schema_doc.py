"""docs/schema.md matches the ORM.

The doc says it is re-derived from ``Base.metadata``, but nothing held it to
that: dropping ``accounts.is_active`` (#484) left the column in the ER diagram
until review caught it. This compares every table and column name in the
``erDiagram`` block with the models. Types, keys and relationships are not
checked; names are what drift.
"""

import os
import re
from pathlib import Path

import app.main  # noqa: F401 - imports every model module
from app.db.base import Base

ROOT = (
    Path(os.environ["REPO_ROOT"])
    if "REPO_ROOT" in os.environ
    else Path(__file__).parent.parent.parent
)
SCHEMA_DOC = ROOT / "docs" / "schema.md"


def _documented_tables() -> dict[str, set[str]]:
    """Each ``name { type column ... }`` block of the erDiagram."""
    text = SCHEMA_DOC.read_text()
    [diagram] = re.findall(r"```mermaid\nerDiagram\n(.*?)```", text, re.DOTALL)
    return {
        table: {line.split()[1] for line in body.strip().splitlines()}
        for table, body in re.findall(
            r"^\s*(\w+) \{\n(.*?)^\s*\}", diagram, re.M | re.S
        )
    }


def test_schema_doc_lists_every_table_and_column_of_the_models():
    models = {
        name: {column.name for column in table.columns}
        for name, table in Base.metadata.tables.items()
    }
    documented = _documented_tables()

    assert sorted(documented) == sorted(
        models
    ), "docs/schema.md tables differ from Base.metadata; re-derive the doc"
    drift = {
        table: {
            "missing from doc": sorted(models[table] - columns),
            "not in models": sorted(columns - models[table]),
        }
        for table, columns in documented.items()
        if columns != models[table]
    }
    assert not drift, f"docs/schema.md columns differ from Base.metadata: {drift}"
