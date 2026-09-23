"""Message rendering, command validation on the Python side, scoring, and who is due for a send."""
import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from src import inbox, message, scoring, users
from src.main import build_day, new_context
from src.paths import DATA


@pytest.fixture
def day(config, offline_prices, offline_fred, offline_treasury, offline_universe, offline_news, offline_edgar, no_network, monkeypatch, tmp_path):
    monkeypatch.setattr(scoring, "PREDICTIONS", tmp_path / "predictions.json")
    ctx = new_context("2026-09-18", config, {}, weekday=2)
    ctx["schedule"]["start_date"] = "2026-09-14"          # the saved prices end on 2026-09-18; week 1 must cover it
    return build_day("2026-09-18", ctx=ctx)


def test_full_message_fits_and_has_the_parts(day):
    text = message.full_message(day, "en")
    assert len(text) < 4096
    assert "<pre>" in text and "S&P 500" in text and "10-year" in text     # snapshot table
    assert "fast movers" in text and "slow mover alerts" in text and "8-K filings" in text
    assert "Deep dive" in text and "Nike" in text
    assert "https://batyrkhan9.github.io/morning-market-brief/en/" in text
    assert day["date"] == "2026-09-18" and day["delivery_date"] == "2026-09-19"
    for name, txt in message.all_messages(day).items():
        assert name == "full_en.txt" and len(txt) < 4096


def test_message_marks_unofficial_and_failed_sections(day):
    day["unofficial"] = True
    day["sections"]["movers"] = {"error": "boom"}
    text = message.full_message(day, "en")
    assert "unofficial" in text and "movers" in text and "⚠️" in text


def test_inbox_validation_and_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(scoring, "PREDICTIONS", tmp_path / "predictions.json")
    monkeypatch.setattr(inbox, "THESES", tmp_path / "theses")
    sched = tmp_path / "schedule.yaml"
    sched.write_text("start_date: 2026-09-21\nschedule:\n  - {week: 1, ticker: NKE, competitors: []}\nqueue: []\n")
    monkeypatch.setattr(inbox, "SCHEDULE", sched)
    payload = {"items": [
        {"id": "a", "type": "predict", "user": "owner", "ts": "2026-09-22T10:00:00Z",
         "data": {"ticker": "NKE", "direction": "above", "level": 40, "by": "2026-12-31", "reason": "turnaround"}},
        {"id": "b", "type": "predict", "user": "owner", "data": {"ticker": "NKE", "direction": "up", "level": 40, "by": "2026-12-31", "reason": "x"}},
        {"id": "c", "type": "predict", "user": "stranger", "data": {"ticker": "NKE", "direction": "above", "level": 40, "by": "2026-12-31", "reason": "x"}},
        {"id": "d", "type": "thesis", "user": "owner", "ts": "2026-09-22T10:00:00Z", "data": {"ticker": "NKE", "text": "Five sentences about Nike and its turnaround."}},
        {"id": "e", "type": "queue", "user": "owner", "data": {"ticker": "ZTS"}},
        {"id": "f", "type": "queue", "user": "owner", "data": {"ticker": "NKE"}},          # already scheduled: accepted, not duplicated
        {"id": "g", "type": "queue", "user": "owner", "data": {"ticker": "../etc"}},
    ], "languages": {"father": "ru"}}
    state = {}
    applied, rejected = inbox.apply(payload, state, users=[{"id": "owner"}, {"id": "father"}])
    assert applied == ["a", "d", "e", "f"] and rejected == ["b", "c", "g"]
    preds = scoring.load()
    assert len(preds) == 1 and preds[0]["status"] == "open" and preds[0]["user"] == "owner"
    assert "Five sentences" in (tmp_path / "theses" / "NKE.md").read_text()
    assert "ZTS" in sched.read_text() and sched.read_text().count("NKE") == 1
    assert state["languages"] == {"father": "ru"}


def test_scoring_right_wrong_and_open():
    preds = [
        {"id": "1", "ticker": "NKE", "direction": "above", "level": 40, "by": "2026-09-10", "status": "open"},
        {"id": "2", "ticker": "NKE", "direction": "below", "level": 40, "by": "2026-09-10", "status": "open"},
        {"id": "3", "ticker": "SPX", "direction": "above", "level": 7000, "by": "2026-12-31", "status": "open"},
        {"id": "4", "ticker": "US10Y", "direction": "below", "level": 5.0, "by": "2026-09-10", "status": "open"},
    ]
    fake = lambda symbol, date: ({"NKE": (36.0, date), "US10Y": (4.9, date)}[symbol])
    scored = scoring.score(preds, "2026-09-18", fetch=fake)
    assert [p["id"] for p in scored] == ["1", "2", "4"]
    assert preds[0]["status"] == "wrong" and preds[1]["status"] == "right" and preds[3]["status"] == "right"
    assert preds[2]["status"] == "open"                                    # not due yet
    assert scoring.hit_rate(preds) == pytest.approx(2 / 3)
    assert preds[0]["close"] == 36.0 and preds[0]["scored_on"] == "2026-09-18"


def test_scoring_fetch_failure_keeps_prediction_open():
    preds = [{"id": "1", "ticker": "ZZZZ", "direction": "above", "level": 1, "by": "2026-09-10", "status": "open"}]
    def boom(symbol, date):
        raise RuntimeError("no data")
    assert scoring.score(preds, "2026-09-18", fetch=boom) == []
    assert preds[0]["status"] == "open" and "no data" in preds[0]["score_error"]


def test_close_lookup_uses_saved_prices(subset_closes):
    close, on = scoring.close_on_or_before("NKE", "2026-09-13", closes=subset_closes)   # Saturday -> Friday's close
    assert on == "2026-09-11" and close == float(subset_closes["NKE"].loc["2026-09-11"])


def test_due_users_by_local_send_hour(monkeypatch):
    monkeypatch.setenv("USERS", json.dumps([
        {"id": "owner", "chat_id": 1, "mode": "full", "languages": ["en"], "timezone": "America/Los_Angeles", "send_hour": 6, "is_owner": True},
        {"id": "father", "chat_id": 2, "mode": "simple", "languages": ["kk", "ru"], "default_language": "kk", "timezone": "Asia/Almaty", "send_hour": 8},
    ]))
    us = users.load_users()
    now = datetime(2026, 9, 22, 13, 30, tzinfo=timezone.utc)      # 06:30 in LA, 18:30 in Almaty
    assert [u["id"] for u in users.due_users(us, {}, "2026-09-21", now)] == ["owner", "father"]
    assert [u["id"] for u in users.due_users(us, {"sent": {"owner": "2026-09-21"}}, "2026-09-21", now)] == ["father"]
    early = datetime(2026, 9, 22, 12, 30, tzinfo=timezone.utc)    # 05:30 in LA: not yet
    assert [u["id"] for u in users.due_users(us, {}, "2026-09-21", early)] == ["father"]
    sunday = datetime(2026, 9, 20, 13, 30, tzinfo=timezone.utc)
    assert [u["id"] for u in users.due_users(us, {}, "2026-09-18", sunday)] == ["owner"]   # simple mode gets nothing on Sunday
    assert users.language_of(us[1], {"languages": {"father": "ru"}}) == "ru"
    assert users.language_of(us[1], {"languages": {"father": "en"}}) == "kk"               # not enabled: default
