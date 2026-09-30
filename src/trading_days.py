"""NYSE sessions: which trading day a build should cover, and whether its official close is available."""
from datetime import datetime, timezone

import pandas as pd
import pandas_market_calendars as mcal

from src.sources import constituents, fred, prices

ANCHOR = "^GSPC"
MIN_COVERAGE = 0.98  # share of S&P 500 stocks that must have the day's close before an official build
SECOND_SOURCE = "SP500"  # FRED's daily S&P 500 close; Stooq now sits behind a JavaScript browser check
MAX_DIFF = 0.01  # the two closes must agree within 1%


def expected_trading_day(now=None):
    """The last NYSE session whose close is already in the past (as an ISO date)."""
    now = now or datetime.now(timezone.utc)
    nyse = mcal.get_calendar("NYSE")
    sched = nyse.schedule(start_date=(now - pd.Timedelta(days=10)).date(), end_date=now.date())
    closed = sched[sched["market_close"] <= pd.Timestamp(now)]
    if closed.empty:
        raise RuntimeError("no completed NYSE session in the last 10 days")
    return closed.index[-1].date().isoformat()


def next_trading_day(date):
    nyse = mcal.get_calendar("NYSE")
    sched = nyse.schedule(start_date=pd.Timestamp(date) + pd.Timedelta(days=1),
                          end_date=pd.Timestamp(date) + pd.Timedelta(days=10))
    return sched.index[0].date().isoformat()


def close_available(trading_day):
    """(available, detail). True when Yahoo has the anchor's close for the day and FRED's SP500 series agrees.

    Yahoo is the price source for everything else, so its daily bar must exist; FRED is the cross-check.
    """
    detail = {}
    d = pd.Timestamp(trading_day)
    try:
        closes = prices.get_prices([ANCHOR], period="5d")
        yahoo = float(closes[ANCHOR].loc[d]) if d in closes.index and pd.notna(closes[ANCHOR].loc[d]) else None
    except Exception as e:  # noqa: BLE001
        yahoo, detail["yahoo_error"] = None, f"{type(e).__name__}: {e}"
    try:
        s = fred.get_series(SECOND_SOURCE, (d - pd.Timedelta(days=10)).date())
        second = float(s.loc[d]) if d in s.index else None
    except Exception as e:  # noqa: BLE001
        second, detail["fred_error"] = None, f"{type(e).__name__}: {e}"
    detail.update({"yahoo": yahoo, "fred": second})
    # Yahoo publishes the index close before the individual stocks. Building then would show the
    # previous day's stock moves, so the whole universe must have the day's close too.
    try:
        tickers = constituents.get_sp500()["ticker"].tolist()
        uni = prices.get_prices(tickers, period="5d")
        have = int(uni.loc[d].notna().sum()) if d in uni.index else 0
        detail["coverage"] = round(have / len(tickers), 3)
    except Exception as e:  # noqa: BLE001
        detail["coverage"], detail["coverage_error"] = 0.0, f"{type(e).__name__}: {e}"
    if yahoo is None:
        return False, detail
    if second is None:
        return False, detail
    if abs(yahoo / second - 1) > MAX_DIFF:
        detail["disagree"] = True
        return False, detail
    if detail["coverage"] < MIN_COVERAGE:
        return False, detail
    return True, detail


def delivery_date(trading_day):
    """The morning the brief for a trading day is read: the next calendar day."""
    return (pd.Timestamp(trading_day) + pd.Timedelta(days=1)).date().isoformat()
