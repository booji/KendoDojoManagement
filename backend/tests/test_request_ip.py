"""Client-IP resolution behind a trusted reverse proxy (issue #200).

The app sits behind Traefik in UAT/PROD, so every request's peer IP is the
proxy's container IP. `client_ip` must honour X-Forwarded-For — but only when
TRUST_PROXY_XFF is explicitly enabled, so dev stays spoof-proof.
"""

from starlette.requests import Request

from app import config
from app.core.request_ip import client_ip


def _request(peer: str | None, headers: dict[str, str] | None = None) -> Request:
    header_list = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {
        "type": "http",
        "client": (peer, 12345) if peer else None,
        "headers": header_list,
    }
    return Request(scope)


def test_defaults_to_peer_ip_when_untrusted(monkeypatch) -> None:
    """Flag off (dev default): use peer IP, ignore any X-Forwarded-For."""
    monkeypatch.setattr(config, "TRUST_PROXY_XFF", False)
    req = _request("10.0.0.5", {"X-Forwarded-For": "1.2.3.4"})
    assert client_ip(req) == "10.0.0.5"


def test_uses_xff_when_trusted(monkeypatch) -> None:
    """Flag on (behind Traefik): use the client IP from X-Forwarded-For."""
    monkeypatch.setattr(config, "TRUST_PROXY_XFF", True)
    req = _request("10.0.0.5", {"X-Forwarded-For": "203.0.113.7"})
    assert client_ip(req) == "203.0.113.7"


def test_takes_leftmost_xff_entry_when_trusted(monkeypatch) -> None:
    """Leftmost XFF entry is the real client; the rest are proxy hops."""
    monkeypatch.setattr(config, "TRUST_PROXY_XFF", True)
    req = _request("10.0.0.5", {"X-Forwarded-For": " 203.0.113.7 , 10.0.0.1 "})
    assert client_ip(req) == "203.0.113.7"


def test_falls_back_to_peer_when_trusted_but_no_xff(monkeypatch) -> None:
    """Trusted but header absent → peer IP."""
    monkeypatch.setattr(config, "TRUST_PROXY_XFF", True)
    req = _request("10.0.0.5")
    assert client_ip(req) == "10.0.0.5"


def test_unknown_when_no_client_and_no_xff(monkeypatch) -> None:
    monkeypatch.setattr(config, "TRUST_PROXY_XFF", False)
    req = _request(None)
    assert client_ip(req) == "unknown"
