"""
jugantor.py — HTML/sitemap scraper for www.jugantor.com.

Jugantor blocks /feed, /rss.xml, /feed/rss.xml, and every variant we tried
("Access denied. Requested page not found."), but its robots.txt openly
declares:

    Sitemap: https://www.jugantor.com/sitemap.xml
    Sitemap: https://www.jugantor.com/news_sitemap.xml

The second is a 270 KB Google News sitemap with ~500 fresh entries —
same schema as Samakal / Bhorer Kagoj / Kaler Kantho — so we reuse the
shared parser. Title and publish date are present per entry; image_url
is not provided (placeholder shows in Flutter).
"""

from __future__ import annotations

from typing import Any, Dict, List

from scraper.html_scrapers.base import parse_google_news_sitemap


SITEMAP_URL = "https://www.jugantor.com/news_sitemap.xml"


async def fetch(site: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse Jugantor's Google News sitemap into pipeline-shape article dicts."""
    return await parse_google_news_sitemap(site, SITEMAP_URL)


# ─────────────────────────────────────────────────────────────────────────────
# Manual smoke test: `python -m scraper.html_scrapers.jugantor`
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import json

    test_site = {"slug": "jugantor", "language": "bn"}
    rows = asyncio.run(fetch(test_site))
    print(f"Got {len(rows)} entries.")
    if rows:
        first = {**rows[0]}
        first["published_at"] = first["published_at"].isoformat() if first.get("published_at") else None
        first["scraped_at"]   = first["scraped_at"].isoformat()   if first.get("scraped_at")   else None
        print(json.dumps(first, indent=2, ensure_ascii=False))
