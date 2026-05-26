"""Per-IP rate limiter shared by all routers.

Cloud Run terminates TLS and forwards the real client IP in the
`X-Forwarded-For` header. `slowapi.util.get_remote_address` does NOT
read that header — it returns `request.client.host`, which on Cloud Run
is always the Google frontend proxy. That makes every request look like
it came from the same IP, so all users would share one bucket and a
single noisy client (or our own probing) trips the limit for everyone.

`_client_ip` reads X-Forwarded-For first (first IP = original client),
falling back to `get_remote_address` for local dev where the header
is absent.
"""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        # X-Forwarded-For is a comma-separated chain: "client, proxy1, proxy2".
        # The leftmost entry is the original client.
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip)
