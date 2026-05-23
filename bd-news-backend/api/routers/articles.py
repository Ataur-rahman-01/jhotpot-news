from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorCollection

from api.database import articles_bn, articles_en
from api.models import ArticleResponse

router = APIRouter(prefix="/articles", tags=["articles"])

_MAX_LIMIT = 100


def _build_filter(category: Optional[str], source: Optional[str]) -> dict:
    f: dict = {}
    if category:
        f["category"] = category
    if source:
        f["source"] = source
    return f


_LIST_PROJECTION = {"content": 0}  # content only needed on single-article view

async def _fetch_page(
    col: AsyncIOMotorCollection,
    page: int,
    limit: int,
    category: Optional[str],
    source: Optional[str],
) -> list[ArticleResponse]:
    skip = (page - 1) * limit
    query = _build_filter(category, source)
    cursor = col.find(query, _LIST_PROJECTION).sort("published_at", -1).skip(skip).limit(limit)
    docs = await cursor.to_list(length=limit)
    return [ArticleResponse.model_validate(doc) for doc in docs]


@router.get("/bn", response_model=list[ArticleResponse])
async def get_bangla_articles(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=_MAX_LIMIT),
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
) -> list[ArticleResponse]:
    return await _fetch_page(articles_bn, page, limit, category, source)


@router.get("/en", response_model=list[ArticleResponse])
async def get_english_articles(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=_MAX_LIMIT),
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
) -> list[ArticleResponse]:
    return await _fetch_page(articles_en, page, limit, category, source)


@router.get("/{article_id}", response_model=ArticleResponse)
async def get_article(article_id: str) -> ArticleResponse:
    try:
        oid = ObjectId(article_id)
    except InvalidId:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Article not found")

    doc = await articles_bn.find_one({"_id": oid})
    if doc is None:
        doc = await articles_en.find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Article not found")

    return ArticleResponse.model_validate(doc)
