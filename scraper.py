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
COMPANIES_FILE = ROOT / "companies.json"
OUT_FILE = ROOT / "data" / "news.json"

JUNK_SNIPPETS = (
    "view full coverage",
    "full coverage",
    "read more",
    "continue reading",
    "appeared first on",
    "the post ",
)

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


def clean_summary(raw: str) -> str:
    """Turn an RSS description/summary into a short, clean blurb (or '')."""
    text = html.unescape(raw or "")
    text = TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""
    low = text.lower()
    for junk in JUNK_SNIPPETS:
        idx = low.find(junk)
        if idx > 0:
            text = text[:idx].strip(" .-–—")
            low = text.lower()
    if len(text) > 240:
        text = text[:240].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
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


def build_finance_filter(keywords: list[str], patterns: dict) -> re.Pattern | None:
    """One regex that matches a finance keyword OR any watched company name."""
    terms = [re.escape(k) for k in keywords if k]
    # Reuse the company aliases so e.g. "Tesla recalls cars" still counts.
    for pat in patterns.values():
        terms.append(pat.pattern)
    if not terms:
        return None
    return re.compile(r"(?<![\w])(?:" + "|".join(terms) + r")(?![\w])", re.IGNORECASE)


def is_financial(title: str, finance_re: re.Pattern | None) -> bool:
    if finance_re is None:
        return True
    if any(sym in title for sym in "$£€¥%"):
        return True
    return bool(finance_re.search(title))


def fetch_source(source: dict, max_items: int,
                 finance_re: re.Pattern | None = None) -> dict | None:
    """Return a rendered source dict, or None if nothing could be fetched."""
    name = source["name"]
    domain = source["domain"]
    do_filter = bool(source.get("filter", False))
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
            if do_filter and not is_financial(title, finance_re):
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
                    "summary": clean_summary(
                        entry.get("summary") or entry.get("description") or ""
                    ),
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


def load_watchlist() -> tuple[dict, int, int]:
    """Compile the company watchlist into {display_name: regex}."""
    if not COMPANIES_FILE.exists():
        return {}, 4, 3
    cfg = json.loads(COMPANIES_FILE.read_text(encoding="utf-8"))
    patterns: dict[str, re.Pattern] = {}
    for name, aliases in cfg.get("companies", {}).items():
        escaped = [re.escape(a) for a in aliases if a]
        if not escaped:
            continue
        # Whole-word, case-insensitive: matches "Tesla", "Tesla's", "(Tesla)".
        patterns[name] = re.compile(
            r"(?<![\w])(?:" + "|".join(escaped) + r")(?![\w])", re.IGNORECASE
        )
    return patterns, int(cfg.get("min_sources", 4)), int(cfg.get("top_n", 3))


def detect_highlights(sources: list[dict], patterns: dict, min_sources: int,
                      top_n: int) -> list[dict]:
    """Find companies named across >= min_sources sources; return the top_n."""
    hits: dict[str, dict] = {}
    for source in sources:
        for item in source["items"]:
            text = item["title"]
            for name, pattern in patterns.items():
                if pattern.search(text):
                    bucket = hits.setdefault(name, {"sources": {}, "articles": []})
                    bucket["sources"].setdefault(source["name"], source["favicon"])
                    bucket["articles"].append(
                        {
                            "title": item["title"],
                            "link": item["link"],
                            "ts": item["ts"],
                            "summary": item.get("summary", ""),
                            "source": source["name"],
                            "favicon": source["favicon"],
                        }
                    )

    highlights = []
    for name, bucket in hits.items():
        source_count = len(bucket["sources"])
        if source_count < min_sources:
            continue
        articles = sorted(bucket["articles"], key=lambda a: a["ts"], reverse=True)
        # A one-line blurb: the freshest real summary. Skip Google-News-style
        # "summaries" that merely repeat the headline (title contained in text).
        blurb = ""
        for art in articles:
            summary = art["summary"]
            if len(summary) < 50:
                continue
            head = art["title"][:40].lower()
            if head and head in summary.lower():
                continue
            blurb = summary
            break
        highlights.append(
            {
                "name": name,
                "source_count": source_count,
                "mentions": len(articles),
                "sources": [
                    {"name": n, "favicon": f} for n, f in bucket["sources"].items()
                ],
                "blurb": blurb,
                "articles": articles[:5],
            }
        )

    # Rank by how many distinct sources picked it up, then total mentions.
    highlights.sort(key=lambda h: (h["source_count"], h["mentions"]), reverse=True)
    return highlights[:top_n]


def main() -> int:
    config = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    max_items = int(config.get("max_items_per_source", 12))
    patterns, min_sources, top_n = load_watchlist()
    finance_re = build_finance_filter(config.get("finance_keywords", []), patterns)

    rendered: list[dict] = []
    for source in config.get("sources", []):
        print(f"Fetching {source['name']} ...")
        result = fetch_source(source, max_items, finance_re)
        if result:
            print(f"  -> {len(result['items'])} items")
            rendered.append(result)
        else:
            print(f"  -> skipped (no items)")

    # Sources with the freshest news float to the top.
    rendered.sort(key=lambda s: s["latest_ts"], reverse=True)

    highlights = detect_highlights(rendered, patterns, min_sources, top_n)
    print(
        f"\nHighlights: {', '.join(h['name'] for h in highlights) or 'none'} "
        f"(>= {min_sources} sources)"
    )

    # Drop the per-item summary from the source lists — the cards are title-only,
    # so it would just bloat the JSON. Summaries are kept inside `highlights`.
    for source in rendered:
        for item in source["items"]:
            item.pop("summary", None)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_count": len(rendered),
        "item_count": sum(len(s["items"]) for s in rendered),
        "highlights": highlights,
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
