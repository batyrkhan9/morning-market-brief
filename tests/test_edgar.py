"""EDGAR: acceptance-time pairing, annual facts extraction, 8-K scan, earnings, deep dive, and an outage."""
import json

import pandas as pd
import pytest

from src import facts as F
from src import filings, render
from src.main import build_day, new_context
from src.sections import deep_dive
from src.sources import edgar
from tests.conftest import FIX


def test_trading_day_pairing():
    td = pd.bdate_range("2026-09-14", "2026-09-25")
    assert filings.trading_day_for("2026-09-18T19:59:00.000Z", td) == "2026-09-18"   # 15:59 ET, same day
    assert filings.trading_day_for("2026-09-18T20:01:00.000Z", td) == "2026-09-21"   # 16:01 ET, next trading day
    assert filings.trading_day_for("2026-09-18T11:30:00.000Z", td) == "2026-09-18"   # before the open
    assert filings.trading_day_for("2026-09-19T14:00:00.000Z", td) == "2026-09-21"   # Saturday -> Monday
    assert filings.trading_day_for("2026-09-25T21:00:00.000Z", td) is None            # beyond known days


def test_annual_facts_nke(offline_edgar):
    cands = edgar.settings()["facts"]
    m = F.metrics(offline_edgar["facts"], cands)
    rev = m["revenue"]
    assert rev and len(rev["periods"]) == 10 and all(p.endswith("-05-31") for p in rev["periods"])  # Nike FY ends in May
    by_year = dict(zip([p[:4] for p in rev["periods"]], rev["values"]))
    assert 51.0e9 < by_year["2023"] < 51.5e9 and 51.0e9 < by_year["2024"] < 51.7e9 and 46.0e9 < by_year["2025"] < 46.6e9
    assert len(rev["tags"]) >= 1
    gm = m["gross_margin"]
    assert gm and all(40 < v < 50 for v in gm["values"] if v is not None)
    assert m["shares"] and m["net_income"]


def test_missing_metrics_skip_cleanly():
    bank = {"facts": {"us-gaap": {"NetIncomeLoss": {"units": {"USD": [
        {"start": "2024-01-01", "end": "2024-12-31", "val": 5e9, "fp": "FY", "form": "10-K", "filed": "2025-02-01"}]}}}}}
    m = F.metrics(bank, edgar.settings()["facts"])
    assert m["revenue"] is None and m["gross_margin"] is None and m["operating_margin"] is None
    assert m["net_income"]["values"] == [5e9]


def test_scan_and_earnings_from_saved_submissions(config, offline_prices, offline_fred, offline_treasury,
                                                  offline_universe, offline_news, offline_edgar, no_network):
    ctx = new_context("2026-09-21", config, {})
    day = build_day("2026-09-21", ctx=ctx)
    assert ctx["filings_error"] is None
    scan = ctx["filings_8k"]
    assert scan["as_of"] == "2026-09-18" and scan["errors"] == {}
    for t, hits in scan["by_ticker"].items():
        assert all(h["trading_day"] == "2026-09-18" for h in hits)
    er = day["sections"]["earnings"]
    assert "error" not in er
    for r in er["rows"]:
        assert any(i["code"] == "2.02" for i in r["items"]) and r["exhibit_url"].startswith("https://www.sec.gov/")
    fm = day["sections"]["movers"]
    assert all(m["filings_error"] is None for m in fm["gainers"] + fm["losers"])
    html = render.render_html(day)
    assert "Earnings" in html


def test_deep_dive_chunks_offline(config, offline_prices, offline_fred, offline_treasury, offline_universe,
                                  offline_news, offline_edgar, no_network, monkeypatch, tmp_path):
    for weekday, chunk in [(1, "business"), (2, "numbers"), (3, "competitors"), (4, "earnings_release"), (5, "risk_factors"), (6, "mdna")]:
        ctx = new_context("2026-09-21", config, {}, weekday=weekday)
        day = build_day("2026-09-21", ctx=ctx)
        dd = day["sections"]["deep_dive"]
        assert "error" not in dd, dd
        assert dd["week"] == 1 and dd["ticker"] == "NKE" and dd["chunk"] == chunk
        d = dd["data"]
        if chunk == "numbers":
            assert d["metrics"]["revenue"] and d["price"]
        elif chunk == "competitors":
            rows = {r["ticker"]: r for r in d["table"]}
            assert rows["NKE"]["files_10k"] and rows["NKE"]["revenue_growth"] is not None
            assert not rows["ADDYY"]["files_10k"] and "price chart only" in rows["ADDYY"]["note"]   # foreign competitor
            assert "NKE" in d["chart"]                                                       # ADDYY has no saved prices
        elif chunk == "earnings_release":
            assert d["text"] and "ex991" in d["exhibit_url"]
        elif chunk in ("business", "risk_factors", "mdna"):
            item = {"business": "1", "risk_factors": "1A", "mdna": "7"}[chunk]
            if d["text"]:
                assert d["filing"]["url"].startswith("https://www.sec.gov/")
            else:
                assert any(e["where"] == f"10-K item {item}" for e in dd["errors"])   # link plus note on failure
        written = render.write_pages(day, docs_dir=tmp_path)
        assert (tmp_path / "en" / "deep-dive" / "2026-09-21.html").exists()
        page = (tmp_path / "en" / "deep-dive" / "2026-09-21.html").read_text()
        assert "NIKE" in page.upper() and "Week 1" in page


def test_rest_of_brief_renders_when_edgar_is_down(config, offline_prices, offline_fred, offline_treasury,
                                                  offline_universe, offline_news, no_network, monkeypatch, tmp_path):
    def boom(url, as_json=True):
        raise RuntimeError("EDGAR 503 (simulated)")
    monkeypatch.setenv("EDGAR_CONTACT_EMAIL", "test@example.com")
    monkeypatch.setattr(edgar, "cached_get", boom)
    monkeypatch.setattr("src.retry.BACKOFF_SECONDS", 0)
    ctx = new_context("2026-09-21", config, {}, weekday=2)
    day = build_day("2026-09-21", ctx=ctx)
    assert "EDGAR 503" in ctx["filings_error"]
    assert "EDGAR 503" in day["sections"]["earnings"]["error"]
    fm = day["sections"]["movers"]
    assert "error" not in fm and len(fm["gainers"]) == 5
    assert all("EDGAR 503" in m["filings_error"] for m in fm["gainers"])
    dd = day["sections"]["deep_dive"]
    assert "error" not in dd and dd["data"]["metrics"] is None and any("EDGAR 503" in e["message"] for e in dd["errors"])
    assert dd["data"]["price"]                                            # price chart still there
    for name in ("snapshot", "sectors", "heatmap", "slow_movers"):
        assert "error" not in day["sections"][name]
    written = render.write_pages(day, docs_dir=tmp_path)
    html = (tmp_path / "en" / "index.html").read_text()
    assert "EDGAR 503 (simulated)" in html and "Top gainers" in html and "Deep dive" in html


def test_missing_contact_email_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("EDGAR_CONTACT_EMAIL", raising=False)
    with pytest.raises(RuntimeError, match="EDGAR_CONTACT_EMAIL"):
        edgar.headers()


def test_html_to_text():
    html = "<html><style>p{}</style><body><p>Revenue &amp; margin</p><div>Second&nbsp;line</div></body></html>"
    assert edgar.html_to_text(html) == "Revenue & margin\n\nSecond line"


def test_rotation_reads_schedule():
    sched = {"start_date": "2026-09-21", "schedule": [{"ticker": "NKE"}, {"ticker": "NVDA"}], "queue": ["ZTS"]}
    assert deep_dive.week_entry(sched, "2026-09-27")[0] == 1
    assert deep_dive.week_entry(sched, "2026-09-28")[1]["ticker"] == "NVDA"
    assert deep_dive.week_entry(sched, "2026-10-05")[1]["ticker"] == "ZTS"
    with pytest.raises(RuntimeError):
        deep_dive.week_entry(sched, "2026-10-12")
    assert [deep_dive.chunk_for(i) for i in range(7)] == ["macro", "business", "numbers", "competitors", "earnings_release", "risk_factors", "mdna"]
