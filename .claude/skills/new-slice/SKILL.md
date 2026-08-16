---
name: new-slice
description: Scaffolds a complete vertical slice for a new domain concept in KendoDojoManagement, following the UoW + repository pattern. Use when adding a new domain module (e.g. "member", "session", "attendance"), implementing a new GitHub issue, or when the user says "new slice", "add a module", or "scaffold".
---

# New Slice

Scaffolds a full vertical slice for a domain concept: SQLAlchemy model, abstract + concrete repository, FastAPI router, dependency wiring, and stub-based tests — all following the established patterns in this codebase.

## Workflow

### 1. Read the codebase patterns

Before generating anything, read:
- `backend/app/db/base.py` — UUIDBase model
- `backend/app/grades/repository.py` — per-concept `Abstract{Concept}Repository(ABC)` + SQL implementation
- `backend/app/db/unit_of_work.py` — AbstractUnitOfWork / SQLAlchemyUnitOfWork
- `backend/app/dependencies.py` — get_uow pattern
- `backend/app/routers/health.py` — router pattern
- `backend/app/main.py` — how routers are registered

Also check `backend/app/` for existing domain modules to follow the same structure.

### 2. Interview the user

Ask these questions **one at a time**. Stop when you have enough to generate all files.

1. **Fields** — what columns does the model need? (name, type, nullable, default, FK?)
2. **Relationships** — does it belong to / have many of another model?
3. **Query methods** — beyond `get(id)` and `add()`, what does the repository need? (e.g. `list_by_status`, `get_by_email`)
4. **Write operations** — are any writes multi-table? (grade promotion touches member + grade_history → use UoW)
5. **Endpoints** — which HTTP verbs and paths? (default: GET list, GET by id, POST create, PUT update, DELETE/deactivate)
6. **Auth** — which endpoints are admin-only vs member-accessible?

Skip questions answerable from the GitHub issue or PRD context already in the conversation.

### 3. Generate files

Generate all files in this order. Use `backend/app/{concept}/` as the module directory.

```
backend/app/{concept}/
  __init__.py
  models.py        # SQLAlchemy model(s) extending UUIDBase
  repository.py    # Abstract{Concept}Repository + Sql{Concept}Repository
  schemas.py       # Pydantic request/response models
  dependencies.py  # get_{concept}_repo() FastAPI dependency
  router.py        # APIRouter with endpoints
backend/tests/
  test_{concept}.py  # stub-based tests, no DB
```

Then register the router in `backend/app/main.py`.

See [PATTERNS.md](PATTERNS.md) for exact code templates.

### 4. Verify

Run from `backend/`:
```bash
.venv/bin/ruff check . --fix
.venv/bin/pytest tests/test_{concept}.py -q
```

Both must pass before finishing.

## Rules

- **UUID PKs always** — every model extends `UUIDBase`, never uses `Integer` PK
- **No session in routers** — routers import repository deps, never `AsyncSession` directly
- **UoW for multi-table writes** — if a route touches 2+ tables, inject `get_uow` and share `uow.session` across repos
- **Stub tests, no DB** — tests use `StubRepository`, override `app.dependency_overrides`, never create an engine
- **Python 3.13** — use `X | None` not `Optional[X]`, `list[X]` not `List[X]`, `str` UUIDs
- **Kendo domain language** — use terms from `UBIQUITOUS_LANGUAGE.md` (Member, Session, Attendance, Grade, Promotion, Check-in, etc.)
