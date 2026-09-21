"""Refresh the offline fixtures from the real APIs. Run manually: .venv/bin/python -m tests.make_fixtures"""
import json
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.paths import CONFIG, ROOT
from src.sources import fred, prices

FIX = Path(__file__).parent / "fixtures"
FRED_START = "2024-12-01"


def main():
    load_dotenv(ROOT / ".env")
    cfg = yaml.safe_load(open(CONFIG / "tickers.yaml", encoding="utf-8"))
    (FIX / "fred").mkdir(parents=True, exist_ok=True)
    for item in cfg["snapshot"]["rates_fred"]:
        payload = fred._fetch(item["series"], FRED_START)  # raw response, no key inside
        (FIX / "fred" / f"{item['series']}.json").write_text(json.dumps(payload, indent=1) + "\n")
        print("fred", item["series"], len(payload["observations"]))
    tickers = [i["ticker"] for k in ("us", "world", "other") for i in cfg["snapshot"][k]]
    tickers += [i["ticker"] for i in cfg["sectors"]]
    closes = prices.get_prices(tickers, period="2y")
    (FIX / "prices").mkdir(exist_ok=True)
    closes.to_csv(FIX / "prices" / "closes_2y.csv", float_format="%.6f")
    print("prices", closes.shape, closes.index[0].date(), closes.index[-1].date())


if __name__ == "__main__":
    main()
