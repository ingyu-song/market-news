#!/usr/bin/env python3
"""Fetch the daily X (Twitter) scrape from Apify, summarize it with Gemini, and
write data/x_summary.json for the website's top "What X is talking about" panel.

All credentials come from environment variables — never hard-code them:
    APIFY_API_TOKEN   (required)
    GEMINI_API_KEY    (required)
    GROQ_API_KEY      (optional — used only as a fallback)

Optional tuning via env:
    APIFY_TASK_ID     default "igsong522/daily-twitter-scrape"
    X_USE_LAST_RUN    "1" to reuse the last SUCCEEDED Apify run instead of
                      triggering a fresh one (cheaper; use if the task is
                      already scheduled on Apify's side)
    X_MAX_TWEETS      default 200   (hard cap on tweets sent to Gemini)
    X_MAX_PER_AUTHOR  default 5     (limits spammy accounts)

On any failure it logs and exits non-zero WITHOUT touching an existing
x_summary.json, so the site keeps showing the last good summary.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_FILE = ROOT / "data" / "x_summary.json"

TASK_ID = os.environ.get("APIFY_TASK_ID", "igsong522/daily-twitter-scrape")
USE_LAST_RUN = os.environ.get("X_USE_LAST_RUN", "0") == "1"
MAX_TWEETS = int(os.environ.get("X_MAX_TWEETS", "200"))
MAX_PER_AUTHOR = int(os.environ.get("X_MAX_PER_AUTHOR", "5"))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# JSON shape we force Gemini to return.
RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "top_3": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "mentions": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                },
                "required": ["topic", "mentions", "summary"],
            },
        },
        "others": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "mentions": {"type": "array", "items": {"type": "string"}},
                    "summary": {"type": "string"},
                },
                "required": ["topic", "mentions", "summary"],
            },
        },
    },
    "required": ["top_3", "others"],
}

PROMPT_TEMPLATE = """You are a senior macro/markets analyst at a hedge fund. \
Below is a batch of finance-focused tweets from X, each tagged with its author \
handle. Cluster them into the distinct market/macro NARRATIVES being discussed \
today (e.g. "AI infrastructure / memory pricing", "Fed & rates", "China tech").

Return ONLY a JSON object (no markdown, no code fences) with this exact shape:
{{
  "top_3": [
    {{"topic": "Brief Theme Name", "mentions": ["@Handle1", "@Handle2"], "summary": "1-2 sentence explanation of the narrative."}}
  ],
  "others": [
    {{"topic": "Brief Theme Name", "mentions": ["@Handle3"], "summary": "1-2 sentence explanation."}}
  ]
}}

Rules:
- "top_3": the THREE most significant / most-discussed market themes. Exactly 3 if possible.
- "others": the remaining noteworthy themes (up to ~7). Omit pure noise/spam/non-finance chatter.
- "mentions": the @handles (with the @) that discussed that theme. Keep it to the relevant ones.
- "summary": 1-2 tight sentences, preserve key tickers/numbers/jargon, no filler.
- Every handle in "mentions" must start with "@".

Raw tweets:
{data}
"""


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _field(obj, key, default=None):
    """Read a field from an Apify run whether it's a dict or an object."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# --------------------------------------------------------------------------- #
# Apify
# --------------------------------------------------------------------------- #
def fetch_tweets() -> list[dict]:
    """Return a list of {text, author, created_at} from the Apify dataset."""
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        raise SystemExit("APIFY_API_TOKEN is not set.")

    from apify_client import ApifyClient

    client = ApifyClient(token)
    task = client.task(TASK_ID)

    if USE_LAST_RUN:
        log(f"Reading last SUCCEEDED run of task {TASK_ID} ...")
        run = task.last_run(status="SUCCEEDED").get()
        if not run:
            raise SystemExit("No successful previous run found on Apify.")
    else:
        log(f"Triggering Apify task {TASK_ID} and waiting for it to finish ...")
        run = task.call()  # starts the run and blocks until it finishes
        status = _field(run, "status")
        if not run or status != "SUCCEEDED":
            raise SystemExit(f"Apify run did not succeed: status={status!r}")

    dataset_id = _field(run, "defaultDatasetId") or _field(run, "default_dataset_id")
    if not dataset_id:
        raise SystemExit(f"Apify run has no dataset id; run={run!r}")
    log(f"Reading dataset {dataset_id} ...")

    tweets: list[dict] = []
    for item in client.dataset(dataset_id).iterate_items():
        text = (item.get("text") or item.get("fullText")
                or item.get("full_text") or "").strip()
        author = ""
        a = item.get("author")
        if isinstance(a, dict):
            author = a.get("userName") or a.get("username") or a.get("screen_name") or ""
        author = (author or item.get("userName") or item.get("username")
                  or item.get("handle") or "").lstrip("@").strip()
        if not text or not author:
            continue
        tweets.append({
            "text": text,
            "author": author,
            "created_at": item.get("createdAt") or item.get("created_at") or "",
        })
    log(f"Fetched {len(tweets)} tweets.")
    return tweets


def _ts(value: str) -> float:
    """Best-effort parse of either ISO or Twitter date strings; 0.0 if unknown."""
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        return 0.0


def balance(tweets: list[dict]) -> list[dict]:
    """At most MAX_PER_AUTHOR (newest) per account, then a hard MAX_TWEETS cap."""
    by_author: dict[str, list[dict]] = {}
    for t in tweets:
        by_author.setdefault(t["author"], []).append(t)

    picked: list[dict] = []
    for author, items in by_author.items():
        items.sort(key=lambda x: _ts(x["created_at"]), reverse=True)
        picked.extend(items[:MAX_PER_AUTHOR])

    picked.sort(key=lambda x: _ts(x["created_at"]), reverse=True)
    return picked[:MAX_TWEETS]


# --------------------------------------------------------------------------- #
# Summarization
# --------------------------------------------------------------------------- #
def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def summarize_gemini(prompt: str) -> dict:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    client = genai.Client(api_key=api_key)

    # Try strict structured output first; if this SDK build rejects the dict
    # schema, fall back to plain JSON mode (the prompt already specifies shape).
    configs = [
        types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=RESPONSE_SCHEMA,
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
            log(f"  Gemini config {i}/{len(configs)} failed: {type(exc).__name__}: {exc}")
    raise last_err


def summarize_groq(prompt: str) -> dict:
    """Optional fallback if Gemini is unavailable and GROQ_API_KEY is set."""
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


def summarize(tweets: list[dict]) -> dict:
    data_block = "\n".join(f"- {t['text']} (@{t['author']})" for t in tweets)
    prompt = PROMPT_TEMPLATE.format(data=data_block)

    try:
        return summarize_gemini(prompt)
    except Exception as exc:  # noqa: BLE001
        log(f"Gemini failed: {exc}")
        if os.environ.get("GROQ_API_KEY"):
            log("Falling back to Groq ...")
            return summarize_groq(prompt)
        raise


def normalize(result: dict) -> dict:
    """Defensive: ensure the two arrays exist and items have the right keys."""
    def clean(items):
        out = []
        for it in (items or []):
            if not isinstance(it, dict):
                continue
            topic = str(it.get("topic", "")).strip()
            summary = str(it.get("summary", "")).strip()
            mentions = it.get("mentions") or []
            mentions = [
                ("@" + m.lstrip("@")).strip()
                for m in mentions if isinstance(m, str) and m.strip()
            ]
            if topic and summary:
                out.append({"topic": topic, "mentions": mentions, "summary": summary})
        return out

    return {"top_3": clean(result.get("top_3"))[:3], "others": clean(result.get("others"))}


# --------------------------------------------------------------------------- #
def _key_hint(name: str) -> str:
    v = os.environ.get(name) or ""
    if not v:
        return f"{name}=MISSING"
    return f"{name} set (len={len(v)}, starts '{v[:4]}…')"


def main() -> int:
    # Startup diagnostics — visible in the Actions log, no secrets leaked.
    log("=== x_processor starting ===")
    log("  " + _key_hint("APIFY_API_TOKEN"))
    log("  " + _key_hint("GEMINI_API_KEY"))
    log(f"  task={TASK_ID}  use_last_run={USE_LAST_RUN}  model={GEMINI_MODEL}")
    if not (os.environ.get("GEMINI_API_KEY") or "").startswith("AIza"):
        log("  WARNING: a Gemini API key normally starts with 'AIza'. If yours "
            "doesn't, generate one at https://aistudio.google.com/apikey")

    tweets = fetch_tweets()
    if not tweets:
        raise SystemExit("No tweets fetched — leaving existing summary untouched.")

    selected = balance(tweets)
    accounts = len({t["author"] for t in selected})
    log(f"Summarizing {len(selected)} tweets from {accounts} accounts ...")

    result = normalize(summarize(selected))
    if not result["top_3"]:
        raise SystemExit("Model returned no themes — leaving existing summary untouched.")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tweet_count": len(selected),
        "account_count": accounts,
        "top_3": result["top_3"],
        "others": result["others"],
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Wrote {OUT_FILE.relative_to(ROOT)}: "
        f"{len(payload['top_3'])} top themes, {len(payload['others'])} others.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
