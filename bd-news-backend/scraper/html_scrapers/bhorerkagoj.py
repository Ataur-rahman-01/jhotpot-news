"""
bhorerkagoj.py — HTML/sitemap scraper for www.bhorerkagoj.com.

Why sitemap and not HTML/RSS?
    /feed and /rss.xml both 404. The site does publish a Google News sitemap
    at /news_sitemap.xml (declared in robots.txt) — ~167 fresh entries in
    the same schema Samakal uses, so we reuse the shared parser.

LANGUAGE FOOTNOTE (flag for review):
    SKILL.md lists Bhorer Kagoj under "English (6 sites)" but the sitemap
    declares <news:language>bn</news:language> and every title observed is
    in Bangla. The site appears to publish Bangla content under a domain
    name that's romanised. If you confirm this, flip the sites.py entry's
    `language` from "en" to "bn" — articles will then route to articles_bn.

NOTE on image_url: This sitemap does not include <image:loc> either, so
articles land in MongoDB with image_url=None and Flutter shows the
placeholder per SKILL.md rule.
"""

from __future__ import annotations

from typing import Any, Dict, List

from scraper.html_scrapers.base import parse_google_news_sitemap


SITEMAP_URL = "https://www.bhorerkagoj.com/news_sitemap.xml"


async def fetch(site: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse Bhorer Kagoj's Google News sitemap into pipeline-shape article dicts."""
    return await parse_google_news_sitemap(site, SITEMAP_URL)


# ─────────────────────────────────────────────────────────────────────────────
# Manual smoke test: `python -m scraper.html_scrapers.bhorerkagoj`
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import asyncio
    import json

    test_site = {"slug": "bhorerkagoj", "language": "en"}  # matches sites.py for now
    rows = asyncio.run(fetch(test_site))
    print(f"Got {len(rows)} entries.")
    if rows:
        first = {**rows[0]}
        first["published_at"] = first["published_at"].isoformat() if first.get("published_at") else None
        first["scraped_at"]   = first["scraped_at"].isoformat()   if first.get("scraped_at")   else None
        print(json.dumps(first, indent=2, ensure_ascii=False))
