from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Optional

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def _coerce_objectid(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    return v


PyObjectId = Annotated[str, BeforeValidator(_coerce_objectid)]


class MongoBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[PyObjectId] = Field(None, alias="_id")


# ---------------------------------------------------------------------------
# Article
# ---------------------------------------------------------------------------

class ArticleResponse(MongoBase):
    url: str
    title: str
    content: str = ""
    summary: Optional[str] = None  # removed from new docs; kept for backward compat
    image_url: Optional[str] = None
    source: str
    language: str                       # "bn" | "en"
    published_at: Optional[datetime] = None
    scraped_at: datetime
    category: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    sentiment: Optional[str] = None     # "positive" | "neutral" | "negative"
    ai_summary: Optional[str] = None
    ai_processed: bool = False


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    firebase_uid: str
    email: str
    display_name: str
    language_pref: list[str] = Field(default_factory=lambda: ["bn"])

    @field_validator("language_pref")
    @classmethod
    def _validate_langs(cls, v: list[str]) -> list[str]:
        bad = [lang for lang in v if lang not in ("bn", "en")]
        if bad:
            raise ValueError(f"Invalid language values: {bad}. Allowed: 'bn', 'en'")
        return v


class UserProfile(MongoBase):
    firebase_uid: str
    email: str
    display_name: str
    language_pref: list[str] = Field(default_factory=lambda: ["bn"])
    onboarding_done: bool = False
    created_at: Optional[datetime] = None
    last_active: Optional[datetime] = None
    category_weights: dict[str, float] = Field(default_factory=dict)
    source_weights: dict[str, float] = Field(default_factory=dict)
    keyword_weights: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# User actions
# ---------------------------------------------------------------------------

class ReadEvent(BaseModel):
    article_id: PyObjectId
    article_url: str
    source: str
    category: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    language: str
    read_duration: int = Field(0, ge=0, description="Seconds spent reading")


class BookmarkCreate(BaseModel):
    article_id: PyObjectId
    title: str
    image_url: Optional[str] = None
    source: str
    category: Optional[str] = None
    language: str


class BookmarkResponse(MongoBase):
    firebase_uid: str
    article_id: PyObjectId
    title: str
    image_url: Optional[str] = None
    source: str
    category: Optional[str] = None
    language: str
    saved_at: Optional[datetime] = None
