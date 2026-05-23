"""
test_rss.py — Sanity-check every RSS feed in scraper/sites.py.

Run from the project root:
    python scripts/test_rss.py

For each of the 15 sites it prints:
    name           — display name
    status         — OK / FAIL
    article count  — entries returned by feedparser
    image found    — yes / no in the first entry

Ends with a summary line like:  Working: 13/15

This is a SYNC script on purpose — easier to read line-by-line output while
debugging a feed, and we are not in a hurry.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Optional

import feedparser

# Allow `python scripts/test_rss.py` from the project root by adding it to sys.path.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scraper.sites import SITES  # noqa: E402
from scraper.rss_parser import extract_image  # noqa: E402


COL_NAME = 22
COL_STATUS = 6
COL_COUNT = 7
COL_IMAGE = 11


def _has_image(entry: Any) -> bool:
    return extract_image(entry) is not None


def _fmt(name: str, status: str, count: str, image: str, extra: str = "") -> str:
    return (
        f"{name:<{COL_NAME}} "
        f"{status:<{COL_STATUS}} "
        f"{count:<{COL_COUNT}} "
        f"{image:<{COL_IMAGE}} "
        f"{extra}"
    )


def main() -> int:
    print(_fmt("SITE", "STATUS", "COUNT", "IMAGE@[0]", "DETAIL"))
    print("-" * 78)

    working = 0
    rss_total = 0
    total_time = 0.0

    for site in SITES:
        name = site["name"]
        # Sites with scrape_method='html' have rss_url=None and must NOT
        # be passed to feedparser — they belong to scraper/html_scrapers/.
        if site.get("scrape_method") != "rss":
            print(_fmt(name, "SKIP", "-", "-", f"method={site.get('scrape_method')!r} (not RSS)"))
            continue

        rss_total += 1
        url = site["rss_url"]

        t0 = time.monotonic()
        try:
            feed = feedparser.parse(url)
            elapsed = time.monotonic() - t0
            total_time += elapsed

            entries = getattr(feed, "entries", []) or []
            count = len(entries)

            if count == 0:
                bozo_exc: Optional[Any] = feed.get("bozo_exception")
                detail = f"empty feed ({type(bozo_exc).__name__})" if bozo_exc else "empty feed"
                print(_fmt(name, "FAIL", "0", "-", detail))
                continue

            image_present = _has_image(entries[0])
            print(_fmt(
                name,
                "OK",
                str(count),
                "yes" if image_present else "no",
                f"{elapsed:.2f}s",
            ))
            working += 1

        except Exception as exc:  # noqa: BLE001
            elapsed = time.monotonic() - t0
            total_time += elapsed
            print(_fmt(name, "FAIL", "-", "-", f"{type(exc).__name__}: {exc}"))

    print("-" * 78)
    print(
        f"Working: {working}/{rss_total} RSS sites    "
        f"(skipped {len(SITES) - rss_total} HTML-method sites)    "
        f"Total fetch time: {total_time:.1f}s"
    )
    return 0 if working == rss_total else 1


if __name__ == "__main__":
    sys.exit(main())
