"""Slow mover rules. Pure functions over a price Series, no network.

A crossing means the condition was false on the previous trading day and true on the last one.
Alerts are per ticker per day: the rules that fired become tags, the ticker's severity is the
highest of them. Inside the cooldown a ticker alerts again only when it reaches a higher
severity in the same direction (escalation).
"""
import pandas as pd


def rule_names(cfg):
    return list(cfg["rules"].keys())


def direction_of(rule_cfg):
    return "up" if rule_cfg["kind"] == "high" or "above" in rule_cfg else "down"


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


def conditions(s, cfg):
    """DataFrame of booleans, one column per rule, indexed like s (NaN history -> False).

    attrs["ret_1y"] and attrs["ret_5y"] carry the return series for display.
    """
    names = rule_names(cfg)
    s = s.dropna().astype("float64")
    if s.empty:
        return pd.DataFrame(columns=names, dtype=bool)
    returns = {}
    cond = pd.DataFrame(index=s.index)
    for name, r in cfg["rules"].items():
        if r["kind"] == "return":
            y = r["years"]
            if y not in returns:
                returns[y] = _return_over(s, y)
            cond[name] = returns[y] < r["below"] if "below" in r else returns[y] > r["above"]
        elif r["kind"] == "low":
            cond[name] = s < _prior_extreme(s, r["window"], "min")
        else:
            cond[name] = s > _prior_extreme(s, r["window"], "max")
    cond = cond[names].fillna(False).astype(bool)
    cond.attrs["ret_1y"] = returns.get(1, _return_over(s, 1))
    cond.attrs["ret_5y"] = returns.get(5, _return_over(s, 5))
    return cond


def crossings(cond):
    """True where a condition is true today and was known false on the previous trading day."""
    prev = cond.shift(1)
    return cond & (prev == False)  # noqa: E712 - NaN previous must not fire


def summarize(fired, cfg):
    """(severity, direction) of a set of fired rules: the most severe rule wins, down beats up on a tie."""
    if not fired:
        return 0, None
    best = max(fired, key=lambda r: (cfg["rules"][r]["severity"], direction_of(cfg["rules"][r]) == "down"))
    return cfg["rules"][best]["severity"], direction_of(cfg["rules"][best])


def should_alert(last, date, severity, direction, price, cfg):
    """Decide whether a ticker alerts today given its last alert {date, severity, direction, price}.

    - no previous alert: alert
    - lower severity than the last alert in the same direction within no_deescalation_days: never
    - cooldown over: alert
    - inside the cooldown: a direction change, an escalation (higher severity), or a price override
      (moved another price_override in the same direction since the last alert price)
    """
    if not last:
        return True, "first"
    days = (pd.Timestamp(date) - pd.Timestamp(last["date"])).days
    same_direction = direction == last.get("direction")
    if same_direction and severity < last.get("severity", 0) and days < cfg["no_deescalation_days"]:
        return False, "lower severity"
    if days >= cfg["repeat_cooldown_days"]:
        return True, "cooldown over"
    if not same_direction:
        return True, "direction change"
    if severity > last.get("severity", 0):
        return True, "escalation"
    last_price = last.get("price")
    if last_price and price:
        moved = price / last_price - 1
        if (direction == "down" and moved <= -cfg["price_override"]) or (direction == "up" and moved >= cfg["price_override"]):
            return True, f"price override ({moved * 100:+.0f}% since last alert)"
    return False, "cooldown"


def next_state(last, date, severity, direction, rules_fired, price, cfg):
    """The state entry after an alert. The first alert of a streak is kept while alerts keep coming
    inside no_deescalation_days, so the ongoing page can show change since the first alert."""
    streak = bool(last and last.get("direction") == direction
                  and (pd.Timestamp(date) - pd.Timestamp(last["date"])).days < cfg["no_deescalation_days"])
    return {"date": str(date)[:10], "severity": severity, "direction": direction, "rules": rules_fired, "price": price,
            "first_date": last["first_date"] if streak and last.get("first_date") else str(date)[:10],
            "first_price": last["first_price"] if streak and last.get("first_price") else price,
            "count": (last.get("count", 1) + 1) if streak else 1}


def flags_on(s, date, cfg):
    """Rule names that fired on `date` (the last trading day). Empty if date has no close."""
    cond = conditions(s, cfg)
    if cond.empty or pd.Timestamp(date) not in cond.index:
        return []
    x = crossings(cond).loc[pd.Timestamp(date)]
    return [r for r in rule_names(cfg) if bool(x[r])]


def backtest(s, start, end, cfg):
    """Every (date, rule) crossing between start and end inclusive, before the cooldown logic."""
    x = crossings(conditions(s, cfg))
    x = x[(x.index >= pd.Timestamp(start)) & (x.index <= pd.Timestamp(end))]
    return [(d.date().isoformat(), r) for d, row in x.iterrows() for r in rule_names(cfg) if row[r]]


def simulate_alerts(s, start, end, cfg, cooldown_days=None):
    """Alerts a live run would have sent: one per ticker-day, after cooldown, escalation, price
    override and the no-de-escalation rule. The state starts empty at `start`."""
    cfg = dict(cfg, repeat_cooldown_days=cfg["repeat_cooldown_days"] if cooldown_days is None else cooldown_days)
    by_date = {}
    for d, r in backtest(s, start, end, cfg):
        by_date.setdefault(d, []).append(r)
    last, alerts = None, []
    for d in sorted(by_date):
        fired = by_date[d]
        sev, direction = summarize(fired, cfg)
        price = float(s.loc[d])
        ok, why = should_alert(last, d, sev, direction, price, cfg)
        if ok:
            alerts.append({"date": d, "rules": fired, "severity": sev, "direction": direction, "close": price, "why": why})
            last = next_state(last, d, sev, direction, fired, price, cfg)
    return alerts


def current(s, cfg):
    """Conditions true on the last close (baseline watchlist), plus the 1y and 5y returns."""
    cond = conditions(s, cfg)
    if cond.empty:
        return [], None, None
    last = cond.iloc[-1]
    r1, r5 = cond.attrs["ret_1y"].iloc[-1], cond.attrs["ret_5y"].iloc[-1]
    return ([r for r in rule_names(cfg) if bool(last[r])],
            None if pd.isna(r1) else float(r1), None if pd.isna(r5) else float(r5))


def at_extremes(closes, as_of, window="365D"):
    """Breadth: tickers whose close on as_of is the lowest / highest of the trailing window (inclusive)."""
    as_of = pd.Timestamp(as_of)
    win = closes[(closes.index > as_of - pd.Timedelta(window)) & (closes.index <= as_of)]
    if win.empty or as_of not in win.index:
        return [], [], 0
    last = win.loc[as_of]
    valid = last.notna() & (win.notna().sum() >= 200)  # need most of a year of data
    lows = [t for t in closes.columns if valid[t] and last[t] <= win[t].min()]
    highs = [t for t in closes.columns if valid[t] and last[t] >= win[t].max()]
    return sorted(lows), sorted(highs), int(valid.sum())
