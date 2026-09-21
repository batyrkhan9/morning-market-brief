"""Slow mover rules. Pure functions over a price Series, no network, no state.

A flag means the condition was false on the previous trading day and true on the last one.
The 30 day no-repeat rule lives in state.json and is applied by the section, not here.
"""
import pandas as pd

WINDOWS = {"52w": "365D", "3y": "1096D", "5y": "1826D"}
RULES = ["1y_below", "1y_above", "52w_low", "52w_high", "3y_low", "3y_high", "5y_low", "5y_high", "5y_below"]


def _return_over(s, years):
    """Return vs the last close on or before the same date N years earlier. NaN when history is short."""
    ref = s.reindex(s.index - pd.DateOffset(years=years), method="ffill")
    ref.index = s.index
    return s / ref - 1


def _prior_extreme(s, window, kind):
    """Rolling max/min of the closes strictly before each date over a calendar window.

    NaN until a full window of history exists, so a stock with a short history never
    looks like it is at a 5 year low on its second day of trading.
    """
    roll = s.rolling(window, closed="left")
    out = roll.max() if kind == "max" else roll.min()
    full = s.index >= s.index[0] + pd.Timedelta(window)
    return out.where(full)


def conditions(s, thresholds):
    """DataFrame of booleans, one column per rule, indexed like s (NaN history -> False)."""
    s = s.dropna().astype("float64")
    if s.empty:
        return pd.DataFrame(columns=RULES, dtype=bool)
    t = thresholds
    r1 = _return_over(s, 1)
    r5 = _return_over(s, 5)
    cond = pd.DataFrame(index=s.index)
    cond["1y_below"] = r1 < t["one_year_return_below"]
    cond["1y_above"] = r1 > t["one_year_return_above"]
    cond["5y_below"] = r5 < t["five_year_return_below"]
    for name, window in WINDOWS.items():
        cond[f"{name}_low"] = s < _prior_extreme(s, window, "min")
        cond[f"{name}_high"] = s > _prior_extreme(s, window, "max")
    cond = cond[RULES].fillna(False).astype(bool)
    cond.attrs["ret_1y"] = r1
    cond.attrs["ret_5y"] = r5
    return cond


def crossings(cond):
    """True where a condition is true today and was known false on the previous trading day."""
    prev = cond.shift(1)
    return cond & (prev == False)  # noqa: E712 - NaN previous must not fire


def flags_on(s, date, thresholds):
    """Rule names that fired on `date` (the last trading day). Empty if date has no close."""
    cond = conditions(s, thresholds)
    if cond.empty or pd.Timestamp(date) not in cond.index:
        return []
    x = crossings(cond).loc[pd.Timestamp(date)]
    return [r for r in RULES if bool(x[r])]


def backtest(s, start, end, thresholds):
    """Every (date, rule) that would have fired between start and end inclusive."""
    x = crossings(conditions(s, thresholds))
    x = x[(x.index >= pd.Timestamp(start)) & (x.index <= pd.Timestamp(end))]
    return [(d.date().isoformat(), r) for d, row in x.iterrows() for r in RULES if row[r]]


def current(s, thresholds):
    """Conditions that are true on the last close (for the baseline watchlist), plus the returns."""
    cond = conditions(s, thresholds)
    if cond.empty:
        return [], None, None
    last = cond.iloc[-1]
    r1 = cond.attrs["ret_1y"].iloc[-1]
    r5 = cond.attrs["ret_5y"].iloc[-1]
    return [r for r in RULES if bool(last[r])], (None if pd.isna(r1) else float(r1)), (None if pd.isna(r5) else float(r5))
