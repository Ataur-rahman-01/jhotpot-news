"""
mzamin.py — HTML/sitemap scraper for www.mzamin.com (Manab Zamin).

Why a custom parser?
    Unlike Samakal / Bhorer Kagoj / Kaler Kantho, Manab Zamin's sitemap
    does NOT use the Google News namespace — no <news:title>, no
    <news:publication_date>. We have only <loc> and <lastmod>.

    The good news: titles live in the URL slug. Article URLs look like:
        https://www.mzamin.com/article/18463/<bangla-slug-with-dashes>
    So we URL-decode the slug, replace dashes with spaces, and use that
    as the title. Gemini handles the rest from the title alone.

The sitemap is 1.7 MB with ~5,000 entries, listed newest-first. We take
the first MAX_ARTICLES_PER_RUN article-shaped entries and skip the
~5 nav entries (homepage, /archive, /print, etc.) at the top.

Per-run yield (default cap): 20 newest articles.

No image_url, no summary — placeholder shows in Flutter, Gemini classifies
from title only. Less ideal than the Google News sites but functional.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from lxml import etree

from scraper.html_scrapers.base import (
    GOOGLE_NEWS_NS,
    build_article,
    fetch_bytes,
)


SITEMAP_URL = "https://www.mzamin.com/post-sitemap.xml"
MAX_ARTICLES_PER_RUN = 20

# Article URL pattern. Path: /article/<numeric-id>/<bangla-slug>
_ARTICLE_URL_RE = re.compile(r"^https?://[^/]+/article/\d+/.+", re.IGNORECASE)


def _title_from_url(url: str) -> str:
    """Derive a human-readable Bangla title from the URL slug.

    Example:
        https://www.mzamin.com/article/18463/হাম-ও-হামের-উপসর্গে-১৩-শিশু-মৃত্যু-৫০০-ছাড়ালো
            →  হাম ও হামের উপসর্গে ১৩ শিশু মৃত্যু ৫০০ ছাড়ালো
    """
    try:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        decoded = unquote(slug)
        return decoded.replace("-", " ").strip()
    except Exception:  # noqa: BLE001
        return ""


def _parse_lastmod(value: Optional[str]) -> Optional[datetime]:
    """ISO-8601 (with or without offset) → naive UTC datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def fetch(site: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse Manab Zamin's WordPress post-sitemap into pipeline-shape article dicts."""
    slug = site.get("slug", "mzamin")

    # Stage 1 — fetch.
    try:
        raw = await fetch_bytes(SITEMAP_URL)
    except Exception as exc:  # noqa: BLE001
        print(f"[{slug}] sitemap fetch failed: {type(exc).__name__}: {exc}")
        return []

    # Stage 2 — parse XML.
    try:
        parser = etree.XMLParser(recover=True, huge_tree=True)
        root = etree.fromstring(raw, parser=parser)
    except etree.XMLSyntaxError as exc:
        print(f"[{slug}] sitemap parse failed: {exc}")
        return []

    if root is None:
        print(f"[{slug}] sitemap root element missing")
        return []

    # `or` shortcut would fail if findall returns an empty list AND elements
    # are involved elsewhere — be explicit and check len directly.
    url_nodes = root.findall("sm:url", namespaces=GOOGLE_NEWS_NS)
    if not url_nodes:
        url_nodes = root.findall("url")

    # Stage 3 — filter to article-shaped URLs and cap.
    articles: List[Dict[str, Any]] = []
    skipped_nav = 0

    for node in url_nodes:
        # NOTE: lxml elements with no children are FALSY, so the
        # `find(...) or find(...)` shortcut treats a valid <loc> (which
        # only has text content) as missing. Always compare with `is None`.
        loc_el = node.find("sm:loc", namespaces=GOOGLE_NEWS_NS)
        if loc_el is None:
            loc_el = node.find("loc")
        if loc_el is None or not loc_el.text:
            continue
        loc = loc_el.text.strip()

        if not _ARTICLE_URL_RE.match(loc):
            skipped_nav += 1
            continue

        lastmod_el = node.find("sm:lastmod", namespaces=GOOGLE_NEWS_NS)
        if lastmod_el is None:
            lastmod_el = node.find("lastmod")
        published_at = _parse_lastmod(lastmod_el.text if lastmod_el is not None else None)

        title = _title_from_url(loc)
        if not title:
            continue  # un-titled = useless

        articles.append(build_article(
            site=site,
            url=loc,
            title=title,
            summary="",         # plain sitemap has no description
            image_url=None,     # placeholder shows in Flutter
            published_at=published_at,
        ))

        if len(articles) >= MAX_ARTICLES_PER_RUN:
            break

    print(
        f"[{slug}] sitemap parsed {len(articles)} articles "
        f"(skipped {skipped_nav} nav entries, total feed {len(url_nodes)})"
    )
    return articles


# ─────────────────────────────────────────────────────────────────────────────
# Manual smoke test: `python -m scraper.html_scrapers.mzamin`
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import json

    test_site = {"slug": "mzamin", "language": "bn"}
    rows = asyncio.run(fetch(test_site))
    print(f"Got {len(rows)} entries.")
    if rows:
        first = {**rows[0]}
        first["published_at"] = first["published_at"].isoformat() if first.get("published_at") else None
        first["scraped_at"]   = first["scraped_at"].isoformat()   if first.get("scraped_at")   else None
        print(json.dumps(first, indent=2, ensure_ascii=False))
