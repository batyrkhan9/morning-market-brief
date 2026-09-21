"""Section: the 11 sector ETFs ranked by 1 day change, with 1 month and YTD."""
from src.sections.common import changes, last_trading_day
from src.sections.snapshot import yahoo_url
from src.sources import prices


def build(ctx):
    items = ctx["config"]["sectors"]
    tickers = [i["ticker"] for i in items]
    closes = prices.get_prices(tickers, period="2y")
    as_of = ctx.get("as_of") or last_trading_day(closes)
    rows = []
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
    rows.sort(key=lambda r: (r.get("chg_1d") is None, -(r.get("chg_1d") or 0)))
    return {"as_of": str(as_of)[:10], "rows": rows}
