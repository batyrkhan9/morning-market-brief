"""Backtest the slow mover rules for one ticker: python -m src.backtest NKE 2022-01-01 [END]

Prints every raw crossing, then the alerts a live run would have sent under the per-ticker
cooldown with escalation, for the configured cooldown and for 90 days.
"""
import sys
from datetime import date

import yaml

from src import rules
from src.paths import CONFIG
from src.sources import prices


def main(ticker, start, end=None):
    cfg = yaml.safe_load(open(CONFIG / "thresholds.yaml", encoding="utf-8"))["slow_movers"]
    end = end or date.today().isoformat()
    s = prices.get_prices([ticker], period="max")[ticker].dropna()
    print(f"{ticker}: {len(s)} closes from {s.index[0].date()} to {s.index[-1].date()}")
    fired = rules.backtest(s, start, end, cfg)
    print(f"\n{len(fired)} raw crossings on {len({d for d, _ in fired})} dates between {start} and {end}")
    alerts = rules.simulate_alerts(s, start, end, cfg)
    print(f"\n{len(alerts)} alerts with cooldown {cfg['repeat_cooldown_days']}d, price override "
          f"{cfg['price_override'] * 100:.0f}%, no de-escalation {cfg['no_deescalation_days']}d:")
    for a in alerts:
        print(f"  {a['date']}  sev {a['severity']} {a['direction']:<4} close={a['close']:>8.2f}  "
              f"{', '.join(a['rules']):<45} {a['why']}")
    return fired


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
