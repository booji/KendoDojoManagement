"""Recovery code generation — pure functions, no I/O."""

from __future__ import annotations

import secrets
import string

import bcrypt

_ALPHABET = string.ascii_letters + string.digits
_SEGMENT_LEN = 4
_SEGMENTS = 3
_CODE_COUNT = 8


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
