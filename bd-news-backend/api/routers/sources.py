from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel

from api.database import articles_bn, articles_en
from scraper.sites import SITES

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceResponse(BaseModel):
    slug: str
    name: str
    language: str
    scrape_method: str
    article_count: int


async def _count_for_source(slug: str, language: str) -> int:
    col = articles_bn if language == "bn" else articles_en
    return await col.count_documents({"source": slug})


@router.get("", response_model=list[SourceResponse])
async def get_sources() -> list[SourceResponse]:
    tasks = [_count_for_source(s["slug"], s["language"]) for s in SITES]  # type: ignore[arg-type]
    counts = await asyncio.gather(*tasks)

    return [
        SourceResponse(
            slug=site["slug"],          # type: ignore[arg-type]
            name=site["name"],          # type: ignore[arg-type]
            language=site["language"],  # type: ignore[arg-type]
            scrape_method=site["scrape_method"],  # type: ignore[arg-type]
            article_count=count,
        )
        for site, count in zip(SITES, counts)
    ]
