"""
cf_fetch.py — Cloudflare-bypass HTTP client for sources whose WAF blocks
GCP/datacenter IPs when contacted via plain httpx.

Uses curl_cffi with Chrome TLS impersonation (ja3/ja4 fingerprint) — Cloudflare
treats the request as a real Chrome browser instead of a Python HTTP client,
so the body is returned instead of a managed-challenge / 403 page.

Used ONLY for sources listed in CF_BYPASS_SOURCES. Every other site continues
through the existing httpx flow (faster, lighter, no native libcurl dep).
"""

from __future__ import annotations

from typing import Optional, Set

try:
    from curl_cffi.requests import AsyncSession
    _CURL_CFFI_OK = True
except ImportError:  # pragma: no cover — curl_cffi is in requirements.txt
    _CURL_CFFI_OK = False
    AsyncSession = None  # type: ignore[assignment]


# Slugs whose feeds / article pages are blocked by Cloudflare from Cloud Run.
# Verified May 2026: identical fetches succeed from a residential IP via plain
# httpx, but return a challenge page from GCP egress. curl_cffi's Chrome TLS
# fingerprint slips past in both cases.
CF_BYPASS_SOURCES: Set[str] = {"ittefaq", "samakal", "banglatribune"}

# curl_cffi's TLS handshake is a touch slower than httpx; give it margin.
CF_TIMEOUT_SECONDS = 25.0


def needs_bypass(source: Optional[str]) -> bool:
    """Return True iff the given source slug should be fetched via curl_cffi."""
    return bool(source) and source in CF_BYPASS_SOURCES


async def fetch_text(url: str, *, timeout: float = CF_TIMEOUT_SECONDS) -> str:
    """GET via Chrome-impersonated TLS. Returns decoded text. Raises on failure."""
    if not _CURL_CFFI_OK:
        raise RuntimeError(
            "curl_cffi not installed — required for CF-bypass sources"
        )
    async with AsyncSession(impersonate="chrome", timeout=timeout) as session:
        resp = await session.get(url)
        resp.raise_for_status()
        return resp.text


async def fetch_bytes(url: str, *, timeout: float = CF_TIMEOUT_SECONDS) -> bytes:
    """GET via Chrome-impersonated TLS. Returns raw bytes. Raises on failure.

    Prefer this when the result is parsed by lxml or fed to feedparser — those
    inspect the XML declaration for encoding and work best on raw bytes.
    """
    if not _CURL_CFFI_OK:
        raise RuntimeError(
            "curl_cffi not installed — required for CF-bypass sources"
        )
    async with AsyncSession(impersonate="chrome", timeout=timeout) as session:
        resp = await session.get(url)
        resp.raise_for_status()
        return resp.content
