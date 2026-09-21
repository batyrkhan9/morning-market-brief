"""Section: S&P 500 treemap data. Box size by market cap, color by 1 day change, grouped by sector."""
from src.sections.common import last_on_or_before


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
        s = closes[t].dropna()
        d0, v0 = last_on_or_before(s, as_of)
        prev = s[s.index < d0] if d0 is not None else s.iloc[0:0]
        if d0 is None or prev.empty:
            skipped.append(t)
            continue
        rows.append({"ticker": t, "name": rec["name"], "sector": rec["sector"], "cap": cap,
                     "chg_1d": (v0 / float(prev.iloc[-1]) - 1) * 100})
    if not rows:
        raise RuntimeError("no constituents with both a market cap and two closes")
    return {"as_of": as_of, "rows": rows, "skipped": skipped, "caps_fetched_at": u.get("caps_fetched_at")}
