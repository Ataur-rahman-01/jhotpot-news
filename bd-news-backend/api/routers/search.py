from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from api.database import articles_bn, articles_en
from api.models import ArticleResponse
from archive.b2_client import B2Client
from archive.compressor import decompress

router = APIRouter(tags=["search"])

_b2_client: B2Client | None = None

def _get_b2() -> B2Client:
    global _b2_client
    if _b2_client is None:
        _b2_client = B2Client()
    return _b2_client

_MAX_LIMIT = 100
_ARCHIVE_MONTHS = 6
_ARCHIVE_MIN_RESULTS = 5
_ARCHIVE_MAX_RESULTS = 10


class SearchResponse(BaseModel):
    query: str
    count: int
    results: list[ArticleResponse]


# ---------------------------------------------------------------------------
# MongoDB text search
# ---------------------------------------------------------------------------

async def _mongo_search(
    q: str,
    lang: Optional[str],
    page: int,
    limit: int,
) -> list[dict]:
    pipeline = [
        {"$match": {"$text": {"$search": q}}},
        {"$addFields": {"_score": {"$meta": "textScore"}}},
        {"$sort": {"_score": -1, "published_at": -1}},
        {"$skip": (page - 1) * limit},
        {"$limit": limit},
    ]

    if lang == "bn":
        collections = [articles_bn]
    elif lang == "en":
        collections = [articles_en]
    else:
        collections = [articles_bn, articles_en]

    if len(collections) == 1:
        return await collections[0].aggregate(pipeline).to_list(length=limit)

    bn_docs, en_docs = await asyncio.gather(
        articles_bn.aggregate(pipeline).to_list(length=limit),
        articles_en.aggregate(pipeline).to_list(length=limit),
    )
    merged = sorted(
        bn_docs + en_docs,
        key=lambda d: d.get("_score", 0),
        reverse=True,
    )
    return merged[:limit]


# ---------------------------------------------------------------------------
# Archive (B2) search
# ---------------------------------------------------------------------------

def _recent_archive_filenames(months: int) -> list[tuple[str, str]]:
    """Return (folder, filename) pairs for the last `months` months."""
    now = datetime.now(tz=timezone.utc)
    pairs: list[tuple[str, str]] = []
    year, month = now.year, now.month
    for _ in range(months):
        filename = f"{year}_{month:02d}.json.gz"
        pairs.append(("bn", filename))
        pairs.append(("en", filename))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return pairs


def _search_archive_docs(docs: list[dict], q: str) -> list[dict]:
    terms = q.lower().split()
    hits: list[dict] = []
    for doc in docs:
        haystack = (
            (doc.get("title") or "")
            + " " + (doc.get("summary") or "")
            + " " + (doc.get("ai_summary") or "")
        ).lower()
        if all(t in haystack for t in terms):
            hits.append(doc)
    return hits


async def _archive_search(q: str, lang: Optional[str]) -> list[ArticleResponse]:
    b2 = _get_b2()

    pairs = _recent_archive_filenames(_ARCHIVE_MONTHS)
    if lang in ("bn", "en"):
        pairs = [(f, name) for f, name in pairs if f == lang]

    hits: list[dict] = []

    def _fetch_and_search(folder: str, filename: str) -> list[dict]:
        try:
            raw = b2.download(filename, folder)
            docs = decompress(raw)
            return _search_archive_docs(docs, q)
        except Exception:
            return []

    loop = asyncio.get_running_loop()
    tasks = [
        loop.run_in_executor(None, _fetch_and_search, folder, filename)
        for folder, filename in pairs
    ]
    results = await asyncio.gather(*tasks)

    for batch in results:
        hits.extend(batch)
        if len(hits) >= _ARCHIVE_MAX_RESULTS:
            break

    articles: list[ArticleResponse] = []
    for doc in hits[:_ARCHIVE_MAX_RESULTS]:
        try:
            articles.append(ArticleResponse.model_validate(doc))
        except Exception:
            continue
    return articles


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/search", response_model=SearchResponse)
async def search_articles(
    q: str = Query(..., min_length=1),
    lang: Optional[str] = Query(None, pattern="^(bn|en)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=_MAX_LIMIT),
    include_archive: bool = Query(False),
) -> SearchResponse:
    mongo_docs = await _mongo_search(q, lang, page, limit)
    results = [ArticleResponse.model_validate(doc) for doc in mongo_docs]

    if include_archive and len(results) < _ARCHIVE_MIN_RESULTS:
        archive_results = await _archive_search(q, lang)
        seen_urls = {r.url for r in results}
        for article in archive_results:
            if article.url not in seen_urls:
                results.append(article)
                seen_urls.add(article.url)

    return SearchResponse(query=q, count=len(results), results=results)
