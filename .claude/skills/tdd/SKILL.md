---
name: tdd
description: TDD and QA enforcer for KendoDojoManagement. Ensures red-green-refactor vertical slices, stub-based backend tests with no DB, and clean test hygiene. Use when writing tests, reviewing test quality, checking coverage gaps, or when the user mentions "write a test", "check tests", or "QA".
---

# TDD / QA

## The workflow
1. **Red** — write one failing test for the next small behaviour. Confirm it fails.
2. **Green** — write the minimum implementation to make it pass.
3. **Refactor** — clean up, then move to the next behaviour.

Never write a full test suite before implementing. Never implement without a test first.

## Two test modes

The project has **two distinct backend test tiers**. Use the right tier for the right job.

### Tier 1 — Unit tests (stub-based, no DB)

- Framework: `pytest` + `anyio` (`@pytest.mark.anyio`)
- **No DB** — use `StubRepository` (plain Python class, no engine)
- Override deps via `app.dependency_overrides[get_x_repo] = lambda: stub`
- Always add an `autouse=True` fixture that calls `app.dependency_overrides.clear()`
- Test files: `backend/tests/test_{concept}.py`

This is the default tier. Write unit tests here for all new routes and domain logic.

> **All pytest runs — including Tier 1 — must run inside the test container.** `conftest.py` raises `RuntimeError` on startup if `DATABASE_URL` is not a PostgreSQL URL, so `pytest` on the host will always fail.

### Tier 2 — PostgreSQL integration tests (container-backed)

Use these when the test **must verify real SQL behaviour** — constraint enforcement, savepoint rollback, migration correctness, query semantics.

**Fixtures (defined in `conftest.py`):**

| Fixture | Scope | What it provides |
|---------|-------|-----------------|
| `pg_engine` | session | `AsyncEngine` pointing at `DATABASE_URL` (PostgreSQL, required — no fallback) |
| `db_session` | function | `AsyncSession` wrapped in a savepoint; rolled back after each test for isolation |

`DATABASE_URL` is injected by the test container via `.env.test`:
```
DATABASE_URL=postgresql+asyncpg://kendo_test:kendo_test_password@db:5432/kendo_test
```

**Running the container stack:**
```bash
# One-shot: runs all tests (unit + integration + e2e) then exits
podman-compose -f docker-compose.test.yml run --rm test

# Scope it, or pass pytest flags (trailing args after the service name are the
# container command under podman-compose, so flags must go through PYTEST_ARGS)
podman-compose -f docker-compose.test.yml run --rm \
  -e PYTEST_TARGET=tests/test_foo.py -e PYTEST_ARGS=-x test

# Drop the stack when done
podman-compose -f docker-compose.test.yml down
```

The test container (`backend-e2e-deps` stage) includes Python, Node 22, and Playwright/Chromium. `run_tests.sh` starts uvicorn on `:8000` and Vite on `:5173`, waits for both, then runs `pytest tests/ -x -q`. The `db` service is ephemeral — destroyed on `down`.

**Writing a container-backed test:**
```python
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.mark.anyio
async def test_member_persists(db_session: AsyncSession) -> None:
    await db_session.execute(
        text("INSERT INTO members (id, email) VALUES (:id, :email)"),
        {"id": "uuid-1", "email": "a@b.com"},
    )
    result = await db_session.execute(
        text("SELECT email FROM members WHERE id = :id"), {"id": "uuid-1"}
    )
    assert result.scalar() == "a@b.com"
```

**Tier 2 guard — only use `db_session` / `pg_engine` when:**
- Testing a repository implementation against real SQL
- Verifying DB constraints (unique, FK, not-null)
- Testing migration correctness
- Anything where a stub's looser semantics would mask a real-SQL bug

Do **not** use `db_session` for route-level tests — those belong in Tier 1 with stubs.

## What to test
- Observable HTTP behaviour: status codes, response body shape, error messages
- State changes visible through the public interface
- Edge cases: not-found (404), duplicate (409), invalid input (422)

## Anti-patterns — flag and fix these
- Mocking internal methods (`MagicMock`, `patch` on private methods)
- Asserting on private state (reading `._session`, `._items` in tests)
- Tests that only pass because the stub returns a hardcoded value without exercising route logic
- Missing `autouse` cleanup — causes test-order pollution
- Using `db_session` in route tests (use a stub instead; the container is for repository/SQL tests)

## Coverage gaps to check
After any new route or repository method, verify tests exist for:
- Happy path (2xx)
- Not found (404) if applicable
- Validation error (422) for required fields
- Unauthorised (401) if the endpoint is protected
- For new repository implementations: at least one Tier 2 test verifying real SQL behaviour

## Playwright browser tests

### Setup
Playwright is included in `requirements-dev.txt` and installed with browsers in the `backend-e2e-deps` image stage — no local setup required.

Tests live in `backend/tests/test_e2e_*.py`. They run automatically as part of `podman-compose -f docker-compose.test.yml run --rm test` — `run_tests.sh` starts uvicorn and Vite before invoking pytest.

### Fixtures
```python
# conftest.py additions
import pytest
from playwright.sync_api import Page, expect

BASE_URL = "http://localhost:5173"  # Vite dev server

@pytest.fixture(scope="session")
def base_url():
    return BASE_URL
```

### Writing browser tests
```python
def test_member_list_renders(page: Page):
    page.goto(f"{BASE_URL}/members")
    expect(page.get_by_role("heading", name="Members")).to_be_visible()

def test_check_in_button_visible_on_mobile(page: Page):
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto(BASE_URL)
    expect(page.get_by_role("button", name="Check In")).to_be_visible()
```

### xfail lifecycle — critical

`xfail(strict=True)` is a **temporary red-phase marker only**. It must be removed and replaced with real assertions once implementation is done.

| Phase | What to do |
|-------|-----------|
| Red (TDD agent) | Write stub with `@pytest.mark.xfail(strict=True, reason="not implemented")` and a `pytest.fail("not implemented")` body |
| Green (after implementation) | Remove `xfail`, replace body with real Playwright assertions against the live UI |
| QA agent | Any test still carrying `xfail` is **not done** — promote it or escalate |

A stub that stays `xfail` forever provides zero protection. The point of the stub is to reserve the test slot; the QA agent's job is to fill it with real assertions.

**Red phase stub:**
```python
@pytest.mark.xfail(strict=True, reason="not implemented")
def test_user_can_register(page: Page) -> None:
    pytest.fail("not implemented")
```

**Promoted real test (QA phase):**
```python
def test_user_can_register(page: Page) -> None:
    page.goto("http://localhost:5173/register")
    page.get_by_label("Email").fill("newuser@example.com")
    page.get_by_label("Password").fill("Str0ng!Pass")
    page.get_by_label("Confirm password").fill("Str0ng!Pass")
    page.get_by_role("button", name="Register").click()
    expect(page).to_have_url("http://localhost:5173/login")
```

### Rules
- Browser tests assert **observable UI behaviour** — visible text, button states, navigation — not implementation details
- One browser test per acceptance criterion from the issue; do not write exhaustive UI tests
- Run via: `podman-compose -f docker-compose.test.yml run --rm test` (includes e2e automatically)
- Never leave `xfail` stubs in place after implementation — promote or escalate
