"""Section: the 11 sector ETFs ranked by 1 day change, with 1 month and YTD."""
from src.sections.common import last_trading_day
from src.sections.snapshot import price_row
from src.sources import prices


def build(ctx):
    items = ctx["config"]["sectors"]
    tickers = [i["ticker"] for i in items]
    closes = prices.get_prices(tickers, period="2y")
    as_of = ctx.get("as_of") or last_trading_day(closes)
    rows = [price_row(item, closes, as_of) for item in items]
    rows.sort(key=lambda r: (r.get("chg_1d") is None, -(r.get("chg_1d") or 0)))
    return {"as_of": str(as_of)[:10], "rows": rows}
