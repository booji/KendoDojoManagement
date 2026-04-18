"""Recovery code generation — pure functions, no I/O."""

from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime, timedelta

import bcrypt

_ALPHABET = string.ascii_letters + string.digits
_SEGMENT_LEN = 4
_SEGMENTS = 3
_CODE_COUNT = 8
_ADMIN_TOKEN_BYTES = 32
_ADMIN_TOKEN_EXPIRY_MINUTES = 60


def _random_segment() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_SEGMENT_LEN))


def generate_recovery_codes() -> list[str]:
    """Generate exactly 8 cryptographically random codes in xxxx-xxxx-xxxx format."""
    return [
        "-".join(_random_segment() for _ in range(_SEGMENTS))
        for _ in range(_CODE_COUNT)
    ]


def hash_codes(codes: list[str]) -> list[str]:
    """Bcrypt-hash each plaintext recovery code."""
    return [bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode() for code in codes]


def generate_admin_token_plaintext() -> str:
    """Generate a cryptographically secure plaintext admin recovery token."""
    return secrets.token_urlsafe(_ADMIN_TOKEN_BYTES)


def hash_admin_token(plaintext: str) -> str:
    """Bcrypt-hash a plaintext admin recovery token."""
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def admin_token_expiry() -> datetime:
    """Return the expiry datetime for a newly generated admin token."""
    return datetime.now(UTC) + timedelta(minutes=_ADMIN_TOKEN_EXPIRY_MINUTES)


def check_admin_token(plaintext: str, token_hash: str) -> bool:
    """Return True if plaintext matches token_hash."""
    return bcrypt.checkpw(plaintext.encode(), token_hash.encode())


def is_admin_token_valid(token_record: dict) -> bool:
    """Return True if the token is unused and not expired."""
    if token_record["used_at"] is not None:
        return False
    expires_at = token_record["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return datetime.now(UTC) < expires_at
