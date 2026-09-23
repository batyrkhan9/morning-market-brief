"""Score predictions against closing prices once their due date has passed. No LLM, no state beyond predictions.json."""
import json

import pandas as pd

from src.paths import DATA
from src.sources import prices, treasury

PREDICTIONS = DATA / "predictions.json"
SNAPSHOT_ITEMS = {"SPX": "^GSPC", "NDX": "^IXIC", "DJI": "^DJI", "RUT": "^RUT", "VIX": "^VIX",
                  "DXY": "DX-Y.NYB", "OIL": "CL=F", "GOLD": "GC=F"}
TREASURY_ITEMS = {"US2Y": "2 Yr", "US10Y": "10 Yr"}


def load():
    return json.loads(PREDICTIONS.read_text(encoding="utf-8")) if PREDICTIONS.exists() else []


def save(preds):
    PREDICTIONS.write_text(json.dumps(preds, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def close_on_or_before(symbol, date, closes=None, curve=None):
    """Closing value on the due date, or the last close before it."""
    if symbol in TREASURY_ITEMS:
        curve = curve if curve is not None else treasury.get_yields((pd.Timestamp(date) - pd.Timedelta(days=30)).date())
        s = curve[TREASURY_ITEMS[symbol]].dropna()
    else:
        ticker = SNAPSHOT_ITEMS.get(symbol, symbol)
        if closes is None or ticker not in closes.columns:
            closes = prices.get_prices([ticker], period="3mo")
        s = closes[ticker].dropna()
    s = s[s.index <= pd.Timestamp(date)]
    if s.empty:
        raise RuntimeError(f"no close on or before {date} for {symbol}")
    return float(s.iloc[-1]), s.index[-1].date().isoformat()


def score(preds, as_of, fetch=close_on_or_before):
    """Mark open predictions whose due date <= as_of as right or wrong. Returns the ones scored now."""
    scored = []
    for p in preds:
        if p.get("status") != "open" or p["by"] > as_of:
            continue
        try:
            close, on = fetch(p["ticker"], p["by"])
        except Exception as e:  # noqa: BLE001 - leave it open, try again next build
            p["score_error"] = f"{type(e).__name__}: {e}"
            continue
        hit = close > p["level"] if p["direction"] == "above" else close < p["level"]
        p.update({"status": "right" if hit else "wrong", "close": close, "close_date": on, "scored_on": as_of})
        p.pop("score_error", None)
        scored.append(p)
    return scored


def hit_rate(preds):
    done = [p for p in preds if p.get("status") in ("right", "wrong")]
    if not done:
        return None
    return sum(1 for p in done if p["status"] == "right") / len(done)
