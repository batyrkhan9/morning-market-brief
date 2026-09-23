"""Seed data/state.json with the slow mover alerts of the last N days, as if they had been sent, so the
first real run only shows genuine new crossings: python -m src.seed_state [days=180] [--dry-run]"""
import json
import sys
from datetime import date

import pandas as pd
import yaml

from src import rules
from src.paths import CONFIG, DATA
from src.sources import constituents, prices

STATE = DATA / "state.json"


def seed(days=180, write=True):
    cfg = yaml.safe_load(open(CONFIG / "thresholds.yaml", encoding="utf-8"))["slow_movers"]
    cons = constituents.get_sp500()
    end = date.today().isoformat()
    start = (pd.Timestamp(end) - pd.Timedelta(days=days)).date().isoformat()
    closes = prices.get_prices(cons["ticker"].tolist(), period="7y")
    alerts = {}
    for t in cons["ticker"]:
        if t not in closes.columns:
            continue
        s = closes[t].dropna()
        last = None
        for a in rules.simulate_alerts(s, start, end, cfg):
            last = rules.next_state(last, a["date"], a["severity"], a["direction"], a["rules"], a["close"], cfg)
        if last:
            alerts[t] = last
    in_cooldown = sum(1 for a in alerts.values() if (pd.Timestamp(end) - pd.Timestamp(a["date"])).days < cfg["repeat_cooldown_days"])
    print(f"{len(alerts)} tickers alerted between {start} and {end}; {in_cooldown} are inside the {cfg['repeat_cooldown_days']} day cooldown")
    if write:
        state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
        state["slow_mover_alerts"] = alerts
        state["seeded"] = {"on": end, "from": start}
        STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {STATE}")
    else:
        print("dry run: state.json untouched")
    return alerts


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    seed(int(args[0]) if args else 180, write="--dry-run" not in sys.argv)
