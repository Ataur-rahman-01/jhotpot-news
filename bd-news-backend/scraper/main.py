"""
main.py — Entry point for the scraper pipeline. Driven by Cloud Scheduler.

Usage:
    python -m scraper.main --group a     # Group A sites (indexes 0–2)
    python -m scraper.main --group b     # Group B sites (indexes 3–5)
    python -m scraper.main --group c     # Group C sites (indexes 6–8)
    python -m scraper.main --group d     # Group D sites (indexes 9–10)
    python -m scraper.main --group e     # Group E sites (indexes 11–13)
    python -m scraper.main --group all   # All 14 sites (default)

Pipeline:
    1. Ensure indexes exist (idempotent).
    2. Fetch latest 20 articles per site in PARALLEL (RSS or HTML scraper).
    3. Fetch full article content for every stub — also in parallel.
    4. Drop any article whose content could not be extracted.
    5. Upsert surviving articles (with content) into articles_bn / articles_en.
    6. Tag unprocessed articles with Gemini SEQUENTIALLY (rate-limit safe).
    7. Print summary stats — Cloud Run logs surface them.
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
    get_existing_urls,
    get_unprocessed,
    mark_processed,
)
from scraper.gemini import tag_article                                # noqa: E402
from scraper.content_fetcher import fetch_contents                    # noqa: E402
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
# Stage 1 + 2 + 3 — fetch stubs, fetch content inline, save only if content.
# ─────────────────────────────────────────────────────────────────────────────
async def _fetch_and_save(sites: List[Dict[str, str]]) -> Dict[str, int]:
    """
    Parallel-fetch latest 20 article stubs per site, immediately fetch full
    content for each stub, then save only articles where content was found.
    Articles with no extractable content are dropped and never reach MongoDB.
    """
    print(f"[fetch] starting {len(sites)} sites in parallel")
    t0 = time.monotonic()

    results = await asyncio.gather(
        *(_dispatch_fetch(s) for s in sites),
        return_exceptions=True,
    )

    all_stubs: List[Dict[str, Any]] = []
    for site, items in zip(sites, results):
        if isinstance(items, Exception):
            print(f"[fetch] {site['slug']} raised {type(items).__name__}: {items}")
            continue
        all_stubs.extend(items)

    fetch_secs = time.monotonic() - t0
    print(f"[fetch] done in {fetch_secs:.1f}s — {len(all_stubs)} stubs total")

    if not all_stubs:
        return {"bn": 0, "en": 0}

    # Skip stubs already in MongoDB — no point re-fetching their content.
    bn_urls = [a["url"] for a in all_stubs if a.get("language") == "bn" and a.get("url")]
    en_urls = [a["url"] for a in all_stubs if a.get("language") == "en" and a.get("url")]
    existing = get_existing_urls(COLLECTION_BN, bn_urls) | get_existing_urls(COLLECTION_EN, en_urls)
    new_stubs = [a for a in all_stubs if a.get("url") not in existing]
    print(f"[dedup] {len(existing)} already in DB, {len(new_stubs)} new stubs to process")

    if not new_stubs:
        return {"bn": 0, "en": 0}

    # Fetch full body text only for genuinely new articles.
    print(f"[content] fetching content for {len(new_stubs)} stubs")
    content_map = await fetch_contents(new_stubs)

    bn_articles: List[Dict[str, Any]] = []
    en_articles: List[Dict[str, Any]] = []
    skipped = 0

    for article in new_stubs:
        url = article.get("url", "")
        content = content_map.get(url, "")
        if not content:
            skipped += 1
            continue
        article["content"] = content
        lang = article.get("language")
        if lang == "bn":
            bn_articles.append(article)
        elif lang == "en":
            en_articles.append(article)
        else:
            print(f"[fetch] {article.get('source','?')} unknown language {lang!r} — skipped")

    print(
        f"[content] {len(bn_articles) + len(en_articles)} with content, "
        f"{skipped} dropped (no content)"
    )

    # Sync writes — pymongo bulk_write is fast enough to not warrant to_thread.
    new_bn = save_articles(bn_articles, COLLECTION_BN) if bn_articles else 0
    new_en = save_articles(en_articles, COLLECTION_EN) if en_articles else 0

    return {"bn": new_bn, "en": new_en}


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
    End-to-end run. `group` is 'a'–'e' or 'all'.
    Safe to call multiple times — every stage is idempotent.
    """
    overall_t0 = time.monotonic()
    print(f"=== BD News Archive scraper — group={group!r} ===")

    # Stage 1: indexes.
    print("[indexes] ensuring all indexes are in place")
    setup_indexes()

    # Stage 2/3: pick site list, fetch stubs + content, save articles with content.
    sites = SITES if group == "all" else get_group(group)
    saved = await _fetch_and_save(sites)
    print(f"[save] +{saved['bn']} new bn, +{saved['en']} new en")

    # Stage 4: Gemini queue — every article in the queue already has content.
    tag_stats = await _drain_gemini_queue()
    print(
        f"[gemini] tagged={tag_stats['tagged']} "
        f"failed={tag_stats['failed']} "
        f"vanished={tag_stats['skipped_zero_quota']}"
    )

    # Stage 5: Emergency size check — archive oldest months if DB >= 480 MB.
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
        choices=["a", "b", "c", "d", "e", "all"],
        default="all",
        help=(
            "Which site group to run. "
            "'a'=sites 0–2, 'b'=sites 3–5, 'c'=sites 6–9, "
            "'d'=sites 10–12, 'e'=sites 13–15, 'all'=every site (default)."
        ),
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
