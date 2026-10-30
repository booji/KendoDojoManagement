"""Structured security event logging — pure function, no I/O beyond logging."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

_VALID_EVENT_TYPES = frozenset(
    {
        "login_passkey",
        "recovery_redeem",
        "admin_token_generated",
        "passkey_registered",
        "passkey_deleted",
        "invite_minted",
        "invite_revoked",
        "invite_redeemed",
        "setup_claim",
        "sign_out_everywhere",
        # Admin writes and exports (#460)
        "member_created",
        "member_updated",
        "member_erased",
    }
)

# The client IP of the request being served, bound by ClientIPMiddleware, so
# every event raised during a request records where it came from without each
# call site threading the IP through (#460). None outside a request.
request_ip: ContextVar[str | None] = ContextVar("security_event_ip", default=None)

# Own stdout handler (#461): nothing configures the root logger, so without
# one every INFO event fell through to logging.lastResort and was dropped.
# The container's stdout is the journal (docs/deployment.md, "Logs").
# propagate=False so a later root config cannot print each event twice.
_logger = logging.getLogger("security_events")
_logger.setLevel(logging.INFO)
_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_handler)
_logger.propagate = False


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
    ip_address = ip_address or request_ip.get()
    if ip_address is not None:
        entry["ip_address"] = ip_address
    if detail is not None:
        entry["detail"] = detail

    _logger.info(json.dumps(entry, separators=(",", ":")))
