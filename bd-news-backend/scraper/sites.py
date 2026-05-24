"""
sites.py — Configuration for all 16 Bangladeshi news sources.

History note: started at 15 sites; Amar Desh and New Age BD were dropped
because their robots.txt explicitly disallows all crawlers. Janakantha and
Financial Express were dropped because no reliable data source was found
(Janakantha's server is unresponsive from cloud runners; Financial Express
is a Nuxt SPA whose /feed returns the homepage HTML). 5 new Bangla sources
were added from FeedSpot's top-25 list: Bangla Tribune, BD24Live, Risingbd,
Bangladesh Journal, Ajker Patrika.

Each site is collected by ONE of two methods:
    scrape_method == "rss"   →  scraper/rss_parser.py
    scrape_method == "html"  →  scraper/html_scrapers/<slug>.py

Group split — 5 Cloud Scheduler jobs, staggered 12 min apart:
    Group A  → indexes  0–2   (3 Bangla sites)   cron '0 * * * *'  → :00
    Group B  → indexes  3–5   (3 Bangla sites)   cron '12 * * * *' → :12
    Group C  → indexes  6–8   (3 Bangla sites)   cron '24 * * * *' → :24
    Group D  → indexes  9–10  (2 Bangla sites)   cron '36 * * * *' → :36
    Group E  → indexes 11–13  (3 English sites)  cron '48 * * * *' → :48

Each entry routes to a MongoDB collection by language:
    language == 'bn' → articles_bn
    language == 'en' → articles_en
"""

from typing import List, Dict, Literal, Optional

Language = Literal["bn", "en"]
ScrapeMethod = Literal["rss", "html"]
Site = Dict[str, Optional[str]]

# ─────────────────────────────────────────────────────────────────────────────
# Master list — order determines group membership (see GROUP_*_RANGE below).
# Removed sites:
#     amardesh     — robots.txt: User-agent: *  Disallow: /
#     newagebd     — robots.txt: User-agent: *  Disallow: /
#     kalerkantho  — article pages return 403; content can never be fetched
# ─────────────────────────────────────────────────────────────────────────────
SITES: List[Site] = [
    # ── Group A (indexes 0–2) ─────────────────────────────────────────────────
    {
        "slug": "prothomalo",
        "name": "Prothom Alo",
        "scrape_method": "rss",
        "rss_url": "https://www.prothomalo.com/feed/",
        "language": "bn",
    },
    {
        "slug": "bd-pratidin",
        "name": "Bangladesh Pratidin",
        # Domain migrated from bd-pratidin.com → bdpratidin.net (verified May 2026)
        "scrape_method": "rss",
        "rss_url": "https://bdpratidin.net/rss/category/latest",
        "language": "bn",
    },
    {
        "slug": "jugantor",
        "name": "Jugantor",
        # No working RSS path. /feed/* returns "Access denied" / 404.
        "scrape_method": "html",
        "rss_url": None,
        "language": "bn",
    },
    # ── Group B (indexes 3–5) ─────────────────────────────────────────────────
    {
        "slug": "ittefaq",
        "name": "Ittefaq",
        # Trailing slash matters — /feed 404s, /feed/ returns RSS.
        "scrape_method": "rss",
        "rss_url": "https://www.ittefaq.com.bd/feed/",
        "language": "bn",
    },
    {
        "slug": "samakal",
        "name": "Samakal",
        # No RSS — /feed returns homepage HTML. Sitemap-based scraper instead.
        # news_sitemap.xml gives ~260 fresh entries in Google News format.
        "scrape_method": "html",
        "rss_url": None,
        "language": "bn",
    },
    {
        "slug": "mzamin",
        "name": "Manab Zamin",
        # No RSS — /feed* all 404. Tiny sitemap available; HTML scraper required.
        "scrape_method": "html",
        "rss_url": None,
        "language": "bn",
    },
    # ── Group C (indexes 6–8) ─────────────────────────────────────────────────
    {
        "slug": "bhorerkagoj",
        "name": "Bhorer Kagoj",
        # Originally listed under English in SKILL.md, but the site publishes
        # Bangla content (sitemap declares <news:language>bn</news:language>
        # and all observed titles are in Bangla). Moved to Group A.
        # No RSS — /feed 404s; uses Google News sitemap at /news_sitemap.xml.
        "scrape_method": "html",
        "rss_url": None,
        "language": "bn",
    },

    {
        "slug": "banglatribune",
        "name": "Bangla Tribune",
        "scrape_method": "rss",
        "rss_url": "https://www.banglatribune.com/feed/",
        "language": "bn",
    },
    {
        "slug": "bd24live",
        "name": "BD24Live",
        # The site is bilingual; /bangla/feed/ is the Bangla-only subsection.
        "scrape_method": "rss",
        "rss_url": "https://www.bd24live.com/bangla/feed/",
        "language": "bn",
    },
    # ── Group D (indexes 9–10) ────────────────────────────────────────────────
    {
        "slug": "bd-journal",
        "name": "Bangladesh Journal",
        "scrape_method": "rss",
        "rss_url": "https://www.bd-journal.com/feed/latest-rss.xml",
        "language": "bn",
    },
    {
        "slug": "ajkerpatrika",
        "name": "Ajker Patrika",
        # No RSS — /rss.xml and /feed return the SPA homepage HTML.
        # robots.txt declares /news-sitemap.xml (note the DASH, not underscore).
        # Standard Google News sitemap schema → shared parser handles it.
        "scrape_method": "html",
        "rss_url": None,
        "language": "bn",
    },

    # ── Group E (indexes 12–14) ───────────────────────────────────────────────
    {
        "slug": "thedailystar",
        "name": "The Daily Star",
        "scrape_method": "rss",
        # frontpage/rss.xml is permanently stale (2022 data) — news/bangladesh gives today's articles
        "rss_url": "https://www.thedailystar.net/news/bangladesh/rss.xml",
        "language": "en",
    },
    {
        "slug": "dhakatribune",
        "name": "Dhaka Tribune",
        # Trailing slash matters — /feed 404s, /feed/ returns RSS.
        "scrape_method": "rss",
        "rss_url": "https://www.dhakatribune.com/feed/",
        "language": "en",
    },
    {
        "slug": "tbsnews",
        "name": "TBS News",
        "scrape_method": "rss",
        "rss_url": "https://www.tbsnews.net/rss.xml",
        "language": "en",
    },
]

# Sanity checks — fail fast on misconfiguration at import time.
assert len(SITES) == 14, f"Expected 14 sites, got {len(SITES)}"
assert len({s['slug'] for s in SITES}) == 14, "Duplicate slug detected in SITES"
assert sum(1 for s in SITES if s['language'] == 'bn') == 11, "Expected 11 Bangla sites"
assert sum(1 for s in SITES if s['language'] == 'en') == 3, "Expected 3 English sites"
assert all(s['scrape_method'] in ('rss', 'html') for s in SITES), \
    "Every site needs scrape_method in {'rss','html'}"
# RSS sites must have a URL; HTML sites must not.
for _s in SITES:
    if _s['scrape_method'] == 'rss':
        assert _s.get('rss_url'), f"{_s['slug']}: rss_url required when method='rss'"
    else:
        assert _s.get('rss_url') is None, f"{_s['slug']}: rss_url must be None when method='html'"

# ─────────────────────────────────────────────────────────────────────────────
# Group boundaries — 5 groups staggered 12 min apart in Cloud Scheduler.
# ─────────────────────────────────────────────────────────────────────────────
GROUP_A_RANGE = (0,  3)   # indexes  0–2  → 3 Bangla  (prothomalo, bd-pratidin, jugantor)
GROUP_B_RANGE = (3,  6)   # indexes  3–5  → 3 Bangla  (ittefaq, samakal, mzamin)
GROUP_C_RANGE = (6,  9)   # indexes  6–8  → 3 Bangla  (bhorerkagoj, banglatribune, bd24live)
GROUP_D_RANGE = (9,  11)  # indexes  9–10 → 2 Bangla  (bd-journal, ajkerpatrika)
GROUP_E_RANGE = (11, 14)  # indexes 11–13 → 3 English (thedailystar, dhakatribune, tbsnews)

_GROUP_RANGES = {
    "a": GROUP_A_RANGE,
    "b": GROUP_B_RANGE,
    "c": GROUP_C_RANGE,
    "d": GROUP_D_RANGE,
    "e": GROUP_E_RANGE,
}


def get_group(group: str) -> List[Site]:
    """
    Return the subset of SITES belonging to the requested group.

    Args:
        group: 'a', 'b', 'c', 'd', or 'e' (case-insensitive).

    Returns:
        List of site dicts for that group.

    Raises:
        ValueError: if group is not one of the five letters.
    """
    g = group.strip().lower()
    if g not in _GROUP_RANGES:
        raise ValueError(f"Unknown group {group!r} — expected one of {sorted(_GROUP_RANGES)}")
    start, end = _GROUP_RANGES[g]
    return SITES[start:end]


def get_by_slug(slug: str) -> Site:
    """Look up a single site by its slug. Raises KeyError if not found."""
    for s in SITES:
        if s["slug"] == slug:
            return s
    raise KeyError(f"No site with slug {slug!r}")


def get_by_language(language: Language) -> List[Site]:
    """Return all sites for a given language ('bn' or 'en')."""
    return [s for s in SITES if s["language"] == language]


def get_by_method(method: ScrapeMethod) -> List[Site]:
    """Return all sites with the given scrape_method ('rss' or 'html')."""
    return [s for s in SITES if s["scrape_method"] == method]


if __name__ == "__main__":
    # Quick visual check — run `python -m scraper.sites` to inspect.
    print(f"Total sites: {len(SITES)}")
    print(f"  Bangla : {len(get_by_language('bn'))}")
    print(f"  English: {len(get_by_language('en'))}")
    print(f"  RSS    : {len(get_by_method('rss'))}")
    print(f"  HTML   : {len(get_by_method('html'))}")
    print()
    for label in ("a", "b", "c", "d", "e"):
        group = get_group(label)
        print(f"Group {label.upper()} ({len(group)} sites):")
        for s in group:
            print(f"  [{s['language']}] [{s['scrape_method']:<4}] {s['slug']:<18} {s['name']}")
        print()
