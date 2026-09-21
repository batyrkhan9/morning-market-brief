"""One-time baseline: every S&P 500 stock currently beyond each slow mover threshold (the starting watchlist)."""
import pandas as pd

from src import rules


def build(ctx):
    u = ctx["universe"]
    cfg = ctx["config_thresholds"]["slow_movers"]
    as_of = pd.Timestamp(ctx["as_of"])
    meta = u["constituents"].set_index("ticker")
    by_rule = {r: [] for r in rules.rule_names(cfg)}
    short_history = []
    for t in u["constituents"]["ticker"]:
        if t not in u["closes"].columns:
            continue
        s = u["closes"][t].dropna()
        s = s[s.index <= as_of]
        if s.empty:
            continue
        active, r1, r5 = rules.current(s, cfg)
        if r5 is None:
            short_history.append(t)
        rec = meta.loc[t]
        for r in active:
            by_rule[r].append({"ticker": t, "name": rec["name"], "sector": rec["sector"], "last": float(s.iloc[-1]),
                               "ret_1y": None if r1 is None else r1 * 100, "ret_5y": None if r5 is None else r5 * 100,
                               "source_url": "https://finance.yahoo.com/quote/" + t})
    for r in by_rule:
        key = "ret_5y" if r.startswith("5y") else "ret_1y"
        by_rule[r].sort(key=lambda x: (x[key] is None, x[key] or 0))
    return {"as_of": ctx["as_of"], "by_rule": by_rule, "short_history": short_history,
            "universe_size": int(u["constituents"].shape[0]), "rules": cfg["rules"]}
