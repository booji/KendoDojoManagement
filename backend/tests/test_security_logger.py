"""Failing tests for issue #102 — structured security event logging.

Tests the `log_security_event` function in `app/core/security_logger.py`.

Acceptance criteria exercised:
  AC1. security_logger.py exists as a pure function module (no DB dependency)
  AC2. Each log line is valid single-line JSON with required keys
  AC3. event_type covers all 8 defined event types
  AC4. auth/router.py emits events on passkey/password login and lockout
  AC5. passkey_service.py emits events on passkey registration and deletion
  AC6. recovery_service.py emits events on redemption and admin token generation
  AC7. attendance/repository.py emits event on check-in token generation
  AC8. Unit tests: valid JSON, required keys, optional keys cleanly omitted/included
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import (
    get_admin_token_repo,
    get_passkey_repo,
    get_recovery_repo,
)
from app.auth.guards import REQUIRE_ADMIN, REQUIRE_MEMBER
from app.auth.models import AccountClaims
from app.main import app

pytestmark = pytest.mark.usefixtures("security_events_to_caplog")

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class StubPasskeyRepo:
    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        return [r for r in self._store.values() if r["user_id"] == user_id]

    async def get(self, passkey_id: str) -> dict[str, Any] | None:
        return self._store.get(passkey_id)

    async def update_label(
        self, passkey_id: str, user_id: str, label: str
    ) -> dict[str, Any] | None:
        record = self._store.get(passkey_id)
        if record is None or record["user_id"] != user_id:
            return None
        record["label"] = label
        return record

    async def delete(self, passkey_id: str, user_id: str) -> bool:
        record = self._store.get(passkey_id)
        if record is None or record["user_id"] != user_id:
            return False
        del self._store[passkey_id]
        return True

    async def count_for_user(self, user_id: str) -> int:
        return sum(1 for r in self._store.values() if r["user_id"] == user_id)

    def _seed(self, user_id: str, *, label: str = "Test Key") -> dict[str, Any]:
        pk_id = str(uuid.uuid4())
        record: dict[str, Any] = {
            "id": pk_id,
            "user_id": user_id,
            "credential_id": b"cred-" + pk_id.encode(),
            "public_key": b"pubkey",
            "label": label,
            "aaguid": None,
            "sign_count": 0,
        }
        self._store[pk_id] = record
        return record


class StubRecoveryRepo:
    def __init__(self, *, unused_count: int = 1) -> None:
        self._unused_count = unused_count

    async def count_unused(self, user_id: str) -> int:
        return self._unused_count

    async def create_codes(self, user_id: str, hashed_codes: list, set_id: str) -> list:
        return []

    async def has_active_set(self, user_id: str) -> bool:
        return False

    async def invalidate_all(self, user_id: str) -> None:
        return

    async def get_all_for_user(self, user_id: str) -> list:
        return []

    async def get_unused_codes_with_hash(self, user_id: str) -> list:
        return []

    async def mark_used(self, code_id: str) -> None:
        return


class StubAdminTokenRepo:
    async def get_live_admin_tokens_for_account(self, user_id: str) -> list:
        return []

    async def mark_admin_token_used(self, token_id: str) -> None:
        return

    async def create_admin_token(
        self,
        user_id: str,
        created_by_id: str,
        token_hash: str,
        expires_at: Any,
    ) -> dict[str, Any]:
        return {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "created_by_id": created_by_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "used_at": None,
        }


class StubAttemptRepo:
    def __init__(self, *, failures: int = 0) -> None:
        self._failures = failures
        self.logged: list[dict[str, Any]] = []

    async def is_locked_out(self, user_id: str) -> bool:
        return self._failures >= 5

    async def log_attempt(self, user_id: str, ip: str, *, success: bool) -> None:
        self.logged.append({"user_id": user_id, "ip": ip, "success": success})


# An empty session instance fake: get() finds nothing, which is what these
# tests need.


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper: capture log output from security_logger
# ---------------------------------------------------------------------------


def _capture_security_logs(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Parse captured log records from the security_events logger as JSON."""
    records = [r for r in caplog.records if r.name == "security_events"]
    results = []
    for record in records:
        results.append(json.loads(record.getMessage()))
    return results


# ===========================================================================
# AC1 — Module exists as a pure function with no DB dependency
# ===========================================================================


def test_security_logger_module_exists() -> None:
    """app/core/security_logger.py must be importable."""
    import app.core.security_logger  # noqa: F401


def test_log_security_event_is_callable() -> None:
    """log_security_event must be a callable in security_logger."""
    from app.core.security_logger import log_security_event

    assert callable(log_security_event)


# Production wiring (#461): nothing configures the root logger, so without its
# own handler every INFO event fell through to logging.lastResort (WARNING+)
# and was dropped. caplog attaches a handler of its own and hid that, so this
# runs a fresh interpreter with only uvicorn's logging config, as in the
# container, and reads the process's real stdout.
_PRODUCTION_LOGGING = """
import logging, logging.config, sys
from uvicorn.config import LOGGING_CONFIG
logging.config.dictConfig(LOGGING_CONFIG)
import app.main
from app.core.security_logger import log_security_event
# A later root config must not print the event a second time.
logging.basicConfig(stream=sys.stdout, level=logging.INFO)
log_security_event("setup_claim", "success")
"""


def test_security_event_reaches_stdout_once_under_uvicorn_logging() -> None:
    out = subprocess.run(
        [sys.executable, "-c", _PRODUCTION_LOGGING],
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    events = [line for line in out.splitlines() if "setup_claim" in line]
    assert len(events) == 1, out
    event = json.loads(events[0])
    assert (event["event_type"], event["result"]) == ("setup_claim", "success")


# ===========================================================================
# AC2 — Each log line is valid single-line JSON with required keys
# ===========================================================================


def test_log_emits_valid_json(caplog: pytest.LogCaptureFixture) -> None:
    """log_security_event must emit a single log record parseable as JSON."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(event_type="login_passkey", result="success")

    logs = _capture_security_logs(caplog)
    assert len(logs) == 1, "Expected exactly one log record"


def test_log_required_key_timestamp(caplog: pytest.LogCaptureFixture) -> None:
    """Each log entry must contain a 'timestamp' key."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(event_type="login_passkey", result="success")

    logs = _capture_security_logs(caplog)
    assert "timestamp" in logs[0]


def test_log_required_key_event_type(caplog: pytest.LogCaptureFixture) -> None:
    """Each log entry must contain an 'event_type' key."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(event_type="login_passkey", result="success")

    logs = _capture_security_logs(caplog)
    assert "event_type" in logs[0]
    assert logs[0]["event_type"] == "login_passkey"


def test_log_required_key_result(caplog: pytest.LogCaptureFixture) -> None:
    """Each log entry must contain a 'result' key with value 'success' or 'failure'."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(event_type="login_passkey", result="success")

    logs = _capture_security_logs(caplog)
    assert "result" in logs[0]
    assert logs[0]["result"] == "success"


def test_log_result_failure(caplog: pytest.LogCaptureFixture) -> None:
    """result='failure' is emitted correctly."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(event_type="login_passkey", result="failure")

    logs = _capture_security_logs(caplog)
    assert logs[0]["result"] == "failure"


def test_log_timestamp_is_iso_string(caplog: pytest.LogCaptureFixture) -> None:
    """timestamp must be an ISO-format datetime string."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(event_type="login_passkey", result="success")

    logs = _capture_security_logs(caplog)
    ts = logs[0]["timestamp"]
    assert isinstance(ts, str)
    # Must parse as ISO datetime (raises ValueError if not)
    from datetime import datetime

    datetime.fromisoformat(ts)


# ===========================================================================
# AC2/AC8 — Optional keys omitted when not passed
# ===========================================================================


def test_optional_user_id_omitted_when_not_passed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """user_id must NOT appear in the log when not provided."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(event_type="login_passkey", result="failure")

    logs = _capture_security_logs(caplog)
    assert "user_id" not in logs[0]


def test_optional_ip_address_omitted_when_not_passed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ip_address must NOT appear in the log when not provided."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(event_type="login_passkey", result="failure")

    logs = _capture_security_logs(caplog)
    assert "ip_address" not in logs[0]


def test_optional_detail_omitted_when_not_passed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """detail must NOT appear in the log when not provided."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(event_type="login_passkey", result="failure")

    logs = _capture_security_logs(caplog)
    assert "detail" not in logs[0]


# ===========================================================================
# AC8 — Optional keys present when passed
# ===========================================================================


def test_optional_user_id_included_when_passed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """user_id must appear in the log when explicitly provided."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(
            event_type="login_passkey",
            result="success",
            user_id="test-user-123",
        )

    logs = _capture_security_logs(caplog)
    assert logs[0].get("user_id") == "test-user-123"


def test_ip_address_included_when_a_request_bound_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ip_address is the IP ClientIPMiddleware bound for the request."""
    from app.core.security_logger import log_security_event, request_ip

    token = request_ip.set("192.168.1.1")
    try:
        with caplog.at_level(logging.INFO, logger="security_events"):
            log_security_event(event_type="login_passkey", result="failure")
    finally:
        request_ip.reset(token)

    logs = _capture_security_logs(caplog)
    assert logs[0].get("ip_address") == "192.168.1.1"


def test_optional_detail_included_when_passed(caplog: pytest.LogCaptureFixture) -> None:
    """detail must appear in the log when explicitly provided."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(
            event_type="recovery_redeem",
            result="failure",
            detail="too many failed attempts",
        )

    logs = _capture_security_logs(caplog)
    assert logs[0].get("detail") == "too many failed attempts"


def test_all_optional_keys_included_together(caplog: pytest.LogCaptureFixture) -> None:
    """Both optional keys included when both are provided."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(
            event_type="admin_token_generated",
            result="success",
            user_id="admin-456",
            detail="session abc",
        )

    logs = _capture_security_logs(caplog)
    entry = logs[0]
    assert entry.get("user_id") == "admin-456"
    assert entry.get("detail") == "session abc"


# ===========================================================================
# AC3 — All 8 event_type values are accepted
# ===========================================================================


@pytest.mark.parametrize(
    "event_type",
    [
        "login_passkey",
        "recovery_redeem",
        "admin_token_generated",
        "passkey_registered",
        "passkey_deleted",
        "sign_out_everywhere",
    ],
)
def test_all_event_types_accepted(
    event_type: str, caplog: pytest.LogCaptureFixture
) -> None:
    """log_security_event must accept each of the defined event_type values."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(event_type=event_type, result="success")

    logs = _capture_security_logs(caplog)
    assert len(logs) == 1
    assert logs[0]["event_type"] == event_type


# ===========================================================================
# AC2 — JSON must be valid single-line (no embedded newlines in value)
# ===========================================================================


def test_log_output_is_single_line(caplog: pytest.LogCaptureFixture) -> None:
    """The JSON log line must not contain embedded newlines."""
    from app.core.security_logger import log_security_event

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event(event_type="login_passkey", result="success")

    records = [r for r in caplog.records if r.name == "security_events"]
    assert len(records) == 1
    msg = records[0].getMessage()
    assert "\n" not in msg


# ===========================================================================
# AC4 — auth/router.py emits login events
# ===========================================================================
# These integration tests use the shared PostgreSQL `db_client` fixture
# (conftest.py; savepoint-scoped, rolled back per test) because the auth
# router has deep UoW coupling. We verify that after each auth action a
# security_events log record is emitted.


async def _register_user(email: str, password: str = "Str0ng!Pass") -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test/api"
    ) as c:
        await c.post(
            "/auth/register/password",
            json={"email": email, "password": password},
        )


@pytest.mark.xfail(
    strict=False,
    reason="POST /auth/login/password removed in issue #155 (passkey-only auth)",
)
@pytest.mark.asyncio
async def test_password_login_success_emits_log(
    db_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Successful password login must emit a login_password/success event."""
    await _register_user("logtest_success@dojo.test")

    with caplog.at_level(logging.INFO, logger="security_events"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            await c.post(
                "/auth/login/password",
                json={"email": "logtest_success@dojo.test", "password": "Str0ng!Pass"},
            )

    logs = _capture_security_logs(caplog)
    assert any(
        log["event_type"] == "login_password" and log["result"] == "success"
        for log in logs
    ), f"Expected login_password/success event, got: {logs}"


@pytest.mark.xfail(
    strict=False,
    reason="POST /auth/login/password removed in issue #155 (passkey-only auth)",
)
@pytest.mark.asyncio
async def test_password_login_failure_emits_log(
    db_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Failed password login must emit a login_password/failure event."""
    await _register_user("logtest_fail@dojo.test")

    with caplog.at_level(logging.INFO, logger="security_events"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            await c.post(
                "/auth/login/password",
                json={"email": "logtest_fail@dojo.test", "password": "WrongPassword!"},
            )

    logs = _capture_security_logs(caplog)
    assert any(
        log["event_type"] == "login_password" and log["result"] == "failure"
        for log in logs
    ), f"Expected login_password/failure event, got: {logs}"


@pytest.mark.xfail(
    strict=False,
    reason="POST /auth/login/password removed in issue #155 (passkey-only auth)",
)
@pytest.mark.asyncio
async def test_password_login_unknown_user_emits_failure_log(
    db_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Login attempt for unknown email must emit a login_password/failure event."""
    with caplog.at_level(logging.INFO, logger="security_events"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            await c.post(
                "/auth/login/password",
                json={"email": "nobody@dojo.test", "password": "whatever"},
            )

    logs = _capture_security_logs(caplog)
    assert any(
        log["event_type"] == "login_password" and log["result"] == "failure"
        for log in logs
    ), f"Expected login_password/failure event, got: {logs}"


@pytest.mark.asyncio
async def test_passkey_login_failure_emits_log(
    db_client, caplog: pytest.LogCaptureFixture
) -> None:
    """A passkey login_complete that fails must emit a login_passkey/failure event."""
    # /login/passkey/complete with a garbage payload should fail
    with caplog.at_level(logging.INFO, logger="security_events"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            await c.post(
                "/auth/login/passkey/complete",
                json={
                    "email": "passkey_fail@dojo.test",
                    "credential": {
                        "id": "fake",
                        "rawId": "fake",
                        "response": {
                            "clientDataJSON": "fake",
                            "authenticatorData": "fake",
                            "signature": "fake",
                        },
                        "type": "public-key",
                    },
                },
            )

    logs = _capture_security_logs(caplog)
    assert any(
        log["event_type"] == "login_passkey" and log["result"] == "failure"
        for log in logs
    ), f"Expected login_passkey/failure event, got: {logs}"


@pytest.mark.xfail(
    strict=False,
    reason="POST /auth/login/password removed in issue #155 (passkey-only auth)",
)
@pytest.mark.asyncio
async def test_account_lockout_emits_log(
    db_client, caplog: pytest.LogCaptureFixture
) -> None:
    """10 consecutive failed password logins must emit at least one login_lockout event."""
    await _register_user("lockout@dojo.test")

    with caplog.at_level(logging.INFO, logger="security_events"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            for _ in range(10):
                await c.post(
                    "/auth/login/password",
                    json={"email": "lockout@dojo.test", "password": "wrong"},
                )

    logs = _capture_security_logs(caplog)
    assert any(log["event_type"] == "login_lockout" for log in logs), (
        f"Expected login_lockout event, got: {logs}"
    )


# ===========================================================================
# AC5 — passkey_service.py emits on registration and deletion
# ===========================================================================


async def test_passkey_deletion_emits_log(caplog: pytest.LogCaptureFixture) -> None:
    """DELETE /auth/passkeys/{id} must emit a passkey_deleted/success event."""
    user = AccountClaims(sub="del-user", email="del@dojo.test", role="member")
    passkey_repo = StubPasskeyRepo()
    recovery_repo = StubRecoveryRepo(unused_count=1)

    # Seed two passkeys so deletion of one is allowed
    record1 = passkey_repo._seed(user.sub, label="Keep")
    record2 = passkey_repo._seed(user.sub, label="Delete Me")

    app.dependency_overrides[REQUIRE_MEMBER] = lambda: user
    app.dependency_overrides[get_passkey_repo] = lambda: passkey_repo
    app.dependency_overrides[get_recovery_repo] = lambda: recovery_repo

    with caplog.at_level(logging.INFO, logger="security_events"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            await c.delete(f"/auth/passkeys/{record2['id']}")

    logs = _capture_security_logs(caplog)
    assert any(
        log["event_type"] == "passkey_deleted" and log["result"] == "success"
        for log in logs
    ), f"Expected passkey_deleted/success event, got: {logs}"


@pytest.mark.asyncio
async def test_passkey_registration_emits_log(
    db_client, caplog: pytest.LogCaptureFixture
) -> None:
    """An attempt at the email-addressed registration complete emits a
    passkey_registered/failure event. The route is a decoy since Members
    became invite-only (#472), so every attempt there is a failure an
    operator may want to see.
    """
    with caplog.at_level(logging.INFO, logger="security_events"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            await c.post(
                "/auth/register/passkey/complete",
                json={
                    "email": "reg_passkey@dojo.test",
                    "credential": {
                        "id": "fake",
                        "rawId": "fake",
                        "response": {
                            "clientDataJSON": "fake",
                            "attestationObject": "fake",
                        },
                        "type": "public-key",
                    },
                },
            )

    logs = _capture_security_logs(caplog)
    assert any(
        log["event_type"] == "passkey_registered" and log["result"] == "failure"
        for log in logs
    ), f"Expected passkey_registered/failure event, got: {logs}"


# ===========================================================================
# AC6 — recovery_service.py emits on redemption and admin token generation
# ===========================================================================


@pytest.mark.asyncio
async def test_recovery_redeem_failure_emits_log(
    db_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Failed recovery code redemption must emit a recovery_redeem/failure event."""
    # Seed a user with no codes — redemption will fail
    from tests.account_support import seed_account

    user_id = str(uuid.uuid4())
    await seed_account(db_client, "redeem_fail@dojo.test", user_id=user_id)
    await db_client.flush()

    with caplog.at_level(logging.INFO, logger="security_events"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            await c.post(
                "/auth/recovery/redeem",
                json={"email": "redeem_fail@dojo.test", "code": "bad-code-here"},
            )

    logs = _capture_security_logs(caplog)
    assert any(
        log["event_type"] == "recovery_redeem" and log["result"] == "failure"
        for log in logs
    ), f"Expected recovery_redeem/failure event, got: {logs}"


@pytest.mark.asyncio
async def test_admin_token_generation_emits_log(
    db_client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """POST /auth/recovery/admin-token must emit an admin_token_generated/success event."""
    from tests.account_support import seed_account, seed_member

    target_user_id = str(uuid.uuid4())
    target_member_id = await seed_member(db_client, "target@dojo.test")
    await seed_account(db_client, "target@dojo.test", user_id=target_user_id)
    await db_client.flush()

    admin_claims = AccountClaims(
        sub="admin-uuid", email="admin@dojo.test", role="admin"
    )
    admin_token_repo = StubAdminTokenRepo()

    app.dependency_overrides[REQUIRE_ADMIN] = lambda: admin_claims
    app.dependency_overrides[get_admin_token_repo] = lambda: admin_token_repo

    with caplog.at_level(logging.INFO, logger="security_events"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test/api"
        ) as c:
            await c.post(
                "/auth/recovery/admin-token",
                json={"member_id": target_member_id},
            )

    logs = _capture_security_logs(caplog)
    assert any(
        log["event_type"] == "admin_token_generated"
        and log["result"] == "success"
        # The Account the token is for, resolved from the Member (#445).
        and log["detail"] == {"target_user_id": target_user_id}
        for log in logs
    ), f"Expected admin_token_generated/success event, got: {logs}"


# ===========================================================================
# #460 — every event raised while serving a request carries the client IP
# ===========================================================================

_FAKE_PASSKEY_LOGIN = {
    "email": "passkey_ip@dojo.test",
    "credential": {
        "id": "fake",
        "rawId": "fake",
        "response": {
            "clientDataJSON": "fake",
            "authenticatorData": "fake",
            "signature": "fake",
        },
        "type": "public-key",
    },
}


@pytest.mark.asyncio
async def test_sign_in_event_carries_client_ip(
    db_client, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="security_events"):
        async with AsyncClient(
            transport=ASGITransport(app=app, client=("203.0.113.7", 4242)),
            base_url="http://test/api",
        ) as c:
            await c.post("/auth/login/passkey/complete", json=_FAKE_PASSKEY_LOGIN)

    events = [
        e for e in _capture_security_logs(caplog) if e["event_type"] == "login_passkey"
    ]
    assert events and all(e["ip_address"] == "203.0.113.7" for e in events), events


@pytest.mark.asyncio
async def test_event_after_a_request_does_not_inherit_its_ip(
    db_client, caplog: pytest.LogCaptureFixture
) -> None:
    """The bound IP ends with its request: a later event outside one has none."""
    from app.core.security_logger import log_security_event

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("203.0.113.7", 4242)),
        base_url="http://test/api",
    ) as c:
        await c.post("/auth/login/passkey/complete", json=_FAKE_PASSKEY_LOGIN)

    with caplog.at_level(logging.INFO, logger="security_events"):
        log_security_event("login_passkey", "failure")

    assert "ip_address" not in _capture_security_logs(caplog)[-1]


def test_every_event_type_is_documented_for_operators():
    """Operators filter the journal by event_type, so docs/deployment.md
    must name every one the app can emit."""
    from app.core.security_logger import _VALID_EVENT_TYPES

    root = Path(os.environ.get("REPO_ROOT", Path(__file__).parents[2]))
    doc = (root / "docs" / "deployment.md").read_text()
    missing = sorted(t for t in _VALID_EVENT_TYPES if f"`{t}`" not in doc)
    assert not missing, (
        f"add to the Security events tables in docs/deployment.md: {missing}"
    )
