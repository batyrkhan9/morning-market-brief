"""User profiles from the USERS secret (JSON), current languages, and who is due for a send."""
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def load_users():
    raw = os.environ.get("USERS", "").strip()
    if not raw:
        raise RuntimeError("USERS is not set (JSON list of user profiles)")
    users = json.loads(raw)
    for u in users:
        u.setdefault("mode", "full")
        u.setdefault("languages", ["en"])
        u.setdefault("default_language", u["languages"][0])
        u.setdefault("send_hour", 6)
        u.setdefault("timezone", "UTC")
    return users


def language_of(user, state):
    """Current language: the Worker's KV value (synced into state) or the profile default."""
    lang = (state.get("languages") or {}).get(user["id"])
    return lang if lang in user["languages"] else user["default_language"]


def owner(users):
    return next((u for u in users if u.get("is_owner")), None)


def due_users(users, state, edition, now=None):
    """Users whose local time has reached their send hour and who have not received this edition."""
    now = now or datetime.now(timezone.utc)
    sent = state.get("sent", {})
    due = []
    for u in users:
        local = now.astimezone(ZoneInfo(u["timezone"]))
        if local.hour < u["send_hour"]:
            continue
        if sent.get(u["id"]) == edition:
            continue
        if u["mode"] == "simple" and local.weekday() == 6:  # Sunday: nothing for simple mode
            continue
        due.append(u)
    return due
