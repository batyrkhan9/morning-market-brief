"""Run the slow mover alert logic over the whole S&P 500 for the last N years and report alert cards
per day: python -m src.simulate [years=2]. Uses today's constituents (survivorship applies)."""
import sys
import time
from collections import Counter
from datetime import date

import pandas as pd
import yaml

from src import rules
from src.paths import CONFIG
from src.sources import constituents, prices


def main(years=2):
    cfg = yaml.safe_load(open(CONFIG / "thresholds.yaml", encoding="utf-8"))["slow_movers"]
    cons = constituents.get_sp500()
    end = date.today().isoformat()
    start = (pd.Timestamp(end) - pd.DateOffset(years=years)).date().isoformat()
    t0 = time.time()
    closes = prices.get_prices(cons["ticker"].tolist(), period=f"{years + 6}y")  # 5y windows need history before start
    print(f"downloaded {closes.shape[1]} tickers x {closes.shape[0]} days in {time.time() - t0:.0f}s")
    per_day, per_ticker, whys = Counter(), Counter(), Counter()
    t0 = time.time()
    for t in cons["ticker"]:
        if t not in closes.columns:
            continue
        for a in rules.simulate_alerts(closes[t].dropna(), start, end, cfg):
            per_day[a["date"]] += 1
            per_ticker[t] += 1
            whys[a["why"].split(" (")[0]] += 1
    days = pd.Series(per_day)
    trading_days = closes.index[(closes.index >= start) & (closes.index <= end)]
    full = days.reindex([d.date().isoformat() for d in trading_days]).fillna(0)
    print(f"simulated in {time.time() - t0:.0f}s: {int(full.sum())} alerts over {len(full)} trading days "
          f"({start} to {end}), {len(per_ticker)} tickers ever alerted")
    print(f"alerts per day: mean {full.mean():.2f}, median {full.median():.0f}, 90th pct {full.quantile(0.9):.0f}, "
          f"days with >5: {int((full > 5).sum())} ({(full > 5).mean() * 100:.0f}%), days with 0: {int((full == 0).sum())}")
    print("busiest days:")
    for d, n in days.sort_values(ascending=False).head(5).items():
        print(f"  {d}  {int(n)} cards")
    print("why:", dict(whys.most_common()))
    print("most alerted tickers:", per_ticker.most_common(8))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2)
