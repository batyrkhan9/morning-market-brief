"""Rule 5: a broken source never stops the page. Fake a yfinance failure and check the page renders."""
import pytest

from src import render
from src.main import build_day
from src.sources import fred, prices


def _boom(*a, **k):
    raise RuntimeError("yfinance is down (simulated)")


def test_page_builds_when_yfinance_fails(config, offline_fred, no_network, monkeypatch, tmp_path):
    monkeypatch.setattr(prices, "get_prices", _boom)
    day = build_day("2026-09-21", config)

    snap = day["sections"]["snapshot"]
    assert "error" not in snap  # snapshot survives, rates still present
    assert any(e["where"] == "prices" for e in snap["errors"])
    rates = next(g for g in snap["groups"] if g["key"] == "rates_fred")
    assert all("error" not in r for r in rates["rows"])
    assert "yfinance is down" in day["sections"]["sectors"]["error"]

    written = render.write_pages(day, docs_dir=tmp_path)
    html = (tmp_path / "en" / "index.html").read_text()
    assert "yfinance is down (simulated)" in html          # visible note, not silent
    assert "Part of this section failed" in html            # snapshot partial note
    assert "This section failed to build" in html           # sectors note
    assert "DGS10" in html and "bp" in html                 # rates table still rendered
    assert (tmp_path / "index.html").exists()               # root redirect written too
    assert len(written) == 2


def test_page_builds_when_fred_fails(config, offline_prices, no_network, monkeypatch, tmp_path):
    monkeypatch.setattr(fred, "get_series", _boom)
    day = build_day("2026-09-21", config)
    snap = day["sections"]["snapshot"]
    assert any(e["where"] == "rates" for e in snap["errors"])
    assert "error" not in day["sections"]["sectors"]
    html = render.render_html(day)
    assert "^GSPC" in html and "XLK" in html
    assert "no data: RuntimeError: yfinance is down" in html
