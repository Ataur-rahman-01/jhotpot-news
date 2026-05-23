"""
ajkerpatrika.py — HTML/sitemap scraper for www.ajkerpatrika.com.

Ajker Patrika is a Nuxt/Next-style SPA — /rss.xml and /feed both return
200 OK but with the homepage HTML, not XML. The robots.txt declares:

    Sitemap: https://www.ajkerpatrika.com/sitemap.xml
    Sitemap: https://www.ajkerpatrika.com/news-sitemap.xml   ← dash, not underscore

The news-sitemap.xml is a standard Google News sitemap with ~320 fresh
entries (title, publication_date, occasionally image:loc). Uses the shared
parser → 3-line scraper.

Common gotcha when probing this site: trying `/news_sitemap.xml` (with
underscore) returns the SPA homepage HTML because the SPA's catch-all
route swallows unknown paths. The dash spelling is what works.
"""

from __future__ import annotations

from typing import Any, Dict, List

from scraper.html_scrapers.base import parse_google_news_sitemap


SITEMAP_URL = "https://www.ajkerpatrika.com/news-sitemap.xml"


async def fetch(site: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse Ajker Patrika's Google News sitemap into pipeline-shape article dicts."""
    return await parse_google_news_sitemap(site, SITEMAP_URL)


# ─────────────────────────────────────────────────────────────────────────────
# Manual smoke test: `python -m scraper.html_scrapers.ajkerpatrika`
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import json

    test_site = {"slug": "ajkerpatrika", "language": "bn"}
    rows = asyncio.run(fetch(test_site))
    print(f"Got {len(rows)} entries.")
    if rows:
        first = {**rows[0]}
        first["published_at"] = first["published_at"].isoformat() if first.get("published_at") else None
        first["scraped_at"]   = first["scraped_at"].isoformat()   if first.get("scraped_at")   else None
        print(json.dumps(first, indent=2, ensure_ascii=False))
