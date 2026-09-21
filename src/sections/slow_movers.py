"""Section: slow movers. Flags computed from price history (rules.py); state.json only stops repeats."""
from datetime import timedelta

import pandas as pd

from src import rules
from src.sections.common import last_on_or_before
from src.sections.movers import headlines_for
from src.sources import news


def chart_data(s, bench, as_of, years=5):
    """Weekly closes of the stock and the benchmark over `years`, both indexed to 100."""
    start = pd.Timestamp(as_of) - pd.DateOffset(years=years)
    a = s[(s.index > start) & (s.index <= as_of)].dropna()
    b = bench.reindex(a.index, method="ffill").dropna()
    a = a.reindex(b.index)
    a, b = a.resample("W-FRI").last().dropna(), b.resample("W-FRI").last().dropna()
    b = b.reindex(a.index)
    return {"dates": [d.date().isoformat() for d in a.index],
            "stock": [round(float(v) / float(a.iloc[0]) * 100, 2) for v in a],
            "benchmark": [round(float(v) / float(b.iloc[0]) * 100, 2) for v in b]}


def build(ctx):
    u = ctx["universe"]
    as_of = pd.Timestamp(ctx["as_of"])
    thresholds = ctx["config_thresholds"]["slow_movers"]
    cooldown = timedelta(days=thresholds["repeat_cooldown_days"])
    alerts = ctx["state"].setdefault("slow_mover_alerts", {})
    per_item = news.settings()["headlines_per_item"]
    closes, bench = u["closes"], u["closes"][u["benchmark"]]
    meta = u["constituents"].set_index("ticker")
    flagged, suppressed, new_alerts = [], [], {}
    for t in u["constituents"]["ticker"]:
        if t not in closes.columns:
            continue
        s = closes[t].dropna()
        fired = rules.flags_on(s, as_of, thresholds)
        if not fired:
            continue
        keep = []
        for r in fired:
            key = f"{t}|{r}"
            last = alerts.get(key)
            if last and as_of - pd.Timestamp(last) < cooldown:
                suppressed.append({"ticker": t, "rule": r, "last": last})
            else:
                keep.append(r)
                new_alerts[key] = as_of.date().isoformat()
        if not keep:
            continue
        cond = rules.conditions(s, thresholds)
        d0, v0 = last_on_or_before(s, as_of)
        prev = s[s.index < d0]
        rec = meta.loc[t]
        items, err = headlines_for(rec["name"], t, per_item)
        r1, r5 = cond.attrs["ret_1y"].iloc[-1], cond.attrs["ret_5y"].iloc[-1]
        flagged.append({
            "ticker": t, "name": rec["name"], "sector": rec["sector"], "rules": keep,
            "last": v0, "chg_1d": (v0 / float(prev.iloc[-1]) - 1) * 100 if not prev.empty else None,
            "ret_1y": None if pd.isna(r1) else float(r1) * 100,
            "ret_5y": None if pd.isna(r5) else float(r5) * 100,
            "chart": chart_data(s, bench, as_of), "headlines": items, "news_error": err,
            "source_url": "https://finance.yahoo.com/quote/" + t,
        })
    flagged.sort(key=lambda f: f["ticker"])
    return {"as_of": ctx["as_of"], "flagged": flagged, "suppressed": suppressed, "new_alerts": new_alerts}
