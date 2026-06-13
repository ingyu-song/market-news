#!/usr/bin/env python3
"""Fetch financial-market news from RSS feeds and write data/news.json.

The site (index.html + app.js) reads that JSON and renders cards grouped by
source, coroke.net-style. Run locally with `python scraper.py`, or let the
GitHub Action run it on a schedule.
"""

import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser

ROOT = Path(__file__).resolve().parent
SOURCES_FILE = ROOT / "sources.json"
OUT_FILE = ROOT / "data" / "news.json"

# A real browser UA — some feeds (FT, Investing.com) reject the default one.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

TAG_RE = re.compile(r"<[^>]+>")


def clean_title(raw: str, source_title: str | None = None) -> str:
    """Strip HTML tags/entities and the trailing ' - Publisher' Google News adds."""
    text = html.unescape(raw or "").strip()
    text = TAG_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Google News appends " - Publisher" to every headline; drop it when we can
    # match it to the entry's declared source, otherwise drop the last segment.
    if source_title:
        suffix = f" - {source_title.strip()}"
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def entry_timestamp(entry) -> float:
    """Best-effort published time as a UNIX timestamp; 0.0 if unknown."""
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            try:
                return time.mktime(value)
            except (OverflowError, ValueError):
                pass
    for key in ("published", "updated"):
        value = entry.get(key)
        if value:
            try:
                return parsedate_to_datetime(value).timestamp()
            except (TypeError, ValueError):
                pass
    return 0.0


def fetch_source(source: dict, max_items: int) -> dict | None:
    """Return a rendered source dict, or None if nothing could be fetched."""
    name = source["name"]
    domain = source["domain"]
    items: list[dict] = []
    seen_links: set[str] = set()
    seen_titles: set[str] = set()

    for feed_url in source.get("feeds", []):
        try:
            parsed = feedparser.parse(
                feed_url, request_headers={"User-Agent": USER_AGENT}
            )
        except Exception as exc:  # noqa: BLE001 — never let one feed kill the run
            print(f"  ! {name}: error parsing {feed_url}: {exc}", file=sys.stderr)
            continue

        if parsed.bozo and not parsed.entries:
            print(f"  ! {name}: no entries from {feed_url}", file=sys.stderr)
            continue

        for entry in parsed.entries:
            source_title = (entry.get("source") or {}).get("title")
            title = clean_title(entry.get("title", ""), source_title)
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            title_key = title.lower()
            if link in seen_links or title_key in seen_titles:
                continue
            seen_links.add(link)
            seen_titles.add(title_key)
            items.append(
                {
                    "title": title,
                    "link": link,
                    "ts": entry_timestamp(entry),
                }
            )

    if not items:
        return None

    items.sort(key=lambda i: i["ts"], reverse=True)
    items = items[:max_items]

    latest_ts = max((i["ts"] for i in items), default=0.0)
    return {
        "name": name,
        "domain": domain,
        "favicon": f"https://www.google.com/s2/favicons?domain={domain}&sz=64",
        "latest_ts": latest_ts,
        "items": items,
    }


def main() -> int:
    config = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    max_items = int(config.get("max_items_per_source", 12))

    rendered: list[dict] = []
    for source in config.get("sources", []):
        print(f"Fetching {source['name']} ...")
        result = fetch_source(source, max_items)
        if result:
            print(f"  -> {len(result['items'])} items")
            rendered.append(result)
        else:
            print(f"  -> skipped (no items)")

    # Sources with the freshest news float to the top.
    rendered.sort(key=lambda s: s["latest_ts"], reverse=True)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_count": len(rendered),
        "item_count": sum(len(s["items"]) for s in rendered),
        "sources": rendered,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"\nWrote {OUT_FILE.relative_to(ROOT)}: "
        f"{payload['source_count']} sources, {payload['item_count']} items."
    )
    return 0 if rendered else 1


if __name__ == "__main__":
    raise SystemExit(main())
