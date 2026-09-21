import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.paths import CONFIG
from src.sources import fred, prices

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
