"""Shared change math for sections. Pure functions, no network."""
import pandas as pd


def last_on_or_before(s, date):
    s = s.dropna()
    s = s[s.index <= pd.Timestamp(date)]
    if s.empty:
        return None, None
    return s.index[-1], float(s.iloc[-1])


def last_trading_day(closes, anchor=None):
    """Last date with a finished US session.

    Prefer the anchor column's last valid date (e.g. ^GSPC), else the last date where at least
    half of the columns have a value. Futures and FX print on days when US stocks do not.
    """
    if anchor is not None and anchor in closes.columns and not closes[anchor].dropna().empty:
        return closes[anchor].dropna().index[-1]
    counts = closes.notna().sum(axis=1)
    ok = counts[counts >= max(1, closes.shape[1] / 2)]
    if ok.empty:
        raise RuntimeError("no rows with price data")
    return ok.index[-1]


def changes(s, as_of, unit, detect_stale=False):
    """Last value on or before as_of, its date, and 1 day / 1 month / YTD changes.

    unit "pct": changes are percent (0.5 means +0.5%).
    unit "bp": the series is in percent points, changes are basis points (0.03 pp -> 3 bp).
    detect_stale: for instruments that trade daily, an identical close on the last two dates
    means the feed did not update; the row is marked stale instead of showing 0.00%.
    """
    s = s.dropna()
    d0, v0 = last_on_or_before(s, as_of)
    if d0 is None:
        raise RuntimeError(f"no value on or before {pd.Timestamp(as_of).date()}")
    prev = s[s.index < d0]
    v1 = float(prev.iloc[-1]) if not prev.empty else None
    _, vm = last_on_or_before(s, d0 - pd.DateOffset(months=1))
    _, vy = last_on_or_before(s, pd.Timestamp(year=d0.year - 1, month=12, day=31))

    def diff(a, b):
        if b is None:
            return None
        if unit == "bp":
            return (a - b) * 100.0
        return (a / b - 1.0) * 100.0

    return {
        "last": v0,
        "date": d0.date().isoformat(),
        "chg_1d": diff(v0, v1),
        "chg_1m": diff(v0, vm),
        "chg_ytd": diff(v0, vy),
        "unit": unit,
        "stale": bool(detect_stale and v1 is not None and v0 == v1),
    }
