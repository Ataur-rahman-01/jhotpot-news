"""
base.py — Shared helpers for every per-site HTML scraper.

Each concrete scraper (samakal.py, jugantor.py, …) exposes:

    async def fetch(site: dict) -> list[dict]

and returns article dicts in the SAME shape as rss_parser.fetch_site:

    {url, title, summary, image_url, published_at,
     source, language, scraped_at}

This file provides only the building blocks — HTTP client, headers,
error contract — so the per-site modules stay short and focused.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx
from lxml import etree


# ─────────────────────────────────────────────────────────────────────────────
# HTTP defaults
# ─────────────────────────────────────────────────────────────────────────────
# A real Chrome UA. Several BD news sites 403/404 on the default httpx or
# feedparser agents but answer happily to this string.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# These extra headers help against naive bot detection that checks for
# presence/values rather than full TLS fingerprinting.
DEFAULT_HEADERS: Dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
    # NOTE: deliberately omit 'br'. httpx only decompresses gzip/deflate
    # natively; advertising 'br' makes some servers (e.g. bhorerkagoj.com)
    # return Brotli-compressed bytes that we cannot decode without the
    # optional `brotli` package. gzip is universally supported.
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Sitemaps can be 200–400 KB; allow generous time. Bangladesh-hosted servers
# can be slow from US GHA runners.
DEFAULT_TIMEOUT_SECONDS = 20.0


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers — keep the per-site modules from each managing httpx settings.
# ─────────────────────────────────────────────────────────────────────────────
async def fetch_text(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    follow_redirects: bool = True,
) -> str:
    """GET a URL and return the response body decoded as text.

    Raises httpx.HTTPError on transport errors and httpx.HTTPStatusError on
    4xx/5xx — the caller (scraper module) is expected to catch and return
    [] on failure so one bad site can't kill the gather.
    """
    merged = {**DEFAULT_HEADERS, **(headers or {})}
    async with httpx.AsyncClient(
        headers=merged,
        timeout=timeout,
        follow_redirects=follow_redirects,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def fetch_bytes(
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    follow_redirects: bool = True,
) -> bytes:
    """GET a URL and return the raw bytes — preferred for lxml XML parsing.

    lxml's XML parser is happiest with bytes (it inspects the XML declaration
    for encoding) rather than a pre-decoded str.
    """
    merged = {**DEFAULT_HEADERS, **(headers or {})}
    async with httpx.AsyncClient(
        headers=merged,
        timeout=timeout,
        follow_redirects=follow_redirects,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


# ─────────────────────────────────────────────────────────────────────────────
# Article dict builder — single source of truth for the shape.
# ─────────────────────────────────────────────────────────────────────────────
def build_article(
    *,
    site: Dict[str, Any],
    url: str,
    title: str,
    summary: str = "",
    image_url: Optional[str] = None,
    published_at: Optional[datetime] = None,
    scraped_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Construct an article dict in the exact shape rss_parser.fetch_site returns,
    so the rest of the pipeline (db.py, gemini.py) does not need to care
    whether the source was RSS or HTML.

    Mandatory:
        site, url, title

    Optional (filled with safe defaults):
        summary       defaults to ""
        image_url     defaults to None  (Flutter placeholder kicks in)
        published_at  defaults to utcnow() — mirrors rss_parser's fallback
        scraped_at    defaults to utcnow()
    """
    now = datetime.utcnow()
    return {
        "url": url,
        "title": title,
        "summary": summary,
        "image_url": image_url,
        "published_at": published_at or now,
        "source": site.get("slug", ""),
        "language": site.get("language", ""),
        "scraped_at": scraped_at or now,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Type alias for the per-site fetch contract — used by the registry.
# ─────────────────────────────────────────────────────────────────────────────
ScraperFn = Callable[[Dict[str, Any]], Awaitable[List[Dict[str, Any]]]]


# ─────────────────────────────────────────────────────────────────────────────
# Shared Google News sitemap parser
# ─────────────────────────────────────────────────────────────────────────────
# Many BD news sites publish a Google News sitemap at /news_sitemap.xml.
# It's a structured XML feed with:
#   <urlset>
#     <url>
#       <loc>...</loc>
#       <news:news>
#         <news:title>...</news:title>
#         <news:publication_date>2026-05-23T15:46:03+06:00</news:publication_date>
#         <news:keywords>...</news:keywords>
#       </news:news>
#       <image:image><image:loc>...</image:loc></image:image>   ← rare
#     </url>
#   </urlset>
#
# Any site whose sitemap matches this schema can use parse_google_news_sitemap()
# directly — its scraper module collapses to ~10 lines.
# ─────────────────────────────────────────────────────────────────────────────

GOOGLE_NEWS_NS = {
    "sm":    "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news":  "http://www.google.com/schemas/sitemap-news/0.9",
    "image": "http://www.google.com/schemas/sitemap-image/1.1",
}


def _xml_text(node: "etree._Element", xpath: str) -> Optional[str]:
    """Return stripped text of the first XPath match, or None."""
    found = node.find(xpath, namespaces=GOOGLE_NEWS_NS)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _parse_iso_to_naive_utc(value: Optional[str]) -> Optional[datetime]:
    """ISO-8601 with offset (e.g. 2026-05-23T15:46:03+06:00) → naive UTC datetime.

    Naive UTC is the schema-wide convention (matches rss_parser.parse_date)
    so Mongo + the FastAPI side never have to think about timezones.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def parse_google_news_sitemap(
    site: Dict[str, Any],
    sitemap_url: str,
    *,
    max_articles: int = 300,
) -> List[Dict[str, Any]]:
    """
    Fetch and parse a Google News sitemap into article dicts.

    Args:
        site:         the site config from sites.py (carries slug + language)
        sitemap_url:  full URL to the /news_sitemap.xml endpoint
        max_articles: cap on entries returned per run — defensive against a
                      site republishing 5,000 entries at once

    Returns:
        List of article dicts in the standard pipeline shape (build_article).
        Empty list on ANY failure — caller must not raise.

    Behaviour notes:
        - image_url is taken from <image:loc> if present, else None
        - summary is built from <news:keywords> (comma-list) — gives Gemini
          extra signal beyond the headline for category classification
        - published_at is converted from sitemap's timezone-offset to naive UTC
    """
    slug = site.get("slug", "?")

    # Stage 1 — fetch raw XML bytes.
    try:
        raw = await fetch_bytes(sitemap_url)
    except Exception as exc:  # noqa: BLE001
        print(f"[{slug}] sitemap fetch failed: {type(exc).__name__}: {exc}")
        return []

    # Stage 2 — parse with lxml. recover=True salvages partially-broken XML.
    try:
        parser = etree.XMLParser(recover=True, huge_tree=False)
        root = etree.fromstring(raw, parser=parser)
    except etree.XMLSyntaxError as exc:
        print(f"[{slug}] sitemap parse failed: {exc}")
        return []

    if root is None:
        print(f"[{slug}] sitemap root element missing")
        return []

    # Stage 3 — iterate <url> entries.
    url_nodes = root.findall("sm:url", namespaces=GOOGLE_NEWS_NS)
    if not url_nodes:
        # Some sitemaps strip the default namespace prefix.
        url_nodes = root.findall("url")

    articles: List[Dict[str, Any]] = []

    for node in url_nodes[:max_articles]:
        loc = _xml_text(node, "sm:loc") or _xml_text(node, "loc")
        if not loc:
            continue

        title = _xml_text(node, "news:news/news:title") or ""
        date_str = _xml_text(node, "news:news/news:publication_date")
        published_at = _parse_iso_to_naive_utc(date_str)

        keywords = _xml_text(node, "news:news/news:keywords") or ""
        summary = keywords.replace(",", ", ").strip()

        image_url = _xml_text(node, "image:image/image:loc")

        articles.append(build_article(
            site=site,
            url=loc,
            title=title,
            summary=summary,
            image_url=image_url,
            published_at=published_at,
        ))

    print(
        f"[{slug}] sitemap parsed {len(articles)} entries "
        f"(of {len(url_nodes)} in feed)"
    )
    return articles
