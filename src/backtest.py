"""Backtest the slow mover rules for one ticker: python -m src.backtest NKE 2022-01-01"""
import sys
from datetime import date

import yaml

from src import rules
from src.paths import CONFIG
from src.sources import prices


def main(ticker, start, end=None):
    thresholds = yaml.safe_load(open(CONFIG / "thresholds.yaml", encoding="utf-8"))["slow_movers"]
    end = end or date.today().isoformat()
    closes = prices.get_prices([ticker], period="max")
    s = closes[ticker].dropna()
    print(f"{ticker}: {len(s)} closes from {s.index[0].date()} to {s.index[-1].date()}")
    fired = rules.backtest(s, start, end, thresholds)
    print(f"{len(fired)} flags between {start} and {end}:")
    for d, r in fired:
        print(f"  {d}  {r:<10} close={float(s.loc[d]):.2f}")
    return fired


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
