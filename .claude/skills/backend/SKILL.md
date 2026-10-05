---
name: backend
description: FastAPI/Python backend specialist for KendoDojoManagement. Knows the full stack (Python 3.13, FastAPI, SQLAlchemy 2.0 async, Alembic, bcrypt, webauthn), UoW + per-concept repository ABC pattern, async session rules, and ruff/pytest quality gates. Use when working on any backend Python file, adding routes, models, repositories, auth, migrations, or writing backend tests.
---

# Backend

## Stack
- Python 3.13, FastAPI, SQLAlchemy 2.0 async, Alembic
- Auth: `webauthn` (passkeys — the only login path), Auth Sessions and recovery tokens as opaque server-side rows (ADR-0008) — no JWTs, `bcrypt` (recovery codes and admin recovery tokens). There is no password login (#155)
- DB driver: `asyncpg` (PostgreSQL everywhere — dev, test, prod), via `DATABASE_URL`

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
   # Lint on the host, from backend/
   .venv/bin/ruff check . --fix

   # Tests in a container, from the repo root. Podman is the supported
   # runtime (`docker compose` works only with the podman-docker shim). Bare
   # pytest on the host raises a RuntimeError in conftest.py, which requires
   # a PostgreSQL DATABASE_URL.
   podman-compose -f docker-compose.test.yml run --rm test
   ```
   Scope a run with `-e PYTEST_TARGET=tests/test_foo.py`, and pass pytest
   flags with `-e PYTEST_ARGS=-x` — trailing arguments after the service name
   are the container command under podman-compose, not pytest flags. Never
   start uvicorn or Vite yourself — the container entrypoint does it.
4. Register new routers in `app/main.py`.
5. When a model changes, remind the user to create an Alembic migration:
   ```
   .venv/bin/alembic revision --autogenerate -m "<message>"
   .venv/bin/alembic upgrade head
   ```

## Functional programming style
- **Business logic lives in pure functions** — plain module-level functions, no side effects, no I/O
- **Side effects at the edges only** — routers call pure functions, then write results via repos; pure functions never touch the DB or HTTP
- **No classes except where the framework requires it** — SQLAlchemy models, `Abstract*Repository`, `Sql*Repository`, and `SQLAlchemyUnitOfWork` are the only permitted classes
- **Immutable data in, immutable data out** — transform Pydantic models into new Pydantic models; never mutate an input argument
- **No shared mutable state** — no module-level variables that change at runtime; configuration via dependency injection

```python
# Good — pure function, testable without DB
def compute_membership_expiry(enrolled_on: date, months: int) -> date:
    return enrolled_on + relativedelta(months=months)

# Bad — business logic inside a route or repo method
async def create_member(data: MemberCreate, repo: MemberRepo) -> Member:
    data.expiry = data.enrolled_on + relativedelta(months=12)  # logic buried in I/O layer
    return await repo.add(data)
```

## Python style
- `X | None` not `Optional[X]` — `list[X]` not `List[X]`
- Ruff target `py313`, line-length `88`
- All async: `async def`, `await`, `AsyncSession` — no sync SQLAlchemy calls
