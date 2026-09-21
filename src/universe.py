"""The S&P 500 universe: constituents, one batched price download, and weekly-cached market caps."""
import json
import time
from datetime import datetime, timezone

from src.paths import DATA
from src.sources import constituents, prices

CAPS_CACHE = DATA / "market_caps.json"
CAPS_MAX_AGE_DAYS = 7


def _age_days(iso):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 86400


def load_market_caps(tickers, cache_path=CAPS_CACHE, force=False):
    """{ticker: cap}. Refreshed at most weekly, or when more than 10% of tickers are missing."""
    cached = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else None
    if cached and not force:
        have = [t for t in tickers if cached["caps"].get(t)]
        if _age_days(cached["fetched_at"]) < CAPS_MAX_AGE_DAYS and len(have) >= 0.9 * len(tickers):
            return cached["caps"], False
    caps = prices.get_market_caps(tickers)
    if cached:  # keep old values for tickers that failed this time
        for t, v in cached["caps"].items():
            if caps.get(t) is None and v:
                caps[t] = v
    payload = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "caps": caps}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=0) + "\n", encoding="utf-8")
    return caps, True


def load(config, with_caps=True):
    """Fetch everything the heatmap, movers and slow movers need. Returns a dict with timing."""
    cfg = config["universe"]
    timing = {}
    t = time.time()
    cons = constituents.get_sp500()
    timing["constituents_s"] = round(time.time() - t, 1)
    tickers = cons["ticker"].tolist()
    t = time.time()
    closes = prices.get_prices(tickers + [cfg["benchmark"]], period=cfg["history_period"])
    timing["prices_s"] = round(time.time() - t, 1)
    caps, refreshed = ({}, False)
    if with_caps:
        t = time.time()
        caps, refreshed = load_market_caps(tickers)
        timing["caps_s"] = round(time.time() - t, 1)
    timing["caps_refreshed"] = refreshed
    timing["tickers"] = len(tickers)
    timing["rows"] = int(closes.shape[0])
    return {"constituents": cons, "closes": closes, "caps": caps, "benchmark": cfg["benchmark"],
            "timing": timing, "constituents_stale": bool(cons.attrs.get("stale"))}
