from datetime import UTC, datetime, timedelta

from joserfc import jwt
from joserfc.jwk import OctKey

from app import config
from app.auth.models import UserClaims


def _key() -> OctKey:
    if not config.JWT_SECRET:
        raise RuntimeError("JWT_SECRET environment variable must be set")
    return OctKey.import_key(config.JWT_SECRET.encode())


def encode_token(claims: UserClaims) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=config.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": claims.sub,
        "email": claims.email,
        "role": claims.role,
        "is_active": claims.is_active,
        "exp": int(expire.timestamp()),
    }
    return jwt.encode({"alg": "HS256"}, payload, _key())


def decode_token(token: str) -> UserClaims:
    try:
        token_obj = jwt.decode(token, _key(), algorithms=["HS256"])
        payload = token_obj.claims
        if int(payload["exp"]) < int(datetime.now(UTC).timestamp()):
            raise ValueError("Token expired")
    except (ValueError, KeyError) as exc:
        raise ValueError("Invalid or expired token") from exc
    return UserClaims(
        sub=payload["sub"],
        email=payload["email"],
        role=payload["role"],
        is_active=payload["is_active"],
    )
