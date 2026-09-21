import pytest

from src.sources import news
from tests.conftest import FIX


def test_parse_google_feed_publisher_and_paywall():
    items = news.parse_google((FIX / "news" / "google_nike.xml").read_text(encoding="utf-8"))
    assert len(items) > 10
    for it in items[:10]:
        assert it["title"] and it["url"].startswith("http") and it["publisher"]
        assert not it["title"].endswith(" - " + it["publisher"])  # publisher suffix stripped
    assert isinstance(items[0]["paywall"], bool)


def test_parse_yahoo_feed_uses_link_domain():
    items = news.parse_yahoo((FIX / "news" / "yahoo_nke.xml").read_text(encoding="utf-8"))
    assert items and all(it["publisher"] and "." in it["publisher"] for it in items)


def test_paywall_domains():
    assert news.is_paywall("bloomberg.com") and news.is_paywall("www.wsj.com"[4:]) and news.is_paywall("markets.ft.com")
    assert not news.is_paywall("reuters.com")


def test_dedupe_and_limit():
    a = {"title": "Nike shares fall!", "url": "u1", "publisher": "A", "paywall": False, "published": ""}
    b = {"title": "nike shares fall", "url": "u2", "publisher": "B", "paywall": False, "published": ""}
    c = {"title": "Other", "url": "u3", "publisher": "C", "paywall": False, "published": ""}
    assert [x["url"] for x in news.dedupe([a, b, c])] == ["u1", "u3"]


def test_google_first_then_yahoo_fallback(monkeypatch):
    monkeypatch.setattr(news, "DELAY_SECONDS", 0)
    monkeypatch.setattr("src.retry.BACKOFF_SECONDS", 0)
    yahoo = (FIX / "news" / "yahoo_nke.xml").read_text(encoding="utf-8")
    calls = []

    def fake_get(url):
        calls.append(url)
        if "news.google.com" in url:
            raise RuntimeError("google 503")
        return yahoo
    monkeypatch.setattr(news, "_polite_get", fake_get)
    items = news.get_headlines('"Nike" stock', n=3, ticker="NKE")
    assert len(items) == 3 and any("finance.yahoo.com" in u for u in calls)
    assert sum("news.google.com" in u for u in calls) == 3  # retried 3 times before falling back


def test_all_sources_fail_raises(monkeypatch):
    monkeypatch.setattr(news, "DELAY_SECONDS", 0)
    monkeypatch.setattr("src.retry.BACKOFF_SECONDS", 0)

    def boom(url):
        raise RuntimeError("down")
    monkeypatch.setattr(news, "_polite_get", boom)
    with pytest.raises(RuntimeError, match="google.*yahoo"):
        news.get_headlines("x", ticker="X")
