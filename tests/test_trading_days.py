from datetime import datetime, timezone

import pandas as pd

from src import trading_days
from src.sources import fred, prices


def test_expected_trading_day_and_delivery():
    assert trading_days.expected_trading_day(datetime(2026, 9, 22, 19, 0, tzinfo=timezone.utc)) == "2026-09-21"  # before the close
    assert trading_days.expected_trading_day(datetime(2026, 9, 22, 20, 30, tzinfo=timezone.utc)) == "2026-09-22"  # after 16:00 ET
    assert trading_days.expected_trading_day(datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)) == "2026-09-18"   # Sunday -> Friday
    assert trading_days.delivery_date("2026-09-18") == "2026-09-19"
    assert trading_days.next_trading_day("2026-09-18") == "2026-09-21"


STOCKS = ["AAA", "BBB", "CCC", "DDD", "EEE"]
IDX = pd.DatetimeIndex(["2026-09-21", "2026-09-22"])


def _fake_prices(index_close, stocks_with_close=5):
    """Yahoo as seen right after the bell: the index may have its close before the stocks do."""
    def get(tickers, period="5d"):
        data = {}
        for t in tickers:
            if t == "^GSPC":
                data[t] = [7764.70, index_close]
            else:
                data[t] = [10.0, 11.0 if STOCKS.index(t) < stocks_with_close else float("nan")]
        return pd.DataFrame(data, index=IDX)
    return get


def _setup(monkeypatch, index_close=7764.27, stocks_with_close=5, fred_value=7764.64, fred_day="2026-09-22"):
    from src.sources import constituents
    monkeypatch.setattr(constituents, "get_sp500", lambda force=False, cache_path=None: pd.DataFrame({"ticker": STOCKS}))
    monkeypatch.setattr(fred, "get_series", lambda sid, start: pd.Series([fred_value], index=pd.DatetimeIndex([fred_day])))
    monkeypatch.setattr(prices, "get_prices", _fake_prices(index_close, stocks_with_close))


def test_close_available_requires_both_sources_to_agree(monkeypatch):
    _setup(monkeypatch)
    ok, detail = trading_days.close_available("2026-09-22")
    assert ok and detail["yahoo"] == 7764.27 and detail["fred"] == 7764.64 and detail["coverage"] == 1.0
    _setup(monkeypatch, index_close=float("nan"))                                    # Yahoo index not published yet
    assert trading_days.close_available("2026-09-22")[0] is False
    _setup(monkeypatch, index_close=7000.0)                                          # disagreement > 1%
    ok, detail = trading_days.close_available("2026-09-22")
    assert ok is False and detail.get("disagree")
    _setup(monkeypatch, fred_value=7764.70, fred_day="2026-09-21")                   # FRED lacks the day: no cross-check yet
    assert trading_days.close_available("2026-09-22")[0] is False

    def boom(sid, start):
        raise RuntimeError("fred down")
    monkeypatch.setattr(fred, "get_series", boom)
    monkeypatch.setattr("src.retry.BACKOFF_SECONDS", 0)
    ok, detail = trading_days.close_available("2026-09-22")
    assert ok is False and "fred down" in detail["fred_error"]


def test_close_not_available_until_the_stocks_have_closes_too(monkeypatch):
    """The 2026-09-29 bug: the index close was there, the stocks were not, and the brief showed yesterday's moves."""
    _setup(monkeypatch, stocks_with_close=0)
    ok, detail = trading_days.close_available("2026-09-22")
    assert ok is False and detail["yahoo"] == 7764.27 and detail["coverage"] == 0.0
    _setup(monkeypatch, stocks_with_close=4)                                         # 80% is still below the 98% bar
    assert trading_days.close_available("2026-09-22")[0] is False
    _setup(monkeypatch, stocks_with_close=5)
    assert trading_days.close_available("2026-09-22")[0] is True
