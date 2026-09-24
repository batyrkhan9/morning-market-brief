"""User profiles from the Worker's KV store (GET /users), and who is due for a send.

Records: id, chat_id, mode (full|simple), lang (en|kk|ru), tz (IANA), send_hour, paused, created.
"""
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from src.retry import retry

MODES = ("full", "simple")
LANGS = ("en", "kk", "ru")


def _auth():
    url = os.environ.get("WORKER_URL", "").rstrip("/")
    secret = os.environ.get("WORKER_SHARED_SECRET", "")
    if not url or not secret:
        raise RuntimeError("WORKER_URL or WORKER_SHARED_SECRET is not set")
    return url, {"Authorization": f"Bearer {secret}"}


def _fetch_users():
    url, headers = _auth()
    resp = requests.get(url + "/users", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()["users"]


def load_users():
    """Every registered user, validated. Malformed records are skipped, never crash the send."""
    out = []
    for u in retry(_fetch_users):
        if u.get("mode") in MODES and u.get("lang") in LANGS and u.get("tz") and isinstance(u.get("send_hour"), int):
            u.setdefault("paused", False)
            out.append(u)
    return out


def report_send(ok):
    """Tell the Worker about a send for the owner's /stats. Best effort."""
    try:
        url, headers = _auth()
        requests.post(url + "/report", headers=headers, json={"ok": bool(ok)}, timeout=15)
    except Exception:  # noqa: BLE001
        pass


def owner_chat_id():
    v = os.environ.get("OWNER_CHAT_ID", "").strip()
    return int(v) if v else None


def variant_of(user):
    """Which pre-rendered message a user gets: full_en, simple_en, simple_kk, simple_ru."""
    lang = user["lang"] if user["mode"] == "simple" else "en"
    return f"{user['mode']}_{lang}"


def due_users(users, state, edition, now=None):
    """Users whose local time has reached their send hour and who have not received this edition."""
    now = now or datetime.now(timezone.utc)
    sent = state.get("sent", {})
    due = []
    for u in users:
        if u.get("paused"):
            continue
        try:
            local = now.astimezone(ZoneInfo(u["tz"]))
        except Exception:  # noqa: BLE001 - unknown zone: skip, never crash
            continue
        if local.hour < u["send_hour"]:
            continue
        if sent.get(u["id"]) == edition:
            continue
        if u["mode"] == "simple" and local.weekday() == 6:  # Sunday: nothing for simple mode
            continue
        due.append(u)
    return due
