#!/usr/bin/env python3
"""Fetch recent daily closes for the morning-briefing tickers and write prices.json.

Usage: fetch_prices.py <output_dir>
Writes <output_dir>/prices.json. Exits non-zero (and leaves the old file alone)
if no ticker could be fetched.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

TICKERS = {
    "SCHX": "Schwab U.S. Large-Cap",
    "FLJP": "Franklin FTSE Japan",
    "SCHF": "Schwab International Equity",
    "SCHA": "Schwab U.S. Small-Cap",
    "NVDA": "NVIDIA",
}
INDEXES = {"^GSPC": "S&P 500", "^DJI": "Dow", "^IXIC": "Nasdaq", "^RUT": "Russell 2000"}
SESSIONS = 15  # trading days kept per ticker


def closes(symbol):
    hist = yf.Ticker(symbol).history(period="1mo", interval="1d", auto_adjust=False)
    hist = hist.dropna(subset=["Close"]).tail(SESSIONS)
    return [{"date": idx.strftime("%Y-%m-%d"), "close": round(float(row["Close"]), 4)}
            for idx, row in hist.iterrows()]


def summarize(name, series):
    out = {"name": name, "closes": series}
    if len(series) >= 2:
        last, prev = series[-1]["close"], series[-2]["close"]
        out.update(last_date=series[-1]["date"], last_close=last, prev_close=prev,
                   change=round(last - prev, 4), pct_change=round((last / prev - 1) * 100, 3))
    elif series:
        out.update(last_date=series[-1]["date"], last_close=series[-1]["close"])
    return out


def main():
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    result = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "tickers": {}, "indexes": {}, "errors": {}}
    for group, table in (("tickers", TICKERS), ("indexes", INDEXES)):
        for sym, name in table.items():
            try:
                series = closes(sym)
                if not series:
                    raise ValueError("no data returned")
                result[group][sym] = summarize(name, series)
            except Exception as exc:  # keep going; record the failure
                result["errors"][sym] = str(exc)[:200]
    if not result["tickers"]:
        print("No ticker data fetched; leaving prices.json unchanged.", file=sys.stderr)
        sys.exit(1)
    tmp = out_dir / "prices.json.tmp"
    tmp.write_text(json.dumps(result, indent=1) + "\n")
    tmp.replace(out_dir / "prices.json")
    print(f"Wrote {len(result['tickers'])} tickers, {len(result['indexes'])} indexes, "
          f"{len(result['errors'])} errors")


if __name__ == "__main__":
    main()
