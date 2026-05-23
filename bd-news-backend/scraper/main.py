"""
main.py — Entry point for the scraper pipeline. Driven by GitHub Actions.

Usage:
    python -m scraper.main --group a     # Group A sites (indexes 0–7)
    python -m scraper.main --group b     # Group B sites (indexes 8–14)
    python -m scraper.main --group all   # All 15 sites (default)

Pipeline (matches SKILL.md flow):
    1. Ensure indexes exist (idempotent).
    2. Fetch every site's RSS in PARALLEL  (asyncio.gather + fetch_site).
    3. Bucket articles by language → upsert into articles_bn / articles_en.
    4. Pull up to 50 unprocessed articles from each collection.
    5. Tag each with Gemini SEQUENTIALLY (built-in 2s delay → 15 RPM safe).
    6. Print summary stats — GHA logs surface them.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any, Dict, List

from dotenv import load_dotenv

# .env is for local dev; in GitHub Actions the secrets are real env vars
# and load_dotenv silently no-ops.
load_dotenv()

from scraper.sites import SITES, get_group                            # noqa: E402
from scraper.rss_parser import fetch_site as _rss_fetch_site          # noqa: E402
from scraper.html_scrapers import fetch_site_html as _html_fetch_site # noqa: E402
from scraper.db import (                                              # noqa: E402
    setup_indexes,
    save_articles,
    get_unprocessed,
    get_articles_without_content,
    update_content,
    mark_processed,
)
from scraper.gemini import tag_article                                # noqa: E402
from scraper.content_fetcher import fetch_contents, FETCH_LIMIT_PER_RUN  # noqa: E402
from archive.archiver import check_and_archive_if_needed              # noqa: E402


async def _dispatch_fetch(site: Dict[str, str]) -> List[Dict[str, Any]]:
    """Route to HTML scraper or RSS parser based on site config."""
    if site.get("scrape_method") == "html":
        return await _html_fetch_site(site)
    return await _rss_fetch_site(site)


COLLECTION_BN = "articles_bn"
COLLECTION_EN = "articles_en"
GEMINI_QUEUE_LIMIT = 50  # per collection, per run


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 + 2 + 3 — fetch in parallel, bucket by language, save.
# ─────────────────────────────────────────────────────────────────────────────
async def _fetch_and_save(sites: List[Dict[str, str]]) -> Dict[str, int]:
    """Parallel fetch, then synchronous upsert. Returns counts by language."""
    print(f"[fetch] starting {len(sites)} sites in parallel")
    t0 = time.monotonic()

    # return_exceptions=True is belt-and-braces — fetch_site already
    # catches everything and returns [], but this stops a stray crash in
    # asyncio internals from tanking the whole gather.
    results = await asyncio.gather(
        *(_dispatch_fetch(s) for s in sites),
        return_exceptions=True,
    )

    bn_articles: List[Dict[str, Any]] = []
    en_articles: List[Dict[str, Any]] = []

    for site, items in zip(sites, results):
        if isinstance(items, Exception):
            print(f"[fetch] {site['slug']} raised {type(items).__name__}: {items}")
            continue
        if site["language"] == "bn":
            bn_articles.extend(items)
        elif site["language"] == "en":
            en_articles.extend(items)
        else:
            print(f"[fetch] {site['slug']} has unknown language {site['language']!r} — skipped")

    fetch_secs = time.monotonic() - t0
    print(
        f"[fetch] done in {fetch_secs:.1f}s — "
        f"{len(bn_articles)} bn entries, {len(en_articles)} en entries"
    )

    # Sync writes — pymongo bulk_write is fast enough to not warrant to_thread.
    new_bn = save_articles(bn_articles, COLLECTION_BN) if bn_articles else 0
    new_en = save_articles(en_articles, COLLECTION_EN) if en_articles else 0

    return {"bn": new_bn, "en": new_en}


# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — fetch full article content before Gemini tagging.
# ─────────────────────────────────────────────────────────────────────────────
async def _fetch_content_stage() -> Dict[str, int]:
    """Fetch full body text for articles that were just saved with empty content."""
    totals = {"fetched": 0, "failed": 0}

    for collection in (COLLECTION_BN, COLLECTION_EN):
        stubs = get_articles_without_content(collection, limit=FETCH_LIMIT_PER_RUN)
        if not stubs:
            print(f"[content] {collection}: nothing to fetch")
            continue

        print(f"[content] {collection}: fetching content for {len(stubs)} articles")
        results = await fetch_contents(stubs)

        for stub in stubs:
            url = stub.get("url", "")
            text = results.get(url, "")
            if text:
                ok = update_content(collection, stub["_id"], text)
                totals["fetched" if ok else "failed"] += 1
            else:
                totals["failed"] += 1

    return totals


# ─────────────────────────────────────────────────────────────────────────────
# Stage 5 + 6 — drain the Gemini queue sequentially (rate-limit aware).
# ─────────────────────────────────────────────────────────────────────────────
async def _drain_gemini_queue() -> Dict[str, int]:
    """Tag unprocessed articles in both collections. Sequential by design."""
    totals = {"tagged": 0, "failed": 0, "skipped_zero_quota": 0}

    for collection in (COLLECTION_BN, COLLECTION_EN):
        queue = get_unprocessed(collection, limit=GEMINI_QUEUE_LIMIT)
        print(f"[gemini] {collection}: {len(queue)} articles in queue")

        for article in queue:
            ai_data = await tag_article(article)
            if ai_data is None:
                totals["failed"] += 1
                continue

            ok = mark_processed(collection, article["_id"], ai_data)
            if ok:
                totals["tagged"] += 1
            else:
                # Article vanished between fetch and update — rare but possible
                # if the archive job ran concurrently. Not a real failure.
                totals["skipped_zero_quota"] += 1

    return totals


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────────────
async def run_scraper(group: str = "all") -> None:
    """
    End-to-end run. `group` is 'a', 'b', or 'all'.
    Safe to call multiple times — every stage is idempotent.
    """
    overall_t0 = time.monotonic()
    print(f"=== BD News Archive scraper — group={group!r} ===")

    # Stage 1: indexes.
    print("[indexes] ensuring all indexes are in place")
    setup_indexes()

    # Stage 2/3: pick site list.
    if group == "all":
        sites = SITES
    else:
        sites = get_group(group)  # raises ValueError on bad group

    saved = await _fetch_and_save(sites)
    print(f"[save] +{saved['bn']} new bn, +{saved['en']} new en")

    # Stage 4: fetch full article content before Gemini.
    content_stats = await _fetch_content_stage()
    print(
        f"[content] fetched={content_stats['fetched']} "
        f"failed={content_stats['failed']}"
    )

    # Stage 5/6: Gemini queue.
    tag_stats = await _drain_gemini_queue()
    print(
        f"[gemini] tagged={tag_stats['tagged']} "
        f"failed={tag_stats['failed']} "
        f"vanished={tag_stats['skipped_zero_quota']}"
    )

    # Stage 7: Emergency size check — archive oldest months if DB >= 480 MB.
    check_and_archive_if_needed()

    elapsed = time.monotonic() - overall_t0
    print(f"=== done in {elapsed:.1f}s ===")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bd-news-scraper",
        description="Scrape Bangladeshi news sites, save to MongoDB, tag with Gemini.",
    )
    parser.add_argument(
        "--group",
        choices=["a", "b", "all"],
        default="all",
        help="Which site group to run. 'a' = sites 0–7, 'b' = sites 8–14, "
             "'all' = every site (default).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        asyncio.run(run_scraper(args.group))
    except KeyboardInterrupt:
        print("\n[main] interrupted — exiting cleanly")
    except Exception as exc:  # noqa: BLE001 — top-level safety net for GHA exit code
        print(f"[main] FATAL: {type(exc).__name__}: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
