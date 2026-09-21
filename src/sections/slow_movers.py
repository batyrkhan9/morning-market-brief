"""Section: slow movers. One alert per ticker per day, rules as tags, severity = most severe rule.

Flags are computed from price history (rules.py). state.json only holds each ticker's last alert
for the cooldown and escalation logic. The brief shows the top N by severity then market cap;
the rest go to the full list page.
"""
import pandas as pd

from src import rules
from src.sections.common import last_on_or_before
from src.sections.movers import headlines_for
from src.sources import news

TOP_N = 5


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
    cfg = ctx["config_thresholds"]["slow_movers"]
    cooldown = cfg["repeat_cooldown_days"]
    last_alerts = ctx["state"].setdefault("slow_mover_alerts", {})
    per_item = news.settings()["headlines_per_item"]
    closes, bench, caps = u["closes"], u["closes"][u["benchmark"]], u["caps"]
    meta = u["constituents"].set_index("ticker")
    alerts, suppressed, new_alerts = [], [], {}
    for t in u["constituents"]["ticker"]:
        if t not in closes.columns:
            continue
        s = closes[t].dropna()
        fired = rules.flags_on(s, as_of, cfg)
        if not fired:
            continue
        severity, direction = rules.summarize(fired, cfg)
        last = last_alerts.get(t)
        if not rules.should_alert(last, as_of, severity, direction, cooldown):
            suppressed.append({"ticker": t, "rules": fired, "severity": severity, "last": last})
            continue
        new_alerts[t] = {"date": as_of.date().isoformat(), "severity": severity, "direction": direction, "rules": fired}
        cond = rules.conditions(s, cfg)
        d0, v0 = last_on_or_before(s, as_of)
        prev = s[s.index < d0]
        rec = meta.loc[t]
        r1, r5 = cond.attrs["ret_1y"].iloc[-1], cond.attrs["ret_5y"].iloc[-1]
        alerts.append({
            "ticker": t, "name": rec["name"], "sector": rec["sector"], "rules": fired,
            "severity": severity, "direction": direction, "cap": caps.get(t) or 0,
            "escalation": bool(last and as_of - pd.Timestamp(last["date"]) < pd.Timedelta(days=cooldown)),
            "last": v0, "chg_1d": (v0 / float(prev.iloc[-1]) - 1) * 100 if not prev.empty else None,
            "ret_1y": None if pd.isna(r1) else float(r1) * 100,
            "ret_5y": None if pd.isna(r5) else float(r5) * 100,
            "chart": chart_data(s, bench, as_of), "headlines": [], "news_error": None,
            "source_url": "https://finance.yahoo.com/quote/" + t,
        })
    alerts.sort(key=lambda a: (-a["severity"], -a["cap"], a["ticker"]))
    for a in alerts[:TOP_N]:
        a["headlines"], a["news_error"] = headlines_for(a["name"], a["ticker"], per_item)
    return {"as_of": ctx["as_of"], "alerts": alerts, "top": [a["ticker"] for a in alerts[:TOP_N]],
            "rest": [a["ticker"] for a in alerts[TOP_N:]], "suppressed": suppressed, "new_alerts": new_alerts}
