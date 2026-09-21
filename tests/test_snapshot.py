import pandas as pd

from src.sections import sectors, snapshot
from tests.conftest import fred_payload


def _row(section, rid):
    for g in section.get("groups", [section]):
        for r in g["rows"]:
            if r["id"] == rid:
                return r
    raise KeyError(rid)


def test_snapshot_matches_hand_computation(config, offline_prices, offline_fred, no_network, fixture_closes):
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


def test_rates_are_in_basis_points_with_their_own_date(config, offline_prices, offline_fred, no_network):
    out = snapshot.build({"config": config})
    r = _row(out, "DGS10")
    assert r["unit"] == "bp"
    obs = [(o["date"], float(o["value"])) for o in fred_payload("DGS10")["observations"] if o["value"] != "."]
    obs = [o for o in obs if o[0] <= out["as_of"]]
    assert r["date"] == obs[-1][0]  # FRED's own (lagging) date, not the trading day
    assert abs(r["chg_1d"] - (obs[-1][1] - obs[-2][1]) * 100) < 1e-9


def test_sectors_ranked_by_one_day_change(config, offline_prices, no_network):
    out = sectors.build({"config": config})
    assert len(out["rows"]) == 11
    chg = [r["chg_1d"] for r in out["rows"]]
    assert chg == sorted(chg, reverse=True)
