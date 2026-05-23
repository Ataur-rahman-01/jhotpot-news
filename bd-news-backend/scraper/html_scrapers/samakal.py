"""
samakal.py — HTML/sitemap scraper for samakal.com.

Why sitemap and not HTML scraping?
    Samakal exposes a Google News sitemap at /news_sitemap.xml — a structured
    feed of ~260 fresh articles with url, title, publish-date, and keywords.
    Parsing this is faster, more stable, and less likely to break than HTML
    scraping their SPA-style homepage.

NOTE on image_url: Samakal's news sitemap does NOT include <image:loc>.
Per SKILL.md image rule the article goes into MongoDB with image_url=None
and Flutter's CachedNetworkImage shows the placeholder icon.

The shared Google News sitemap parser lives in html_scrapers/base.py —
any site that uses the same schema (Bhorer Kagoj, likely others) can
reuse it without copy-pasting.
"""

from __future__ import annotations

from typing import Any, Dict, List

from scraper.html_scrapers.base import parse_google_news_sitemap


SITEMAP_URL = "https://samakal.com/news_sitemap.xml"


async def fetch(site: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse Samakal's Google News sitemap into pipeline-shape article dicts."""
    return await parse_google_news_sitemap(site, SITEMAP_URL)


# ─────────────────────────────────────────────────────────────────────────────
# Manual smoke test: `python -m scraper.html_scrapers.samakal`
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import json

    test_site = {"slug": "samakal", "language": "bn"}
    rows = asyncio.run(fetch(test_site))
    print(f"Got {len(rows)} entries.")
    if rows:
        first = {**rows[0]}
        first["published_at"] = first["published_at"].isoformat() if first.get("published_at") else None
        first["scraped_at"]   = first["scraped_at"].isoformat()   if first.get("scraped_at")   else None
        print(json.dumps(first, indent=2, ensure_ascii=False))
