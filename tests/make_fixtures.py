"""Refresh the offline fixtures from the real APIs. Run manually: .venv/bin/python -m tests.make_fixtures"""
import json
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.paths import CONFIG, ROOT
from src.sources import fred, prices, treasury

FIX = Path(__file__).parent / "fixtures"
FRED_START = "2024-12-01"


def main():
    load_dotenv(ROOT / ".env")
    cfg = yaml.safe_load(open(CONFIG / "tickers.yaml", encoding="utf-8"))
    (FIX / "fred").mkdir(parents=True, exist_ok=True)
    for item in cfg["snapshot"]["rates"]:
        payload = fred._fetch(item["fred"], FRED_START)  # raw response, no key inside
        (FIX / "fred" / f"{item['fred']}.json").write_text(json.dumps(payload, indent=1) + "\n")
        print("fred", item["fred"], len(payload["observations"]))
    (FIX / "treasury").mkdir(exist_ok=True)
    for year in (2025, 2026):
        text = treasury._fetch_year(year)
        (FIX / "treasury" / f"{year}.csv").write_text(text)
        print("treasury", year, text.count("\n"), "lines")
    tickers = []
    for k in ("us", "world", "other"):
        for i in cfg["snapshot"][k]:
            tickers.append(i["ticker"])
            if i.get("fallback"):
                tickers.append(i["fallback"])
    tickers += [i["ticker"] for i in cfg["sectors"]]
    closes = prices.get_prices(tickers, period="2y")
    (FIX / "prices").mkdir(exist_ok=True)
    closes.to_csv(FIX / "prices" / "closes_2y.csv", float_format="%.6f")
    print("prices", closes.shape, closes.index[0].date(), closes.index[-1].date())


if __name__ == "__main__" and not {"m2", "m3"} & set(__import__("sys").argv):
    main()


SUBSET = ["AAPL", "MSFT", "NVDA", "NKE", "JPM", "XOM", "LLY", "GOOGL", "CAT", "COST", "NEE", "PLD", "LIN",
          "BRK-B", "META", "AMZN", "TSLA", "UNH", "HD", "PG", "KO", "PFE", "INTC", "BA", "DIS", "GEV", "SOLV", "KVUE", "HOOD", "CEG"]


def milestone2():
    """Wikipedia HTML (gzipped), Google and Yahoo RSS for Nike, a 30 ticker subset of the 6 year download, caps."""
    import gzip
    from src.sources import constituents, news, prices
    (FIX / "constituents").mkdir(parents=True, exist_ok=True)
    html = constituents._fetch()
    with gzip.open(FIX / "constituents" / "wikipedia_sp500.html.gz", "wt", encoding="utf-8") as f:
        f.write(html)
    print("wikipedia", len(html), "chars")
    (FIX / "news").mkdir(exist_ok=True)
    (FIX / "news" / "google_nike.xml").write_text(news._polite_get(news.google_url('"Nike" stock')), encoding="utf-8")
    (FIX / "news" / "yahoo_nke.xml").write_text(news._polite_get(news.yahoo_url("NKE")), encoding="utf-8")
    print("rss saved")
    closes = prices.get_prices(SUBSET + ["^GSPC"], period="6y")
    (FIX / "prices").mkdir(exist_ok=True)
    closes.to_csv(FIX / "prices" / "subset_6y.csv", float_format="%.4f")
    print("subset prices", closes.shape)
    caps = prices.get_market_caps(SUBSET)
    (FIX / "market_caps_subset.json").write_text(json.dumps(caps, indent=1) + "\n")
    print("caps", sum(1 for v in caps.values() if v), "of", len(caps))


if __name__ == "__main__" and "m2" in __import__("sys").argv:
    milestone2()


def milestone3():
    """EDGAR: submissions for the 30 ticker subset (trimmed to recent 8-Ks and 10-Ks), NKE company facts
    trimmed to the candidate tags, NKE 10-K sections (first 3000 chars each), NKE press release text."""
    from src.sources import constituents, edgar
    load_dotenv(ROOT / ".env")
    cons = constituents.get_sp500()
    cons = cons[cons["ticker"].isin(SUBSET)]
    (FIX / "edgar" / "submissions").mkdir(parents=True, exist_ok=True)
    keep_forms = {"8-K", "8-K/A", "10-K", "10-K/A"}
    for rec in cons.to_dict(orient="records"):
        sub = edgar.get_submissions(rec["cik"])
        rec_f = sub["filings"]["recent"]
        n = len(rec_f["accessionNumber"])
        idx = [i for i in range(n) if rec_f["form"][i] in keep_forms][:60]
        trimmed = {k: [v[i] for i in idx] for k, v in rec_f.items() if isinstance(v, list) and len(v) == n}
        payload = {"cik": sub["cik"], "name": sub["name"], "tickers": sub.get("tickers"),
                   "filings": {"recent": trimmed}}
        (FIX / "edgar" / "submissions" / f"{rec['ticker']}.json").write_text(json.dumps(payload, indent=0) + "\n")
    print("submissions", len(cons))
    nke_cik = cons.loc[cons["ticker"] == "NKE", "cik"].item()
    facts = edgar.get_company_facts(nke_cik)
    cands = {t for tags in edgar.settings()["facts"].values() for t in tags}
    trimmed = {"cik": facts["cik"], "entityName": facts["entityName"], "facts": {"us-gaap": {}, "dei": {}}}
    for tax in ("us-gaap", "dei"):
        for tag, entry in facts["facts"].get(tax, {}).items():
            if tag in cands or ("dei:" + tag) in cands:
                trimmed["facts"][tax][tag] = entry
    (FIX / "edgar" / "companyfacts_NKE.json").write_text(json.dumps(trimmed, indent=0) + "\n")
    print("companyfacts NKE tags", {k: len(v) for k, v in trimmed["facts"].items()})
    secs = edgar.get_10k_sections(nke_cik)
    secs["sections"] = {k: (v[:3000] if v else None) for k, v in secs["sections"].items()}
    (FIX / "edgar" / "tenk_sections_NKE.json").write_text(json.dumps(secs, indent=1) + "\n")
    print("10-K sections NKE", {k: len(v or "") for k, v in secs["sections"].items()}, secs["errors"])
    latest = next(f for f in edgar.get_recent_filings(nke_cik, forms=("8-K",)) if "2.02" in f["items"])
    url = edgar.get_exhibit_url(nke_cik, latest["accessionNumber"])
    text = edgar.get_document_text(url)[:5000]
    (FIX / "edgar" / "press_release_NKE.json").write_text(json.dumps({"url": url, "text": text}, indent=1) + "\n")
    print("press release", url, len(text))


if __name__ == "__main__" and "m3" in __import__("sys").argv:
    milestone3()
