"""Section: fast movers. Top N gainers and losers in the S&P 500 by 1 day change, with the sector's
move on the same day and 3 headlines each. (8-K items come in milestone 3.)"""
from src.sections.common import last_on_or_before
from src.sources import news


def headlines_for(name, ticker, n):
    """Headlines for one company. Returns (items, error). Never raises."""
    try:
        return news.get_headlines(f'"{name}" stock', n=n, ticker=ticker), None
    except Exception as e:  # noqa: BLE001
        return [], f"{type(e).__name__}: {e}"


def one_day_moves(u, as_of):
    """{ticker: chg_1d %} for every constituent with two closes up to as_of."""
    closes = u["closes"]
    out = {}
    for t in u["constituents"]["ticker"]:
        if t not in closes.columns:
            continue
        s = closes[t].dropna()
        d0, v0 = last_on_or_before(s, as_of)
        if d0 is None:
            continue
        prev = s[s.index < d0]
        if prev.empty:
            continue
        out[t] = (v0 / float(prev.iloc[-1]) - 1) * 100
    return out


def build(ctx):
    u = ctx["universe"]
    as_of = ctx["as_of"]
    n = ctx["config"]["universe"]["movers_count"]
    per_item = news.settings()["headlines_per_item"]
    gics_to_etf = {s["gics"]: s["ticker"] for s in ctx["config"]["sectors"]}
    sector_moves = ctx.get("sector_moves", {})
    meta = u["constituents"].set_index("ticker")
    moves = one_day_moves(u, as_of)
    ranked = sorted(moves.items(), key=lambda kv: kv[1], reverse=True)
    gainers, losers = ranked[:n], list(reversed(ranked[-n:]))

    def row(t, chg):
        rec = meta.loc[t]
        etf = gics_to_etf.get(rec["sector"])
        items, err = headlines_for(rec["name"], t, per_item)
        return {"ticker": t, "name": rec["name"], "sector": rec["sector"], "chg_1d": chg,
                "sector_etf": etf, "sector_chg_1d": sector_moves.get(etf),
                "headlines": items, "news_error": err,
                "source_url": "https://finance.yahoo.com/quote/" + t}

    return {"as_of": as_of, "gainers": [row(t, c) for t, c in gainers],
            "losers": [row(t, c) for t, c in losers], "universe_size": len(moves)}
