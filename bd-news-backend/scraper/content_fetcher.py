"""
content_fetcher.py — Fetch full article body text from news article URLs.

After the RSS/HTML scrapers save article stubs (url + title + summary),
this module visits each article URL and extracts the main body text.
The result is stored in the 'content' field in MongoDB so that Gemini
receives the full article instead of just the 1-2 sentence RSS snippet.

Extraction strategy (tried in order):
    1. trafilatura — purpose-built news-article extractor, handles the
       widest variety of HTML structures without needing site-specific selectors.
    2. schema.org [itemprop='articleBody'] — most reliable for news sites
    3. Site-specific CSS selectors (see _SITE_SELECTORS below)
    4. Common news-CMS class patterns (.article-body, .entry-content, …)
    5. <article> semantic tag
    6. Fallback: join all <p> tags — catches custom templates

Concurrency:
    MAX_CONCURRENT parallel requests (asyncio.Semaphore). Polite to servers.
    FETCH_LIMIT_PER_RUN caps articles per scraper run so GHA stays fast.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List

import httpx
from bs4 import BeautifulSoup

from scraper.html_scrapers.base import DEFAULT_HEADERS, DEFAULT_TIMEOUT_SECONDS

try:
    import trafilatura
    _TRAFILATURA_OK = True
except ImportError:
    _TRAFILATURA_OK = False


MAX_CONCURRENT = 5          # parallel HTTP requests
FETCH_LIMIT_PER_RUN = 50    # articles per collection per run (raised from 30)
MAX_CONTENT_CHARS = 8_000   # cap stored text — plenty for Gemini
MIN_TEXT_LEN = 150           # below this the extraction is considered failed

# Generic selectors tried in order — first match with >= MIN_TEXT_LEN chars wins.
_PRIORITY_SELECTORS = [
    "[itemprop='articleBody']",
    ".article-body",
    ".article-content",
    ".story-content",
    ".news-content",
    ".post-content",
    ".entry-content",
    ".content-detail",
    ".news-description",
    ".single-post-content",
    ".story-element-text",
    ".details-content",
    "article",
]

# Site-specific overrides — tried BEFORE the generic list when trafilatura fails.
# Verified against live article pages (May 2026).
_SITE_SELECTORS: Dict[str, List[str]] = {
    # English sites
    "thedailystar": [".clearfix"],
    "dhakatribune":  [".article-body-content", ".article-body"],
    "tbsnews":       [".article-full-content", ".article-body"],
    # Bangla sites — RSS-based
    "ittefaq":       [".news-description", ".description"],
    "prothomalo":    [".story-element"],        # body split across multiple .story-element divs
    "banglatribune": [".post-content", ".single-post-content"],
    "bd24live":      [".content_p", ".entry-content"],
    "risingbd":      [".details-content", ".news-body"],
    "bd-pratidin":   [".post-content", ".details-news", ".news-content"],
    "bd-journal":    [".entry-content"],        # site often 403s; selector kept as fallback
    # Bangla sites — sitemap-based
    "samakal":       [".dNewsDesc"],
    "mzamin":        [".content-body", ".details-content"],
    "jugantor":      [".desktopDetailBody", ".detailBody", ".details-body"],
    "ajkerpatrika":  [".block-full_richtext", ".article-body"],
    # kalerkantho: article pages return 403; no selector can help
}

_WHITESPACE_RE = re.compile(r"\s+")


def _extract_text(page_html: str, source: str = "") -> str:
    """Parse page HTML and return the main article body as plain text.

    Tries trafilatura first (purpose-built for news articles), then falls back
    to site-specific CSS selectors, generic selectors, and finally <p> tags.
    """
    # Stage 1: trafilatura — handles the widest variety of news site layouts.
    if _TRAFILATURA_OK:
        try:
            result = trafilatura.extract(
                page_html,
                include_comments=False,
                include_tables=False,
                deduplicate=True,
                no_fallback=False,
            )
            if result and len(result) >= MIN_TEXT_LEN:
                return result[:MAX_CONTENT_CHARS]
        except Exception:
            pass

    # Stage 2: CSS selectors — site-specific first, then generic list.
    soup = BeautifulSoup(page_html, "lxml")

    for noise in soup.find_all(
        ["script", "style", "nav", "header", "footer", "aside",
         "figure", "figcaption", "noscript"]
    ):
        noise.decompose()

    selectors = _SITE_SELECTORS.get(source, []) + _PRIORITY_SELECTORS
    for selector in selectors:
        try:
            nodes = soup.select(selector)
        except Exception:
            continue
        if nodes:
            # Join all matching nodes — handles sites like Prothom Alo where
            # the article body is split across multiple sibling .story-element divs.
            text = _WHITESPACE_RE.sub(
                " ", " ".join(n.get_text(separator=" ") for n in nodes)
            ).strip()
            if len(text) >= MIN_TEXT_LEN:
                return text[:MAX_CONTENT_CHARS]

    # Stage 3: <p> tag fallback — catches sites with fully custom CSS.
    paragraphs = soup.find_all("p")
    text = _WHITESPACE_RE.sub(
        " ", " ".join(p.get_text(separator=" ") for p in paragraphs)
    ).strip()
    if len(text) >= MIN_TEXT_LEN:
        return text[:MAX_CONTENT_CHARS]

    return ""


async def _fetch_one(url: str, source: str, semaphore: asyncio.Semaphore) -> str:
    """Fetch one article URL and return extracted text. Returns "" on any error."""
    async with semaphore:
        try:
            async with httpx.AsyncClient(
                headers=DEFAULT_HEADERS,
                timeout=DEFAULT_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return _extract_text(resp.text, source)
        except Exception as exc:  # noqa: BLE001
            print(f"[content] {url[:80]}: {type(exc).__name__}: {exc}")
            return ""


async def fetch_contents(articles: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Fetch full article body text for a list of article stubs concurrently.

    Args:
        articles: list of dicts that each have at least a 'url' key.

    Returns:
        Dict mapping url → extracted body text (may be "" when extraction failed).
    """
    if not articles:
        return {}

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    url_source_pairs = [
        (a["url"], a.get("source", ""))
        for a in articles if a.get("url")
    ]

    raw_results = await asyncio.gather(
        *(_fetch_one(url, source, semaphore) for url, source in url_source_pairs),
        return_exceptions=True,
    )

    output: Dict[str, str] = {}
    for (url, _), result in zip(url_source_pairs, raw_results):
        output[url] = "" if isinstance(result, Exception) else (result or "")

    success = sum(1 for v in output.values() if v)
    print(f"[content] fetched text for {success}/{len(url_source_pairs)} articles")
    return output
