import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.paths import CONFIG
from src.sources import fred, prices, treasury

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def config():
    return yaml.safe_load(open(CONFIG / "tickers.yaml", encoding="utf-8"))


@pytest.fixture
def fixture_closes():
    return pd.read_csv(FIX / "prices" / "closes_2y.csv", index_col="date", parse_dates=True)


def fred_payload(series_id):
    return json.loads((FIX / "fred" / f"{series_id}.json").read_text())


@pytest.fixture
def offline_prices(monkeypatch, fixture_closes):
    """get_prices answers from the saved yfinance closes, no network."""
    monkeypatch.setattr(prices, "get_prices", lambda tickers, period="2y": fixture_closes[list(tickers)].copy())


@pytest.fixture
def offline_fred(monkeypatch):
    """get_series answers from saved FRED responses, no network."""
    monkeypatch.setattr(
        fred, "get_series", lambda sid, start: fred.parse_observations(fred_payload(sid), sid)
    )


@pytest.fixture
def no_network(monkeypatch):
    """Any real HTTP or yfinance call fails loudly so tests cannot silently go online."""
    import requests
    import yfinance

    def boom(*a, **k):
        raise AssertionError("network call attempted in an offline test")

    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(yfinance, "download", boom)


@pytest.fixture
def offline_treasury(monkeypatch):
    """get_yields answers from saved Treasury CSVs, no network."""
    def fake(start):
        frames = [treasury.parse_csv((FIX / "treasury" / f"{y}.csv").read_text()) for y in (2025, 2026)]
        df = pd.concat(frames).sort_index()
        return df[df.index >= pd.Timestamp(start)]
    monkeypatch.setattr(treasury, "get_yields", fake)


SUBSET_TICKERS = ["AAPL", "MSFT", "NVDA", "NKE", "JPM", "XOM", "LLY", "GOOGL", "CAT", "COST", "NEE", "PLD", "LIN",
                  "BRK-B", "META", "AMZN", "TSLA", "UNH", "HD", "PG", "KO", "PFE", "INTC", "BA", "DIS", "GEV", "SOLV",
                  "KVUE", "HOOD", "CEG"]


@pytest.fixture
def thresholds():
    return yaml.safe_load(open(CONFIG / "thresholds.yaml", encoding="utf-8"))["slow_movers"]


@pytest.fixture
def wikipedia_html():
    import gzip
    with gzip.open(FIX / "constituents" / "wikipedia_sp500.html.gz", "rt", encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def subset_closes():
    return pd.read_csv(FIX / "prices" / "subset_6y.csv", index_col="date", parse_dates=True)


@pytest.fixture
def offline_universe(monkeypatch, wikipedia_html, subset_closes, fixture_closes, tmp_path):
    """A 30 ticker S&P 500 universe from saved responses: constituents, closes, caps. No network.

    get_prices serves the 6 year subset for constituents and the 2 year snapshot/sector fixture for the rest.
    """
    from src import universe
    from src.sources import constituents, prices
    cons = constituents.parse_html(wikipedia_html)
    cons = cons[cons["ticker"].isin(SUBSET_TICKERS)].reset_index(drop=True)
    caps = json.loads((FIX / "market_caps_subset.json").read_text())

    def fake_prices(tickers, period="2y"):
        cols = [subset_closes[t] if t in subset_closes.columns else fixture_closes[t] for t in tickers]
        return pd.concat(cols, axis=1).sort_index()
    monkeypatch.setattr(constituents, "get_sp500", lambda force=False, cache_path=None: cons)
    monkeypatch.setattr(prices, "get_prices", fake_prices)
    monkeypatch.setattr(prices, "get_market_caps", lambda tickers, pause=0: {t: caps.get(t) for t in tickers})
    monkeypatch.setattr(universe, "CAPS_CACHE", tmp_path / "market_caps.json")
    return {"constituents": cons, "closes": subset_closes, "caps": caps}


@pytest.fixture
def offline_news(monkeypatch):
    """Google RSS answers from the saved Nike feed for every query, no delays."""
    from src.sources import news
    monkeypatch.setattr(news, "DELAY_SECONDS", 0)
    google = (FIX / "news" / "google_nike.xml").read_text(encoding="utf-8")
    monkeypatch.setattr(news, "_polite_get", lambda url: google)


@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    from src import main
    monkeypatch.setattr(main, "STATE", tmp_path / "state.json")
    sched = tmp_path / "schedule.yaml"
    sched.write_text("schedule:\n  - {week: 1, ticker: NKE, competitors: []}\nqueue: []\n")
    monkeypatch.setattr(main, "SCHEDULE", sched)
    return tmp_path


@pytest.fixture
def offline_edgar(monkeypatch):
    """EDGAR answers from saved responses: submissions per subset ticker, NKE facts, sections, press release."""
    from src.sources import edgar
    monkeypatch.setenv("EDGAR_CONTACT_EMAIL", "test@example.com")
    subs = {}
    for f in (FIX / "edgar" / "submissions").glob("*.json"):
        payload = json.loads(f.read_text())
        subs[str(int(payload["cik"])).zfill(10)] = payload
    facts = json.loads((FIX / "edgar" / "companyfacts_NKE.json").read_text())
    sections = json.loads((FIX / "edgar" / "tenk_sections_NKE.json").read_text())
    press = json.loads((FIX / "edgar" / "press_release_NKE.json").read_text())

    subs["0001000045"] = {"cik": "1000045", "name": "ADIDAS AG", "filings": {"recent": {   # foreign filer: 20-F only
        "accessionNumber": ["0001000045-26-000001"], "filingDate": ["2026-03-10"], "reportDate": ["2025-12-31"],
        "acceptanceDateTime": ["2026-03-10T10:00:00.000Z"], "form": ["20-F"], "primaryDocument": ["adidas20f.htm"],
        "primaryDocDescription": ["20-F"], "items": [""]}}}

    def fake_get(url, as_json=True):
        if "/submissions/CIK" in url:
            cik = url.split("CIK")[1][:10]
            if cik in subs:
                return subs[cik]
            raise RuntimeError("404 no saved submissions for " + cik)
        if "/companyfacts/CIK" in url:
            if url.split("CIK")[1][:10] == str(int(facts["cik"])).zfill(10):
                return facts
            raise RuntimeError("404 no saved facts")
        if url.endswith("/index.json"):
            return {"directory": {"item": [{"name": "nke-ex991.htm"}, {"name": "form8k.htm"}]}}
        if url == press["url"] or "ex991" in url:
            return "<html><body>" + "".join(f"<p>{p}</p>" for p in press["text"].split("\n\n")) + "</body></html>"
        if url.endswith("company_tickers.json"):
            return {"0": {"cik_str": int(facts["cik"]), "ticker": "NKE", "title": "NIKE, Inc."},
                    "1": {"cik_str": 1000045, "ticker": "ADDYY", "title": "ADIDAS AG"}}
        raise RuntimeError("no fixture for " + url)
    monkeypatch.setattr(edgar, "cached_get", fake_get)
    monkeypatch.setattr(edgar, "get_10k_sections", lambda cik, items=("1", "1A", "7"): {
        "filing": sections["filing"], "sections": {i: sections["sections"].get(i) for i in items},
        "errors": {i: sections["errors"][i] for i in items if i in sections["errors"]}})
    return {"submissions": subs, "facts": facts, "sections": sections, "press": press}
