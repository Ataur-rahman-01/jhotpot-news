import os
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_client: AsyncIOMotorClient | None = None


def _get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            raise RuntimeError("MONGO_URI environment variable is not set")
        _client = AsyncIOMotorClient(mongo_uri, serverSelectionTimeoutMS=10_000)
    return _client


def _get_db() -> AsyncIOMotorDatabase:
    db_name = os.getenv("MONGO_DB_NAME", "bd_news_archive")
    return _get_client()[db_name]


_db = _get_db()

articles_bn = _db["articles_bn"]
articles_en = _db["articles_en"]
sources_col = _db["sources"]
users_col = _db["users"]
user_history_col = _db["user_history"]
user_bookmarks_col = _db["user_bookmarks"]


async def get_database() -> AsyncIOMotorDatabase:
    return _get_db()
