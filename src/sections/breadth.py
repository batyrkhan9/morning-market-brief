"""Section: breadth. How many S&P 500 stocks closed at a 52 week low vs high on the last trading day."""
from src import rules


def build(ctx):
    u = ctx["universe"]
    window = ctx["config_thresholds"]["breadth"]["window"]
    closes = u["closes"][[t for t in u["constituents"]["ticker"] if t in u["closes"].columns]]
    lows, highs, counted = rules.at_extremes(closes, ctx["as_of"], window)
    return {"as_of": ctx["as_of"], "lows": lows, "highs": highs, "counted": counted}
