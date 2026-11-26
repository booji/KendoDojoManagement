"""Recovery code and admin token generation, hashing and checking.

No database I/O. Every bcrypt call runs off the event loop, which its second
or two would otherwise stall: hash_codes, hash_admin_token and match_secret
are async for that reason alone.
"""

from __future__ import annotations

import secrets
import string
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any, Literal

import anyio
import bcrypt

_ALPHABET = string.ascii_letters + string.digits
_SEGMENT_LEN = 4
_SEGMENTS = 3
_CODE_COUNT = 8
_ADMIN_TOKEN_BYTES = 32
_ADMIN_TOKEN_EXPIRY_MINUTES = 60
# bcrypt cost of every recovery code and admin token hash: the default.
BCRYPT_ROUNDS = 12
# bcrypt reads at most this many bytes of a secret, and raises past them (#588).
MAX_SECRET_BYTES = 72

SecretKind = Literal["code", "admin_token"]


def _random_segment() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_SEGMENT_LEN))


def generate_recovery_codes() -> list[str]:
    """Generate exactly 8 cryptographically random codes in xxxx-xxxx-xxxx format."""
    return [
        "-".join(_random_segment() for _ in range(_SEGMENTS))
        for _ in range(_CODE_COUNT)
    ]


def _hash(secret: str) -> str:
    return bcrypt.hashpw(secret.encode(), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()


async def hash_codes(codes: list[str]) -> list[str]:
    """Bcrypt-hash each plaintext recovery code."""
    return await anyio.to_thread.run_sync(lambda: [_hash(code) for code in codes])


def generate_admin_token_plaintext() -> str:
    """Generate a cryptographically secure plaintext admin recovery token."""
    return secrets.token_urlsafe(_ADMIN_TOKEN_BYTES)


async def hash_admin_token(plaintext: str) -> str:
    """Bcrypt-hash a plaintext admin recovery token."""
    return await anyio.to_thread.run_sync(_hash, plaintext)


def admin_token_expiry() -> datetime:
    """Return the expiry datetime for a newly generated admin token."""
    return datetime.now(UTC) + timedelta(minutes=_ADMIN_TOKEN_EXPIRY_MINUTES)


@cache
def _dummy_hash(rounds: int) -> str:
    return bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt(rounds)).decode()


def _first_match(code: str, hashes: list[str]) -> int | None:
    padding = [_dummy_hash(BCRYPT_ROUNDS)] * (_CODE_COUNT + 1 - len(hashes))
    for index, code_hash in enumerate(hashes + padding):
        if bcrypt.checkpw(code.encode(), code_hash.encode()) and index < len(hashes):
            return index
    return None


async def match_secret(
    code: str, codes: list[dict[str, Any]], admin_tokens: list[dict[str, Any]]
) -> tuple[SecretKind, dict[str, Any]] | None:
    """The first of the recovery `codes` and `admin_tokens` records that
    `code` matches, and its kind; None if none does.

    Compares against at least a full code set plus one admin token, padding
    with a dummy hash, so the cost does not say whether an email has an
    Account, or how many unused codes it has (#588).
    """
    hashes = [c["code_hash"] for c in codes] + [t["token_hash"] for t in admin_tokens]
    index = await anyio.to_thread.run_sync(_first_match, code, hashes)
    if index is None:
        return None
    if index < len(codes):
        return "code", codes[index]
    return "admin_token", admin_tokens[index - len(codes)]


def is_admin_token_valid(token_record: dict) -> bool:
    """Return True if the token is unused and not expired."""
    if token_record["used_at"] is not None:
        return False
    expires_at = token_record["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return datetime.now(UTC) < expires_at
