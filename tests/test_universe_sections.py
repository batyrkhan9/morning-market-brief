"""Heatmap, fast movers and slow movers from a 30 ticker offline universe, including a news outage."""
from src import render
from src.main import apply_state, build_day, load_state, new_context
from src.sources import news


def _day(config, state=None):
    ctx = new_context("2026-09-21", config, state or {})
    return build_day("2026-09-21", ctx=ctx), ctx


def test_sections_build_from_offline_universe(config, offline_prices, offline_fred, offline_treasury,
                                              offline_universe, offline_news, no_network, tmp_path):
    day, ctx = _day(config)
    assert day["timing"]["tickers"] == 30
    hm, fm, sm = day["sections"]["heatmap"], day["sections"]["movers"], day["sections"]["slow_movers"]
    assert "error" not in hm and len(hm["rows"]) >= 25
    assert "error" not in fm and len(fm["gainers"]) == 5 and len(fm["losers"]) == 5
    assert fm["gainers"][0]["chg_1d"] >= fm["gainers"][-1]["chg_1d"] >= fm["losers"][-1]["chg_1d"] >= fm["losers"][0]["chg_1d"]
    g = fm["gainers"][0]
    assert g["sector_etf"] and g["sector_chg_1d"] is not None      # sector's move for the same day
    assert len(g["headlines"]) == 3 and all(h["publisher"] for h in g["headlines"])
    assert "error" not in sm
    nke = next(f for f in sm["flagged"] if f["ticker"] == "NKE")    # NKE made new lows on 2026-09-18
    assert "52w_low" in nke["rules"] and "5y_low" in nke["rules"]
    assert len(nke["chart"]["dates"]) > 200 and nke["chart"]["stock"][0] == 100.0
    html = render.render_html(day, docs_dir=None)
    assert 'id="heatmap"' in html and "Top gainers" in html and 'id="slow-NKE"' in html


def test_movers_render_when_news_fails(config, offline_prices, offline_fred, offline_treasury,
                                       offline_universe, no_network, monkeypatch):
    monkeypatch.setattr(news, "DELAY_SECONDS", 0)

    def boom(query, n=3, hl="en-US", gl="US", ticker=None):
        raise RuntimeError("rss down (simulated)")
    monkeypatch.setattr(news, "get_headlines", boom)
    day, _ = _day(config)
    fm = day["sections"]["movers"]
    assert "error" not in fm and len(fm["gainers"]) == 5
    assert all(m["headlines"] == [] and "rss down" in m["news_error"] for m in fm["gainers"] + fm["losers"])
    html = render.render_html(day)
    assert "Headlines unavailable" in html and "rss down (simulated)" in html
    assert fm["gainers"][0]["ticker"] in html                      # the movers themselves still render


def test_thirty_day_no_repeat_and_queue(config, offline_prices, offline_fred, offline_treasury,
                                        offline_universe, offline_news, no_network, isolated_state):
    day, ctx = _day(config, state={})
    first = {f["ticker"]: f["rules"] for f in day["sections"]["slow_movers"]["flagged"]}
    assert "NKE" in first
    state = {}
    apply_state(day, state)
    saved = load_state()
    assert saved["slow_mover_alerts"]["NKE|52w_low"] == "2026-09-18"
    sched = (isolated_state / "schedule.yaml").read_text()
    assert "queue:" in sched and "NKE" not in sched.split("queue:")[1]  # NKE already in the schedule
    day2, _ = _day(config, state=saved)                              # same day again: every flag suppressed
    sm2 = day2["sections"]["slow_movers"]
    assert not any(f["ticker"] == "NKE" for f in sm2["flagged"])
    assert any(x["ticker"] == "NKE" and x["rule"] == "52w_low" for x in sm2["suppressed"])


def test_page_builds_when_universe_fails(config, offline_prices, offline_fred, offline_treasury, no_network, monkeypatch):
    from src.sources import constituents

    def boom(force=False, cache_path=None):
        raise RuntimeError("wikipedia down (simulated)")
    monkeypatch.setattr(constituents, "get_sp500", boom)
    day, _ = _day(config)
    for name in ("heatmap", "movers", "slow_movers"):
        assert "wikipedia down" in day["sections"][name]["error"]
    assert "error" not in day["sections"]["snapshot"]
    html = render.render_html(day)
    assert html.count("This section failed to build") == 3
