from src.sources import constituents


def test_parse_wikipedia_table(wikipedia_html):
    df = constituents.parse_html(wikipedia_html)
    assert list(df.columns) == ["ticker", "name", "sector", "cik"]
    assert 495 <= len(df) <= 510
    assert "BRK-B" in set(df["ticker"]) and "BRK.B" not in set(df["ticker"])  # dots to dashes
    assert "BF-B" in set(df["ticker"])
    assert df["cik"].str.len().eq(10).all() and df["cik"].str.isdigit().all()
    assert df.loc[df["ticker"] == "AAPL", "cik"].item() == "0000320193"
    assert df.loc[df["ticker"] == "NKE", "sector"].item() == "Consumer Discretionary"
    assert df["ticker"].is_unique


def test_cache_roundtrip_and_stale_fallback(wikipedia_html, tmp_path, monkeypatch):
    df = constituents.parse_html(wikipedia_html)
    path = tmp_path / "constituents.json"
    constituents.save_cache(df, path)
    again = constituents.get_sp500(cache_path=path)  # fresh cache: no fetch attempted
    assert len(again) == len(df) and "fetched_at" in again.attrs

    def boom():
        raise RuntimeError("wikipedia down")
    monkeypatch.setattr(constituents, "_fetch", boom)
    monkeypatch.setattr("src.retry.BACKOFF_SECONDS", 0)
    stale = constituents.get_sp500(force=True, cache_path=path)
    assert stale.attrs.get("stale") is True and len(stale) == len(df)
