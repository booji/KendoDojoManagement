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

## Backend test rules
- Framework: `pytest` + `anyio` (`@pytest.mark.anyio`)
- **No DB in tests** — use `StubRepository` (plain Python class, no engine)
- Override deps via `app.dependency_overrides[get_x_repo] = lambda: stub`
- Always add an `autouse=True` fixture that calls `app.dependency_overrides.clear()`
- Test files: `backend/tests/test_{concept}.py`
- Run: `.venv/bin/pytest -q` from `backend/`

## What to test
- Observable HTTP behaviour: status codes, response body shape, error messages
- State changes visible through the public interface
- Edge cases: not-found (404), duplicate (409), invalid input (422)

## Anti-patterns — flag and fix these
- Mocking internal methods (`MagicMock`, `patch` on private methods)
- Asserting on private state (reading `._session`, `._items` in tests)
- Tests that only pass because the stub returns a hardcoded value without exercising route logic
- Missing `autouse` cleanup — causes test-order pollution

## Coverage gaps to check
After any new route or repository method, verify tests exist for:
- Happy path (2xx)
- Not found (404) if applicable
- Validation error (422) for required fields
- Unauthorised (401) if the endpoint is protected

## Playwright browser tests

### Setup
All commands run from `backend/` with the venv active:
```bash
cd backend
. .venv/bin/activate
pip install pytest-playwright
playwright install chromium
```

Tests live in `backend/tests/test_e2e_*.py`. They require both servers running — the orchestrator starts them before invoking the QA agent.

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
- Run with: `. .venv/bin/activate && pytest backend/tests/test_e2e_*.py --headed=false -q` from `backend/`
- Never leave `xfail` stubs in place after implementation — promote or escalate
