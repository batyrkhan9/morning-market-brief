import numpy as np
import pandas as pd

from src import rules


def _series(values, start="2015-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=idx, dtype="float64")


def test_flag_fires_only_on_the_crossing_day(thresholds):
    # Flat at 100 for 6 years, then a slide: 100 -> 71 (1y return -29%) -> 69 (-31%) -> 68 (still below).
    n = 252 * 6
    s = _series([100.0] * n + [71.0, 69.0, 68.0])
    d_first_below = s.index[n + 1]
    x = rules.crossings(rules.conditions(s, thresholds))
    assert x.loc[d_first_below, "1y_below"]
    assert not x.loc[s.index[n + 2], "1y_below"]        # still below, but no new crossing
    assert not x.loc[s.index[n], "1y_below"]            # -29% is not below -30%
    assert x.loc[s.index[n], "52w_low"] and x.loc[s.index[n], "5y_low"]  # 71 < 100: new lows
    assert not x.loc[s.index[n + 1], "52w_low"]         # consecutive low: condition already true


def test_short_history_never_flags(thresholds):
    s = _series(np.linspace(100, 40, 120))  # 6 months of steady decline
    cond = rules.conditions(s, thresholds)
    assert not cond.any().any()                          # no 1y/5y return, no full window: nothing fires
    assert rules.flags_on(s, s.index[-1], thresholds) == []


def test_new_high_after_full_window(thresholds):
    s = _series([50.0] * 400 + [51.0, 51.0, 80.0])
    x = rules.crossings(rules.conditions(s, thresholds))
    assert x.loc[s.index[400], "52w_high"]
    assert not x.loc[s.index[401], "52w_high"]           # equal to prior max: not a new high
    assert x.loc[s.index[402], "1y_above"]               # 80/50 = +60%


def test_nke_backtest_matches_saved_history(subset_closes, thresholds):
    s = subset_closes["NKE"].dropna()
    fired = rules.backtest(s, "2025-09-01", "2026-09-18", thresholds)
    assert ("2026-09-18", "52w_low") in fired and ("2026-09-18", "5y_low") in fired
    assert all(not r.endswith("high") and r != "1y_above" for _, r in fired)
