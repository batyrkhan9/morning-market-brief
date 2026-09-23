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
    x = rules.crossings(rules.conditions(s, thresholds))
    assert x.loc[s.index[n + 1], "1y_below_30"]
    assert not x.loc[s.index[n + 2], "1y_below_30"]     # still below, but no new crossing
    assert not x.loc[s.index[n], "1y_below_30"]         # -29% is not below -30%
    assert x.loc[s.index[n], "52w_low"] and x.loc[s.index[n], "5y_low"]  # 71 < 100: new lows
    assert not x.loc[s.index[n + 1], "52w_low"]         # consecutive low: condition already true


def test_short_history_never_flags(thresholds):
    s = _series(np.linspace(100, 40, 120))  # 6 months of steady decline
    cond = rules.conditions(s, thresholds)
    assert not cond.any().any()
    assert rules.flags_on(s, s.index[-1], thresholds) == []


def test_new_high_after_full_window(thresholds):
    s = _series([50.0] * 400 + [51.0, 51.0, 80.0, 160.0])
    x = rules.crossings(rules.conditions(s, thresholds))
    assert x.loc[s.index[400], "52w_high"]
    assert not x.loc[s.index[401], "52w_high"]           # equal to prior max: not a new high
    assert x.loc[s.index[402], "1y_above_50"]            # 80/50 = +60%
    assert x.loc[s.index[403], "1y_above_200"]           # 160/50 = +220%


def test_severity_and_direction(thresholds):
    assert rules.summarize(["52w_low", "1y_below_30"], thresholds) == (1, "down")
    assert rules.summarize(["52w_low", "3y_low", "1y_below_50"], thresholds) == (2, "down")
    assert rules.summarize(["5y_low"], thresholds) == (3, "down")
    assert rules.summarize(["52w_high", "1y_above_100"], thresholds) == (2, "up")
    assert rules.summarize([], thresholds) == (0, None)


def test_cooldown_escalation_price_override_and_no_deescalation(thresholds):
    cfg = thresholds  # cooldown 90, price override 20%, no de-escalation 180
    last = {"date": "2026-01-10", "severity": 2, "direction": "down", "price": 100.0}
    ok = lambda date, sev, direction, price: rules.should_alert(last, date, sev, direction, price, cfg)[0]
    assert rules.should_alert(None, "2026-01-11", 1, "down", 90.0, cfg) == (True, "first")
    assert not ok("2026-02-01", 2, "down", 95.0)          # same severity inside cooldown
    assert ok("2026-02-01", 3, "down", 95.0)              # escalation
    assert ok("2026-02-01", 2, "down", 79.0)              # price override: -21% since last alert price
    assert not ok("2026-02-01", 2, "down", 81.0)          # -19% is not enough
    assert rules.should_alert(last, "2026-02-01", 1, "up", 130.0, cfg) == (True, "direction change")   # inside cooldown
    assert rules.should_alert(last, "2026-05-01", 1, "up", 130.0, cfg) == (True, "cooldown over")      # reversal after cooldown
    assert not ok("2026-04-15", 1, "down", 70.0)          # lower severity within 180 days, even after cooldown and a big move
    assert ok("2026-04-15", 2, "down", 95.0)              # cooldown over (95 days), same severity
    assert ok("2026-07-15", 1, "down", 70.0)              # lower severity allowed after 180 days
    assert not ok("2026-04-09", 2, "down", 95.0)          # 89 days: still inside the cooldown


def test_next_state_tracks_streaks(thresholds):
    a = rules.next_state(None, "2026-01-10", 1, "down", ["52w_low"], 100.0, thresholds)
    assert a["first_date"] == "2026-01-10" and a["first_price"] == 100.0 and a["count"] == 1
    b = rules.next_state(a, "2026-02-20", 3, "down", ["5y_low"], 75.0, thresholds)
    assert b["first_date"] == "2026-01-10" and b["first_price"] == 100.0 and b["count"] == 2 and b["price"] == 75.0
    c = rules.next_state(b, "2026-09-01", 1, "down", ["52w_low"], 60.0, thresholds)   # > 180 days: new streak
    assert c["first_date"] == "2026-09-01" and c["count"] == 1


def test_simulated_alerts_collapse_clusters(thresholds):
    n = 252 * 6
    # new lows on 5 consecutive weeks, then quiet, then a 3 year low escalation two weeks after the first.
    s = _series([100.0] * n + [90, 89, 88, 87, 86, 85, 84, 83, 82, 81] + [81.0] * 30)
    alerts = rules.simulate_alerts(s, s.index[n], s.index[-1], thresholds, cooldown_days=30)
    assert len(alerts) == 1                                # one alert: the rest are same-severity repeats (81/90 = -10%)
    assert alerts[0]["date"] == s.index[n].date().isoformat()


def test_nke_backtest_matches_saved_history(subset_closes, thresholds):
    s = subset_closes["NKE"].dropna()
    fired = rules.backtest(s, "2025-09-01", "2026-09-18", thresholds)
    assert ("2026-09-18", "52w_low") in fired and ("2026-09-18", "5y_low") in fired
    assert all(not r.endswith("high") and "above" not in r for _, r in fired)
    alerts = rules.simulate_alerts(s, "2025-09-01", "2026-09-18", thresholds)
    assert 2 <= len(alerts) <= 6 and all(a["direction"] == "down" for a in alerts)


def test_breadth_at_extremes(subset_closes):
    lows, highs, counted = rules.at_extremes(subset_closes.drop(columns="^GSPC"), "2026-09-18")
    assert "NKE" in lows and "NKE" not in highs and counted >= 25
