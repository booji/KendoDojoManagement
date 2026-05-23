import os

from fastapi import Request
from slowapi import Limiter

PER_IP_LIMIT: str = os.getenv("RATE_LIMIT_PER_IP", "20/minute")


def _real_ip(request: Request) -> str:
    # Use the actual peer IP, not X-Forwarded-For, to prevent spoofing.
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_real_ip)
