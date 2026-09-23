"""Pull the Worker's KV queue (predictions, theses, deep dive queue items, languages) into the repo.
Every item is re-validated here so nothing malformed reaches the files."""
import json
import os
import re
from datetime import datetime, timezone

import requests
import yaml

from src import scoring
from src.paths import CONFIG, DATA
from src.retry import retry

TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
ITEMS = set(scoring.SNAPSHOT_ITEMS) | set(scoring.TREASURY_ITEMS)
THESES = DATA / "theses"
SCHEDULE = CONFIG / "deep_dive_schedule.yaml"


def _auth():
    url = os.environ.get("WORKER_URL", "").rstrip("/")
    secret = os.environ.get("WORKER_SHARED_SECRET", "")
    if not url or not secret:
        raise RuntimeError("WORKER_URL or WORKER_SHARED_SECRET is not set")
    return url, {"Authorization": f"Bearer {secret}"}


def pull():
    url, headers = _auth()
    resp = requests.get(url + "/pull", headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def ack(ids):
    if not ids:
        return
    url, headers = _auth()
    resp = requests.post(url + "/ack", headers=headers, json={"ids": ids}, timeout=30)
    resp.raise_for_status()


def valid_predict(d):
    return (isinstance(d, dict) and (TICKER.match(str(d.get("ticker", ""))) or d.get("ticker") in ITEMS)
            and d.get("direction") in ("above", "below") and isinstance(d.get("level"), (int, float)) and d["level"] > 0
            and re.match(r"^\d{4}-\d{2}-\d{2}$", str(d.get("by", ""))) and isinstance(d.get("reason"), str))


def apply(payload, state, users=None):
    """Write valid items to the repo files. Returns (applied ids, rejected ids)."""
    applied, rejected = [], []
    preds = scoring.load()
    sched = yaml.safe_load(open(SCHEDULE, encoding="utf-8"))
    queue = sched.setdefault("queue", []) or []
    known = {u["id"] for u in (users or [])} or None
    for item in payload.get("items", []):
        d, kind, user = item.get("data") or {}, item.get("type"), item.get("user")
        ok = False
        if known is not None and user not in known:
            ok = False
        elif kind == "predict" and valid_predict(d):
            preds.append({"id": item["id"], "user": user, "ticker": d["ticker"], "direction": d["direction"],
                          "level": float(d["level"]), "by": d["by"], "reason": d["reason"][:500],
                          "created": item.get("ts", datetime.now(timezone.utc).isoformat()), "status": "open"})
            ok = True
        elif kind == "thesis" and TICKER.match(str(d.get("ticker", ""))) and isinstance(d.get("text"), str) and len(d["text"]) >= 20:
            THESES.mkdir(parents=True, exist_ok=True)
            path = THESES / f"{d['ticker']}.md"
            stamp = (item.get("ts") or "")[:10]
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n## {stamp}\n\n{d['text'].strip()}\n")
            ok = True
        elif kind == "queue" and TICKER.match(str(d.get("ticker", ""))):
            if d["ticker"] not in queue and d["ticker"] not in [s["ticker"] for s in sched["schedule"]]:
                queue.append(d["ticker"])
            ok = True
        (applied if ok else rejected).append(item.get("id"))
    scoring.save(preds)
    sched["queue"] = queue
    SCHEDULE.write_text(yaml.safe_dump(sched, sort_keys=False, allow_unicode=True), encoding="utf-8")
    langs = payload.get("languages") or {}
    if langs:
        state.setdefault("languages", {}).update(langs)
    return applied, rejected


def sync(state, users=None):
    """Pull, apply, ack. Returns a summary dict; raises only if the pull itself fails."""
    payload = retry(pull)
    applied, rejected = apply(payload, state, users)
    ack(applied + rejected)
    return {"applied": len(applied), "rejected": len(rejected), "languages": payload.get("languages") or {}}
