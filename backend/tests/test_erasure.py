"""
Tests for issue #229 — GDPR erasure (admin-only, irreversible anonymisation).

RED PHASE — no production code exists yet. These tests are expected to fail:
  - the pure-unit tests (build_erasure_plan / can_erase) fail with ImportError
    because app/members/erasure.py does not exist yet.
  - the stub-based guard tests fail because POST /members/{id}/erase does not
    exist yet (404 instead of the expected 403/409).
  - the Postgres integration test fails for the same reason (404), and once
    an endpoint exists but is incomplete, it will fail on state assertions.

Planned contract (see .claude task brief for issue #229 for full detail):

    app/members/erasure.py
        build_erasure_plan() -> ErasurePlan
            .scrub: dict[str, Any]   — field -> anonymised value
            .delete: set[str] | frozenset[str]  — related record type names
        can_erase(actor_user_id: str, member: dict, is_admin: bool,
                   admin_count: int) -> ErasureDecision
            .allowed: bool
            .reason: str | None

    app/members/dependencies.py
        get_admin_directory() -> AbstractAdminDirectory
            .is_admin(user_id: str | None) -> bool
            .count_admins() -> int
        (exact dependency name is a suggestion for the implementer; guard
        tests below degrade gracefully if the name differs — the important,
        load-bearing assertion is the HTTP status code / response body.)

    app/members/router.py
        POST /members/{member_id}/erase  (admin only)
            200 -> anonymised MemberResponse ("Deleted" / "member")
            403 -> non-admin actor
            409 -> member not archived / self-erase / last-admin erase
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app
from tests.fake_repositories import InMemoryMemberRepository

# ---------------------------------------------------------------------------
# Lazy import of the not-yet-existing erasure module.
#
# We deliberately do NOT `from app.members.erasure import ...` at module
# scope: that would turn a missing module into a collection error for the
# *entire file*, hiding every other test behind one opaque error. Instead we
# capture the ImportError and re-raise it lazily inside each test that needs
# it, so every test reports its own clean failure.
# ---------------------------------------------------------------------------

try:
    from app.members import erasure as _erasure_module
except ImportError as _exc:  # pragma: no cover - exercised by design in RED phase
    _erasure_module = None
    _erasure_import_error: ImportError | None = _exc
else:
    _erasure_import_error = None


def _erasure() -> Any:
    """Return the app.members.erasure module, or raise the original ImportError."""
    if _erasure_module is None:
        assert _erasure_import_error is not None
        raise _erasure_import_error
    return _erasure_module


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def _member(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "member-1",
        "email": "taro@dojo.test",
        "first_name": "Taro",
        "surname": "Yamada",
        "display_name": "Taro Y",
        "dob": "1990-01-01",
        "join_date": "2020-01-01",
        "membership_status": "archived",
        "is_coach": False,
        "is_first_aider": False,
        "emergency_contact_name": "Hanako Yamada",
        "emergency_contact_phone": "+447700900000",
        "user_id": "user-1",
    }
    base.update(overrides)
    return base


# ===========================================================================
# Pure unit tests — build_erasure_plan (no DB, no I/O)
# ===========================================================================


class TestBuildErasurePlan:
    def test_scrub_overwrites_pii_fields_with_expected_values(self) -> None:
        plan = _erasure().build_erasure_plan()
        assert plan.scrub["first_name"] == "Deleted"
        assert plan.scrub["surname"] == "member"
        assert plan.scrub["email"] is None
        assert plan.scrub["display_name"] is None
        assert plan.scrub["dob"] is None
        assert plan.scrub["emergency_contact_name"] is None
        assert plan.scrub["emergency_contact_phone"] is None
        assert plan.scrub["user_id"] is None

    def test_scrub_does_not_alter_id(self) -> None:
        """The plan never touches the primary key — erasure anonymises in place."""
        plan = _erasure().build_erasure_plan()
        assert "id" not in plan.scrub

    def test_delete_names_exactly_the_expected_related_record_types(self) -> None:
        plan = _erasure().build_erasure_plan()
        expected = {
            "user",
            "passkey_credentials",
            "recovery_codes",
            "recovery_attempts",
            "admin_recovery_tokens",
            "grade_history",
            "member_federations",
        }
        assert set(plan.delete) == expected

    def test_attendance_is_never_scheduled_for_deletion(self) -> None:
        plan = _erasure().build_erasure_plan()
        assert "attendance" not in plan.delete
        assert "attendances" not in plan.delete


# ===========================================================================
# Pure unit tests — can_erase (no DB, no I/O)
# ===========================================================================


class TestCanErase:
    def test_deny_when_member_not_archived(self) -> None:
        member = _member(membership_status="active")
        decision = _erasure().can_erase(
            actor_user_id="admin-1", member=member, is_admin=False, admin_count=2
        )
        assert decision.allowed is False
        assert decision.reason is not None
        assert "archived" in decision.reason.lower()

    def test_deny_self_erase(self) -> None:
        member = _member(membership_status="archived", user_id="admin-1")
        decision = _erasure().can_erase(
            actor_user_id="admin-1", member=member, is_admin=False, admin_count=2
        )
        assert decision.allowed is False
        assert decision.reason is not None
        assert (
            "self" in decision.reason.lower() or "yourself" in decision.reason.lower()
        )

    def test_deny_last_admin(self) -> None:
        member = _member(membership_status="archived", user_id="other-admin")
        decision = _erasure().can_erase(
            actor_user_id="admin-1", member=member, is_admin=True, admin_count=1
        )
        assert decision.allowed is False
        assert decision.reason is not None
        assert "last admin" in decision.reason.lower()

    def test_allow_archived_non_admin_not_self(self) -> None:
        member = _member(membership_status="archived", user_id="some-other-user")
        decision = _erasure().can_erase(
            actor_user_id="admin-1", member=member, is_admin=False, admin_count=2
        )
        assert decision.allowed is True

    def test_allow_when_member_is_admin_but_not_the_last_one(self) -> None:
        member = _member(membership_status="archived", user_id="other-admin")
        decision = _erasure().can_erase(
            actor_user_id="admin-1", member=member, is_admin=True, admin_count=2
        )
        assert decision.allowed is True


# ===========================================================================
# Endpoint guard tests — stub-based, no DB (Tier 1)
# ===========================================================================


_MEMBER_CLAIMS = UserClaims(
    sub="member-uuid-self", email="self@dojo.test", role="member", is_active=True
)
_ADMIN_CLAIMS = UserClaims(
    sub="admin-1", email="admin@dojo.test", role="admin", is_active=True
)


def _override_member_repo(records: dict[str, dict[str, Any]]) -> None:
    from app.members.dependencies import get_member_repo

    repo = InMemoryMemberRepository(list(records.values()))
    app.dependency_overrides[get_member_repo] = lambda: repo


async def test_erase_as_non_admin_returns_403() -> None:
    from app.auth.token import encode_token

    _override_member_repo({"member-1": _member()})
    token = encode_token(_MEMBER_CLAIMS)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(
            "/members/member-1/erase", cookies={"access_token": token}
        )
    assert response.status_code == 403


async def test_erase_unauthenticated_returns_401() -> None:
    _override_member_repo({"member-1": _member()})
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/members/member-1/erase")
    assert response.status_code == 401


async def test_erase_member_not_archived_returns_409() -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN_CLAIMS
    _override_member_repo(
        {"member-1": _member(membership_status="active", user_id="someone-else")}
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/members/member-1/erase")
    assert response.status_code == 409
    assert "archived" in response.json()["detail"].lower()


async def test_erase_self_returns_409() -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN_CLAIMS
    _override_member_repo(
        {"member-1": _member(membership_status="archived", user_id=_ADMIN_CLAIMS.sub)}
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/members/member-1/erase")
    assert response.status_code == 409
    detail = response.json()["detail"].lower()
    assert "self" in detail or "yourself" in detail


async def test_erase_missing_member_returns_404() -> None:
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: _ADMIN_CLAIMS
    _override_member_repo({})
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post("/members/does-not-exist/erase")
    assert response.status_code == 404


# ===========================================================================
# Integration test — real Postgres (Tier 2)
#
# Verifies actual SQL side-effects: anonymised member row, deleted auth /
# passkey / recovery / grade / federation rows, and RETAINED attendance rows
# that still reference the member id. Uses db_session (savepoint-backed) from
# conftest.py, following the pattern in test_pg_isolation.py.
# ===========================================================================


class _DbSessionUnitOfWork:
    """Adapts a raw AsyncSession (already inside a test savepoint) to the
    AbstractUnitOfWork protocol, without ending the surrounding transaction.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    async def commit(self) -> None:
        await self._session.flush()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def __aenter__(self) -> _DbSessionUnitOfWork:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


async def test_erase_endpoint_anonymises_deletes_and_retains_attendance(
    db_session: AsyncSession,
) -> None:
    from app.dependencies import get_uow
    from app.members.dependencies import get_member_repo
    from app.members.repository import SqlMemberRepository

    actor_id = str(uuid.uuid4())
    member_user_id = str(uuid.uuid4())
    member_id = str(uuid.uuid4())
    federation_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    attendance_id = str(uuid.uuid4())

    # --- seed: two admin-adjacent users (actor is a distinct admin) ---------
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, role, is_active, theme) "
            "VALUES (:id, :email, 'admin', true, 'system')"
        ),
        {"id": actor_id, "email": f"actor-{actor_id}@dojo.test"},
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, email, role, is_active, theme) "
            "VALUES (:id, :email, 'member', true, 'system')"
        ),
        {"id": member_user_id, "email": f"member-{member_user_id}@dojo.test"},
    )

    # --- seed: the archived member to be erased -----------------------------
    await db_session.execute(
        text(
            "INSERT INTO members (id, email, first_name, surname, display_name, "
            "dob, join_date, membership_status, is_coach, is_first_aider, "
            "emergency_contact_name, emergency_contact_phone, user_id) "
            "VALUES (:id, :email, 'Taro', 'Yamada', 'Taro Y', '1990-01-01', "
            "'2020-01-01', 'archived', false, false, 'Hanako Yamada', "
            "'+447700900000', :user_id)"
        ),
        {
            "id": member_id,
            "email": f"member-{member_id}@dojo.test",
            "user_id": member_user_id,
        },
    )

    # --- seed: related records that must be DELETED -------------------------
    await db_session.execute(
        text(
            "INSERT INTO passkey_credentials "
            "(id, user_id, credential_id, public_key, sign_count, label, "
            "created_at) "
            "VALUES (:id, :user_id, :cred, :pk, 0, 'Passkey', now())"
        ),
        {
            "id": str(uuid.uuid4()),
            "user_id": member_user_id,
            "cred": b"credential-bytes",
            "pk": b"public-key-bytes",
        },
    )
    await db_session.execute(
        text(
            "INSERT INTO recovery_codes "
            "(id, user_id, code_hash, set_id, created_at) "
            "VALUES (:id, :user_id, 'hash', 'set-1', now())"
        ),
        {"id": str(uuid.uuid4()), "user_id": member_user_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO recovery_attempts "
            "(id, user_id, ip_address, success, attempted_at) "
            "VALUES (:id, :user_id, '127.0.0.1', false, now())"
        ),
        {"id": str(uuid.uuid4()), "user_id": member_user_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO admin_recovery_tokens "
            "(id, user_id, token_hash, expires_at, created_at) "
            "VALUES (:id, :user_id, 'hash', now() + interval '1 day', now())"
        ),
        {"id": str(uuid.uuid4()), "user_id": member_user_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO grade_history "
            "(id, member_id, grade, display_name, promoted_at, status) "
            "VALUES (:id, :member_id, '1 Kyu', 'Taro Yamada', '2020-01-01', "
            "'confirmed')"
        ),
        {"id": str(uuid.uuid4()), "member_id": member_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO federations (id, name, is_pinned, is_active) "
            "VALUES (:id, 'Test Federation', false, true)"
        ),
        {"id": federation_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO member_federations "
            "(id, member_id, federation_id, member_number) "
            "VALUES (:id, :member_id, :federation_id, 'MN-1')"
        ),
        {
            "id": str(uuid.uuid4()),
            "member_id": member_id,
            "federation_id": federation_id,
        },
    )

    # --- seed: attendance, which must be RETAINED ---------------------------
    await db_session.execute(
        text(
            "INSERT INTO session_instances (id, title, date, cancelled) "
            "VALUES (:id, 'Practice', '2024-01-01', false)"
        ),
        {"id": session_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO attendance "
            "(id, session_id, member_id, checked_in_at, recorded_by) "
            "VALUES (:id, :session_id, :member_id, '2024-01-01T18:00:00', "
            ":recorded_by)"
        ),
        {
            "id": attendance_id,
            "session_id": session_id,
            "member_id": member_id,
            "recorded_by": actor_id,
        },
    )
    await db_session.flush()

    uow = _DbSessionUnitOfWork(db_session)
    app.dependency_overrides[get_uow] = lambda: uow
    app.dependency_overrides[get_member_repo] = lambda: SqlMemberRepository(db_session)
    app.dependency_overrides[REQUIRE_ADMIN] = lambda: UserClaims(
        sub=actor_id, email="actor@dojo.test", role="admin", is_active=True
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        response = await c.post(f"/members/{member_id}/erase")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["first_name"] == "Deleted"
    assert body["surname"] == "member"

    # --- assert: member row anonymised in place ------------------------------
    row = (
        (
            await db_session.execute(
                text(
                    "SELECT first_name, surname, email, display_name, dob, "
                    "emergency_contact_name, emergency_contact_phone, user_id "
                    "FROM members WHERE id = :id"
                ),
                {"id": member_id},
            )
        )
        .mappings()
        .one()
    )
    assert row["first_name"] == "Deleted"
    assert row["surname"] == "member"
    assert row["email"] is None
    assert row["display_name"] is None
    assert row["dob"] is None
    assert row["emergency_contact_name"] is None
    assert row["emergency_contact_phone"] is None
    assert row["user_id"] is None

    # --- assert: related auth / recovery / grade / federation rows deleted --
    for table, column, value in [
        ("users", "id", member_user_id),
        ("passkey_credentials", "user_id", member_user_id),
        ("recovery_codes", "user_id", member_user_id),
        ("recovery_attempts", "user_id", member_user_id),
        ("admin_recovery_tokens", "user_id", member_user_id),
        ("grade_history", "member_id", member_id),
        ("member_federations", "member_id", member_id),
    ]:
        count = (
            await db_session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {column} = :value"),
                {"value": value},
            )
        ).scalar_one()
        assert count == 0, f"expected {table} rows for {column}={value} to be deleted"

    # --- assert: attendance retained, still referencing the member id -------
    attendance_count = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM attendance "
                "WHERE id = :id AND member_id = :member_id"
            ),
            {"id": attendance_id, "member_id": member_id},
        )
    ).scalar_one()
    assert attendance_count == 1, "attendance row must be retained and keep member_id"

    # --- the actor admin must NOT have been deleted (only the erased member's
    #     own user account is in scope) ---------------------------------------
    actor_count = (
        await db_session.execute(
            text("SELECT COUNT(*) FROM users WHERE id = :id"), {"id": actor_id}
        )
    ).scalar_one()
    assert actor_count == 1


async def test_list_search_tolerates_erased_member_with_null_email(
    db_session: AsyncSession,
) -> None:
    """Regression: erasure nulls email/first_name/surname, so the repository's
    search filter must not blow up (AttributeError -> 500) on None values.
    """
    from app.members.repository import SqlMemberRepository

    erased_id = str(uuid.uuid4())
    await db_session.execute(
        text(
            "INSERT INTO members (id, email, first_name, surname, join_date, "
            "membership_status, is_coach, is_first_aider) "
            "VALUES (:id, NULL, 'Deleted', 'member', '2020-01-01', 'archived', "
            "false, false)"
        ),
        {"id": erased_id},
    )
    await db_session.flush()

    repo = SqlMemberRepository(db_session)
    # A search that would previously call None.lower() on the null email.
    results = await repo.list(status="archived", search="anything")
    assert all(r["id"] != erased_id for r in results)  # no match, but no crash
    # And a search that DOES match the tombstone name still works.
    matched = await repo.list(status="archived", search="deleted")
    assert any(r["id"] == erased_id for r in matched)


# Silence an unused-import lint warning: REQUIRE_MEMBER is kept as documentation
# of the guard pair used elsewhere in the members test suite.
_ = REQUIRE_MEMBER
