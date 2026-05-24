"""
html_scrapers — Registry of per-site HTML scrapers.

Each scraper module exposes:

    async def fetch(site: dict) -> list[dict]

and is wired up in REGISTRY below. The dispatcher pattern means
scraper/main.py never has to know which sites are HTML-only:

    from scraper.html_scrapers import fetch_site_html
    articles = await fetch_site_html(site)   # routes by slug

Adding a new scraper takes 2 lines:
    1. import scraper.html_scrapers.<slug>
    2. add {"<slug>": module.fetch} to REGISTRY
"""

from __future__ import annotations

from typing import Any, Dict, List

from scraper.html_scrapers.base import ScraperFn
from scraper.html_scrapers import (
    ajkerpatrika,
    bhorerkagoj,
    jugantor,
    mzamin,
    samakal,
)


# ─────────────────────────────────────────────────────────────────────────────
# Registry — slug → fetch coroutine. Add new scrapers here.
# ─────────────────────────────────────────────────────────────────────────────
REGISTRY: Dict[str, ScraperFn] = {
    "samakal":      samakal.fetch,
    "bhorerkagoj":  bhorerkagoj.fetch,
    "mzamin":       mzamin.fetch,
    "jugantor":     jugantor.fetch,
    "ajkerpatrika": ajkerpatrika.fetch,
    # All HTML-method sites in sites.py are now covered. Add new entries here.
}


def has_scraper(slug: str) -> bool:
    """True iff an HTML scraper is registered for this slug."""
    return slug in REGISTRY


def get_scraper(slug: str) -> ScraperFn:
    """Return the fetch coroutine for a slug. Raises KeyError if missing."""
    if slug not in REGISTRY:
        raise KeyError(f"No HTML scraper registered for slug={slug!r}")
    return REGISTRY[slug]


async def fetch_site_html(site: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Dispatcher with the same async contract as rss_parser.fetch_site.

    Returns [] (and prints the error) for any site missing a registered
    scraper or any scraper that raises — one broken site never kills the
    parent gather.
    """
    slug = site.get("slug", "?")
    if not has_scraper(slug):
        print(f"[html_scrapers] no scraper registered for {slug!r} — skipped")
        return []
    try:
        return await REGISTRY[slug](site)
    except Exception as exc:  # noqa: BLE001 — one bad site mustn't stop the run
        print(f"[html_scrapers] {slug} fetch failed: {type(exc).__name__}: {exc}")
        return []
