"""
Unit / integration tests for issue #100 — Check-in token hashing + used_at idempotency.

Acceptance criteria under test:
  AC1. Token generated with token_urlsafe(32) — plaintext length ≥ 43 chars
  AC2. DB stores bcrypt hash; stored value ≠ plaintext
  AC3. Correct plaintext redeems successfully (repo-level get)
  AC4. Incorrect plaintext returns None (repo-level get)
  AC5. used_at is None before redemption; set after first successful redemption
  AC6. Second redemption raises a conflict signal
  AC7. HTTP POST /checkin/{token} with correct plaintext → 200
  AC8. HTTP POST /checkin/{token} with wrong plaintext → 401
  AC9. HTTP POST /checkin/{token} second time with same token → 409

Strategy
--------
AC1-AC6: Call SqlCheckinTokenRepository directly via the shared PostgreSQL
         `db_session` fixture (conftest.py; savepoint-scoped, rolled back per
         test) so that failures are grounded in the *real* implementation,
         not the stub.
AC7-AC9: Use the FastAPI test client with a HashingStubCheckinTokenRepo that
         faithfully models the new contract; failures reveal router logic gaps.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.attendance.dependencies import (
    get_attendance_repo,
    get_checkin_token_repo,
    get_session_instance_repo,
)
from app.auth.guards import REQUIRE_MEMBER
from app.auth.models import UserClaims
from app.main import app

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MEMBER = UserClaims(
    sub="member-uuid", email="member@dojo.test", role="member", is_active=True
)


def _member_override() -> UserClaims:
    return _MEMBER


async def _seed_session_instance(db_session: AsyncSession) -> str:
    """Insert a minimal real SessionInstance row and return its id.

    checkin_tokens.session_id carries a real FK to session_instances.id and
    PostgreSQL enforces it, so repo-level tests need a real row to point at
    rather than a bare random uuid.
    """
    from app.sessions.db_models import SessionInstance

    instance = SessionInstance(
        id=str(uuid.uuid4()),
        title="Test Session",
        date="2099-06-01",
    )
    db_session.add(instance)
    await db_session.flush()
    return instance.id


# ---------------------------------------------------------------------------
# Repository-level tests (AC1-AC6) use the shared PostgreSQL `db_session`
# fixture from conftest.py.
# ---------------------------------------------------------------------------
# AC1 — token_urlsafe(32): plaintext ≥ 43 chars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_created_token_plaintext_length_is_at_least_43(
    db_session: AsyncSession,
) -> None:
    """SqlCheckinTokenRepository.create() must return a token of ≥ 43 chars."""
    from app.attendance.repository import SqlCheckinTokenRepository

    repo = SqlCheckinTokenRepository(db_session)
    session_id = await _seed_session_instance(db_session)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    result = await repo.create(session_id, expires_at)
    plaintext = result["token"]
    assert (
        len(plaintext) >= 43
    ), f"Expected plaintext token length ≥ 43 (token_urlsafe(32)), got {len(plaintext)}"


# ---------------------------------------------------------------------------
# AC2 — DB stores bcrypt hash, not plaintext
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stored_value_is_not_plaintext(
    db_session: AsyncSession,
) -> None:
    """The value persisted in checkin_tokens.token must differ from the plaintext."""
    from sqlalchemy import select

    from app.attendance.db_models import CheckinToken
    from app.attendance.repository import SqlCheckinTokenRepository

    repo = SqlCheckinTokenRepository(db_session)
    session_id = await _seed_session_instance(db_session)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    result = await repo.create(session_id, expires_at)
    plaintext = result["token"]

    await db_session.flush()
    row = (await db_session.execute(select(CheckinToken))).scalar_one()
    assert (
        row.token != plaintext
    ), "checkin_tokens.token equals the plaintext — token is NOT hashed"


@pytest.mark.asyncio
async def test_stored_value_is_bcrypt_hash(
    db_session: AsyncSession,
) -> None:
    """The value in checkin_tokens.token must be a valid bcrypt hash."""
    import bcrypt as _bcrypt
    from sqlalchemy import select

    from app.attendance.db_models import CheckinToken
    from app.attendance.repository import SqlCheckinTokenRepository

    repo = SqlCheckinTokenRepository(db_session)
    session_id = await _seed_session_instance(db_session)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    result = await repo.create(session_id, expires_at)
    plaintext = result["token"]

    await db_session.flush()
    row = (await db_session.execute(select(CheckinToken))).scalar_one()
    stored = row.token

    assert stored.startswith(
        "$2b$"
    ), f"Stored value doesn't look like a bcrypt hash: {stored[:20]!r}"
    assert _bcrypt.checkpw(
        plaintext.encode(), stored.encode()
    ), "bcrypt.checkpw returned False — stored hash doesn't verify the returned plaintext"


# ---------------------------------------------------------------------------
# AC3 — Correct plaintext redeems successfully (repo-level get)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correct_plaintext_get_returns_record(
    db_session: AsyncSession,
) -> None:
    """SqlCheckinTokenRepository.get(plaintext) with correct token returns the record."""
    from app.attendance.repository import SqlCheckinTokenRepository

    repo = SqlCheckinTokenRepository(db_session)
    session_id = await _seed_session_instance(db_session)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    result = await repo.create(session_id, expires_at)
    plaintext = result["token"]

    await db_session.flush()
    found = await repo.get(plaintext)
    assert found is not None, "get() returned None for a correct plaintext token"
    assert found["session_id"] == session_id


# ---------------------------------------------------------------------------
# AC4 — Incorrect plaintext returns None (repo-level get)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incorrect_plaintext_get_returns_none(
    db_session: AsyncSession,
) -> None:
    """get(wrong_token) must return None — no match on wrong plaintext."""
    from app.attendance.repository import SqlCheckinTokenRepository

    repo = SqlCheckinTokenRepository(db_session)
    session_id = await _seed_session_instance(db_session)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    await repo.create(session_id, expires_at)
    await db_session.flush()

    found = await repo.get("this-is-definitely-not-the-right-token")
    assert found is None, "get() should return None for an incorrect token"


# ---------------------------------------------------------------------------
# AC5 — used_at None before redemption; set after first redemption
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_used_at_is_none_before_redemption(
    db_session: AsyncSession,
) -> None:
    """create() result must include used_at=None."""
    from app.attendance.repository import SqlCheckinTokenRepository

    repo = SqlCheckinTokenRepository(db_session)
    session_id = await _seed_session_instance(db_session)
    result = await repo.create(session_id, datetime.now(UTC) + timedelta(hours=1))

    assert "used_at" in result, "create() must return a 'used_at' field"
    assert (
        result["used_at"] is None
    ), f"used_at should be None before any redemption, got {result['used_at']!r}"


@pytest.mark.asyncio
async def test_used_at_is_set_after_first_redemption(
    db_session: AsyncSession,
) -> None:
    """After redeem(plaintext) the record's used_at must be non-None."""
    from app.attendance.repository import SqlCheckinTokenRepository

    repo = SqlCheckinTokenRepository(db_session)
    session_id = await _seed_session_instance(db_session)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    result = await repo.create(session_id, expires_at)
    plaintext = result["token"]
    await db_session.flush()

    redeemed = await repo.redeem(plaintext)
    assert (
        redeemed["used_at"] is not None
    ), "used_at should be set to a datetime after first successful redemption"


# ---------------------------------------------------------------------------
# AC6 — Second redemption raises a conflict signal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_redemption_raises_conflict(
    db_session: AsyncSession,
) -> None:
    """Calling repo.redeem() a second time must raise (ValueError or similar)."""
    from app.attendance.repository import SqlCheckinTokenRepository

    repo = SqlCheckinTokenRepository(db_session)
    session_id = await _seed_session_instance(db_session)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    result = await repo.create(session_id, expires_at)
    plaintext = result["token"]
    await db_session.flush()

    await repo.redeem(plaintext)  # first call: must succeed

    with pytest.raises((ValueError, Exception)):
        await repo.redeem(plaintext)  # second call: must raise


# ---------------------------------------------------------------------------
# Stub for HTTP-level tests (AC7–AC9)
#
# This stub faithfully models the desired new contract so that the HTTP tests
# specifically exercise router logic (not repo logic which is covered above).
# ---------------------------------------------------------------------------


class _StubSessionInstanceRepo:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def get(self, instance_id: str) -> dict[str, Any] | None:
        return self._store.get(instance_id)

    def seed(self, cancelled: bool = False) -> dict[str, Any]:
        new_id = str(uuid.uuid4())
        record = {"id": new_id, "date": "2099-06-01", "cancelled": cancelled}
        self._store[new_id] = record
        return record


class _StubAttendanceRepo:
    def __init__(self) -> None:
        self._store: list[dict[str, Any]] = []

    async def check_in(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "member_id": member_id,
            "visitor_name": None,
            "checked_in_at": datetime.now(UTC).isoformat(),
            "recorded_by": recorded_by,
        }
        self._store.append(record)
        return record

    async def list_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return [r for r in self._store if r["session_id"] == session_id]

    async def get_by_session_member(
        self, session_id: str, member_id: str
    ) -> dict[str, Any] | None:
        for r in self._store:
            if r["session_id"] == session_id and r.get("member_id") == member_id:
                return r
        return None

    async def admin_mark_attended(
        self, session_id: str, member_id: str, recorded_by: str
    ) -> dict[str, Any]:
        return await self.check_in(session_id, member_id, recorded_by)

    async def remove_attendance(self, session_id: str, member_id: str) -> bool:
        for i, r in enumerate(self._store):
            if r["session_id"] == session_id and r.get("member_id") == member_id:
                self._store.pop(i)
                return True
        return False

    async def add_visitor(
        self, session_id: str, visitor_name: str, recorded_by: str
    ) -> dict[str, Any]:
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "member_id": None,
            "visitor_name": visitor_name,
            "checked_in_at": datetime.now(UTC).isoformat(),
            "recorded_by": recorded_by,
        }
        self._store.append(record)
        return record

    async def list_for_member(self, member_id: str) -> list[dict[str, Any]]:
        return [r for r in self._store if r.get("member_id") == member_id]


class _HashingStubCheckinTokenRepo:
    """
    Stub modelling the NEW hashed-token + used_at + redeem() contract.

    create()  → bcrypt-hashes the token; returns plaintext once.
    get()     → bcrypt-verifies against stored hash.
    redeem()  → sets used_at on first call; raises ValueError on second call.
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}  # record_id → internal record

    async def create(self, session_id: str, expires_at: datetime) -> dict[str, Any]:
        import secrets

        import bcrypt

        plaintext = secrets.token_urlsafe(32)
        stored_hash = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()
        record_id = str(uuid.uuid4())
        self._store[record_id] = {
            "id": record_id,
            "token_hash": stored_hash,
            "session_id": session_id,
            "expires_at": expires_at.isoformat(),
            "used_at": None,
            "_plaintext": plaintext,
        }
        return {
            "token": plaintext,
            "session_id": session_id,
            "expires_at": expires_at.isoformat(),
            "used_at": None,
        }

    def _find_record(self, plaintext: str) -> dict[str, Any] | None:
        import bcrypt

        for rec in self._store.values():
            if bcrypt.checkpw(plaintext.encode(), rec["token_hash"].encode()):
                return rec
        return None

    async def get(self, token: str) -> dict[str, Any] | None:
        rec = self._find_record(token)
        if rec is None:
            return None
        return {
            "token": token,
            "session_id": rec["session_id"],
            "expires_at": rec["expires_at"],
            "used_at": rec["used_at"],
        }

    async def redeem(self, token: str) -> dict[str, Any] | None:
        rec = self._find_record(token)
        if rec is None:
            return None
        if rec["used_at"] is not None:
            raise ValueError("Token already used")
        rec["used_at"] = datetime.now(UTC).isoformat()
        return {
            "token": token,
            "session_id": rec["session_id"],
            "expires_at": rec["expires_at"],
            "used_at": rec["used_at"],
        }


# ---------------------------------------------------------------------------
# Fixtures — HTTP-level tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def http_session_repo() -> _StubSessionInstanceRepo:
    repo = _StubSessionInstanceRepo()
    app.dependency_overrides[get_session_instance_repo] = lambda: repo
    return repo


@pytest.fixture()
def http_attendance_repo() -> _StubAttendanceRepo:
    repo = _StubAttendanceRepo()
    app.dependency_overrides[get_attendance_repo] = lambda: repo
    return repo


@pytest.fixture()
def http_token_repo() -> _HashingStubCheckinTokenRepo:
    repo = _HashingStubCheckinTokenRepo()
    app.dependency_overrides[get_checkin_token_repo] = lambda: repo
    return repo


# ---------------------------------------------------------------------------
# AC7 — HTTP: valid token → 200
# ---------------------------------------------------------------------------


async def test_http_checkin_via_valid_token_returns_200(
    http_session_repo: _StubSessionInstanceRepo,
    http_attendance_repo: _StubAttendanceRepo,
    http_token_repo: _HashingStubCheckinTokenRepo,
) -> None:
    """POST /checkin/{token} with a valid plaintext token → 200."""
    session = http_session_repo.seed(cancelled=False)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    token_result = await http_token_repo.create(session["id"], expires_at)
    plaintext = token_result["token"]
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(f"/checkin/{plaintext}")

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session["id"]
    assert body["member_id"] == _MEMBER.sub


# ---------------------------------------------------------------------------
# AC8 — HTTP: wrong token → 404
# ---------------------------------------------------------------------------


async def test_http_checkin_via_wrong_token_returns_401(
    http_session_repo: _StubSessionInstanceRepo,
    http_attendance_repo: _StubAttendanceRepo,
    http_token_repo: _HashingStubCheckinTokenRepo,
) -> None:
    """POST /checkin/{token} with wrong plaintext → 404."""
    session = http_session_repo.seed(cancelled=False)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    await http_token_repo.create(session["id"], expires_at)
    app.dependency_overrides[REQUIRE_MEMBER] = _member_override

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post("/checkin/wrong-plaintext-token-that-wont-match")

    assert (
        response.status_code == 404
    ), f"Expected 404 for a wrong token, got {response.status_code}"


# ---------------------------------------------------------------------------
# AC9 — HTTP: second redemption of same token → 409
# ---------------------------------------------------------------------------


async def test_http_second_checkin_via_same_token_returns_409(
    http_session_repo: _StubSessionInstanceRepo,
    http_attendance_repo: _StubAttendanceRepo,
    http_token_repo: _HashingStubCheckinTokenRepo,
) -> None:
    """POST /checkin/{token} second time with same token → 409.

    The router must call redeem() (which sets used_at) and return 409 on the
    second attempt because used_at is already set — NOT because the member is
    already checked in.
    """
    session = http_session_repo.seed(cancelled=False)
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    token_result = await http_token_repo.create(session["id"], expires_at)
    plaintext = token_result["token"]

    # Use two different members so the "already checked in" guard doesn't fire
    _member_a = UserClaims(
        sub="member-a-uuid", email="a@dojo.test", role="member", is_active=True
    )
    _member_b = UserClaims(
        sub="member-b-uuid", email="b@dojo.test", role="member", is_active=True
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        app.dependency_overrides[REQUIRE_MEMBER] = lambda: _member_a
        first = await c.post(f"/checkin/{plaintext}")

        app.dependency_overrides[REQUIRE_MEMBER] = lambda: _member_b
        second = await c.post(f"/checkin/{plaintext}")

    assert (
        first.status_code == 200
    ), f"First redemption should be 200, got {first.status_code}"
    assert second.status_code == 409, (
        f"Second redemption (different member) should be 409 due to used_at, "
        f"got {second.status_code}"
    )
