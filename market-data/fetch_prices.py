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

import requests  # installed with yfinance
import yfinance as yf

TICKERS = {
    "SCHX": "Schwab U.S. Large-Cap",
    "FLJP": "Franklin FTSE Japan",
    "SCHF": "Schwab International Equity",
    "SCHA": "Schwab U.S. Small-Cap",
    "NVDA": "NVIDIA",
}
INDEXES = {"^GSPC": "S&P 500", "^DJI": "Dow", "^IXIC": "Nasdaq", "^RUT": "Russell 2000"}
# Overnight context: US index futures plus the Nikkei (for FLJP).
FUTURES = {"ES=F": "S&P 500 futures", "NQ=F": "Nasdaq 100 futures",
           "YM=F": "Dow futures", "RTY=F": "Russell 2000 futures", "^N225": "Nikkei 225"}
SESSIONS = 15  # trading days kept per ticker

# NWS (api.weather.gov) for Huntsville, AL. No key needed, but a User-Agent is required.
LAT, LON = 34.7293, -86.5851
OBS_STATION = "KHSV"
NWS_HEADERS = {"User-Agent": "market-data briefing (github.com/gnodabb/market-data)",
               "Accept": "application/geo+json"}
FORECAST_PERIODS = 14  # about 7 days of day/night periods


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


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def quote(symbol, name):
    """Latest trade (intraday/overnight) vs. the prior daily close."""
    t = yf.Ticker(symbol)
    intraday = t.history(period="2d", interval="5m", auto_adjust=False).dropna(subset=["Close"])
    daily = t.history(period="10d", interval="1d", auto_adjust=False).dropna(subset=["Close"])
    if intraday.empty or len(daily) < 1:
        raise ValueError("no data returned")
    last_ts = intraday.index[-1]
    last = float(intraday["Close"].iloc[-1])
    # Prior close = last daily bar dated before the latest trade's session date.
    prior = daily[daily.index.date < last_ts.date()]
    prev = float((prior if not prior.empty else daily)["Close"].iloc[-1])
    return {"name": name, "last": round(last, 4),
            "last_time_utc": last_ts.tz_convert("UTC").isoformat(timespec="minutes"),
            "prev_close": round(prev, 4), "change": round(last - prev, 4),
            "pct_change": round((last / prev - 1) * 100, 3), "fetched_utc": utcnow()}


def nws_get(url):
    r = requests.get(url, headers=NWS_HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()


def c_to_f(c):
    return None if c is None else round(c * 9 / 5 + 32)


def weather():
    point = nws_get(f"https://api.weather.gov/points/{LAT},{LON}")["properties"]
    fc = nws_get(point["forecast"])["properties"]
    periods = [{"name": p["name"], "start": p["startTime"], "is_day": p["isDaytime"],
                "temp_f": p["temperature"], "precip_pct": (p.get("probabilityOfPrecipitation") or {}).get("value"),
                "wind": f'{p["windDirection"]} {p["windSpeed"]}', "short": p["shortForecast"],
                "detail": p["detailedForecast"]} for p in fc["periods"][:FORECAST_PERIODS]]
    out = {"location": "Huntsville, AL", "forecast_updated": fc.get("updateTime") or fc.get("generatedAt"),
           "periods": periods, "alerts": [], "current": None, "fetched_utc": utcnow()}
    alerts = nws_get(f"https://api.weather.gov/alerts/active?point={LAT},{LON}")["features"]
    out["alerts"] = [{"event": a["properties"]["event"], "headline": a["properties"]["headline"],
                      "ends": a["properties"].get("ends") or a["properties"].get("expires")} for a in alerts]
    try:
        ob = nws_get(f"https://api.weather.gov/stations/{OBS_STATION}/observations/latest")["properties"]
        wind_kmh = ob["windSpeed"]["value"]
        out["current"] = {"time": ob["timestamp"], "text": ob["textDescription"],
                          "temp_f": c_to_f(ob["temperature"]["value"]),
                          "wind_mph": None if wind_kmh is None else round(wind_kmh / 1.609),
                          "humidity_pct": None if ob["relativeHumidity"]["value"] is None
                          else round(ob["relativeHumidity"]["value"])}
    except Exception as exc:  # observations are optional
        out["current_error"] = str(exc)[:200]
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
    result["futures"] = {}
    for sym, name in FUTURES.items():
        try:
            result["futures"][sym] = quote(sym, name)
        except Exception as exc:
            result["errors"][sym] = str(exc)[:200]
    try:
        result["weather"] = weather()
    except Exception as exc:
        result["errors"]["weather"] = str(exc)[:200]
    if not result["tickers"]:
        print("No ticker data fetched; leaving prices.json unchanged.", file=sys.stderr)
        sys.exit(1)
    tmp = out_dir / "prices.json.tmp"
    tmp.write_text(json.dumps(result, indent=1) + "\n")
    tmp.replace(out_dir / "prices.json")
    print(f"Wrote {len(result['tickers'])} tickers, {len(result['indexes'])} indexes, "
          f"{len(result['futures'])} futures, weather={'weather' in result}, "
          f"{len(result['errors'])} errors")


if __name__ == "__main__":
    main()
