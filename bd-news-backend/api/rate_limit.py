"""Per-IP rate limiter shared by all routers.

Cloud Run terminates TLS and forwards client IP in X-Forwarded-For,
which get_remote_address handles correctly.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
