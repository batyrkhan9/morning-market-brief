"""Section: ongoing. Every ticker currently inside the slow mover cooldown, with its first alert date
and price, last alert severity, and the change since the first alert. Rendered to its own page."""
import pandas as pd

from src.sections.common import last_on_or_before
from src.sections.slow_movers import chart_data


def build(ctx):
    u = ctx["universe"]
    as_of = pd.Timestamp(ctx["as_of"])
    cfg = ctx["config_thresholds"]["slow_movers"]
    state = dict(ctx["state"].get("slow_mover_alerts", {}))
    state.update(ctx.get("new_alerts_today", {}))
    closes, bench = u["closes"], u["closes"][u["benchmark"]]
    meta = u["constituents"].set_index("ticker")
    rows = []
    for t, last in state.items():
        days = (as_of - pd.Timestamp(last["date"])).days
        if days >= cfg["repeat_cooldown_days"]:
            continue
        row = {"ticker": t, "name": meta.loc[t, "name"] if t in meta.index else t,
               "sector": meta.loc[t, "sector"] if t in meta.index else None,
               "first_date": last.get("first_date", last["date"]), "first_price": last.get("first_price", last.get("price")),
               "last_date": last["date"], "severity": last["severity"], "direction": last["direction"],
               "rules": last.get("rules", []), "count": last.get("count", 1), "days_left": cfg["repeat_cooldown_days"] - days,
               "price": None, "since_first": None, "chart": None, "source_url": "https://finance.yahoo.com/quote/" + t}
        if t in closes.columns:
            s = closes[t].dropna()
            d0, v0 = last_on_or_before(s, as_of)
            if d0 is not None:
                row["price"] = v0
                if row["first_price"]:
                    row["since_first"] = (v0 / row["first_price"] - 1) * 100
                row["chart"] = chart_data(s, bench, as_of)
        rows.append(row)
    rows.sort(key=lambda r: (-r["severity"], r["first_date"], r["ticker"]))
    return {"as_of": ctx["as_of"], "rows": rows, "cooldown_days": cfg["repeat_cooldown_days"]}
