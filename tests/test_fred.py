import pandas as pd

from src.sources import fred
from tests.conftest import fred_payload


class FakeResponse:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def test_get_series_parses_saved_response(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    monkeypatch.setattr(fred.requests, "get", lambda *a, **k: FakeResponse(fred_payload("DGS10")))
    s = fred.get_series("DGS10", "2024-12-01")
    assert isinstance(s, pd.Series)
    assert s.dtype == "float64"
    assert s.name == "DGS10"
    assert s.index.is_monotonic_increasing
    raw = fred_payload("DGS10")["observations"]
    assert len(s) == sum(1 for o in raw if o["value"] != ".")  # '.' rows dropped
    assert s.loc["2026-09-17"] == float(next(o["value"] for o in raw if o["date"] == "2026-09-17"))


def test_get_series_without_key_fails_clearly(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setattr("src.retry.BACKOFF_SECONDS", 0)
    try:
        fred.get_series("DGS10", "2024-12-01")
    except RuntimeError as e:
        assert "FRED_API_KEY" in str(e)
    else:
        raise AssertionError("expected RuntimeError")
