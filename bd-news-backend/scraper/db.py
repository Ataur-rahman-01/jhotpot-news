"""
db.py — Synchronous MongoDB operations for the scraper + Gemini pipeline.

Why sync (not motor)?
    The scraper runs inside GitHub Actions as a short-lived script — there is
    no event loop benefit to async here, and pymongo is simpler. The FastAPI
    side uses motor (async) instead; the two drivers can coexist because each
    process opens its own connection.

Environment:
    MONGO_URI       (required)  full Atlas SRV connection string
    MONGO_DB_NAME   (optional)  defaults to 'bd_news_archive'

Collections touched:
    articles_bn          — Bangla articles  (hot, last 90 days)
    articles_en          — English articles (hot, last 90 days)
    user_history         — per-user read tracking with 90-day TTL
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from datetime import timedelta

from pymongo import MongoClient, ASCENDING, DESCENDING, TEXT, UpdateOne
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import BulkWriteError

# ─────────────────────────────────────────────────────────────────────────────
# Connection — lazy singleton so importing this module is cheap.
# ─────────────────────────────────────────────────────────────────────────────
_CLIENT: Optional[MongoClient] = None
_DB: Optional[Database] = None

ARTICLE_COLLECTIONS = ("articles_bn", "articles_en")
DEFAULT_DB_NAME = "bd_news_archive"
TTL_90_DAYS_SECONDS = 60 * 60 * 24 * 90   # 7,776,000


def _get_db() -> Database:
    """Return the shared Database handle, opening a client on first use."""
    global _CLIENT, _DB
    if _DB is not None:
        return _DB

    uri = os.getenv("MONGO_URI")
    if not uri:
        raise RuntimeError(
            "MONGO_URI is not set. Put it in your environment or .env file. "
            "Never commit it — it is a GitHub Secret in production."
        )

    db_name = os.getenv("MONGO_DB_NAME", DEFAULT_DB_NAME)
    # serverSelectionTimeoutMS keeps GHA from hanging if Atlas is unreachable.
    _CLIENT = MongoClient(uri, serverSelectionTimeoutMS=10_000, appname="bd-news-scraper")
    _DB = _CLIENT[db_name]
    return _DB


def get_collection(name: str) -> Collection:
    """Validated collection accessor — refuses unknown names."""
    if name not in ARTICLE_COLLECTIONS and name not in ("user_history", "users", "user_bookmarks"):
        raise ValueError(f"Unknown collection {name!r}")
    return _get_db()[name]


# ─────────────────────────────────────────────────────────────────────────────
# Index setup — idempotent, safe to call on every scraper run.
# ─────────────────────────────────────────────────────────────────────────────
def setup_indexes() -> None:
    """
    Create every index this project needs. pymongo's create_index is
    idempotent — re-running this is a no-op once indexes exist.

    Indexes on articles_bn AND articles_en:
        url             unique          dedup key
        published_at    desc            feed queries
        source          asc             filter by newspaper
        category        asc             filter by topic
        ai_processed    asc             Gemini queue
        text(title, content, ai_summary)   full-text search

    Indexes on user_history:
        (firebase_uid, article_url)  compound, unique   O(1) duplicate-read check
        read_at                       TTL 90 days       auto-cleanup
    """
    db = _get_db()

    for col_name in ARTICLE_COLLECTIONS:
        col = db[col_name]
        col.create_index([("url", ASCENDING)], unique=True, name="uniq_url")
        col.create_index([("published_at", DESCENDING)], name="published_at_desc")
        col.create_index([("source", ASCENDING)], name="source_asc")
        col.create_index([("category", ASCENDING)], name="category_asc")
        col.create_index([("ai_processed", ASCENDING)], name="ai_processed_asc")

        # Drop old text index that included 'content' — it was the largest index.
        # New index covers only title + ai_summary (same search quality, ~50% smaller).
        try:
            col.drop_index("text_title_content_summary")
        except Exception:
            pass  # didn't exist yet

        col.create_index(
            [("title", TEXT), ("ai_summary", TEXT)],
            name="text_title_summary",
            weights={"title": 10, "ai_summary": 5},
            default_language="none",
            language_override="text_lang",
        )
        print(f"[indexes] {col_name}: ensured 6 indexes")

    # user_history is a separate concern but lives in the same DB, so we
    # set it up here too — keeps "first-run bootstrap" in one place.
    hist = db["user_history"]
    hist.create_index(
        [("firebase_uid", ASCENDING), ("article_url", ASCENDING)],
        unique=True,
        name="uniq_uid_url",
    )
    hist.create_index(
        [("read_at", ASCENDING)],
        expireAfterSeconds=TTL_90_DAYS_SECONDS,
        name="ttl_read_at_90d",
    )
    print(f"[indexes] user_history: ensured 2 indexes (incl. 90d TTL)")

    users = db["users"]
    users.create_index(
        [("firebase_uid", ASCENDING)],
        unique=True,
        name="uniq_firebase_uid",
    )
    print("[indexes] users: ensured 1 index")

    bookmarks = db["user_bookmarks"]
    bookmarks.create_index(
        [("firebase_uid", ASCENDING), ("article_id", ASCENDING)],
        unique=True,
        name="uniq_uid_article",
    )
    bookmarks.create_index(
        [("firebase_uid", ASCENDING), ("saved_at", DESCENDING)],
        name="uid_saved_at_desc",
    )
    print("[indexes] user_bookmarks: ensured 2 indexes")


# ─────────────────────────────────────────────────────────────────────────────
# Article writes — upsert on url, never overwrite existing docs.
# ─────────────────────────────────────────────────────────────────────────────
def save_articles(articles: List[Dict[str, Any]], collection_name: str) -> int:
    """
    Bulk-upsert articles keyed by `url`. Uses $setOnInsert so an existing
    document is NEVER overwritten — preserves AI-enriched fields and the
    original `content` once they've been added by later pipeline stages.

    Args:
        articles:        list of dicts from rss_parser.fetch_site()
        collection_name: 'articles_bn' or 'articles_en'

    Returns:
        Count of NEW documents inserted on this call. Updates/no-ops do not count.
    """
    if collection_name not in ARTICLE_COLLECTIONS:
        raise ValueError(f"save_articles target must be one of {ARTICLE_COLLECTIONS}, got {collection_name!r}")
    if not articles:
        return 0

    col = get_collection(collection_name)
    ops: List[UpdateOne] = []

    for a in articles:
        url = a.get("url")
        if not url:
            continue  # rss_parser already filters these but be safe

        # Defaults applied only on first insert. Existing docs keep their
        # AI fields, content, etc. untouched.
        raw_content = a.get("content", "")
        on_insert = {
            "url": url,
            "title": a.get("title", ""),
            # summary omitted — ai_summary replaces it after Gemini processing
            "content": raw_content[:3000],            # cap at 3000 chars (~9 KB for Bangla)
            "image_url": a.get("image_url"),          # may be None — that is OK
            "source": a.get("source", ""),
            "language": a.get("language", ""),
            "published_at": a.get("published_at"),
            "scraped_at": a.get("scraped_at", datetime.utcnow()),
            # AI fields default empty until gemini.py fills them.
            "category": None,
            "tags": [],
            "sentiment": None,
            "ai_summary": "",
            "ai_processed": False,
        }

        ops.append(UpdateOne(
            {"url": url},
            {"$setOnInsert": on_insert},
            upsert=True,
        ))

    if not ops:
        return 0

    try:
        result = col.bulk_write(ops, ordered=False)
    except BulkWriteError as bwe:
        # Duplicates from race conditions (two GHA runs overlapping) are
        # safe to ignore — the unique index did its job.
        write_errors = bwe.details.get("writeErrors", [])
        non_dup = [e for e in write_errors if e.get("code") != 11000]
        if non_dup:
            print(f"[save_articles] non-duplicate bulk write errors: {non_dup}")
        inserted = bwe.details.get("nUpserted", 0)
        print(f"[save_articles] {collection_name}: +{inserted} new (with conflicts)")
        return inserted

    inserted = result.upserted_count
    print(f"[save_articles] {collection_name}: +{inserted} new / {len(ops)} attempted")
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
# Gemini queue helpers
# ─────────────────────────────────────────────────────────────────────────────
def get_unprocessed(collection_name: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Return up to `limit` articles still waiting for Gemini enrichment.

    Sorted oldest-first by scraped_at so the queue doesn't starve early
    articles when newer batches keep arriving.
    """
    if collection_name not in ARTICLE_COLLECTIONS:
        raise ValueError(f"get_unprocessed target must be one of {ARTICLE_COLLECTIONS}, got {collection_name!r}")
    if limit <= 0:
        return []

    col = get_collection(collection_name)
    cursor = (
        col.find({"ai_processed": False})
           .sort("scraped_at", ASCENDING)
           .limit(limit)
    )
    return list(cursor)


def get_articles_without_content(collection_name: str, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Return articles that still have an empty content field, scoped to the last
    7 days so permanently-blocked sites (403) don't consume the quota forever.

    Sorted newest-first — fresh articles always win over old retry candidates.
    ai_processed is intentionally NOT filtered: an article can be Gemini-tagged
    but still have empty content if the content fetch failed in the same run
    (Gemini runs right after content-fetch, so a failed article gets tagged
    immediately and would otherwise be excluded forever).

    Only _id, url, and source are projected — the caller only needs those.
    """
    if collection_name not in ARTICLE_COLLECTIONS:
        raise ValueError(f"get_articles_without_content target must be one of {ARTICLE_COLLECTIONS}, got {collection_name!r}")
    if limit <= 0:
        return []

    cutoff = datetime.utcnow() - timedelta(days=7)
    col = get_collection(collection_name)
    cursor = (
        col.find(
            {"content": {"$in": ["", None]}, "scraped_at": {"$gte": cutoff}},
            {"_id": 1, "url": 1, "source": 1},
        )
        .sort("scraped_at", DESCENDING)
        .limit(limit)
    )
    return list(cursor)


def update_content(collection_name: str, article_id: Any, content: str) -> bool:
    """
    Write fetched article body text into an article document.

    Only updates when content is still empty (safety guard against overwriting
    text already fetched by a concurrent run). Returns True if one doc was updated.
    """
    if collection_name not in ARTICLE_COLLECTIONS:
        raise ValueError(f"update_content target must be one of {ARTICLE_COLLECTIONS}, got {collection_name!r}")

    col = get_collection(collection_name)
    result = col.update_one(
        {"_id": article_id, "content": ""},
        {"$set": {"content": content[:3000]}},  # cap at 3000 chars
    )
    return result.modified_count == 1


def mark_processed(collection_name: str, article_id: Any, ai_data: Dict[str, Any]) -> bool:
    """
    Apply Gemini's output to an article and flip ai_processed to True.

    Expected keys in ai_data:
        category   str   one of the SKILL.md categories
        tags       list  5–8 keywords in the article's language
        sentiment  str   positive / neutral / negative
        ai_summary str   2–3 sentence summary in the article's language

    Returns True if exactly one document was updated.
    """
    if collection_name not in ARTICLE_COLLECTIONS:
        raise ValueError(f"mark_processed target must be one of {ARTICLE_COLLECTIONS}, got {collection_name!r}")

    update_doc = {
        "category":   ai_data.get("category"),
        "tags":       ai_data.get("tags", []),
        "sentiment":  ai_data.get("sentiment"),
        "ai_summary": ai_data.get("ai_summary", ""),
        "ai_processed": True,
    }

    col = get_collection(collection_name)
    result = col.update_one({"_id": article_id}, {"$set": update_doc})
    return result.modified_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# Manual bootstrap: `python -m scraper.db` creates indexes once.
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    setup_indexes()
    print("Done. All indexes ensured.")
