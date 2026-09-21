import pandas as pd

from src.sections import sectors, snapshot
from src.sources import treasury
from tests.conftest import fred_payload


def _row(section, key):
    for g in section.get("groups", [section]):
        for r in g["rows"]:
            if r["key"] == key:
                return r
    raise KeyError(key)


def test_snapshot_matches_hand_computation(config, offline_prices, offline_fred, offline_treasury, no_network, fixture_closes):
    out = snapshot.build({"config": config})
    assert out["errors"] == []
    as_of = pd.Timestamp(out["as_of"])
    # as_of is the S&P 500's last close, even though futures print on later days.
    assert as_of == fixture_closes["^GSPC"].dropna().index[-1]

    spx = fixture_closes["^GSPC"].dropna()
    r = _row(out, "^GSPC")
    assert r["unit"] == "pct"
    assert r["date"] == as_of.date().isoformat()
    assert r["last"] == float(spx.loc[as_of])
    prev = float(spx[spx.index < as_of].iloc[-1])
    assert abs(r["chg_1d"] - (r["last"] / prev - 1) * 100) < 1e-9
    ytd_ref = float(spx[spx.index <= pd.Timestamp(year=as_of.year - 1, month=12, day=31)].iloc[-1])
    assert abs(r["chg_ytd"] - (r["last"] / ytd_ref - 1) * 100) < 1e-9

    # Oil futures: take the value on or before as_of, never the later print.
    oil = _row(out, "CL=F")
    assert pd.Timestamp(oil["date"]) <= as_of


def test_rates_come_from_treasury_same_day_in_basis_points(config, offline_prices, offline_fred, offline_treasury, no_network):
    out = snapshot.build({"config": config})
    assert out["errors"] == []
    r = _row(out, "US10Y")
    assert r["source"] == "treasury" and r["unit"] == "bp"
    curve = treasury.get_yields("2025-01-01")
    curve = curve[curve.index <= out["as_of"]]
    assert r["date"] == curve.index[-1].date().isoformat()
    assert r["last"] == float(curve["10 Yr"].iloc[-1])
    assert abs(r["chg_1d"] - (curve["10 Yr"].iloc[-1] - curve["10 Yr"].iloc[-2]) * 100) < 1e-9
    spread = _row(out, "US10Y2Y")
    assert abs(spread["last"] - (curve["10 Yr"].iloc[-1] - curve["2 Yr"].iloc[-1])) < 1e-9
    hy = _row(out, "HY")
    assert hy["source"] == "fred" and hy["id"] == "BAMLH0A0HYM2"
    obs = [(o["date"], float(o["value"])) for o in fred_payload("BAMLH0A0HYM2")["observations"] if o["value"] != "."]
    obs = [o for o in obs if o[0] <= out["as_of"]]
    assert hy["date"] == obs[-1][0]  # FRED's own (lagging) date is shown
    assert abs(hy["chg_1d"] - (obs[-1][1] - obs[-2][1]) * 100) < 1e-9


def test_rates_fall_back_to_fred_when_treasury_fails(config, offline_prices, offline_fred, no_network, monkeypatch):
    def boom(start):
        raise RuntimeError("treasury down (simulated)")
    monkeypatch.setattr(treasury, "get_yields", boom)
    out = snapshot.build({"config": config})
    assert any(e["where"] == "treasury" for e in out["errors"])
    r = _row(out, "US10Y")
    assert r["source"] == "fred" and r["id"] == "DGS10" and "error" not in r
    obs = [(o["date"], float(o["value"])) for o in fred_payload("DGS10")["observations"] if o["value"] != "."]
    obs = [o for o in obs if o[0] <= out["as_of"]]
    assert r["date"] == obs[-1][0]
    assert abs(r["chg_1d"] - (obs[-1][1] - obs[-2][1]) * 100) < 1e-9


def test_stale_close_uses_fallback_ticker(config, offline_prices, offline_fred, offline_treasury, no_network, fixture_closes):
    out = snapshot.build({"config": config})
    as_of = pd.Timestamp(out["as_of"])
    dxy = fixture_closes["DX-Y.NYB"].dropna()
    dxy = dxy[dxy.index <= as_of]
    assert dxy.iloc[-1] == dxy.iloc[-2]  # the saved response really is stale
    r = _row(out, "DX-Y.NYB")
    assert r["id"] == "UUP" and "stale" in r["note"] and not r["stale"]
    assert r["last"] == float(fixture_closes["UUP"].dropna().loc[as_of])


def test_stale_without_fallback_is_marked(config, offline_prices, offline_fred, offline_treasury, no_network, monkeypatch):
    items = [dict(i, fallback=None) for i in config["snapshot"]["other"]]
    config["snapshot"]["other"] = items
    out = snapshot.build({"config": config})
    r = _row(out, "DX-Y.NYB")
    assert r["stale"] is True and r["id"] == "DX-Y.NYB"
    html = __import__("src.render", fromlist=["render_html"]).render_html(
        {"date": "x", "as_of": out["as_of"], "built_at": "x",
         "sections": {"snapshot": out, "sectors": {"error": "skip"}, "heatmap": {"error": "skip"},
                      "movers": {"error": "skip"}, "slow_movers": {"error": "skip"}}}
    )
    assert ">stale<" in html and "+0.00%" not in html


def test_sectors_ranked_by_one_day_change(config, offline_prices, no_network):
    out = sectors.build({"config": config})
    assert len(out["rows"]) == 11
    chg = [r["chg_1d"] for r in out["rows"]]
    assert chg == sorted(chg, reverse=True)
