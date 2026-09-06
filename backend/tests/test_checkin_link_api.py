"""
Tests for unifying check-in on the tokenless link.

The single-use token link (#9, #122) and the tokenless iCal link (#191) were
two doors to the same room. The token one is going away; the tokenless
`{origin}/checkin/session/{id}` becomes the one check-in link a session has,
and the REST read paths must surface it so the admin share UI and the iCal
feed quote the same string built in one place.

Acceptance criteria covered here:
  1. GET /sessions/{id} returns `checkin_link` built from PUBLIC_ORIGIN.
  2. GET /sessions returns `checkin_link` on every session.
  3. WEBAUTHN_ORIGIN remains the fallback when PUBLIC_ORIGIN is unset, and a
     trailing slash on either never doubles up in the path.
  4. The link is public: a member sees the same value an admin does.

NO real DB: the shared in-memory fakes stand in for the repositories.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.attendance.dependencies import get_attendance_repo
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app
from app.members.dependencies import get_current_member_id
from app.sessions.dependencies import get_session_instance_repo
from tests.fake_repositories import (
    InMemoryAttendanceRepository,
    InMemorySessionInstanceRepository,
)

_ADMIN = UserClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_MEMBER = UserClaims(
    sub="member-uuid", email="member@dojo.test", role="member", is_active=True
)
_MEMBER_ID = "member-record-uuid"


@pytest.fixture(autouse=True)
def _overrides():
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: _MEMBER
    app.dependency_overrides[get_current_member_id] = lambda: _MEMBER_ID
    app.dependency_overrides[get_attendance_repo] = (
        lambda repo=InMemoryAttendanceRepository(): repo
    )
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def instance_repo() -> InMemorySessionInstanceRepository:
    repo = InMemorySessionInstanceRepository()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


async def _seed(
    instance_repo: InMemorySessionInstanceRepository, **overrides: Any
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "title": "Weekly Keiko",
        "date": "2099-06-02",
        "location": "Main Hall",
        "segments": [
            {
                "start_time": "19:00",
                "duration_minutes": 90,
                "type_ids": [str(uuid.uuid4())],
            }
        ],
    }
    record.update(overrides)
    return await instance_repo.add(record)


async def _get(path: str) -> Any:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        return await c.get(path)


# --- AC1 -------------------------------------------------------------------


async def test_get_session_returns_checkin_link(instance_repo, monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://dojo.example.com")
    record = await _seed(instance_repo)

    response = await _get(f"/sessions/{record['id']}")

    assert response.status_code == 200
    assert response.json()["checkin_link"] == (
        f"https://dojo.example.com/checkin/session/{record['id']}"
    )


# --- AC2 -------------------------------------------------------------------


async def test_list_sessions_returns_checkin_link_on_every_session(
    instance_repo, monkeypatch
) -> None:
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://dojo.example.com")
    first = await _seed(instance_repo, title="Monday Keiko")
    second = await _seed(instance_repo, title="Friday Keiko")

    response = await _get("/sessions")

    assert response.status_code == 200
    by_id = {s["id"]: s["checkin_link"] for s in response.json()}
    for record in (first, second):
        assert by_id[record["id"]] == (
            f"https://dojo.example.com/checkin/session/{record['id']}"
        )


# --- AC3 -------------------------------------------------------------------


async def test_checkin_link_falls_back_to_webauthn_origin(
    instance_repo, monkeypatch
) -> None:
    monkeypatch.delenv("PUBLIC_ORIGIN", raising=False)
    monkeypatch.setenv("WEBAUTHN_ORIGIN", "https://fallback.example.com")
    record = await _seed(instance_repo)

    response = await _get(f"/sessions/{record['id']}")

    assert response.json()["checkin_link"] == (
        f"https://fallback.example.com/checkin/session/{record['id']}"
    )


async def test_checkin_link_does_not_double_slash_on_trailing_slash_origin(
    instance_repo, monkeypatch
) -> None:
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://dojo.example.com/")
    record = await _seed(instance_repo)

    response = await _get(f"/sessions/{record['id']}")

    assert response.json()["checkin_link"] == (
        f"https://dojo.example.com/checkin/session/{record['id']}"
    )


# --- AC4 -------------------------------------------------------------------


async def test_member_and_admin_see_the_same_checkin_link(
    instance_repo, monkeypatch
) -> None:
    """The link is public — it drives a member-authenticated, window-enforced
    endpoint, so there is nothing in it to redact."""
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://dojo.example.com")
    record = await _seed(instance_repo)

    app.dependency_overrides[REQUIRE_MEMBER] = lambda: _MEMBER
    as_member = (await _get(f"/sessions/{record['id']}")).json()["checkin_link"]
    app.dependency_overrides[REQUIRE_MEMBER] = lambda: _ADMIN
    as_admin = (await _get(f"/sessions/{record['id']}")).json()["checkin_link"]

    assert as_member == as_admin


# --- AC5 — the token subsystem is gone -------------------------------------


async def test_session_read_no_longer_carries_checkin_url(instance_repo) -> None:
    """`checkin_url` held a single-use token URL that any member could read
    and redeem. The field, its column and the token that filled it are gone;
    `checkin_link` replaces it."""
    record = await _seed(instance_repo)

    body = (await _get(f"/sessions/{record['id']}")).json()

    assert "checkin_url" not in body


def test_token_routes_are_gone() -> None:
    """The single-use token endpoints are removed, not merely unreachable: a
    404 alone would also be what an unknown token produced."""
    paths = {getattr(route, "path", "") for route in app.routes}

    assert "/sessions/{session_id}/checkin-token" not in paths
    assert "/checkin/{token}" not in paths
