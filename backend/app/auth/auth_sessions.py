"""Auth Sessions: starting, resolving and ending them (#455, ADR-0008).

The cookie holds ``secrets.token_urlsafe(32)``; the row holds its SHA-256.
Role, active flag and email are read from the Account on every request, so
nothing about the Account is ever snapshotted into the Auth Session.

Lifetime: ``JWT_EXPIRE_MINUTES`` idle, ``SESSION_MAX_MINUTES`` absolute (the
names predate this module and are deployment surface, so they stay).
``expires_at`` slides forward once an Auth Session is past the halfway mark of its
idle window — not on every request — and never past the absolute ceiling.

A ``recovery`` Auth Session (#486) is what redeeming a recovery code buys: 15
minutes, never slid, good only for enrolling one passkey.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from app import config
from app.auth.auth_session_repository import AbstractAuthSessionRepository
from app.auth.models import AccountClaims, AuthSessionKind

_RECOVERY_LIFETIME = timedelta(minutes=15)


def _idle() -> timedelta:
    return timedelta(minutes=config.JWT_EXPIRE_MINUTES)


def _ceiling(created_at: datetime) -> datetime:
    return created_at + timedelta(minutes=config.SESSION_MAX_MINUTES)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_auth_session(
    account_id: str,
    passkey_id: str | None,
    now: datetime,
    *,
    kind: AuthSessionKind = "sign_in",
) -> tuple[str, dict[str, Any]]:
    """A fresh token value and the row that stands behind it."""
    value = secrets.token_urlsafe(32)
    if kind == "recovery":
        expires_at = now + _RECOVERY_LIFETIME
    else:
        expires_at = min(now + _idle(), _ceiling(now))
    return value, {
        "token_hash": hash_token(value),
        "account_id": account_id,
        "passkey_id": passkey_id,
        "kind": kind,
        "created_at": now,
        "expires_at": expires_at,
    }


def slid_expiry(
    created_at: datetime, expires_at: datetime, now: datetime
) -> datetime | None:
    """The new ``expires_at`` if this request should slide it, else ``None``.

    ``None`` in the first half of the idle window, where writing on every
    request would be pure churn, and at the ceiling, where there is nowhere
    left to slide to.
    """
    if now < expires_at - _idle() / 2:
        return None
    slid = min(now + _idle(), _ceiling(created_at))
    return slid if slid > expires_at else None


async def start_auth_session(
    repo: AbstractAuthSessionRepository,
    account_id: str,
    passkey_id: str | None = None,
    *,
    kind: AuthSessionKind = "sign_in",
) -> str:
    """Store a new Auth Session and return the token value for it.

    Expired rows are swept here, in one indexed statement: sign-in is
    frequent enough to keep the table small, and there is no scheduler. The
    caller commits.
    """
    now = datetime.now(UTC)
    await repo.delete_expired(now)
    value, row = new_auth_session(account_id, passkey_id, now, kind=kind)
    await repo.add(row)
    return value


async def resolve_auth_session(
    repo: AbstractAuthSessionRepository, value: str
) -> AccountClaims | None:
    """The Account behind token ``value``, read as of now, or ``None``.

    ``recovery_session`` on the result says which kind of Auth Session it is;
    each caller decides whether that kind is welcome.
    """
    token_hash = hash_token(value)
    row = await repo.find(token_hash)
    now = datetime.now(UTC)
    if row is None or now >= row["expires_at"]:
        return None
    recovery = row["kind"] == "recovery"
    slid = None if recovery else slid_expiry(row["created_at"], row["expires_at"], now)
    if slid is not None:
        await repo.slide(token_hash, slid)
    return AccountClaims(
        sub=row["account_id"],
        email=row["email"],
        role=row["role"],
        is_active=row["is_active"],
        recovery_session=recovery,
    )


async def end_every_auth_session(
    repo: AbstractAuthSessionRepository, account_id: str
) -> None:
    """Sign the Account out on every device, this one included (#487).

    Recovery tokens go too (ADR-0008). Someone signing out everywhere may
    be doing it because their Account is compromised, and a recovery token
    left alive would give an attacker 15 minutes to enrol a passkey. The cost
    is a genuine recovery in flight elsewhere, which then needs a fresh code.
    """
    await repo.delete_for_account(account_id)


async def end_auth_session(repo: AbstractAuthSessionRepository, value: str) -> bool:
    """Delete the Auth Session behind ``value``; whether there was one to end."""
    return await repo.delete(hash_token(value))
