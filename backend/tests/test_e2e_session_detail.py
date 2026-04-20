"""
E2E browser tests for issue #54 — Session detail page (/sessions/:id).

Acceptance criteria covered:
  AC9  — Admin navigates to /sessions/:id and sees coach_notes;
          member sees the same page without coach_notes.
  AC10 — Member checks in from the session detail page.

All tests are xfail(strict=True) — red phase stubs only.
Remove xfail and add real Playwright assertions once the page is implemented.
"""

import os
import uuid

import pytest
from dotenv import load_dotenv
from playwright.sync_api import Page

# Load the real JWT_SECRET from .env so tokens pass server-side validation.
_dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=_dotenv_path, override=True)
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production")

from app import config as _config  # noqa: E402
from app.auth.models import UserClaims  # noqa: E402
from app.auth.token import encode_token  # noqa: E402

_config.JWT_SECRET = os.environ["JWT_SECRET"]

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# Auth helpers (same pattern as test_e2e_sessions.py)
# ---------------------------------------------------------------------------


def _make_token(role: str) -> str:
    claims = UserClaims(
        sub=str(uuid.uuid4()),
        email=f"{role}@dojo.test",
        role=role,  # type: ignore[arg-type]
        is_active=True,
    )
    return encode_token(claims)


def _set_cookie(page: Page, token: str) -> None:
    page.goto(BASE_URL)
    page.context.add_cookies(
        [{"name": "access_token", "value": token, "url": BASE_URL}]
    )


def _api_headers(token: str) -> dict:
    return {"Cookie": f"access_token={token}"}


# ---------------------------------------------------------------------------
# AC9 — Admin sees coach_notes; member does not
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_admin_sees_coach_notes_on_session_detail_page(page: Page) -> None:
    pytest.fail("not implemented")


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_member_does_not_see_coach_notes_on_session_detail_page(page: Page) -> None:
    pytest.fail("not implemented")


# ---------------------------------------------------------------------------
# AC10 — Member checks in from the session detail page
# ---------------------------------------------------------------------------


@pytest.mark.xfail(strict=True, reason="not implemented")
def test_member_can_check_in_from_session_detail_page(page: Page) -> None:
    pytest.fail("not implemented")
