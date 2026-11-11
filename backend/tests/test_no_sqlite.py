"""
Repo-hygiene test for Issue #269 — SQLite must be fully removed.

The project has moved to PostgreSQL everywhere (prod, dev, test, CLI). No
SQLite code path, driver dependency, or documentation claim may remain
anywhere in the repository, EXCEPT inside historical Alembic migrations
(`backend/alembic/versions/*`), which are an immutable record of past schema
changes and are excluded by design — rewriting them would falsify history
for no benefit.

It guards against the removal silently regressing: a reintroduced
`sqlite+aiosqlite://` URL, a resurrected connect_args branch, or a doc that
starts claiming SQLite is the dev database again all fail here.
"""

import os
from pathlib import Path

_SEARCH_EXTENSIONS = (".py", ".txt", ".md", ".yml", ".yaml")

# Case-insensitive; matches "sqlite", "aiosqlite", "SQLite", etc.
_PATTERN = "sqlite"

# Paths (relative to repo root) excluded from the scan:
#   - backend/alembic/versions/  : historical migrations, immutable by design
#   - this file itself           : it necessarily contains the word "sqlite"
#     in its own docstring/comments/pattern definition above
_EXCLUDED_DIR_PARTS = ("alembic", "versions")
_THIS_FILE_NAME = "test_no_sqlite.py"


def _find_repo_root() -> Path:
    """Locate the repository root robustly across both run contexts.

    In the Docker test container (docker-compose.test.yml), only
    `backend/` is mounted at `/app` — the full repo tree (needed to see
    top-level files like CLAUDE.md, docker-compose.yml, .env.example) is
    mounted separately at `/repo`, with that path handed to the test via the
    `REPO_ROOT` env var (same convention as tests/test_docker_config.py).
    On a host checkout, no such mount split exists, so fall back to walking
    up from this file until a directory containing both `backend/` and
    `.git` is found.
    """
    if "REPO_ROOT" in os.environ:
        return Path(os.environ["REPO_ROOT"])

    current = Path(__file__).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "backend").is_dir() and (candidate / ".git").exists():
            return candidate
    raise RuntimeError(
        "test_no_sqlite.py could not locate the repository root by walking "
        f"up from {current}; expected an ancestor directory containing both "
        "'backend/' and '.git', or a REPO_ROOT env var."
    )


def _is_excluded(path: Path, repo_root: Path) -> bool:
    if path.name == _THIS_FILE_NAME:
        return True
    rel_parts = path.relative_to(repo_root).parts
    # Excluded if the path passes through .../alembic/versions/... anywhere.
    return any(
        rel_parts[i] == _EXCLUDED_DIR_PARTS[0]
        and i + 1 < len(rel_parts)
        and rel_parts[i + 1] == _EXCLUDED_DIR_PARTS[1]
        for i in range(len(rel_parts))
    )


def _iter_candidate_files(repo_root: Path):
    for ext in _SEARCH_EXTENSIONS:
        yield from repo_root.rglob(f"*{ext}")


def _matching_files(repo_root: Path) -> list[str]:
    offenders: list[str] = []
    for path in _iter_candidate_files(repo_root):
        if not path.is_file():
            continue
        # Skip common noise directories that are irrelevant to the source
        # tree and can be huge (node_modules, venvs, git internals, caches).
        parts = path.parts
        if any(
            noisy in parts
            for noisy in (
                "node_modules",
                ".git",
                # Agent worktrees are throwaway checkouts of other branches
                # living inside the repo; their contents are not this
                # codebase and must not be scanned.
                "worktrees",
                # graphify's knowledge-graph output: an untracked local
                # artefact whose reports quote the codebase's history.
                "graphify-out",
                ".venv",
                "venv",
                "__pycache__",
                ".pytest_cache",
                "dist",
                "build",
            )
        ):
            continue
        if _is_excluded(path, repo_root):
            continue
        try:
            content = path.read_text(errors="ignore")
        except OSError:
            continue
        if _PATTERN in content.lower():
            offenders.append(str(path.relative_to(repo_root)))
    return sorted(offenders)


def test_no_sqlite_references_outside_historical_migrations() -> None:
    repo_root = _find_repo_root()
    offenders = _matching_files(repo_root)

    assert not offenders, (
        "SQLite must be fully removed from the codebase (Issue #269). Found "
        f"{len(offenders)} file(s) still referencing 'sqlite' outside "
        "backend/alembic/versions/ (historical migrations are excluded by "
        "design):\n" + "\n".join(f"  - {f}" for f in offenders)
    )
