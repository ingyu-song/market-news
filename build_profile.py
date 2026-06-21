#!/usr/bin/env python3
"""Build data/editorial_profile.json from Telegram channel exports.

Reads one or more `result.json` files (Telegram Desktop export format),
combines the messages, and writes a heuristic editorial profile to
`data/editorial_profile.json`. The profile captures what the source channels
actually talk about — topic mix, cited tickers, trusted link domains, timing,
and a short style fingerprint. Downstream pipelines (`recap.py`,
`x_processor.py`) read this file to align their English output with the
channels' editorial voice.

Pure Python, no LLM dependency, so the profile is reproducible from the
corpus alone.

Usage:
    python build_profile.py PATH_TO_RESULT.json [MORE_RESULTS...]
"""

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
OUT_FILE = ROOT / "data" / "editorial_profile.json"

# Korean → English name map for the entities the channels cite most often.
# Used to translate e.g. "삼성전자" → "Samsung Electronics" when listing top
# entities so the public profile + the recap stay English-facing.
KO_TO_EN = {
    "삼성전자": "Samsung Electronics",
    "삼성": "Samsung",
    "SK하이닉스": "SK Hynix",
    "하이닉스": "SK Hynix",
    "현대차": "Hyundai Motor",
    "기아": "Kia",
    "포스코": "POSCO",
    "LG에너지솔루션": "LG Energy Solution",
    "LG화학": "LG Chem",
    "LG전자": "LG Electronics",
    "네이버": "Naver",
    "카카오": "Kakao",
    "셀트리온": "Celltrion",
    "한미반도체": "Hanmi Semiconductor",
    "엔비디아": "Nvidia",
    "테슬라": "Tesla",
    "애플": "Apple",
    "마이크로소프트": "Microsoft",
    "구글": "Alphabet",
    "메타": "Meta",
    "아마존": "Amazon",
    "넷플릭스": "Netflix",
    "브로드컴": "Broadcom",
    "팔란티어": "Palantir",
    "오픈AI": "OpenAI",
    "오픈에이아이": "OpenAI",
    "앤트로픽": "Anthropic",
    "마이크론": "Micron",
    "인텔": "Intel",
    "AMD": "AMD",
    "TSMC": "TSMC",
    "ASML": "ASML",
    "퀄컴": "Qualcomm",
    "어도비": "Adobe",
    "오라클": "Oracle",
    "디즈니": "Disney",
    "월마트": "Walmart",
    "비트코인": "Bitcoin",
    "이더리움": "Ethereum",
    "마이크로스트래티지": "MicroStrategy",
    "스트래티지": "MicroStrategy",
    "코인베이스": "Coinbase",
    "리비안": "Rivian",
    "포드": "Ford",
    "보잉": "Boeing",
    "비야디": "BYD",
}

# Topic buckets. Each entry = (English label, list of Korean+English keywords).
# A post may hit multiple buckets; share-of-attention is
#   (posts hitting bucket) / (total posts).
# English keywords are matched whole-word & case-insensitively; Korean
# keywords are matched as substrings (Korean has no word breaks).
TOPIC_BUCKETS = [
    ("US Semis / AI Chips", [
        "엔비디아", "NVDA", "Nvidia",
        "AMD", "Broadcom", "브로드컴", "AVGO",
        "TSMC", "ASML", "ARM", "Marvell", "MRVL",
        "AI 칩", "AI chip", "AI accelerator", "GPU",
        "advanced packaging", "CoWoS", "Blackwell", "Rubin",
        "엔디비아",
    ]),
    ("Memory (DRAM/HBM/NAND)", [
        "HBM", "DRAM", "NAND",
        "메모리", "memory", "Micron", "마이크론", "MU",
        "하이닉스", "Hynix", "삼성전자",
    ]),
    ("Fed / Rates / Macro", [
        "Fed", "FOMC", "연준", "금리", "interest rate", "rate cut", "rate hike",
        "인플레", "inflation", "CPI", "PPI", "PCE",
        "고용", "실업", "jobs", "payroll", "nonfarm",
        "Powell", "파월", "Treasury", "국채", "yield", "yields",
        "달러", "DXY",
    ]),
    ("Korean Equities", [
        "코스피", "코스닥", "KOSPI", "KOSDAQ",
        "외인", "기관", "수급", "공매도", "한투",
    ]),
    ("AI Infrastructure / Hyperscaler Capex", [
        "데이터센터", "datacenter", "data center", "하이퍼스케일러", "hyperscaler",
        "capex", "AWS", "Azure", "GCP",
        "전력", "power grid", "냉각", "cooling",
    ]),
    ("Software / Internet / Platforms", [
        "MSFT", "Microsoft", "Alphabet", "Google", "구글", "Meta", "메타",
        "Amazon", "아마존", "Netflix", "넷플릭스", "Palantir", "팔란티어",
        "SaaS", "ServiceNow", "Snowflake", "Adobe", "Oracle", "오라클",
    ]),
    ("China / Tariffs / Geopolitics", [
        "중국", "China", "Xi", "시진핑", "Trump", "트럼프",
        "tariff", "관세", "sanction", "제재", "수출통제", "export control",
        "Taiwan", "대만",
    ]),
    ("Crypto", [
        "Bitcoin", "비트코인", "BTC", "Ethereum", "이더리움", "ETH",
        "stablecoin", "스테이블코인", "Coinbase", "코인베이스",
        "MicroStrategy", "MSTR", "crypto", "코인",
    ]),
    ("Earnings / Guidance", [
        "실적", "어닝", "earnings", "guidance", "가이던스",
        "revenue", "매출", "operating income", "영업이익",
        "EPS", "beat estimates", "miss estimates",
    ]),
    ("Energy / Commodities", [
        "유가", "원유", "oil", "crude", "Brent", "WTI",
        "OPEC", "natural gas", "LNG",
        "gold", "silver", "copper",
    ]),
    ("Autos / EVs", [
        "테슬라", "Tesla", "TSLA", "BYD", "비야디",
        "EV", "전기차", "Rivian", "리비안", "Lucid",
        "Ford", "현대차", "Hyundai", "Kia", "기아",
    ]),
    ("Trump 2.0 / US Policy", [
        "Trump", "트럼프", "Musk", "머스크", "DOGE",
        "Bessent", "베센트", "Lutnick",
    ]),
    ("Defense / Aerospace", [
        "방산", "defense", "Boeing", "보잉", "Lockheed", "RTX",
        "Palantir", "팔란티어",
    ]),
    ("Biotech / Pharma", [
        "바이오", "biotech", "pharma", "GLP-1", "Eli Lilly", "Novo Nordisk",
        "노보", "릴리", "Moderna", "Pfizer",
    ]),
]

TICKER_RE = re.compile(r"\$([A-Z]{1,6})\b")
EXCHANGE_TICKER_RE = re.compile(r"\b(?:NASDAQ|NYSE|AMEX):([A-Z]{1,6})\b")
KR_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
URL_RE = re.compile(r"https?://[^\s)\]]+", re.IGNORECASE)

# Common all-caps words that look like tickers but aren't. Skip these.
TICKER_BLOCKLIST = {
    "AI", "USD", "EUR", "JPY", "KRW", "CEO", "CFO", "CTO", "COO",
    "ETF", "IPO", "GDP", "CPI", "PPI", "PCE", "FOMC", "FED",
    "WSJ", "FT", "NYT", "BBC", "USA", "UK", "EU", "EV", "PC",
    "API", "SDK", "PR", "QA", "TV", "VR", "AR", "ML", "DL", "RL",
    "LLM", "GPT", "FY", "YTD", "QOQ", "YOY", "MOM",
    "BEV", "ICE", "ITC", "DOJ", "FTC", "SEC", "OPEC",
    "PE", "PB", "ROE", "ROA", "ROIC", "FCF", "MOU", "JV",
    "SGT", "KST", "EST", "EDT", "PT", "UTC", "GMT",
    "OK", "OFF", "ON", "USD", "BPS", "BPS",
}


def flatten_text(node) -> str:
    """Telegram stores message text as either a plain string OR a list of
    strings and `{type, text}` dicts (bold/links/etc). Flatten to one string
    for analysis."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(
            p if isinstance(p, str) else p.get("text", "")
            for p in node if isinstance(p, (str, dict))
        )
    return ""


def extract_link_domains(text_field, entities_field) -> list[str]:
    """Pull link hostnames from the structured `text` / `text_entities`
    arrays plus any bare URLs the editor inlined as plain text."""
    urls: list[str] = []
    for field in (text_field, entities_field):
        if isinstance(field, list):
            for piece in field:
                if not isinstance(piece, dict):
                    continue
                if piece.get("type") in ("link", "text_link"):
                    href = piece.get("href") or piece.get("text") or ""
                    if href.startswith("http"):
                        urls.append(href)
    urls.extend(URL_RE.findall(flatten_text(text_field)))

    domains: list[str] = []
    for u in urls:
        try:
            host = urlparse(u).netloc.lower()
        except ValueError:
            continue
        if host.startswith("www."):
            host = host[4:]
        if host:
            domains.append(host)
    return domains


def extract_tickers(text: str) -> list[str]:
    found: set[str] = set()
    for m in TICKER_RE.finditer(text):
        sym = m.group(1)
        if sym not in TICKER_BLOCKLIST and len(sym) >= 2:
            found.add(sym)
    for m in EXCHANGE_TICKER_RE.finditer(text):
        found.add(m.group(1))
    return sorted(found)


def extract_kr_codes(text: str) -> list[str]:
    return list({m.group(1) for m in KR_CODE_RE.finditer(text)})


def korean_names_in(text: str) -> list[str]:
    """Map Korean company-name substrings to their English display names."""
    return list({en for ko, en in KO_TO_EN.items() if ko in text})


_BUCKET_RES: list[tuple[str, list[tuple[bool, re.Pattern]]]] = []
for _label, _keywords in TOPIC_BUCKETS:
    _compiled: list[tuple[bool, re.Pattern]] = []
    for kw in _keywords:
        has_latin = bool(re.search(r"[A-Za-z]", kw))
        if has_latin:
            _compiled.append((
                True,
                re.compile(r"(?<![A-Za-z0-9])" + re.escape(kw) + r"(?![A-Za-z0-9])",
                           re.IGNORECASE),
            ))
        else:
            _compiled.append((False, re.compile(re.escape(kw))))
    _BUCKET_RES.append((_label, _compiled))


def bucket_post(text: str) -> list[str]:
    """Return the topic labels this post hits (zero, one, or many)."""
    hits: list[str] = []
    for label, patterns in _BUCKET_RES:
        for _, pat in patterns:
            if pat.search(text):
                hits.append(label)
                break
    return hits


def parse_iso_date(s):
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def session_for_kst(dt: datetime) -> str:
    """Rough US-market-session bucket given a KST-ish naive datetime.

    US regular hours 09:30–16:00 ET ≈ 22:30 prev-day – 05:00 next-day KST
    (or 23:30 – 06:00 during EST). We bucket loosely; this is a histogram,
    not a trade clock."""
    h = dt.hour + dt.minute / 60
    if h >= 22.5 or h < 5:
        return "us_regular"
    if 5 <= h < 6.5:
        return "us_postmarket"
    if 21 <= h < 22.5:
        return "us_premarket"
    return "asia_session"


def _sample_voice_examples(all_posts: list[dict], topic_share: list[dict],
                           per_topic: int = 5, max_chars: int = 700) -> list[dict]:
    """Pick ~25 representative posts to serve as voice imitation references.

    Stratified across the top 5 topics; within each topic the most recent
    substantive posts (long enough to show structure, short enough to fit
    the prompt). Returns Korean text untouched — the LLM does the translation
    at recap time.
    """
    top_topics = [t["label"] for t in topic_share[:5]]
    candidates = [
        p for p in all_posts
        if p["datetime"] is not None
        and 180 <= p["text_len"] <= 1400
        and p["topics"]
    ]
    candidates.sort(key=lambda p: p["datetime"], reverse=True)

    picked: list[dict] = []
    seen_text_keys: set[str] = set()
    for topic in top_topics:
        count = 0
        for p in candidates:
            if count >= per_topic:
                break
            if topic not in p["topics"]:
                continue
            key = p["text"][:80]
            if key in seen_text_keys:
                continue
            seen_text_keys.add(key)
            text = p["text"]
            if len(text) > max_chars:
                text = text[:max_chars].rsplit(" ", 1)[0] + "…"
            picked.append({
                "channel": p["channel"],
                "date": p["date"],
                "topic": topic,
                "domains": p["domains"][:3],
                "text": text,
            })
            count += 1
    return picked


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: build_profile.py PATH_TO_RESULT.json [...]", file=sys.stderr)
        return 2

    paths = [Path(p) for p in sys.argv[1:]]
    for p in paths:
        if not p.exists():
            print(f"ERROR: file not found: {p}", file=sys.stderr)
            return 2

    channels: list[dict] = []
    all_posts: list[dict] = []

    for p in paths:
        raw = json.loads(p.read_text(encoding="utf-8"))
        ch_name = raw.get("name") or p.parent.name
        msgs = raw.get("messages", [])
        kept = 0
        first_date = last_date = None
        for m in msgs:
            if m.get("type") != "message":
                continue
            text_field = m.get("text")
            entities_field = m.get("text_entities")
            flat = flatten_text(text_field).strip()
            if len(flat) < 5:
                continue
            kept += 1
            date_str = m.get("date") or ""
            if first_date is None:
                first_date = date_str
            last_date = date_str
            dt = parse_iso_date(date_str)
            has_bold = (
                isinstance(text_field, list)
                and any(isinstance(piece, dict) and piece.get("type") == "bold"
                        for piece in text_field)
            )
            reactions = m.get("reactions") or []
            engagement = sum(r.get("count", 0) for r in reactions)
            all_posts.append({
                "channel": ch_name,
                "date": date_str,
                "datetime": dt,
                "text": flat,
                "text_len": len(flat),
                "has_bold": has_bold,
                "domains": extract_link_domains(text_field, entities_field),
                "tickers": extract_tickers(flat),
                "kr_codes": extract_kr_codes(flat),
                "ko_companies": korean_names_in(flat),
                "topics": bucket_post(flat),
                "engagement": engagement,
            })
        channels.append({
            "name": ch_name,
            "post_count": kept,
            "first_date": first_date,
            "last_date": last_date,
        })

    total = len(all_posts)
    if total == 0:
        print("ERROR: no usable posts parsed", file=sys.stderr)
        return 1

    topic_counts: Counter = Counter()
    for post in all_posts:
        for t in post["topics"]:
            topic_counts[t] += 1
    topic_share = [
        {"label": label, "posts": cnt, "share": round(cnt / total, 4)}
        for label, cnt in topic_counts.most_common()
    ]

    entity_counts: Counter = Counter()
    for post in all_posts:
        for sym in post["tickers"]:
            entity_counts[sym] += 1
        for name in post["ko_companies"]:
            entity_counts[name] += 1
    top_entities = [{"name": n, "mentions": c} for n, c in entity_counts.most_common(50)]

    code_counts: Counter = Counter()
    for post in all_posts:
        for code in post["kr_codes"]:
            code_counts[code] += 1
    top_kr_codes = [{"code": c, "mentions": n} for c, n in code_counts.most_common(25)]

    dom_counts: Counter = Counter()
    for post in all_posts:
        for d in post["domains"]:
            dom_counts[d] += 1
    skip_doms = {"t.me", "telegram.org", "telegram.me", "telegra.ph"}
    top_domains = [
        {"domain": d, "mentions": n}
        for d, n in dom_counts.most_common(40)
        if d not in skip_doms
    ][:25]

    by_hour: Counter = Counter()
    by_session: Counter = Counter()
    by_weekday: Counter = Counter()
    for post in all_posts:
        dt = post["datetime"]
        if dt is None:
            continue
        by_hour[dt.hour] += 1
        by_session[session_for_kst(dt)] += 1
        by_weekday[dt.weekday()] += 1

    avg_len = round(sum(p["text_len"] for p in all_posts) / total, 1)
    bold_share = round(sum(1 for p in all_posts if p["has_bold"]) / total, 3)
    link_share = round(sum(1 for p in all_posts if p["domains"]) / total, 3)

    # The fingerprint is the prompt-ready style note that recap.py feeds into
    # the LLM. We rewrite it slightly based on what we just measured so the
    # description stays honest if the corpus shifts.
    top_topics_text = ", ".join(t["label"] for t in topic_share[:5]) or "general markets"
    fingerprint = (
        "Short-form market briefs translated to English. Posts open with index "
        "or sector moves, use bolded topic markers, and cite outside sources by "
        "link when relevant. Tone is analyst-curt: numbers first, jargon "
        "preserved (HBM, CoWoS, capex), no filler. Editorial focus skews to "
        f"{top_topics_text}."
    )

    # Voice examples — a small stratified sample of real posts, in their
    # original Korean. recap.py feeds these into the LLM so the English
    # output imitates the channels' actual structure, density, and citation
    # cadence rather than the generic style fingerprint.
    voice_examples = _sample_voice_examples(all_posts, topic_share)

    profile = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "channels": channels,
        "post_count": total,
        "topic_share": topic_share,
        "top_entities": top_entities,
        "top_kr_codes": top_kr_codes,
        "top_domains": top_domains,
        "timing": {
            "by_hour_kst": [
                {"hour": h, "posts": by_hour.get(h, 0)} for h in range(24)
            ],
            "by_weekday": [
                {"weekday": wd, "posts": by_weekday.get(i, 0)}
                for i, wd in enumerate(
                    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                )
            ],
            "by_us_session": [
                {"session": s, "posts": by_session.get(s, 0)}
                for s in ("us_premarket", "us_regular", "us_postmarket",
                          "asia_session")
            ],
        },
        "style": {
            "avg_text_length_chars": avg_len,
            "bold_share": bold_share,
            "link_share": link_share,
            "fingerprint": fingerprint,
        },
        "voice_examples": voice_examples,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Wrote {OUT_FILE.relative_to(ROOT)}: {total} posts across "
        f"{len(channels)} channel(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
