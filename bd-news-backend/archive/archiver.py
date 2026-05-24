"""
archiver.py — Monthly archive job: MongoDB → gzip → Backblaze B2.

Two entry points:

  run_archive()
      Sunday cron job. Archives everything older than 90 days.

  check_and_archive_if_needed()
      Called after every scraper run. Checks database size; if it reaches
      480 MB it archives oldest months until 400 MB has been freed, keeping
      the Atlas M0 free tier safely under the 512 MB hard limit.

Safety rule: articles are deleted from MongoDB ONLY after B2 upload is
confirmed. A failed upload leaves MongoDB untouched so no data is lost.

Usage:
    python -m archive.archiver
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
load_dotenv()

from archive.b2_client import B2Client
from archive.compressor import compress
from scraper.db import get_collection, _get_db


COLLECTIONS: List[Tuple[str, str]] = [
    ("articles_bn", "bn"),
    ("articles_en", "en"),
]

SIZE_THRESHOLD_MB = 480   # trigger emergency archive above this
FREE_TARGET_MB    = 400   # keep archiving until this many MB are freed


# ─────────────────────────────────────────────────────────────────────────────
# DB size helper
# ─────────────────────────────────────────────────────────────────────────────
def get_db_size_mb() -> float:
    """Return current MongoDB database data size in MB."""
    stats = _get_db().command("dbStats", scale=1024 * 1024)
    return float(stats["dataSize"])


# ─────────────────────────────────────────────────────────────────────────────
# Shared: archive one year-month group to B2 and delete from MongoDB
# ─────────────────────────────────────────────────────────────────────────────
def _archive_group(
    b2: B2Client,
    col: Any,
    collection_name: str,
    folder: str,
    year: int,
    month: int,
    articles: List[Dict[str, Any]],
    tag: str = "[archive]",
) -> int:
    """
    Compress + upload one month's articles to B2, then delete from MongoDB.
    Returns number of documents deleted (0 on upload failure).
    """
    filename = f"{year}_{month:02d}.json.gz"

    if b2.file_exists(filename, folder):
        print(f"{tag} {collection_name} {year}-{month:02d}: already in B2, skipping")
        # Still safe to delete from MongoDB if the file was uploaded previously.
        ids = [a["_id"] for a in articles]
        result = col.delete_many({"_id": {"$in": ids}})
        if result.deleted_count:
            print(f"{tag} {collection_name} {year}-{month:02d}: "
                  f"cleaned {result.deleted_count} docs still in MongoDB")
        return result.deleted_count

    compressed = compress(articles)
    b2.upload(filename, compressed, folder)

    if not b2.file_exists(filename, folder):
        print(f"{tag} ERROR: upload not confirmed for {folder}/{filename} — MongoDB untouched")
        return 0

    ids = [a["_id"] for a in articles]
    result = col.delete_many({"_id": {"$in": ids}})
    deleted = result.deleted_count

    print(
        f"{tag} {collection_name} {year}-{month:02d}: "
        f"{len(articles)} archived, {deleted} deleted from MongoDB"
    )
    return deleted


# ─────────────────────────────────────────────────────────────────────────────
# Sunday cron job — archive everything older than 90 days
# ─────────────────────────────────────────────────────────────────────────────
def run_archive() -> None:
    cutoff = datetime.utcnow() - timedelta(days=90)
    b2 = B2Client()

    total_archived = 0
    total_deleted  = 0

    for collection_name, folder in COLLECTIONS:
        col = get_collection(collection_name)

        pipeline: List[Dict[str, Any]] = [
            {"$match": {"published_at": {"$lt": cutoff}}},
            {"$group": {
                "_id": {
                    "year":  {"$year":  "$published_at"},
                    "month": {"$month": "$published_at"},
                },
                "articles": {"$push": "$$ROOT"},
            }},
            {"$sort": {"_id.year": 1, "_id.month": 1}},
        ]

        groups = list(col.aggregate(pipeline, allowDiskUse=True))

        if not groups:
            print(f"[archive] {collection_name}: nothing older than 90 days")
            continue

        for group in groups:
            year     = group["_id"]["year"]
            month    = group["_id"]["month"]
            articles = group["articles"]

            deleted = _archive_group(
                b2, col, collection_name, folder, year, month, articles
            )
            total_archived += len(articles)
            total_deleted  += deleted

    print(
        f"[archive] done — {total_archived} articles archived, "
        f"{total_deleted} documents freed from MongoDB"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Size-based emergency archive — called after every scraper run
# ─────────────────────────────────────────────────────────────────────────────
def check_and_archive_if_needed() -> None:
    """
    Check MongoDB data size. If >= 480 MB, archive oldest months (no 90-day
    restriction) until 400 MB has been freed, keeping Atlas M0 safe.
    Freed space is estimated from the raw JSON bytes of archived articles.
    """
    current_mb = get_db_size_mb()
    print(f"[size-check] MongoDB dataSize: {current_mb:.1f} MB")

    if current_mb < SIZE_THRESHOLD_MB:
        print(f"[size-check] Under {SIZE_THRESHOLD_MB} MB — no action needed")
        return

    print(
        f"[size-check] {current_mb:.1f} MB >= {SIZE_THRESHOLD_MB} MB threshold — "
        f"archiving oldest articles until {FREE_TARGET_MB} MB freed"
    )

    b2 = B2Client()
    freed_bytes   = 0
    target_bytes  = FREE_TARGET_MB * 1024 * 1024
    total_deleted = 0

    for collection_name, folder in COLLECTIONS:
        if freed_bytes >= target_bytes:
            break

        col = get_collection(collection_name)

        # No date filter — oldest first, regardless of 90-day rule.
        pipeline: List[Dict[str, Any]] = [
            {"$group": {
                "_id": {
                    "year":  {"$year":  "$published_at"},
                    "month": {"$month": "$published_at"},
                },
                "articles": {"$push": "$$ROOT"},
            }},
            {"$sort": {"_id.year": 1, "_id.month": 1}},
        ]

        groups = list(col.aggregate(pipeline, allowDiskUse=True))

        for group in groups:
            if freed_bytes >= target_bytes:
                break

            year     = group["_id"]["year"]
            month    = group["_id"]["month"]
            articles = group["articles"]

            # Estimate freed bytes from raw JSON size (close to BSON size).
            raw_json = json.dumps(articles, default=str)
            estimated_bytes = len(raw_json.encode("utf-8"))

            deleted = _archive_group(
                b2, col, collection_name, folder,
                year, month, articles,
                tag="[size-archive]",
            )

            if deleted:
                freed_bytes   += estimated_bytes
                total_deleted += deleted

    freed_mb   = freed_bytes / (1024 * 1024)
    final_mb   = get_db_size_mb()
    print(
        f"[size-archive] done — ~{freed_mb:.0f} MB freed, "
        f"{total_deleted} docs deleted, "
        f"MongoDB now {final_mb:.1f} MB"
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["size-check", "full"],
        default="size-check",
        help="size-check: archive only if >= 480 MB (daily job). full: archive all >90 day articles.",
    )
    args = parser.parse_args()
    if args.mode == "size-check":
        check_and_archive_if_needed()
    else:
        run_archive()
