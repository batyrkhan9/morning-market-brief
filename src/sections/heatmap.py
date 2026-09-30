"""Section: S&P 500 treemap data. Box size by market cap, color by 1 day change, grouped by sector."""
from src.sections.common import close_pair_on


def build(ctx):
    u = ctx["universe"]
    closes, caps = u["closes"], u["caps"]
    as_of = ctx["as_of"]
    rows, skipped = [], []
    for rec in u["constituents"].to_dict(orient="records"):
        t = rec["ticker"]
        cap = caps.get(t)
        if t not in closes.columns or not cap:
            skipped.append(t)
            continue
        v0, v1 = close_pair_on(closes[t], as_of)
        if v0 is None:
            skipped.append(t)
            continue
        rows.append({"ticker": t, "name": rec["name"], "sector": rec["sector"], "cap": cap,
                     "chg_1d": (v0 / v1 - 1) * 100})
    if not rows:
        raise RuntimeError("no constituents with both a market cap and two closes")
    return {"as_of": as_of, "rows": rows, "skipped": skipped, "caps_fetched_at": u.get("caps_fetched_at")}
