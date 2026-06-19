#!/usr/bin/env python3
"""Fetch major US index levels from Yahoo Finance (yfinance) -> data/indices.json.

Drives the ticker strip at the very top of the site. Runs in the hourly news
job. Never fails the build: if Yahoo is unreachable it just leaves the file as-is
and the ticker hides itself.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_FILE = ROOT / "data" / "indices.json"

# name shown in the UI, Yahoo Finance symbol
INDICES = [
    ("S&P 500", "^GSPC"),
    ("Nasdaq", "^IXIC"),
    ("Dow Jones", "^DJI"),
    ("Russell 2000", "^RUT"),
]


def fetch_one(ticker) -> dict | None:
    """Return {price, change, change_pct} for one index, or None."""
    price = prev = None

    # Prefer fast_info (last price + previous close); fall back to history.
    try:
        fi = ticker.fast_info
        price = float(fi.last_price)
        prev = float(fi.previous_close)
    except Exception:  # noqa: BLE001
        price = prev = None

    if not price or not prev:
        try:
            hist = ticker.history(period="5d")
            closes = [float(c) for c in hist["Close"].dropna().tolist()]
            if len(closes) >= 2:
                price, prev = closes[-1], closes[-2]
            elif closes:
                price = prev = closes[-1]
        except Exception:  # noqa: BLE001
            return None

    if not price or not prev:
        return None
    change = price - prev
    pct = (change / prev * 100) if prev else 0.0
    return {"price": round(price, 2), "change": round(change, 2),
            "change_pct": round(pct, 2)}


def main() -> int:
    import yfinance as yf

    out = []
    for name, symbol in INDICES:
        print(f"Fetching {name} ({symbol}) ...", file=sys.stderr)
        try:
            data = fetch_one(yf.Ticker(symbol))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! {name}: {exc}", file=sys.stderr)
            data = None
        if data:
            out.append({"name": name, "symbol": symbol, **data})
            print(f"  -> {data['price']} ({data['change_pct']:+.2f}%)", file=sys.stderr)
        else:
            print(f"  ! {name}: no data", file=sys.stderr)

    if not out:
        # Non-fatal: keep whatever is already there and let the ticker hide.
        print("No index data fetched — leaving indices.json untouched.", file=sys.stderr)
        return 0

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "indices": out,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_FILE.name}: {len(out)} indices.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
