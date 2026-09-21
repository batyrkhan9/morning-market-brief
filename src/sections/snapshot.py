"""Section: snapshot table. Last value, 1 day, 1 month, YTD for indexes, world ETFs, rates, other."""
import pandas as pd

from src.sections.common import changes, last_trading_day
from src.sources import fred, prices

ANCHOR = "^GSPC"
FRED_START_OFFSET_DAYS = 400  # enough history for the YTD reference in early January


def yahoo_url(ticker):
    return "https://finance.yahoo.com/quote/" + ticker.replace("^", "%5E")


def build(ctx):
    cfg = ctx["config"]["snapshot"]
    out = {"as_of": None, "groups": [], "errors": []}

    price_groups = [(k, cfg[k]) for k in ("us", "world", "other")]
    tickers = [item["ticker"] for _, items in price_groups for item in items]
    closes = None
    try:
        closes = prices.get_prices(tickers, period="2y")
        as_of = last_trading_day(closes, anchor=ANCHOR)
        out["as_of"] = as_of.date().isoformat()
        ctx["as_of"] = out["as_of"]
    except Exception as e:  # noqa: BLE001
        out["errors"].append({"where": "prices", "message": f"{type(e).__name__}: {e}"})

    for key, items in price_groups:
        rows = []
        if closes is not None:
            for item in items:
                t = item["ticker"]
                row = {"id": t, "label": item["label"], "source_url": yahoo_url(t), "decimals": 2}
                try:
                    if t not in closes.columns:
                        raise RuntimeError("ticker not in response")
                    row.update(changes(closes[t], as_of, "pct"))
                except Exception as e:  # noqa: BLE001
                    row["error"] = f"{type(e).__name__}: {e}"
                rows.append(row)
        out["groups"].append({"key": key, "rows": rows})

    rate_rows = []
    as_of_rates = ctx.get("as_of") or pd.Timestamp.utcnow().tz_localize(None).normalize()
    start = (pd.Timestamp(as_of_rates) - pd.Timedelta(days=FRED_START_OFFSET_DAYS)).date()
    for item in cfg["rates_fred"]:
        sid = item["series"]
        row = {"id": sid, "label": item["label"], "source_url": fred.series_url(sid), "decimals": 2}
        try:
            s = fred.get_series(sid, start)
            row.update(changes(s, as_of_rates, "bp"))
        except Exception as e:  # noqa: BLE001
            row["error"] = f"{type(e).__name__}: {e}"
        rate_rows.append(row)
    if rate_rows and all("error" in r for r in rate_rows):
        out["errors"].append({"where": "rates", "message": rate_rows[0]["error"]})
    # Keep the config order: us, world, rates, other.
    out["groups"].insert(2, {"key": "rates_fred", "rows": rate_rows})
    return out
