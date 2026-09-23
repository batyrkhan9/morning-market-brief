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


def _fake_prices(value):
    idx = pd.DatetimeIndex(["2026-09-21", "2026-09-22"])
    return lambda tickers, period="5d": pd.DataFrame({"^GSPC": [7764.70, value]}, index=idx)


def test_close_available_requires_both_sources_to_agree(monkeypatch):
    monkeypatch.setattr(fred, "get_series", lambda sid, start: pd.Series([7764.64], index=pd.DatetimeIndex(["2026-09-22"])))
    monkeypatch.setattr(prices, "get_prices", _fake_prices(7764.27))
    ok, detail = trading_days.close_available("2026-09-22")
    assert ok and detail["yahoo"] == 7764.27 and detail["fred"] == 7764.64
    monkeypatch.setattr(prices, "get_prices", _fake_prices(float("nan")))            # Yahoo not published yet
    assert trading_days.close_available("2026-09-22")[0] is False
    monkeypatch.setattr(prices, "get_prices", _fake_prices(7000.0))                  # disagreement > 1%
    ok, detail = trading_days.close_available("2026-09-22")
    assert ok is False and detail.get("disagree")
    monkeypatch.setattr(prices, "get_prices", _fake_prices(7764.27))
    monkeypatch.setattr(fred, "get_series", lambda sid, start: pd.Series([7764.70], index=pd.DatetimeIndex(["2026-09-21"])))
    assert trading_days.close_available("2026-09-22")[0] is False                    # FRED lacks the day: no cross-check yet

    def boom(sid, start):
        raise RuntimeError("fred down")
    monkeypatch.setattr(fred, "get_series", boom)
    monkeypatch.setattr("src.retry.BACKOFF_SECONDS", 0)
    ok, detail = trading_days.close_available("2026-09-22")
    assert ok is False and "fred down" in detail["fred_error"]
