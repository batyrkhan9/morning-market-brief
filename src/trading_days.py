"""NYSE sessions: which trading day a build should cover, and whether its official close is available."""
from datetime import datetime, timezone

import pandas as pd
import pandas_market_calendars as mcal

from src.sources import prices, stooq

ANCHOR = "^GSPC"
MAX_DIFF = 0.01  # Yahoo and Stooq closes must agree within 1%


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
    """(available, detail). True when Yahoo has the anchor's close for the day and Stooq agrees."""
    detail = {}
    try:
        closes = prices.get_prices([ANCHOR], period="5d")
        d = pd.Timestamp(trading_day)
        yahoo = float(closes[ANCHOR].loc[d]) if d in closes.index and pd.notna(closes[ANCHOR].loc[d]) else None
    except Exception as e:  # noqa: BLE001
        yahoo, detail["yahoo_error"] = None, f"{type(e).__name__}: {e}"
    try:
        second = stooq.close_on(ANCHOR, trading_day)
    except Exception as e:  # noqa: BLE001
        second, detail["stooq_error"] = None, f"{type(e).__name__}: {e}"
    detail.update({"yahoo": yahoo, "stooq": second})
    if yahoo is None:
        return False, detail
    if second is None:
        return False, detail
    if abs(yahoo / second - 1) > MAX_DIFF:
        detail["disagree"] = True
        return False, detail
    return True, detail


def delivery_date(trading_day):
    """The morning the brief for a trading day is read: the next calendar day."""
    return (pd.Timestamp(trading_day) + pd.Timedelta(days=1)).date().isoformat()
