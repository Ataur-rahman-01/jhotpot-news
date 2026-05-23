from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()  # must run before any project module reads os.environ

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers.articles import router as articles_router
from api.routers.search import router as search_router
from api.routers.sources import router as sources_router
from api.routers.users import router as users_router
from scraper.db import setup_indexes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # setup_indexes uses pymongo (sync) — run in thread to avoid blocking
    await asyncio.to_thread(setup_indexes)
    yield


app = FastAPI(title="BD News Archive API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # can't combine credentials=True with origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(articles_router)
app.include_router(search_router)
app.include_router(sources_router)
app.include_router(users_router)


@app.get("/", tags=["health"])
async def health_check() -> dict:
    return {"status": "ok", "message": "BD News Archive API"}
