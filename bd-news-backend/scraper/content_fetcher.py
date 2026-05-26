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
    A single shared httpx.AsyncClient is reused across all URLs in one run
    so we don't pay TCP+TLS setup cost per article.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from scraper.cf_fetch import CFSessionPool, needs_bypass
from scraper.html_scrapers.base import DEFAULT_HEADERS, DEFAULT_TIMEOUT_SECONDS

try:
    import trafilatura
    _TRAFILATURA_OK = True
except ImportError:
    _TRAFILATURA_OK = False


MAX_CONCURRENT = 5          # parallel HTTP requests
MAX_CONTENT_CHARS = 8_000   # cap stored text — matches db.py save_articles cap
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
}

_WHITESPACE_RE = re.compile(r"\s+")

# Meta tags that carry the article's hero image, tried in order.
# og:image is the de-facto standard — every BD news site we scrape sets it.
_IMAGE_META_PROPERTIES = [
    ("meta", {"property": "og:image"}),
    ("meta", {"property": "og:image:url"}),
    ("meta", {"name": "twitter:image"}),
    ("meta", {"name": "twitter:image:src"}),
    ("link", {"rel": "image_src"}),
]


def extract_image_from_html(page_html: str, page_url: str = "") -> Optional[str]:
    """Pull the article's hero image URL out of the page HTML.

    Order of attempts:
        1. <meta property="og:image">       (Open Graph — universal)
        2. <meta property="og:image:url">
        3. <meta name="twitter:image">      (Twitter Card)
        4. <meta name="twitter:image:src">
        5. <link rel="image_src">
        6. First <img> inside <article> / .article-body that has a real src

    Relative URLs are resolved against page_url. Data URIs and 1px tracking
    pixels are skipped. Returns None when nothing usable is found.
    """
    try:
        soup = BeautifulSoup(page_html, "lxml")
    except Exception:
        return None

    for tag_name, attrs in _IMAGE_META_PROPERTIES:
        tag = soup.find(tag_name, attrs=attrs)
        if tag is None:
            continue
        url = (tag.get("content") or tag.get("href") or "").strip()
        if url and not url.startswith("data:"):
            return urljoin(page_url, url) if page_url else url

    # Fallback — first <img> with a src/data-src inside the article body.
    for container_selector in ("article", ".article-body", ".story-content",
                               ".entry-content", ".post-content"):
        container = soup.select_one(container_selector)
        if container is None:
            continue
        for img in container.find_all("img"):
            src = (img.get("src") or img.get("data-src")
                   or img.get("data-lazy-src") or "").strip()
            if not src or src.startswith("data:"):
                continue
            # Skip obvious 1px trackers / spacers.
            if "1x1" in src or "pixel" in src.lower():
                continue
            return urljoin(page_url, src) if page_url else src

    return None


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


async def _fetch_one(
    client: httpx.AsyncClient,
    cf_pool: Optional[CFSessionPool],
    url: str,
    source: str,
    semaphore: asyncio.Semaphore,
) -> Tuple[str, Optional[str]]:
    """Fetch one article URL and return (extracted text, image URL).

    Both fields are returned together because we only want to make ONE HTTP
    request per article. Returns ("", None) on any error.

    Sources listed in cf_fetch.CF_BYPASS_SOURCES go through the curl_cffi
    warm-session pool (Chrome TLS impersonation + homepage cookies + Referer);
    everything else uses the shared httpx client.
    """
    async with semaphore:
        try:
            if needs_bypass(source) and cf_pool is not None:
                html = await cf_pool.get_text(url)
            else:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text
            return _extract_text(html, source), extract_image_from_html(html, url)
        except Exception as exc:  # noqa: BLE001
            print(f"[content] {url[:80]}: {type(exc).__name__}: {exc}")
            return "", None


async def fetch_contents(
    articles: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Optional[str]]]:
    """
    Fetch full article body text + hero image for a list of article stubs.

    Args:
        articles: list of dicts that each have at least a 'url' key.

    Returns:
        Dict mapping url → {"content": str, "image_url": Optional[str]}.
        content is "" when extraction failed; image_url is None when missing.
    """
    if not articles:
        return {}

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    url_source_pairs = [
        (a["url"], a.get("source", ""))
        for a in articles if a.get("url")
    ]

    # Spin up the CF warm-session pool only if any article in this batch needs
    # bypass — keeps non-CF runs zero-cost.
    needs_cf_pool = any(needs_bypass(s) for _, s in url_source_pairs)

    # One shared client = one connection pool across all fetches. Avoids
    # 100 TCP+TLS handshakes when fetching 100 articles in a single run.
    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        cf_pool_ctx = CFSessionPool() if needs_cf_pool else None
        if cf_pool_ctx is not None:
            await cf_pool_ctx.__aenter__()
        try:
            raw_results = await asyncio.gather(
                *(_fetch_one(client, cf_pool_ctx, url, source, semaphore)
                  for url, source in url_source_pairs),
                return_exceptions=True,
            )
        finally:
            if cf_pool_ctx is not None:
                await cf_pool_ctx.__aexit__(None, None, None)

    output: Dict[str, Dict[str, Optional[str]]] = {}
    for (url, _), result in zip(url_source_pairs, raw_results):
        if isinstance(result, Exception) or result is None:
            output[url] = {"content": "", "image_url": None}
        else:
            text, img = result
            output[url] = {"content": text or "", "image_url": img}

    text_ok = sum(1 for v in output.values() if v["content"])
    img_ok = sum(1 for v in output.values() if v["image_url"])
    print(
        f"[content] fetched text for {text_ok}/{len(url_source_pairs)} articles, "
        f"image for {img_ok}/{len(url_source_pairs)}"
    )
    return output
