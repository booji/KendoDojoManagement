---
name: backend
description: FastAPI/Python backend specialist for KendoDojoManagement. Knows the full stack (Python 3.13, FastAPI, SQLAlchemy 2.0 async, Alembic, passlib[bcrypt], python-jose, webauthn), UoW + AbstractRepository pattern, async session rules, and ruff/pytest quality gates. Use when working on any backend Python file, adding routes, models, repositories, auth, migrations, or writing backend tests.
---

# Backend

## Stack
- Python 3.13, FastAPI, SQLAlchemy 2.0 async, Alembic
- Auth: `passlib[bcrypt]`, `python-jose`, `webauthn`
- DB drivers: `aiosqlite` (dev), `asyncpg` (prod), switched via `DATABASE_URL`

## Core pattern
- Every model extends `UUIDBase` — UUID primary keys, never integers
- One `Abstract{Concept}Repository` + `Sql{Concept}Repository` per domain aggregate
- `SQLAlchemyUnitOfWork` owns the `AsyncSession`; repos share `uow.session`
- Single-table writes: inject a typed repo via `Depends`
- Multi-table writes: inject `get_uow`, share session across repos, one `await uow.commit()`
- Routers never import `AsyncSession` directly

## Workflow

1. **Read first.** Load relevant source + test files before any change.
2. **Red-green TDD.** One failing test → minimum implementation → pass → refactor.
3. After changes run both — both must pass:
   ```
   .venv/bin/ruff check . --fix
   .venv/bin/pytest -q
   ```
4. Register new routers in `app/main.py`.
5. When a model changes, remind the user to create an Alembic migration:
   ```
   .venv/bin/alembic revision --autogenerate -m "<message>"
   .venv/bin/alembic upgrade head
   ```

## Python style
- `X | None` not `Optional[X]` — `list[X]` not `List[X]`
- Ruff target `py313`, line-length `88`
- All async: `async def`, `await`, `AsyncSession` — no sync SQLAlchemy calls
