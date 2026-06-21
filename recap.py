#!/usr/bin/env python3
"""Generate the daily and weekly market recap shown in the site's Recap tab.

Reads (all already produced by the rest of the pipeline):
    data/news.json              — current headlines, grouped by source
    data/x_summary.json         — today's X-themes (optional)
    data/indices.json           — index closes (optional)
    data/editorial_profile.json — what the Telegram channels actually care about

Writes one of:
    data/recap_daily.json       — when --mode daily
    data/recap_weekly.json      — when --mode weekly

The daily run also drops a copy under `data/recap_history/YYYY-MM-DD.json` so
the weekly run can synthesize a week from the last seven daily files. Without
history the weekly mode still produces a usable recap (single day rolled up).

LLM: Gemini first, Groq fallback when GROQ_API_KEY is set. When NO key is
configured, a deterministic heuristic recap is written instead — that keeps
the page useful even before the CI secrets are wired up.

Usage:
    python recap.py --mode daily
    python recap.py --mode weekly
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from build_profile import (  # reuse the topic taxonomy so the recap stays
    TOPIC_BUCKETS,            # aligned with how the profile categorizes posts
    bucket_post,
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
NEWS_FILE = DATA / "news.json"
XSUM_FILE = DATA / "x_summary.json"
INDICES_FILE = DATA / "indices.json"
PROFILE_FILE = DATA / "editorial_profile.json"
HISTORY_DIR = DATA / "recap_history"
DAILY_OUT = DATA / "recap_daily.json"
WEEKLY_OUT = DATA / "recap_weekly.json"

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_ITEMS_PER_BUCKET = int(os.environ.get("RECAP_MAX_PER_BUCKET", "8"))


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


# ----------------------------------------------------------------- loading
def load_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        log(f"WARN: could not parse {path}: {exc}")
        return default


def flatten_news_items(news: dict) -> list[dict]:
    """One flat list of {title, link, ts, source, favicon}."""
    out: list[dict] = []
    for src in news.get("sources", []):
        for item in src.get("items", []):
            out.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "ts": item.get("ts", 0),
                "source": src.get("name", ""),
                "favicon": src.get("favicon", ""),
            })
    return out


# --------------------------------------------------------------- bucketing
def bucket_items(items: list[dict]) -> dict[str, list[dict]]:
    """Group news items by topic-bucket label (an item may land in many)."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        labels = bucket_post(item["title"])
        for label in labels:
            buckets[label].append(item)
    # Sort each bucket by freshness and trim. Order preserved for downstream.
    for label, arr in buckets.items():
        arr.sort(key=lambda x: x.get("ts", 0), reverse=True)
        buckets[label] = arr[:MAX_ITEMS_PER_BUCKET]
    return buckets


def order_buckets_by_profile(profile: dict, buckets: dict) -> list[tuple[str, list]]:
    """Return [(label, items)] in editorial-profile share order. Labels not
    present in the profile fall to the bottom but are still included."""
    share_rank = {t["label"]: i for i, t in enumerate(profile.get("topic_share", []))}
    return sorted(
        buckets.items(),
        key=lambda kv: (share_rank.get(kv[0], 999), -len(kv[1])),
    )


# ----------------------------------------------------------------- prompts
def style_block(profile: dict) -> str:
    style = profile.get("style", {}) or {}
    fp = style.get("fingerprint", "")
    top = ", ".join(
        f'{t["label"]} ({t["share"]*100:.0f}%)'
        for t in profile.get("topic_share", [])[:6]
    )
    domains = ", ".join(d["domain"] for d in profile.get("top_domains", [])[:8])

    # Voice examples: real posts from the source Telegram channels, in
    # Korean. The LLM reads them as imitation reference and writes English
    # output that copies their structure, density, and citation cadence.
    examples = profile.get("voice_examples", []) or []
    if examples:
        rendered = "\n\n".join(
            f"--- [{ex.get('topic','')}] {ex.get('channel','')} · {ex.get('date','')[:10]}\n"
            f"{ex.get('text','')}"
            for ex in examples
        )
        voice_block = (
            "VOICE REFERENCE — real posts from the Korean source channels. "
            "Imitate their structure (short bolded leader, one expansion "
            "sentence, dense numbers, jargon preserved), their density, and "
            "how they cite outside sources. WRITE YOUR OWN OUTPUT IN ENGLISH. "
            "Do NOT translate these examples verbatim; learn the pattern.\n\n"
            f"{rendered}\n"
        )
    else:
        voice_block = ""

    return (
        f"EDITORIAL STYLE (imitate this):\n{fp}\n"
        f"Topic share in the source channels: {top}\n"
        f"Trusted source domains: {domains}\n\n"
        f"{voice_block}"
    )


DAILY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "bullets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "lead": {"type": "string"},
                                "body": {"type": "string"},
                                "story_ids": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                },
                            },
                            "required": ["lead", "body", "story_ids"],
                        },
                    },
                },
                "required": ["label", "bullets"],
            },
        },
        "watchlist": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "note": {"type": "string"},
                    "story_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["name", "note", "story_ids"],
            },
        },
    },
    "required": ["headline", "summary", "sections", "watchlist"],
}


WEEKLY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "narrative": {"type": "string"},
                    "movers": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["label", "narrative", "movers"],
            },
        },
        "watchlist": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["name", "note"],
            },
        },
    },
    "required": ["headline", "summary", "themes", "watchlist"],
}


DAILY_PROMPT = """You are writing the daily English market recap for a finance
website. The voice must match the EDITORIAL STYLE below — copy the channels'
priorities and writing pattern, not generic news priorities.

{style}

INPUT: today's headlines, bucketed into the same topic taxonomy the channels
use. Each story has an integer id in square brackets, then the title and source:
    [3] (CNBC Markets) Nvidia rallies on guidance beat

Bucketed stories:
{data}

X (Twitter) themes today:
{x_block}

Write a JSON object with this exact shape:
{{
  "headline": "<one-line headline, <= 90 chars>",
  "summary": "<2-3 sentence overview of the day, analyst-curt, numbers first>",
  "sections": [
    {{"label": "<topic label, must match one of the input buckets>",
      "bullets": [
        {{"lead": "<short bold leader phrase, declarative, ending with a period. e.g. 'Middle East tensions are intensifying.'>",
          "body": "<1-2 sentences expanding on the leader, preserve tickers/numbers/jargon, no filler>",
          "story_ids": [<int>, <int>, <int>]}}
      ]}}
  ],
  "watchlist": [
    {{"name": "<entity name, e.g. Nvidia / TSMC / Fed>",
      "note": "<one-line read, what to watch tomorrow>",
      "story_ids": [<int>]}}
  ]
}}

Rules:
- 4-6 sections. Order them by importance for THIS DAY, but bias toward the
  channels' topic share when day-priority is unclear.
- Within a section, 2-4 bullets, freshest / highest-signal first.
- "lead" must be a complete short sentence (~6-12 words), ending with a period.
  It will be rendered in bold. Example: "Middle East tensions are intensifying."
- "body" expands on the lead in 1-2 tight sentences. Numbers and tickers stay
  intact. No "according to reports", no "experts say" — just the substance.
- "story_ids" must reference ids that appear in the bucketed stories above.
  Include EVERY story that supports the bullet (do not collapse to one — the
  frontend renders each as its own source chip). Never invent an id.
- "watchlist" = 3-5 single names (companies, tickers, or macro entities like
  "Fed" / "10Y yield") relevant tomorrow. One-line note each.
- No filler, no editorial throat-clearing, no "in summary".
"""


WEEKLY_PROMPT = """You are writing the weekly English market recap. You see a
compressed view of the last seven days assembled from the daily recaps. Imitate
the EDITORIAL STYLE below.

{style}

Last seven daily recaps (most recent first):
{data}

Write a JSON object with this exact shape:
{{
  "headline": "<one-line headline for the week, <= 100 chars>",
  "summary": "<3-5 sentence weekly narrative — what the week was about>",
  "themes": [
    {{"label": "<topic label, e.g. 'Fed / Rates / Macro'>",
      "narrative": "<2-3 sentences on what moved this week within the theme>",
      "movers": ["<entity 1>", "<entity 2>", "..."]}}
  ],
  "watchlist": [
    {{"name": "<entity>", "note": "<what to watch next week>"}}
  ]
}}

Rules:
- 4-6 themes ordered by how much they drove the week.
- Identify week-over-week direction (e.g. "memory tone improved", "risk-off
  return"). Use the daily recaps' own language as your evidence.
- "movers" = up to 5 entities for each theme.
- "watchlist" = 4-6 names. One-line notes.
- No throat-clearing.
"""


# --------------------------------------------------------------- LLM calls
def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def gemini_complete(prompt: str, schema: dict) -> dict:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    client = genai.Client(api_key=api_key)
    configs = [
        types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.3,
        ),
        types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.3,
        ),
    ]
    last_err = None
    for i, cfg in enumerate(configs, 1):
        try:
            resp = client.models.generate_content(
                model=GEMINI_MODEL, contents=prompt, config=cfg
            )
            return json.loads(_strip_fences(resp.text))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log(f"  Gemini config {i}/{len(configs)} failed: "
                f"{type(exc).__name__}: {exc}")
    raise last_err  # type: ignore[misc]


def groq_complete(prompt: str) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")
    from groq import Groq

    client = Groq(api_key=api_key)
    out = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    return json.loads(_strip_fences(out.choices[0].message.content))


def call_llm(prompt: str, schema: dict) -> dict:
    try:
        return gemini_complete(prompt, schema)
    except Exception as exc:  # noqa: BLE001
        log(f"Gemini failed: {exc}")
        if os.environ.get("GROQ_API_KEY"):
            log("Falling back to Groq ...")
            return groq_complete(prompt)
        raise


# ------------------------------------------------------------ heuristic fallback
def heuristic_daily(profile: dict, ordered: list,
                    x_summary: dict | None, flat_lookup: list[dict]) -> dict:
    """A no-LLM recap built from rules. Always produces a usable artifact."""
    # Map title -> id in the flat lookup so we attach the RIGHT source per bullet.
    title_to_id: dict[str, int] = {}
    for i, it in enumerate(flat_lookup):
        title_to_id.setdefault(it["title"], i)

    sections = []
    for label, items in ordered[:6]:
        if not items:
            continue
        bullets = []
        for it in items[:3]:
            sid = title_to_id.get(it["title"])
            # No-LLM mode can't actually rewrite into lead+body, so we hand
            # the title to `lead` and leave `body` empty. The frontend handles
            # the empty body gracefully.
            title = it["title"]
            lead = title if title.endswith((".", "!", "?")) else title + "."
            bullets.append({
                "lead": lead,
                "body": "",
                "story_ids": [sid] if sid is not None else [],
            })
        sections.append({"label": label, "bullets": bullets})

    # Watchlist: top entities seen in *today's* news titles, ranked by mentions.
    name_to_aliases: dict[str, set[str]] = defaultdict(set)
    for e in profile.get("top_entities", []):
        name_to_aliases[e["name"]].add(e["name"].lower())
    counts: Counter = Counter()
    examples: dict[str, tuple[str, int | None]] = {}
    for it in flat_lookup:
        low = it["title"].lower()
        for name, aliases in name_to_aliases.items():
            for a in aliases:
                if a and re.search(r"(?<![a-z])" + re.escape(a) + r"(?![a-z])", low):
                    counts[name] += 1
                    examples.setdefault(name, (it["title"], title_to_id.get(it["title"])))
                    break
    watchlist = []
    for n, _ in counts.most_common(5):
        title, sid = examples.get(n, ("", None))
        watchlist.append({
            "name": n,
            "note": title,
            "story_ids": [sid] if sid is not None else [],
        })
    headline = (
        f"{sections[0]['label']} leads today's tape" if sections
        else "Quiet tape"
    )
    summary = (
        f"Top topic by coverage: {sections[0]['label']}. "
        f"{len(flat_lookup)} headlines bucketed into "
        f"{len(sections)} editorial themes."
    ) if sections else "No bucketed headlines available."
    if x_summary and x_summary.get("themes"):
        summary += f" X chatter highlights {x_summary['themes'][0].get('topic','')}."
    return {
        "headline": headline,
        "summary": summary,
        "sections": sections,
        "watchlist": watchlist,
    }


def heuristic_weekly(history: list[dict]) -> dict:
    """Heuristic weekly from cached daily recaps."""
    if not history:
        return {
            "headline": "Recap history is empty",
            "summary": "Daily recaps have not run yet this week.",
            "themes": [],
            "watchlist": [],
        }
    label_counts: Counter = Counter()
    movers: dict[str, Counter] = defaultdict(Counter)
    for day in history:
        for sec in day.get("sections", []) or []:
            label = sec.get("label", "")
            label_counts[label] += len(sec.get("bullets", []) or [])
            for b in sec.get("bullets", []) or []:
                for w in re.findall(r"\b[A-Z][A-Za-z]{1,12}\b", b.get("text", "")):
                    movers[label][w] += 1
    themes = []
    for label, _ in label_counts.most_common(5):
        top_movers = [w for w, _ in movers[label].most_common(5)]
        themes.append({
            "label": label,
            "narrative": (
                f"{label} accounted for "
                f"{label_counts[label]} bullets across the week's daily recaps."
            ),
            "movers": top_movers,
        })
    return {
        "headline": "Weekly tape, by editorial weight",
        "summary": (
            f"Compiled from {len(history)} daily recap(s). "
            "Themes ordered by coverage volume across the week."
        ),
        "themes": themes,
        "watchlist": [
            {"name": t["movers"][0] if t["movers"] else t["label"],
             "note": f"Most-mentioned name within {t['label']} this week."}
            for t in themes[:5] if t["movers"]
        ],
    }


# ----------------------------------------------------------------- writers
_CHIP_VIA_RE = re.compile(r"\s*\(via [^)]+\)\s*", re.IGNORECASE)
_CHIP_TRAIL_RE = re.compile(r"\s*(markets|finance|business|news)\s*$", re.IGNORECASE)
_CHIP_TAIL_SEP_RE = re.compile(r"\s*[·.,—]\s.+$")


def source_chip_label(name: str) -> str:
    """Same publisher-name normalization the frontend uses. Mirrors
    sourceChipLabel() in app.js so we can dedupe at write time."""
    if not name:
        return ""
    s = name.lower()
    s = _CHIP_VIA_RE.sub("", s)
    s = _CHIP_TRAIL_RE.sub("", s)
    s = _CHIP_TAIL_SEP_RE.sub("", s)
    return s.strip()


def hydrate_story_refs(recap: dict, id_lookup: list[dict]) -> dict:
    """Replace story_ids -> embedded story objects so the frontend doesn't
    need to know about the index. Within each bullet we dedupe by display
    label (so "CNBC Markets" + "CNBC Finance" collapse to a single `cnbc`
    chip) and by link (so the same article cited twice never repeats)."""
    def fetch(ids):
        out = []
        seen_labels: set[str] = set()
        seen_links: set[str] = set()
        for i in (ids or []):
            if not (isinstance(i, int) and 0 <= i < len(id_lookup)):
                continue
            s = id_lookup[i]
            label = source_chip_label(s.get("source", ""))
            link = s.get("link", "")
            if label and label in seen_labels:
                continue
            if link and link in seen_links:
                continue
            if label:
                seen_labels.add(label)
            if link:
                seen_links.add(link)
            out.append({
                "title": s["title"],
                "link": s["link"],
                "source": s["source"],
                "favicon": s["favicon"],
            })
        return out

    for sec in recap.get("sections", []) or []:
        for b in sec.get("bullets", []) or []:
            b["sources"] = fetch(b.pop("story_ids", []))
    for w in recap.get("watchlist", []) or []:
        w["sources"] = fetch(w.pop("story_ids", []))
    return recap


def write_history_copy(daily: dict) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    stamp = daily["for_date"]
    out = HISTORY_DIR / f"{stamp}.json"
    out.write_text(json.dumps(daily, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    # Keep history bounded so the repo doesn't bloat — last 60 days.
    files = sorted(HISTORY_DIR.glob("*.json"))
    for old in files[:-60]:
        try:
            old.unlink()
        except OSError:
            pass
    return out


def load_history(days: int = 7) -> list[dict]:
    if not HISTORY_DIR.exists():
        return []
    files = sorted(HISTORY_DIR.glob("*.json"), reverse=True)[:days]
    out = []
    for f in files:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return out


# ---------------------------------------------------------------- modes
def build_daily(profile: dict) -> dict:
    news = load_json(NEWS_FILE, default={}) or {}
    items = flatten_news_items(news)
    if not items:
        raise SystemExit("No news items found — run scraper.py first.")
    x_summary = load_json(XSUM_FILE)

    buckets = bucket_items(items)
    ordered = order_buckets_by_profile(profile, buckets)

    # Build the flat list of stories sent to the LLM (their indexes ARE the ids).
    flat: list[dict] = []
    flat_lookup: list[dict] = []  # parallel: full record incl source/favicon
    sections_for_prompt: list[str] = []
    for label, arr in ordered:
        if not arr:
            continue
        sections_for_prompt.append(f"## {label}")
        for it in arr:
            idx = len(flat)
            flat.append(it)
            flat_lookup.append(it)
            sections_for_prompt.append(
                f"[{idx}] ({it['source']}) {it['title']}"
            )
        sections_for_prompt.append("")
    data_block = "\n".join(sections_for_prompt)

    x_block = ""
    if x_summary and x_summary.get("themes"):
        x_block = "\n".join(
            f"- {t.get('topic','')}: {t.get('summary','')}"
            for t in x_summary["themes"][:8]
        ) or "(none)"
    else:
        x_block = "(none)"

    prompt = DAILY_PROMPT.format(
        style=style_block(profile), data=data_block, x_block=x_block
    )

    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")):
        log("No LLM key set — writing heuristic daily recap.")
        recap = heuristic_daily(profile, ordered, x_summary, flat_lookup)
    else:
        log(f"Calling LLM for daily recap on {len(flat)} stories ...")
        recap = call_llm(prompt, DAILY_SCHEMA)

    recap = hydrate_story_refs(recap, flat_lookup)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "daily",
        "for_date": today,
        "headline": recap.get("headline", ""),
        "summary": recap.get("summary", ""),
        "sections": recap.get("sections", []),
        "watchlist": recap.get("watchlist", []),
        "story_count": len(flat),
        "bucket_count": sum(1 for _, a in ordered if a),
    }
    DAILY_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    write_history_copy(payload)
    log(f"Wrote {DAILY_OUT.relative_to(ROOT)}: "
        f"{len(payload['sections'])} sections, {len(payload['watchlist'])} watchlist.")
    return payload


def build_weekly(profile: dict) -> dict:
    history = load_history(7)
    # Compressed view: just headlines + section labels + bullet texts per day.
    blocks = []
    for day in history:
        blocks.append(f"=== {day.get('for_date','?')} — {day.get('headline','')}")
        blocks.append(day.get("summary", ""))
        for sec in day.get("sections", []) or []:
            blocks.append(f"  {sec.get('label','')}:")
            for b in sec.get("bullets", []) or []:
                blocks.append(f"    - {b.get('text','')}")
        blocks.append("")
    data_block = "\n".join(blocks) or "(no daily recaps in history)"

    prompt = WEEKLY_PROMPT.format(style=style_block(profile), data=data_block)

    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")):
        log("No LLM key set — writing heuristic weekly recap.")
        recap = heuristic_weekly(history)
    elif not history:
        log("No history yet — heuristic weekly with empty body.")
        recap = heuristic_weekly([])
    else:
        log(f"Calling LLM for weekly recap on {len(history)} day(s) ...")
        recap = call_llm(prompt, WEEKLY_SCHEMA)

    today = datetime.now(timezone.utc)
    week_end = today.strftime("%Y-%m-%d")
    week_start = (today - timedelta(days=6)).strftime("%Y-%m-%d")
    payload = {
        "generated_at": today.isoformat(timespec="seconds"),
        "mode": "weekly",
        "for_week_start": week_start,
        "for_week_ending": week_end,
        "days_covered": len(history),
        "headline": recap.get("headline", ""),
        "summary": recap.get("summary", ""),
        "themes": recap.get("themes", []),
        "watchlist": recap.get("watchlist", []),
    }
    WEEKLY_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    log(f"Wrote {WEEKLY_OUT.relative_to(ROOT)}: "
        f"{len(payload['themes'])} themes, {payload['days_covered']} day(s) of history.")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["daily", "weekly", "both"],
                        default="daily")
    args = parser.parse_args()

    profile = load_json(PROFILE_FILE)
    if not profile:
        raise SystemExit(
            "data/editorial_profile.json missing — run build_profile.py first."
        )

    if args.mode in ("daily", "both"):
        build_daily(profile)
    if args.mode in ("weekly", "both"):
        build_weekly(profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
