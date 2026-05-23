from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, field_validator

from api.database import (
    articles_bn,
    articles_en,
    user_bookmarks_col,
    user_history_col,
    users_col,
)
from api.middleware.auth import get_current_user
from scraper.sites import SITES
from api.models import (
    ArticleResponse,
    BookmarkCreate,
    BookmarkResponse,
    ReadEvent,
    UserCreate,
    UserProfile,
)

router = APIRouter(tags=["users"])

_FEED_SIZE = 20
_CATEGORIES = [
    "politics", "sports", "business", "tech",
    "entertainment", "international", "crime",
    "health", "education", "environment",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _require_self(user_id: str, current_user: dict) -> None:
    if current_user["uid"] != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Forbidden")


def _top_key(weights: dict[str, float]) -> Optional[str]:
    """Return the key with the highest positive weight, or None."""
    if not weights:
        return None
    top = max(weights, key=lambda k: weights[k])
    return top if weights[top] > 0 else None


async def _get_user_or_404(user_id: str) -> dict:
    doc = await users_col.find_one({"firebase_uid": user_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    return doc


_HISTORY_EXCLUDE_LIMIT = 500  # cap $nin size — TTL keeps history under 90 days anyway

async def _read_history_urls(user_id: str) -> set[str]:
    cursor = (
        user_history_col.find(
            {"firebase_uid": user_id},
            projection={"article_url": 1, "_id": 0},
        )
        .sort("read_at", -1)
        .limit(_HISTORY_EXCLUDE_LIMIT)
    )
    docs = await cursor.to_list(length=_HISTORY_EXCLUDE_LIMIT)
    return {d["article_url"] for d in docs}


def _collections_for_prefs(language_pref: list[str]) -> list:
    cols = []
    if "bn" in language_pref:
        cols.append(articles_bn)
    if "en" in language_pref:
        cols.append(articles_en)
    return cols or [articles_bn, articles_en]


async def _fetch_articles(
    query: dict,
    exclude_urls: set[str],
    cols: list,
    needed: int,
) -> list[dict]:
    """Fetch up to `needed` docs matching query, excluding seen URLs, across cols."""
    if not needed:
        return []
    results: list[dict] = []
    for col in cols:
        if len(results) >= needed:
            break
        remaining = needed - len(results)
        # Rebuild per collection so urls found in col[0] are excluded from col[1]
        col_query = {**query, "url": {"$nin": list(exclude_urls)}} if exclude_urls else query
        cursor = col.find(col_query, {"content": 0}).sort("published_at", -1).limit(remaining * 3)
        docs = await cursor.to_list(length=remaining * 3)
        for doc in docs:
            if doc["url"] not in exclude_urls and len(results) < needed:
                results.append(doc)
                exclude_urls.add(doc["url"])
    return results


# ---------------------------------------------------------------------------
# POST /users  — create or update profile
# ---------------------------------------------------------------------------

@router.post("/users", response_model=UserProfile, status_code=status.HTTP_200_OK)
async def upsert_user(
    body: UserCreate,
    current_user: dict = Depends(get_current_user),
) -> UserProfile:
    if current_user["uid"] != body.firebase_uid:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Forbidden")

    default_weights = {cat: 0.0 for cat in _CATEGORIES}
    now = _now()

    await users_col.update_one(
        {"firebase_uid": body.firebase_uid},
        {
            "$setOnInsert": {
                "created_at": now,
                "category_weights": default_weights,
                "source_weights": {},
                "keyword_weights": {},
                "onboarding_done": False,
            },
            "$set": {
                "email": body.email,
                "display_name": body.display_name,
                "language_pref": body.language_pref,
                "last_active": now,
            },
        },
        upsert=True,
    )

    doc = await users_col.find_one({"firebase_uid": body.firebase_uid})
    return UserProfile.model_validate(doc)


# ---------------------------------------------------------------------------
# GET /feed/{user_id}
# ---------------------------------------------------------------------------

@router.get("/feed/{user_id}", response_model=list[ArticleResponse], tags=["feed"])
async def get_feed(
    user_id: str,
    current_user: dict = Depends(get_current_user),
) -> list[ArticleResponse]:
    _require_self(user_id, current_user)
    user = await _get_user_or_404(user_id)

    cat_weights: dict[str, float] = user.get("category_weights", {})
    src_weights: dict[str, float] = user.get("source_weights", {})
    lang_pref: list[str] = user.get("language_pref", ["bn"])

    top_cat = _top_key(cat_weights)
    top_src = _top_key(src_weights)
    preferred_cats = [k for k, v in cat_weights.items() if v > 0]

    cols = _collections_for_prefs(lang_pref)
    seen_urls = await _read_history_urls(user_id)
    feed: list[dict] = []

    slots = [
        # (priority label, query, target count)
        ("p1", {"category": top_cat, "source": top_src} if top_cat and top_src else None, 6),
        ("p2", {"category": top_cat} if top_cat else None, 5),
        ("p3", {"source": top_src} if top_src else None, 4),
        ("p4", {"category": {"$in": preferred_cats}} if preferred_cats else None, 3),
        ("p5", {}, _FEED_SIZE),  # fallback — always runs to fill remaining
    ]

    for _, query, target in slots:
        if len(feed) >= _FEED_SIZE:
            break
        if query is None:
            continue
        needed = min(target, _FEED_SIZE - len(feed))
        docs = await _fetch_articles(query, seen_urls, cols, needed)
        feed.extend(docs)

    return [ArticleResponse.model_validate(doc) for doc in feed[:_FEED_SIZE]]


# ---------------------------------------------------------------------------
# POST /users/{user_id}/read
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def record_read(
    user_id: str,
    body: ReadEvent,
    current_user: dict = Depends(get_current_user),
) -> None:
    _require_self(user_id, current_user)

    now = _now()
    history_doc = {
        "firebase_uid": user_id,
        "article_id": ObjectId(body.article_id),
        "article_url": body.article_url,
        "source": body.source,
        "category": body.category,
        "tags": body.tags,
        "language": body.language,
        "read_at": now,
        "read_duration": body.read_duration,
    }

    weight_inc: dict[str, float] = {}
    if body.category:
        weight_inc[f"category_weights.{body.category}"] = 3.0
    weight_inc[f"source_weights.{body.source}"] = 2.0
    for tag in body.tags:
        weight_inc[f"keyword_weights.{tag}"] = 1.0

    try:
        await user_history_col.insert_one(history_doc)
    except DuplicateKeyError:
        # Already in history — update last_active only, skip weight boost
        await users_col.update_one(
            {"firebase_uid": user_id}, {"$set": {"last_active": now}}
        )
        return

    # Only reached when insert succeeded (first read of this article)
    await users_col.update_one(
        {"firebase_uid": user_id},
        {"$inc": weight_inc, "$set": {"last_active": now}},
    )


# ---------------------------------------------------------------------------
# POST /users/{user_id}/bookmark
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def add_bookmark(
    user_id: str,
    body: BookmarkCreate,
    current_user: dict = Depends(get_current_user),
) -> None:
    _require_self(user_id, current_user)

    now = _now()
    bookmark_doc = {
        "firebase_uid": user_id,
        "article_id": ObjectId(body.article_id),
        "title": body.title,
        "image_url": body.image_url,
        "source": body.source,
        "category": body.category,
        "language": body.language,
        "saved_at": now,
    }

    weight_inc: dict[str, float] = {}
    if body.category:
        weight_inc[f"category_weights.{body.category}"] = 5.0
    weight_inc[f"source_weights.{body.source}"] = 3.0

    result = await user_bookmarks_col.update_one(
        {"firebase_uid": user_id, "article_id": ObjectId(body.article_id)},
        {"$setOnInsert": bookmark_doc},
        upsert=True,
    )
    # Only boost weights on first bookmark — not on duplicate taps
    if result.upserted_id is not None:
        await users_col.update_one(
            {"firebase_uid": user_id},
            {"$inc": weight_inc, "$set": {"last_active": now}},
        )
    else:
        await users_col.update_one(
            {"firebase_uid": user_id},
            {"$set": {"last_active": now}},
        )


# ---------------------------------------------------------------------------
# GET /users/{user_id}/bookmarks
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}/bookmarks", response_model=list[BookmarkResponse])
async def get_bookmarks(
    user_id: str,
    current_user: dict = Depends(get_current_user),
) -> list[BookmarkResponse]:
    _require_self(user_id, current_user)
    cursor = user_bookmarks_col.find({"firebase_uid": user_id}).sort("saved_at", -1).limit(15)
    docs = await cursor.to_list(length=15)
    return [BookmarkResponse.model_validate(doc) for doc in docs]


# ---------------------------------------------------------------------------
# DELETE /users/{user_id}/bookmark/{article_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/users/{user_id}/bookmark/{article_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_bookmark(
    user_id: str,
    article_id: str,
    current_user: dict = Depends(get_current_user),
) -> None:
    _require_self(user_id, current_user)

    try:
        oid = ObjectId(article_id)
    except InvalidId:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bookmark not found")

    result = await user_bookmarks_col.delete_one(
        {"firebase_uid": user_id, "article_id": oid}
    )
    if result.deleted_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Bookmark not found")


# ---------------------------------------------------------------------------
# GET /users/{user_id}/preferences
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}/preferences", response_model=UserProfile)
async def get_preferences(
    user_id: str,
    current_user: dict = Depends(get_current_user),
) -> UserProfile:
    _require_self(user_id, current_user)
    doc = await _get_user_or_404(user_id)
    return UserProfile.model_validate(doc)


# ---------------------------------------------------------------------------
# PUT /users/{user_id}/preferences
# ---------------------------------------------------------------------------

_VALID_SOURCES = {s["slug"] for s in SITES}

class PreferencesUpdate(BaseModel):
    language_pref: Optional[list[str]] = None
    preferred_categories: Optional[list[str]] = None
    preferred_sources: Optional[list[str]] = None

    @field_validator("language_pref")
    @classmethod
    def _validate_langs(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        bad = [lang for lang in v if lang not in ("bn", "en")]
        if bad:
            raise ValueError(f"Invalid language values: {bad}. Allowed: 'bn', 'en'")
        return v

    @field_validator("preferred_categories")
    @classmethod
    def _validate_cats(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        bad = [c for c in v if c not in _CATEGORIES]
        if bad:
            raise ValueError(f"Unknown categories: {bad}. Allowed: {_CATEGORIES}")
        return v

    @field_validator("preferred_sources")
    @classmethod
    def _validate_sources(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is None:
            return v
        bad = [s for s in v if s not in _VALID_SOURCES]
        if bad:
            raise ValueError(f"Unknown sources: {bad}")
        return v


@router.put("/users/{user_id}/preferences", response_model=UserProfile)
async def update_preferences(
    user_id: str,
    body: PreferencesUpdate,
    current_user: dict = Depends(get_current_user),
) -> UserProfile:
    _require_self(user_id, current_user)

    user = await _get_user_or_404(user_id)
    updates: dict = {"last_active": _now()}

    if body.language_pref is not None:
        updates["language_pref"] = body.language_pref

    if body.preferred_categories is not None:
        existing = user.get("category_weights", {})
        for cat in body.preferred_categories:
            updates[f"category_weights.{cat}"] = max(10.0, existing.get(cat, 0.0))

    if body.preferred_sources is not None:
        existing = user.get("source_weights", {})
        for src in body.preferred_sources:
            updates[f"source_weights.{src}"] = max(10.0, existing.get(src, 0.0))

    await users_col.update_one({"firebase_uid": user_id}, {"$set": updates})
    doc = await users_col.find_one({"firebase_uid": user_id})
    return UserProfile.model_validate(doc)
