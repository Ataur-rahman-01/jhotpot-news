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

from typing import Dict, Optional, Set
from urllib.parse import urlparse

try:
    from curl_cffi.requests import AsyncSession
    _CURL_CFFI_OK = True
except ImportError:  # pragma: no cover — curl_cffi is in requirements.txt
    _CURL_CFFI_OK = False
    AsyncSession = None  # type: ignore[assignment]


# Slugs whose feeds / article pages are blocked by Cloudflare from Cloud Run.
# Verified May 2026: identical fetches succeed from a residential IP via plain
# httpx, but return a challenge page from GCP egress. curl_cffi's Chrome TLS
# fingerprint slips past for RSS endpoints; article pages additionally require
# a warm session (cookies from the homepage) + a Referer header.
CF_BYPASS_SOURCES: Set[str] = {"ittefaq", "samakal", "banglatribune"}

# curl_cffi's TLS handshake is a touch slower than httpx; give it margin.
CF_TIMEOUT_SECONDS = 25.0


def needs_bypass(source: Optional[str]) -> bool:
    """Return True iff the given source slug should be fetched via curl_cffi."""
    return bool(source) and source in CF_BYPASS_SOURCES


def _origin_of(url: str) -> str:
    """Return scheme://host/ — used as Referer and the homepage-warm URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/"


# ─────────────────────────────────────────────────────────────────────────────
# One-shot fetchers — open + close a session per call. Cheap to call but each
# request is "cold" (no shared cookies). Fine for feed/sitemap fetches that
# happen once per site per run.
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Warm-session pool — for fetching many article pages on the same host.
# Cloudflare's stricter rules on article pages (vs RSS endpoints) check for
# cf_clearance / __cf_bm cookies; those are only set after a successful
# homepage visit. A long-lived session that hit the homepage once carries
# those cookies through subsequent requests.
# ─────────────────────────────────────────────────────────────────────────────
class CFSessionPool:
    """One curl_cffi AsyncSession per host, pre-warmed by visiting the host root.

    Usage:
        async with CFSessionPool() as pool:
            html = await pool.get_text("https://www.ittefaq.com.bd/.../article-id")
            html2 = await pool.get_text("https://www.ittefaq.com.bd/.../other")
            # second call reuses the warmed session + cookies.
    """

    def __init__(self, timeout: float = CF_TIMEOUT_SECONDS) -> None:
        if not _CURL_CFFI_OK:
            raise RuntimeError(
                "curl_cffi not installed — required for CF-bypass sources"
            )
        self._timeout = timeout
        self._sessions: Dict[str, "AsyncSession"] = {}
        self._warmed: Set[str] = set()

    async def __aenter__(self) -> "CFSessionPool":
        return self

    async def __aexit__(self, *_exc) -> None:
        for s in self._sessions.values():
            try:
                await s.close()
            except Exception:
                pass
        self._sessions.clear()

    async def _session_for(self, origin: str) -> "AsyncSession":
        session = self._sessions.get(origin)
        if session is None:
            session = AsyncSession(impersonate="chrome", timeout=self._timeout)
            self._sessions[origin] = session
        if origin not in self._warmed:
            # Visit the homepage so Cloudflare hands us cf_clearance / __cf_bm.
            # Failure is non-fatal — we still try the article fetch; some sites
            # don't require the warm step, and a homepage 403 doesn't always
            # mean article pages will 403 too.
            try:
                await session.get(origin)
            except Exception:
                pass
            self._warmed.add(origin)
        return session

    async def get_text(self, url: str) -> str:
        origin = _origin_of(url)
        session = await self._session_for(origin)
        resp = await session.get(url, headers={"Referer": origin})
        resp.raise_for_status()
        return resp.text
