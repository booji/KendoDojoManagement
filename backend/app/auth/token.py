from datetime import UTC, datetime, timedelta

from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import OctKey

from app import config
from app.auth.models import AccountClaims

# Only recovery tokens are JWTs now; session cookies are Auth Session ids
# (#485, ADR-0008). #486 moves recovery tokens to rows too.


def _key() -> OctKey:
    if not config.JWT_SECRET:
        raise RuntimeError("JWT_SECRET environment variable must be set")
    return OctKey.import_key(config.JWT_SECRET.encode())


def decode_token(token: str) -> AccountClaims:
    try:
        token_obj = jwt.decode(token, _key(), algorithms=["HS256"])
        payload = token_obj.claims
        if int(payload["exp"]) < int(datetime.now(UTC).timestamp()):
            raise ValueError("Token expired")
    # JoseError covers a malformed or badly-signed token. It does NOT subclass
    # ValueError, so leaving it out let a corrupt token escape as an unhandled
    # exception — a 500 instead of the 401 the caller intends.
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
