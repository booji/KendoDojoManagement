"""Admin writes and exports land in the security event log (#460).

Each event records who (the Admin's user_id), from where (ip_address), and
which object; an edit names the fields it changed, never their values.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.guards import REQUIRE_ADMIN
from app.auth.models import AccountClaims
from app.main import app
from app.members.dependencies import get_member_repo
from tests.fake_repositories import InMemoryMemberRepository

_ADMIN = AccountClaims(
    sub="admin-uuid", email="admin@dojo.test", role="admin", is_active=True
)
_IP = "203.0.113.9"


@pytest.fixture(autouse=True)
def as_admin():
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def member_repo() -> InMemoryMemberRepository:
    repo = InMemoryMemberRepository()
    app.dependency_overrides[get_member_repo] = lambda: repo
    return repo


def _client() -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=(_IP, 4242)),
        base_url="http://test/api",
    )


def _events(caplog: pytest.LogCaptureFixture, event_type: str) -> list[dict[str, Any]]:
    """The logged events of one type, without their (unpredictable) timestamp."""
    return [
        {k: v for k, v in e.items() if k != "timestamp"}
        for e in (
            json.loads(r.getMessage())
            for r in caplog.records
            if r.name == "security_events"
        )
        if e["event_type"] == event_type
    ]


def _member_payload(**overrides: Any) -> dict[str, Any]:
    return {
        "email": "taro@dojo.test",
        "first_name": "Taro",
        "surname": "Yamada",
        "dob": "1990-06-15",
        "join_date": "2024-01-10",
        "membership_status": "active",
        "is_coach": False,
        "is_first_aider": False,
        "emergency_contact_name": "Hanako Yamada",
        "emergency_contact_phone": "+447700900000",
        **overrides,
    }


async def test_member_create_is_logged(member_repo, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="security_events"):
        async with _client() as c:
            response = await c.post("/members", json=_member_payload())

    assert response.status_code == 201
    assert _events(caplog, "member_created") == [
        {
            "event_type": "member_created",
            "result": "success",
            "user_id": "admin-uuid",
            "ip_address": _IP,
            "detail": {"member_id": response.json()["id"]},
        }
    ]


async def test_member_edit_logs_only_the_names_of_fields_that_changed(
    member_repo, caplog
) -> None:
    """The SPA sends the whole form back; only real changes are named, and
    no value, old or new, reaches the log."""
    member = member_repo.seed(**_member_payload())
    with caplog.at_level(logging.INFO, logger="security_events"):
        async with _client() as c:
            response = await c.put(
                f"/members/{member['id']}",
                json=_member_payload(surname="Suzuki", membership_status="inactive"),
            )

    assert response.status_code == 200
    assert _events(caplog, "member_updated") == [
        {
            "event_type": "member_updated",
            "result": "success",
            "user_id": "admin-uuid",
            "ip_address": _IP,
            "detail": {
                "member_id": member["id"],
                "changed_fields": ["membership_status", "surname"],
            },
        }
    ]
    assert "Suzuki" not in caplog.text and "Yamada" not in caplog.text
