"""Structured security event logging — pure function, no I/O beyond logging."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

_VALID_EVENT_TYPES = frozenset(
    {
        "login_passkey",
        "recovery_redeem",
        "admin_token_generated",
        "passkey_registered",
        "passkey_deleted",
        "checkin_token_generated",
    }
)

_logger = logging.getLogger("security_events")
_logger.setLevel(logging.INFO)


def log_security_event(
    event_type: str,
    result: str,
    *,
    user_id: str | None = None,
    ip_address: str | None = None,
    detail: object | None = None,
) -> None:
    """Emit a single-line JSON security event to the 'security_events' logger."""
    if event_type not in _VALID_EVENT_TYPES:
        raise ValueError(f"Unknown security event type: {event_type!r}")
    entry: dict[str, object] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event_type": event_type,
        "result": result,
    }
    if user_id is not None:
        entry["user_id"] = user_id
    if ip_address is not None:
        entry["ip_address"] = ip_address
    if detail is not None:
        entry["detail"] = detail

    _logger.info(json.dumps(entry, separators=(",", ":")))
