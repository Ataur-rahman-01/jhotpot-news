"""
gemini.py — Single-call article enrichment via OpenAI (GPT-4.1 Nano).

Per project rule: ONE call per article returns ALL four AI fields
(category, tags, sentiment, ai_summary). Never split into multiple calls.

To switch back to Gemini: uncomment the Gemini block below, comment out
the OpenAI block, and set GEMINI_API_KEY in your .env / GitHub Secrets.

Environment:
    OPENAI_API_KEY   (required — active)
    GEMINI_API_KEY   (not used — kept for reference)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any, Dict, Optional

# ── Active: OpenAI ────────────────────────────────────────────────────────────
from openai import AsyncOpenAI

# ── Commented out: Gemini ─────────────────────────────────────────────────────
# import google.generativeai as genai


# ─────────────────────────────────────────────────────────────────────────────
# Model config
# ─────────────────────────────────────────────────────────────────────────────
MODEL_NAME = "gpt-4.1-nano"

# Gemini equivalent (uncomment to switch back):
# GEMINI_MODEL_NAME = "gemini-1.5-flash"

ALLOWED_CATEGORIES = {
    "politics", "sports", "business", "technology", "entertainment",
    "international", "crime", "health", "education", "environment",
    "religion", "transportation",
}
ALLOWED_SENTIMENTS = {"positive", "neutral", "negative"}

RATE_LIMIT_DELAY_SECONDS = 3.0   # wait 3 s after each call — gives API time to breathe
MAX_INPUT_WORDS = 500            # cap body at 500 words before sending to the API


# ─────────────────────────────────────────────────────────────────────────────
# OpenAI client — lazy singleton
# ─────────────────────────────────────────────────────────────────────────────
_OPENAI_CLIENT: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _OPENAI_CLIENT
    if _OPENAI_CLIENT is not None:
        return _OPENAI_CLIENT
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set in .env or GitHub Secrets")
    _OPENAI_CLIENT = AsyncOpenAI(api_key=api_key)
    return _OPENAI_CLIENT


# ── Gemini client (commented out) ────────────────────────────────────────────
# _GEMINI_MODEL = None
#
# def _get_gemini_model():
#     global _GEMINI_MODEL
#     if _GEMINI_MODEL is not None:
#         return _GEMINI_MODEL
#     api_key = os.getenv("GEMINI_API_KEY")
#     if not api_key:
#         raise RuntimeError("GEMINI_API_KEY is not set in .env or GitHub Secrets")
#     genai.configure(api_key=api_key)
#     _GEMINI_MODEL = genai.GenerativeModel(GEMINI_MODEL_NAME)
#     return _GEMINI_MODEL


# ─────────────────────────────────────────────────────────────────────────────
# Prompt — shared by both OpenAI and Gemini (same text works for both)
# ─────────────────────────────────────────────────────────────────────────────
def _build_prompt(title: str, body: str, language: str) -> str:
    lang_label = "Bangla" if language == "bn" else "English"
    categories = ", ".join(sorted(ALLOWED_CATEGORIES))
    sentiments  = ", ".join(sorted(ALLOWED_SENTIMENTS))

    return f"""You are a news article tagger. Analyse the article below and return ONLY
valid JSON. No markdown. No explanation. No backticks. No prose before or after.

The article is in {lang_label}.

Return a JSON object with EXACTLY these four fields:

  "category"   — string, MUST be one of: {categories}
  "tags"       — array of 5 to 8 keywords, written in the article's own language ({lang_label})
  "sentiment"  — string, MUST be one of: {sentiments}
  "ai_summary" — string, EXACTLY 2 to 3 sentences, written in the article's own language ({lang_label})

ARTICLE TITLE:
{title}

ARTICLE BODY:
{body}

Respond with valid JSON only, no markdown, no explanation, no backticks."""


# ─────────────────────────────────────────────────────────────────────────────
# Response parsing + validation (shared)
# ─────────────────────────────────────────────────────────────────────────────
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE | re.MULTILINE)


def _parse_json_response(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    cleaned = _FENCE_RE.sub("", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _validate(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict):
        return None

    category = data.get("category")
    if not isinstance(category, str) or category.lower() not in ALLOWED_CATEGORIES:
        return None
    category = category.lower()

    tags = data.get("tags")
    if not isinstance(tags, list):
        return None
    tags = [str(t).strip() for t in tags if str(t).strip()]
    if len(tags) < 3:
        return None
    tags = tags[:8]

    sentiment = data.get("sentiment")
    if not isinstance(sentiment, str) or sentiment.lower() not in ALLOWED_SENTIMENTS:
        return None
    sentiment = sentiment.lower()

    ai_summary = data.get("ai_summary")
    if not isinstance(ai_summary, str) or not ai_summary.strip():
        return None

    return {
        "category":   category,
        "tags":       tags,
        "sentiment":  sentiment,
        "ai_summary": ai_summary.strip(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────
async def tag_article(article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Enrich one article with GPT-4.1 Nano in a single API call.
    Returns {category, tags, sentiment, ai_summary} or None on failure.
    """
    title    = (article.get("title")   or "").strip()
    body     = (article.get("content") or article.get("summary") or "").strip()
    language = article.get("language") or "en"

    if not title and not body:
        return None

    # Truncate to MAX_INPUT_WORDS words — keeps the payload small and fast.
    words = body.split()
    if len(words) > MAX_INPUT_WORDS:
        body = " ".join(words[:MAX_INPUT_WORDS])

    try:
        # ── OpenAI call (active) ──────────────────────────────────────────────
        client  = _get_client()
        prompt  = _build_prompt(title, body, language)

        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or ""

        # ── Gemini call (commented out) ───────────────────────────────────────
        # model    = _get_gemini_model()
        # prompt   = _build_prompt(title, body, language)
        # response = await asyncio.to_thread(
        #     model.generate_content,
        #     prompt,
        #     generation_config=genai.GenerationConfig(
        #         temperature=0.2,
        #         max_output_tokens=512,
        #         response_mime_type="application/json",
        #     ),
        # )
        # raw = response.text or ""

        parsed = _parse_json_response(raw)
        if parsed is None:
            print(f"[ai] JSON parse failed. Raw: {raw[:200]!r}")
            return None

        validated = _validate(parsed)
        if validated is None:
            print(f"[ai] validation failed for keys={list(parsed.keys())}")
            return None

        return validated

    except Exception as exc:  # noqa: BLE001
        print(f"[ai] tag_article failed: {type(exc).__name__}: {exc}")
        return None
    finally:
        await asyncio.sleep(RATE_LIMIT_DELAY_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test: python -m scraper.gemini
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    sample = {
        "title": "Bangladesh wins by 6 wickets against Sri Lanka in Asia Cup",
        "content": (
            "Bangladesh chased down 165 with two overs to spare. Litton Das "
            "scored 62 off 48 balls. The win puts them at the top of Group B. "
            "Captain Najmul praised the bowlers for restricting Sri Lanka to 164."
        ),
        "language": "en",
    }
    result = asyncio.run(tag_article(sample))
    print(json.dumps(result, indent=2, ensure_ascii=False))
