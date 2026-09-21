"""Section: snapshot table. Last value, 1 day, 1 month, YTD for indexes, world ETFs, rates, other."""
import pandas as pd

from src.sections.common import changes, last_trading_day
from src.sources import fred, prices, treasury

ANCHOR = "^GSPC"
HISTORY_DAYS = 400  # enough for the YTD reference in early January


def yahoo_url(ticker):
    return "https://finance.yahoo.com/quote/" + ticker.replace("^", "%5E")


def _err(e):
    return f"{type(e).__name__}: {e}"


def price_row(item, closes, as_of):
    """One snapshot/sector row. Falls back to item['fallback'] when the primary close is stale."""
    t = item["ticker"]
    row = {"key": t, "id": t, "label": item["label"], "source_url": yahoo_url(t), "decimals": 2}
    try:
        if t not in closes.columns:
            raise RuntimeError("ticker not in response")
        row.update(changes(closes[t], as_of, "pct", detect_stale=True))
        fb = item.get("fallback")
        if row["stale"] and fb and fb in closes.columns:
            alt = changes(closes[fb], as_of, "pct", detect_stale=True)
            if not alt["stale"]:
                row.update(alt)
                row.update({"id": fb, "source_url": yahoo_url(fb), "note": f"{t} stale",
                            "label": item.get("fallback_label") or f"{item['label']} ({fb})"})
    except Exception as e:  # noqa: BLE001
        row["error"] = _err(e)
    return row


def rate_rows(items, as_of, errors):
    """Rates from the Treasury curve first, FRED as fallback. Each row keeps its own value date."""
    start = (pd.Timestamp(as_of) - pd.Timedelta(days=HISTORY_DAYS)).date()
    curve = None
    if any(i.get("treasury") for i in items):
        try:
            curve = treasury.get_yields(start)
        except Exception as e:  # noqa: BLE001
            errors.append({"where": "treasury", "message": _err(e) + " (rates shown from FRED instead)"})
    rows = []
    for item in items:
        row = {"key": item["id"], "label": item["label"], "decimals": 2}
        done = False
        cols = item.get("treasury")
        if curve is not None and cols:
            try:
                s = curve[cols[0]] - curve[cols[1]] if isinstance(cols, list) else curve[cols]
                row.update(changes(s.dropna(), as_of, "bp"))
                row.update({"id": "Treasury", "source_url": treasury.page_url(), "source": "treasury"})
                done = True
            except Exception as e:  # noqa: BLE001
                row["note"] = f"Treasury: {_err(e)}"
        if not done and item.get("fred"):
            sid = item["fred"]
            try:
                row.update(changes(fred.get_series(sid, start), as_of, "bp"))
                row.update({"id": sid, "source_url": fred.series_url(sid), "source": "fred"})
                done = True
            except Exception as e:  # noqa: BLE001
                row["error"] = _err(e)
        if not done and "error" not in row:
            row["error"] = row.get("note", "no source configured")
        row.setdefault("id", item.get("fred") or item["id"])
        row.setdefault("source_url", fred.series_url(row["id"]))
        rows.append(row)
    if rows and all("error" in r for r in rows):
        errors.append({"where": "rates", "message": rows[0]["error"]})
    return rows


def build(ctx):
    cfg = ctx["config"]["snapshot"]
    out = {"as_of": None, "groups": [], "errors": []}

    price_groups = [(k, cfg[k]) for k in ("us", "world", "other")]
    tickers = []
    for _, items in price_groups:
        for item in items:
            tickers.append(item["ticker"])
            if item.get("fallback"):
                tickers.append(item["fallback"])
    closes, as_of = None, None
    try:
        closes = prices.get_prices(tickers, period="2y")
        as_of = last_trading_day(closes, anchor=ANCHOR)
        out["as_of"] = as_of.date().isoformat()
        ctx["as_of"] = out["as_of"]
    except Exception as e:  # noqa: BLE001
        out["errors"].append({"where": "prices", "message": _err(e)})

    for key, items in price_groups:
        rows = [price_row(item, closes, as_of) for item in items] if closes is not None else []
        out["groups"].append({"key": key, "rows": rows})

    as_of_rates = ctx.get("as_of") or pd.Timestamp.utcnow().tz_localize(None).normalize()
    out["groups"].insert(2, {"key": "rates", "rows": rate_rows(cfg["rates"], as_of_rates, out["errors"])})
    return out
