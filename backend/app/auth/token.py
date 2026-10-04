from datetime import UTC, datetime, timedelta

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey

from app import config
from app.auth.models import AccountClaims


def _key() -> OctKey:
    if not config.JWT_SECRET:
        raise RuntimeError("JWT_SECRET environment variable must be set")
    return OctKey.import_key(config.JWT_SECRET.encode())


def encode_token(claims: AccountClaims, session_started_at: int | None = None) -> str:
    """Mint an access token for ``claims``.

    ``sst`` is when the *session* began, as opposed to ``iat``, when this
    particular token was minted. Sliding renewal re-issues a token repeatedly
    and each re-issue carries the original ``sst`` forward, so the session has
    a hard ceiling (``SESSION_MAX_MINUTES``) no amount of activity can slide
    past. Omit ``session_started_at`` and a new session starts here — that is
    what every login ceremony wants.
    """
    now = int(datetime.now(UTC).timestamp())
    started = session_started_at if session_started_at is not None else now
    # Never past the session ceiling: a token minted just before it would
    # otherwise carry a full lifetime beyond it, making the documented maximum
    # session silently JWT_EXPIRE_MINUTES longer than it says.
    expire = min(
        int(
            (
                datetime.now(UTC) + timedelta(minutes=config.JWT_EXPIRE_MINUTES)
            ).timestamp()
        ),
        started + 60 * config.SESSION_MAX_MINUTES,
    )
    payload = {
        "sub": claims.sub,
        "email": claims.email,
        "role": claims.role,
        "is_active": claims.is_active,
        "iat": now,
        "sst": started,
        "exp": expire,
    }
    return jwt.encode({"alg": "HS256"}, payload, _key())


def seconds_until_expiry(token: str) -> int:
    """How long ``token`` has left, for a cookie that must not outlive it.

    ``encode_token`` clamps ``exp`` to the session ceiling, so the last token of
    a session is short of a full lifetime. A cookie given the full lifetime
    anyway survives the token inside it: the browser keeps sending something
    already dead, and the stale cookie rides along to /login (#397).

    ``token`` must have been minted by :func:`encode_token`; a token that is
    unreadable or already expired has nothing left, which is 0.
    """
    try:
        exp = int(jwt.decode(token, _key(), algorithms=["HS256"]).claims["exp"])
    except (JoseError, ValueError, KeyError):
        return 0
    return max(0, exp - int(datetime.now(UTC).timestamp()))


def renewal_due(token: str) -> int | None:
    """The session start to carry forward, if ``token`` should be re-issued now.

    Returns ``None`` when the token is still in the first half of its life
    (re-issuing on every request would be pure churn) or when the session has
    reached its hard ceiling — there the token is left to expire, which sends
    the user back through a login ceremony as intended.

    ``token`` must already have passed :func:`decode_token`; this only reads
    the timestamps back out of it.
    """
    try:
        payload = jwt.decode(token, _key(), algorithms=["HS256"]).claims
        exp = int(payload["exp"])
        # Tokens minted before #387 carry neither claim. Derive both from the
        # configured lifetime so an in-flight session survives the deploy.
        issued = int(payload.get("iat", exp - 60 * config.JWT_EXPIRE_MINUTES))
        started = int(payload.get("sst", issued))
    except (JoseError, ValueError, KeyError):
        return None

    now = int(datetime.now(UTC).timestamp())
    if now < issued + (exp - issued) // 2:
        return None
    if now >= started + 60 * config.SESSION_MAX_MINUTES:
        return None
    return started


def decode_token(token: str) -> AccountClaims:
    try:
        token_obj = jwt.decode(token, _key(), algorithms=["HS256"])
        payload = token_obj.claims
        if int(payload["exp"]) < int(datetime.now(UTC).timestamp()):
            raise ValueError("Token expired")
    # JoseError covers a malformed or badly-signed token. It does NOT subclass
    # ValueError, so leaving it out let a corrupt access_token cookie escape as
    # an unhandled exception — a 500 from every authenticated endpoint instead
    # of the 401 the guard intends.
    except (JoseError, ValueError, KeyError) as exc:
        raise ValueError("Invalid or expired token") from exc
    return AccountClaims(
        sub=payload["sub"],
        email=payload["email"],
        role=payload["role"],
        is_active=payload["is_active"],
        recovery_session=bool(payload.get("recovery_session", False)),
    )


def encode_recovery_token(user_id: str, email: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=15)
    payload = {
        "sub": user_id,
        "email": email,
        "role": "member",
        "is_active": True,
        "recovery_session": True,
        "exp": int(expire.timestamp()),
    }
    return jwt.encode({"alg": "HS256"}, payload, _key())
