"""
compressor.py — JSON serialisation + gzip compression for article archives.

compress(articles) -> bytes   : list[dict] → JSON → gzip
decompress(data)   -> list    : gzip → JSON → list[dict]

MongoDB ObjectId and datetime values are serialised to plain strings so the
JSON round-trip is lossless for every field the archive needs to preserve.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime
from typing import Any, List


def _default(obj: Any) -> Any:
    """JSON serialiser fallback for types json.dumps cannot handle natively."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    # bson.ObjectId — match by class name so bson is not a hard dependency.
    if type(obj).__name__ == "ObjectId":
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serialisable")


def compress(articles: List[dict]) -> bytes:
    """
    Serialise articles to JSON and compress with gzip.

    Returns compressed bytes. Prints compression ratio to stdout so the
    archive job log shows how much space each monthly file saves.
    """
    raw_json = json.dumps(articles, default=_default, ensure_ascii=False)
    raw_bytes = raw_json.encode("utf-8")
    compressed = gzip.compress(raw_bytes, compresslevel=9)

    original_kb  = len(raw_bytes)  / 1024
    compressed_kb = len(compressed) / 1024
    reduction = (1 - len(compressed) / len(raw_bytes)) * 100
    print(
        f"[compress] {original_kb:.0f}KB -> {compressed_kb:.0f}KB, "
        f"{reduction:.0f}% reduction"
    )

    return compressed


def decompress(data: bytes) -> List[dict]:
    """Decompress gzip bytes and parse JSON. Returns list of dicts."""
    raw_bytes = gzip.decompress(data)
    return json.loads(raw_bytes.decode("utf-8"))
