"""
rss_parser.py — Pure RSS → dict conversion for the 15 Bangladeshi news sites.

Public surface:
    fetch_site(site)    async — parse one site's RSS feed, return list of article dicts
    extract_image(entry) → Optional[str]  — best-effort image URL extraction
    parse_date(entry)    → datetime       — published_parsed → datetime, fallback to utcnow

Rules from SKILL.md:
    • image_url is a string URL or None — NEVER download the image
    • Bangla → language='bn', English → language='en' (carried over from site config)
    • content / AI fields are NOT set here — that is gemini.py + db.py territory
    • Errors per-feed are swallowed (return []) — one broken site must not stop the run
"""

from __future__ import annotations

import asyncio
import calendar
import html as _html_module
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

import feedparser

from scraper.cf_fetch import fetch_bytes as cf_fetch_bytes, needs_bypass

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags and unescape HTML entities (e.g. Daily Star wraps titles in <a>)."""
    return _html_module.unescape(_HTML_TAG_RE.sub("", text)).strip()


# ─────────────────────────────────────────────────────────────────────────────
# Image extraction
# ─────────────────────────────────────────────────────────────────────────────
def extract_image(entry: Any) -> Optional[str]:
    """
    Try three RSS conventions in order:
        1. media:thumbnail   → entry.media_thumbnail[0]['url']
        2. media:content     → entry.media_content[0]['url']
        3. <enclosure>       → entry.enclosures[0]['url']

    Returns the first URL found, or None. Never raises — bad feeds get None.
    """
    try:
        thumbs = entry.get("media_thumbnail") if hasattr(entry, "get") else getattr(entry, "media_thumbnail", None)
        if thumbs:
            url = thumbs[0].get("url")
            if url:
                return url
    except (AttributeError, IndexError, KeyError, TypeError):
        pass

    try:
        media = entry.get("media_content") if hasattr(entry, "get") else getattr(entry, "media_content", None)
        if media:
            url = media[0].get("url")
            if url:
                return url
    except (AttributeError, IndexError, KeyError, TypeError):
        pass

    try:
        encs = entry.get("enclosures") if hasattr(entry, "get") else getattr(entry, "enclosures", None)
        if encs:
            url = encs[0].get("url")
            if url:
                return url
    except (AttributeError, IndexError, KeyError, TypeError):
        pass

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Date parsing
# ─────────────────────────────────────────────────────────────────────────────
def parse_date(entry: Any) -> datetime:
    """
    Convert feedparser's `published_parsed` (a time.struct_time in UTC) to a
    naive UTC datetime. Falls back to datetime.utcnow() when the field is
    missing or malformed — a missing date never blocks ingestion.
    """
    try:
        published = entry.get("published_parsed") if hasattr(entry, "get") else getattr(entry, "published_parsed", None)
        if published:
            # feedparser already normalises to UTC; calendar.timegm treats the
            # struct_time as UTC (unlike time.mktime which assumes local time).
            return datetime.utcfromtimestamp(calendar.timegm(published))
    except (AttributeError, TypeError, ValueError, OverflowError):
        pass

    # Some feeds use <updated> instead of <pubDate>.
    try:
        updated = entry.get("updated_parsed") if hasattr(entry, "get") else getattr(entry, "updated_parsed", None)
        if updated:
            return datetime.utcfromtimestamp(calendar.timegm(updated))
    except (AttributeError, TypeError, ValueError, OverflowError):
        pass

    return datetime.utcnow()


# ─────────────────────────────────────────────────────────────────────────────
# Main per-site fetcher
# ─────────────────────────────────────────────────────────────────────────────
async def fetch_site(site: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    Parse one site's RSS feed into a list of article dicts ready for db.py.

    Each returned dict has:
        url            str            unique key for dedup (from <link>)
        title          str            raw headline — never modified
        summary        str            RSS <description> (raw)
        image_url      Optional[str]  URL only — None is fine
        published_at   datetime       UTC, fallback to utcnow()
        source         str            site slug (carried through for downstream)
        language       str            'bn' or 'en'
        scraped_at     datetime       set here so downstream doesn't have to

    Returns [] on ANY failure (network error, malformed XML, missing feed, etc.)
    and prints the error so GitHub Actions logs surface it.
    """
    slug = site.get("slug", "?")
    rss_url = site.get("rss_url", "")
    language = site.get("language", "")

    try:
        # CF-bypassed sources: fetch RSS bytes via curl_cffi (Chrome TLS
        # impersonation) and hand them to feedparser. Plain httpx / urllib —
        # which feedparser uses internally — get a Cloudflare challenge page
        # from Cloud Run egress and end up parsing zero entries.
        if needs_bypass(slug):
            raw = await cf_fetch_bytes(rss_url)
            feed = await asyncio.to_thread(feedparser.parse, raw)
        else:
            # feedparser.parse is blocking — push it off the event loop so the
            # 15-site fan-out in scraper/main.py can run concurrently.
            feed = await asyncio.to_thread(feedparser.parse, rss_url)

        # feedparser sets `bozo` to 1 when XML is malformed but often still
        # returns usable entries — log it but keep going.
        if getattr(feed, "bozo", 0) and not feed.entries:
            print(f"[{slug}] bozo feed with no entries: {feed.get('bozo_exception')!r}")
            return []

        articles: List[Dict[str, Any]] = []
        now = datetime.utcnow()

        for entry in feed.entries[:20]:
            url = (entry.get("link") or "").strip()
            if not url:
                # No link = no dedup key = useless.
                continue

            title = _strip_html(entry.get("title") or "")
            summary = _strip_html(entry.get("summary") or entry.get("description") or "")

            articles.append({
                "url": url,
                "title": title,
                "summary": summary,
                "image_url": extract_image(entry),
                "published_at": parse_date(entry),
                "source": slug,
                "language": language,
                "scraped_at": now,
            })

        print(f"[{slug}] fetched {len(articles)} entries")
        return articles

    except Exception as exc:  # noqa: BLE001 — broad on purpose, one bad site can't kill the run
        print(f"[{slug}] fetch failed: {type(exc).__name__}: {exc}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# CLI: `python -m scraper.rss_parser <slug>` — quick manual sanity check
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    from scraper.sites import get_by_slug, SITES

    if len(sys.argv) > 1:
        target = get_by_slug(sys.argv[1])
        rows = asyncio.run(fetch_site(target))
        for r in rows[:3]:
            print(r)
    else:
        # Smoke-test the very first site if no slug passed.
        rows = asyncio.run(fetch_site(SITES[0]))
        print(f"Got {len(rows)} articles from {SITES[0]['slug']}")
        if rows:
            print("First:", rows[0])
