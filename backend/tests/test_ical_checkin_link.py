"""
Tests for issue #191 — tokenless check-in link in the iCal feed.

This slice adds NO time-window enforcement; it only surfaces a stable,
tokenless check-in URL for each upcoming, non-cancelled session in the
public iCal feed.

Acceptance criteria covered here:
  1. The iCal feed router enriches each emitted session with a
     `checkin_link` of the form `{origin}/checkin/session/{id}`; the
     `build_ical` builder stays pure and consumes it via an allowlist entry
     (it does not know about origins or routing).
  2. The VEVENT DESCRIPTION shows "Check in: {url}" as the first line,
     followed by a blank line, then the existing segment breakdown and info.
  3. The link is present only for upcoming, non-cancelled sessions;
     cancelled sessions remain excluded from the feed entirely; no
     admin-only fields (coach_notes, notes) leak.

These tests are RED: `checkin_link` is not yet in `_PUBLIC_FIELDS`, and
`_build_description` does not yet emit the "Check in:" line. The router does
not yet compute/attach `checkin_link` to sessions before calling
`build_ical`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.sessions.dependencies import get_session_instance_repo, get_session_type_repo
from app.sessions.ical import build_ical
from tests.fake_repositories import (
    InMemorySessionInstanceRepository,
    InMemorySessionTypeRepository,
)

# ---------------------------------------------------------------------------
# Pure build_ical tests — call the builder directly with dicts, matching the
# existing style in test_ical.py / test_ical_segments.py.
# ---------------------------------------------------------------------------


def _session(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "uid-checkin-link",
        "title": "Friday Keiko",
        "date": "2099-06-05",
        "location": "Main Dojo",
        "info": "Bring your bogu",
        "cancelled": False,
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 90,
                "type_names": ["Kihon"],
            }
        ],
    }
    base.update(overrides)
    return base


def test_description_first_line_is_checkin_link_when_present() -> None:
    """When a session dict carries checkin_link, DESCRIPTION's first line
    must be 'Check in: {url}'."""
    url = "https://dojo.example.com/checkin/session/uid-checkin-link"
    sessions = [_session(checkin_link=url)]
    result = build_ical(sessions)
    description_line = next(
        line for line in result.split("\r\n") if line.startswith("DESCRIPTION:")
    )
    # DESCRIPTION escaping turns real newlines into literal "\n" — the first
    # line of the (unescaped) description content is "Check in: {url}".
    content = description_line[len("DESCRIPTION:") :]
    assert content.startswith(f"Check in: {url}")


def test_description_has_blank_line_after_checkin_link() -> None:
    """A blank line must separate 'Check in: {url}' from the segment
    breakdown / info that follows."""
    url = "https://dojo.example.com/checkin/session/uid-checkin-link"
    sessions = [_session(checkin_link=url)]
    result = build_ical(sessions)
    description_line = next(
        line for line in result.split("\r\n") if line.startswith("DESCRIPTION:")
    )
    content = description_line[len("DESCRIPTION:") :]
    # Escaped newlines appear as literal "\n" in the DESCRIPTION value.
    assert f"Check in: {url}\\n\\n" in content


def test_description_still_contains_breakdown_and_info_after_checkin_link() -> None:
    """The existing segment breakdown and info must still follow the
    check-in line and blank line, unchanged."""
    url = "https://dojo.example.com/checkin/session/uid-checkin-link"
    sessions = [_session(checkin_link=url)]
    result = build_ical(sessions)
    description_line = next(
        line for line in result.split("\r\n") if line.startswith("DESCRIPTION:")
    )
    content = description_line[len("DESCRIPTION:") :]
    assert "19:00-20:30" in content
    assert "Kihon" in content
    assert "Bring your bogu" in content


def test_description_omits_checkin_line_when_checkin_link_absent() -> None:
    """A session dict without a checkin_link key must produce the same
    DESCRIPTION as before this feature — no 'Check in:' line at all."""
    sessions = [_session()]
    result = build_ical(sessions)
    description_line = next(
        line for line in result.split("\r\n") if line.startswith("DESCRIPTION:")
    )
    content = description_line[len("DESCRIPTION:") :]
    assert "Check in:" not in content
    assert content.startswith("19:00-20:30")


def test_description_omits_checkin_line_when_checkin_link_is_none() -> None:
    """A session dict with checkin_link explicitly None behaves the same as
    checkin_link being absent."""
    sessions = [_session(checkin_link=None)]
    result = build_ical(sessions)
    description_line = next(
        line for line in result.split("\r\n") if line.startswith("DESCRIPTION:")
    )
    content = description_line[len("DESCRIPTION:") :]
    assert "Check in:" not in content


def test_cancelled_session_excluded_even_with_checkin_link() -> None:
    """Cancelled sessions must still be excluded from the feed entirely,
    even when a checkin_link is present on the dict."""
    url = "https://dojo.example.com/checkin/session/uid-cancelled"
    sessions = [
        _session(
            id="uid-cancelled",
            title="Cancelled Night",
            cancelled=True,
            checkin_link=url,
        ),
        _session(id="uid-active", title="Active Night"),
    ]
    result = build_ical(sessions)
    assert "SUMMARY:Cancelled Night" not in result
    assert url not in result
    assert result.count("BEGIN:VEVENT") == 1
    assert "SUMMARY:Active Night" in result


def test_admin_only_fields_still_stripped_when_checkin_link_present() -> None:
    """coach_notes and notes must never leak into the output,
    even alongside a public checkin_link."""
    url = "https://dojo.example.com/checkin/session/uid-secret"
    sessions = [
        _session(
            id="uid-secret",
            title="Secret Night",
            checkin_link=url,
            coach_notes="SECRET coach guidance",
            notes="Internal scheduling note",
        )
    ]
    result = build_ical(sessions)
    assert "SECRET" not in result
    assert "coach_notes" not in result.lower()
    assert "Internal scheduling note" not in result
    # The public checkin_link itself is expected to appear.
    assert url in result


# ---------------------------------------------------------------------------
# Router enrichment — GET /sessions/ical must attach checkin_link built from
# PUBLIC_ORIGIN (falling back to WEBAUTHN_ORIGIN) before calling build_ical.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def instance_repo() -> InMemorySessionInstanceRepository:
    repo = InMemorySessionInstanceRepository()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


@pytest.fixture()
def type_repo() -> InMemorySessionTypeRepository:
    repo = InMemorySessionTypeRepository()
    app.dependency_overrides[get_session_type_repo] = lambda: repo
    return repo


async def test_get_sessions_ical_enriches_upcoming_session_with_checkin_link(
    instance_repo, type_repo, monkeypatch
) -> None:
    """GET /sessions/ical must build each upcoming session's checkin_link as
    {origin}/checkin/session/{id} using PUBLIC_ORIGIN, and the DESCRIPTION
    must show 'Check in: {url}' as its first line."""
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://dojo.example.com")
    t = type_repo.seed(name="Kihon")
    inst_id = str(uuid.uuid4())
    await instance_repo.add(
        {
            "id": inst_id,
            "title": "Saturday Keiko",
            "date": "2099-07-04",
            "segments": [
                {
                    "start_time": "09:00",
                    "duration_minutes": 60,
                    "type_ids": [t["id"]],
                }
            ],
            "location": "Main Dojo",
            "info": "Bring your bogu",
            "cancelled": False,
        }
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/sessions/ical")

    assert response.status_code == 200
    body = response.text
    expected_url = f"https://dojo.example.com/checkin/session/{inst_id}"
    description_line = next(
        line for line in body.split("\r\n") if line.startswith("DESCRIPTION:")
    )
    content = description_line[len("DESCRIPTION:") :]
    assert content.startswith(f"Check in: {expected_url}")


async def test_get_sessions_ical_falls_back_to_webauthn_origin(
    instance_repo, type_repo, monkeypatch
) -> None:
    """When PUBLIC_ORIGIN is unset, WEBAUTHN_ORIGIN must be used as the
    origin for the checkin_link, matching the existing attendance-domain
    pattern (os.getenv("PUBLIC_ORIGIN") or os.getenv("WEBAUTHN_ORIGIN"))."""
    monkeypatch.delenv("PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("WEBAUTHN_ORIGIN", "https://fallback.dojo.test")
    inst_id = str(uuid.uuid4())
    await instance_repo.add(
        {
            "id": inst_id,
            "title": "Sunday Keiko",
            "date": "2099-07-05",
            "segments": [
                {"start_time": "09:00", "duration_minutes": 60, "type_ids": []}
            ],
            "location": None,
            "info": None,
            "cancelled": False,
        }
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/sessions/ical")

    assert response.status_code == 200
    body = response.text
    expected_url = f"https://fallback.dojo.test/checkin/session/{inst_id}"
    assert expected_url in body


async def test_get_sessions_ical_cancelled_session_has_no_checkin_link_leak(
    instance_repo, type_repo, monkeypatch
) -> None:
    """Cancelled sessions must not appear in the feed at all, so no
    checkin_link for them can leak either."""
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://dojo.example.com")
    cancelled_id = str(uuid.uuid4())
    await instance_repo.add(
        {
            "id": cancelled_id,
            "title": "Cancelled Keiko",
            "date": "2099-07-06",
            "segments": [
                {"start_time": "09:00", "duration_minutes": 60, "type_ids": []}
            ],
            "location": None,
            "info": None,
            "cancelled": True,
        }
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.get("/sessions/ical")

    assert response.status_code == 200
    body = response.text
    assert "Cancelled Keiko" not in body
    assert f"/checkin/session/{cancelled_id}" not in body


def test_build_ical_is_still_pure_and_unaware_of_origin() -> None:
    """build_ical must remain a pure function of dicts: passing a
    checkin_link straight through (no origin/env lookups inside the
    builder) must reproduce exactly the same URL in the output."""
    url = "https://any-origin.example/checkin/session/uid-pure"
    sessions = [_session(id="uid-pure", checkin_link=url)]
    result = build_ical(sessions)
    assert url in result
