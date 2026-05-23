"""
kalerkantho.py — HTML/sitemap scraper for www.kalerkantho.com.

The site's bot defenses 403 most automated requests against `/feed`,
`/rss.xml`, and the homepage. The daily news sitemaps, however, are
served happily and contain the same Google News schema as Samakal /
Bhorer Kagoj — so the shared parser handles everything.

URL pattern:
    https://www.kalerkantho.com/daily-sitemap/YYYY-MM-DD/sitemap.xml

That YYYY-MM-DD is BANGLADESH date (Asia/Dhaka, UTC+6). Using UTC would
fetch the wrong file for ~6 hours per day. Today's sitemap grows as the
day progresses — we re-fetch it every cron run and Mongo's unique index
on url absorbs the overlap.

Per-run yield: ~300 entries (full day) growing as the day progresses.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from scraper.html_scrapers.base import parse_google_news_sitemap


# Bangladesh Standard Time — fixed UTC+6 offset, no DST.
_BD_TZ = timezone(timedelta(hours=6))


def _today_bd() -> str:
    """Return today's date as YYYY-MM-DD in Asia/Dhaka time."""
    return datetime.now(_BD_TZ).strftime("%Y-%m-%d")


async def fetch(site: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse Kaler Kantho's daily news sitemap into pipeline-shape article dicts."""
    url = f"https://www.kalerkantho.com/daily-sitemap/{_today_bd()}/sitemap.xml"
    return await parse_google_news_sitemap(site, url)


# ─────────────────────────────────────────────────────────────────────────────
# Manual smoke test: `python -m scraper.html_scrapers.kalerkantho`
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import json

    test_site = {"slug": "kalerkantho", "language": "bn"}
    rows = asyncio.run(fetch(test_site))
    print(f"Got {len(rows)} entries.")
    if rows:
        first = {**rows[0]}
        first["published_at"] = first["published_at"].isoformat() if first.get("published_at") else None
        first["scraped_at"]   = first["scraped_at"].isoformat()   if first.get("scraped_at")   else None
        print(json.dumps(first, indent=2, ensure_ascii=False))
