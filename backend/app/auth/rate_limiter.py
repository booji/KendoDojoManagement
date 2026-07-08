import os

from slowapi import Limiter

from app.core.request_ip import client_ip

PER_IP_LIMIT: str = os.getenv("RATE_LIMIT_PER_IP", "20/minute")

limiter = Limiter(key_func=client_ip)
