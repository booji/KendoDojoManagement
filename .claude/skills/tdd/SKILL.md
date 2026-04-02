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
