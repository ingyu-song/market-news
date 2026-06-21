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
HISTORY_DIR_WEEKLY = DATA / "recap_history_weekly"
DAILY_OUT = DATA / "recap_daily.json"
WEEKLY_OUT = DATA / "recap_weekly.json"
RECAP_INDEX = DATA / "recap_index.json"

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
                                "segments": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "text": {"type": "string"},
                                            "story_ids": {
                                                "type": "array",
                                                "items": {"type": "integer"},
                                            },
                                            "x_ids": {
                                                "type": "array",
                                                "items": {"type": "integer"},
                                            },
                                        },
                                        "required": ["text", "story_ids", "x_ids"],
                                    },
                                },
                            },
                            "required": ["lead", "segments"],
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
                    "x_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["name", "note", "story_ids", "x_ids"],
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

You have TWO indexed inputs:

1) BUCKETED NEWS STORIES — cite via story_ids. Format:
   [3] (CNBC Markets) Nvidia rallies on guidance beat

{data}

2) X CHATTER — cite via x_ids. Each entry is a tweet's author plus the theme
that tweet was discussing on X today. Format:
   [12] (@VinceVentures) AI infra capex — "$400B spend cycle through 2027"

{x_data}

Write a JSON object with this exact shape:
{{
  "headline": "<one-line headline, <= 90 chars>",
  "summary": "<2-3 sentence overview of the day, analyst-curt, numbers first>",
  "sections": [
    {{"label": "<topic label, must match one of the input buckets>",
      "bullets": [
        {{"lead": "<short bold leader sentence, ending with a period>",
          "segments": [
            {{"text": "<one full sentence expanding on the lead, ends with period>",
              "story_ids": [<int>, ...],
              "x_ids": [<int>, ...]}}
          ]}}
      ]}}
  ],
  "watchlist": [
    {{"name": "<entity name, e.g. Nvidia / TSMC / Fed>",
      "note": "<one-line read, what to watch tomorrow>",
      "story_ids": [<int>, ...],
      "x_ids": [<int>, ...]}}
  ]
}}

Rules:
- 4-6 sections. Order them by importance for THIS DAY, but bias toward the
  channels' topic share when day-priority is unclear.
- Within a section, 2-4 bullets, freshest / highest-signal first.
- "lead" is a complete short sentence (~6-12 words). Rendered in bold.
- Each bullet has 1-3 "segments". Each segment is ONE FULL SENTENCE that
  expands the bullet. The frontend renders the segment's chips inline at the
  end of that sentence — so put news sources (story_ids) and X mentions
  (x_ids) on the sentence they actually support.
- A segment can mix story_ids and x_ids (news + X both back it up), be
  news-only (story_ids), or be X-only (x_ids — for chatter / takes that are
  not in mainstream news).
- Include EVERY supporting id — do not collapse to one. Frontend renders each
  chip distinctly. Never invent an id.
- Numbers, tickers, jargon stay intact. No "according to reports", no
  "experts say" — just substance.
- "watchlist" = 3-5 single names (companies, tickers, or macro entities like
  "Fed" / "10Y yield") relevant tomorrow. One-line note each, citing
  story_ids and x_ids that support the call.
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
            # No-LLM mode can't actually rewrite into segments, so it hands
            # the title to `lead` and emits one empty-text segment carrying
            # the source chip.
            title = it["title"]
            lead = title if title.endswith((".", "!", "?")) else title + "."
            bullets.append({
                "lead": lead,
                "segments": [{
                    "text": "",
                    "story_ids": [sid] if sid is not None else [],
                    "x_ids": [],
                }],
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
            "x_ids": [],
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


def attach_weekly_sources(themes: list[dict], history: list[dict],
                          max_per_theme: int = 8) -> list[dict]:
    """For each weekly theme, gather a deduped sources list collected from
    daily-recap bullets whose section label matches the theme. The weekly
    LLM doesn't see the underlying article links — those live on the daily
    snapshots — so we attach them here rather than asking the model to."""
    by_label: dict[str, list[dict]] = {}
    for day in history:
        for sec in day.get("sections", []) or []:
            label = (sec.get("label") or "").strip()
            if not label:
                continue
            collected = []
            for b in sec.get("bullets", []) or []:
                for s in b.get("sources", []) or []:
                    collected.append(s)
            if collected:
                by_label.setdefault(label, []).extend(collected)

    for theme in themes:
        label = (theme.get("label") or "").strip()
        ll = label.lower()
        candidates = list(by_label.get(label, []))
        if not candidates and ll:
            # Fuzzy: if exact label doesn't match (e.g. weekly model rephrased
            # the section), pull from labels that share a substring.
            for k, v in by_label.items():
                kl = k.lower()
                if ll in kl or kl in ll:
                    candidates.extend(v)

        deduped, seen_labels, seen_links = [], set(), set()
        for s in candidates:
            cl = source_chip_label(s.get("source", ""))
            lk = s.get("link", "")
            if cl and cl in seen_labels:
                continue
            if lk and lk in seen_links:
                continue
            if cl:
                seen_labels.add(cl)
            if lk:
                seen_links.add(lk)
            deduped.append({
                "title": s.get("title", ""),
                "link": s.get("link", ""),
                "source": s.get("source", ""),
                "favicon": s.get("favicon", ""),
            })
            if len(deduped) >= max_per_theme:
                break
        theme["sources"] = deduped
    return themes


def _fetch_sources(ids, id_lookup):
    """Resolve story_ids → source dicts, deduped per call by chip label and
    by link (so "CNBC Markets" + "CNBC Finance" collapse to one `cnbc`)."""
    out, seen_labels, seen_links = [], set(), set()
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


def _fetch_x_mentions(ids, x_lookup):
    """Resolve x_ids → {handle,url} chips, deduped by handle within a call."""
    out, seen = [], set()
    for i in (ids or []):
        if not (isinstance(i, int) and 0 <= i < len(x_lookup)):
            continue
        m = x_lookup[i]
        h = (m.get("handle", "") or "").lstrip("@").lower()
        if not h or h in seen:
            continue
        seen.add(h)
        out.append({"handle": m["handle"], "url": m["url"]})
    return out


def hydrate_refs(recap: dict, story_lookup: list[dict],
                 x_lookup: list[dict]) -> dict:
    """Resolve story_ids / x_ids on segments and watchlist into the
    embedded sources / x_mentions arrays the frontend expects. Tolerates
    old-shape bullets (lead + body + story_ids on the bullet itself)
    for backwards compatibility."""
    for sec in recap.get("sections", []) or []:
        for b in sec.get("bullets", []) or []:
            segments = b.get("segments")
            if isinstance(segments, list) and segments:
                for seg in segments:
                    seg["sources"] = _fetch_sources(seg.pop("story_ids", []),
                                                   story_lookup)
                    seg["x_mentions"] = _fetch_x_mentions(seg.pop("x_ids", []),
                                                         x_lookup)
            else:
                # legacy: chips at the bullet level
                b["sources"] = _fetch_sources(b.pop("story_ids", []),
                                              story_lookup)
                b["x_mentions"] = _fetch_x_mentions(b.pop("x_ids", []),
                                                   x_lookup)
    for w in recap.get("watchlist", []) or []:
        w["sources"] = _fetch_sources(w.pop("story_ids", []), story_lookup)
        w["x_mentions"] = _fetch_x_mentions(w.pop("x_ids", []), x_lookup)
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


def write_weekly_history_copy(weekly: dict) -> Path:
    HISTORY_DIR_WEEKLY.mkdir(parents=True, exist_ok=True)
    stamp = weekly.get("for_week_ending") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = HISTORY_DIR_WEEKLY / f"{stamp}.json"
    out.write_text(json.dumps(weekly, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    # Keep ~6 months of weekly snapshots.
    files = sorted(HISTORY_DIR_WEEKLY.glob("*.json"))
    for old in files[:-26]:
        try:
            old.unlink()
        except OSError:
            pass
    return out


def write_recap_index() -> None:
    """Compact index of available history dates so the frontend can build
    the History calendar / list without having to probe every file."""
    daily = sorted(
        p.stem for p in HISTORY_DIR.glob("*.json")
    ) if HISTORY_DIR.exists() else []
    weekly = sorted(
        p.stem for p in HISTORY_DIR_WEEKLY.glob("*.json")
    ) if HISTORY_DIR_WEEKLY.exists() else []
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "daily": list(reversed(daily)),       # newest first
        "weekly": list(reversed(weekly)),     # newest first
    }
    DATA.mkdir(parents=True, exist_ok=True)
    RECAP_INDEX.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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
def flatten_x_mentions(x_themes: list[dict], max_items: int = 40) -> list[dict]:
    """Flatten X themes into a flat indexed list of unique (handle,url)
    mentions for the daily prompt. Each entry keeps the parent theme's
    topic + short summary so the LLM has context for what the tweet is
    about, even though it never sees the raw tweet text."""
    flat: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for t in x_themes or []:
        topic = (t.get("topic") or "").strip()
        summary = (t.get("summary") or "").strip()
        for m in t.get("mentions") or []:
            handle = (m.get("handle") or "").lstrip("@").strip()
            url = m.get("url") or ""
            if not handle:
                continue
            key = (handle.lower(), url)
            if key in seen:
                continue
            seen.add(key)
            flat.append({
                "handle": "@" + handle,
                "url": url or f"https://x.com/{handle}",
                "topic": topic,
                "summary": summary[:180],
            })
            if len(flat) >= max_items:
                return flat
    return flat


def extract_x_themes(x_summary, max_themes: int = 8) -> list[dict]:
    """Pass-through X themes for the frontend. Each theme keeps its topic,
    summary, and the {handle,url} mention list so chips can link to the
    actual tweet."""
    if not x_summary:
        return []
    out = []
    for t in (x_summary.get("themes") or [])[:max_themes]:
        if not isinstance(t, dict):
            continue
        mentions = []
        for m in t.get("mentions") or []:
            if isinstance(m, dict):
                handle = str(m.get("handle", "")).lstrip("@").strip()
                url = m.get("url") or (f"https://x.com/{handle}" if handle else "")
                if handle:
                    mentions.append({"handle": "@" + handle, "url": url})
        out.append({
            "topic": t.get("topic", ""),
            "category": t.get("category", ""),
            "subcategory": t.get("subcategory", ""),
            "summary": t.get("summary", ""),
            "mentions": mentions,
        })
    return out


def build_daily(profile: dict) -> dict:
    news = load_json(NEWS_FILE, default={}) or {}
    items = flatten_news_items(news)
    if not items:
        raise SystemExit("No news items found — run scraper.py first.")
    x_summary = load_json(XSUM_FILE)
    indices_snapshot = load_json(INDICES_FILE)

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

    x_themes_pass = extract_x_themes(x_summary)
    x_flat = flatten_x_mentions(x_themes_pass)
    if x_flat:
        x_data_block = "\n".join(
            f"[{i}] ({m['handle']}) {m['topic']} — \"{m['summary']}\""
            for i, m in enumerate(x_flat)
        )
    else:
        x_data_block = "(none)"

    prompt = DAILY_PROMPT.format(
        style=style_block(profile), data=data_block, x_data=x_data_block
    )

    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY")):
        log("No LLM key set — writing heuristic daily recap.")
        recap = heuristic_daily(profile, ordered, x_summary, flat_lookup)
    else:
        log(f"Calling LLM for daily recap on {len(flat)} stories, "
            f"{len(x_flat)} x_mentions ...")
        recap = call_llm(prompt, DAILY_SCHEMA)

    recap = hydrate_refs(recap, flat_lookup, x_flat)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    x_themes = x_themes_pass
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "daily",
        "for_date": today,
        "headline": recap.get("headline", ""),
        "summary": recap.get("summary", ""),
        "sections": recap.get("sections", []),
        "watchlist": recap.get("watchlist", []),
        "x_themes": x_themes,
        "indices": (indices_snapshot or {}).get("indices") or [],
        "story_count": len(flat),
        "bucket_count": sum(1 for _, a in ordered if a),
    }
    DAILY_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    write_history_copy(payload)
    write_recap_index()
    log(f"Wrote {DAILY_OUT.relative_to(ROOT)}: "
        f"{len(payload['sections'])} sections, {len(payload['watchlist'])} watchlist, "
        f"{len(x_themes)} x_themes, {len(payload['indices'])} indices.")
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

    # Source chips: post-collected from the underlying daily bullets, by label.
    attach_weekly_sources(recap.get("themes") or [], history)

    # Aggregate X themes across the week (most recent day wins on dupes).
    seen_topics: set[str] = set()
    weekly_x: list[dict] = []
    for day in history:
        for t in day.get("x_themes") or []:
            key = (t.get("topic", "") or "").lower().strip()
            if not key or key in seen_topics:
                continue
            seen_topics.add(key)
            weekly_x.append(t)
        if len(weekly_x) >= 10:
            break

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
        "x_themes": weekly_x,
    }
    WEEKLY_OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    write_weekly_history_copy(payload)
    write_recap_index()
    log(f"Wrote {WEEKLY_OUT.relative_to(ROOT)}: "
        f"{len(payload['themes'])} themes, {payload['days_covered']} day(s) of history, "
        f"{len(payload['x_themes'])} x_themes.")
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
