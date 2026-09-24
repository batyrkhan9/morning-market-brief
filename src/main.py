"""Entry point. Supports --dry-run, --date YYYY-MM-DD and --baseline."""
import argparse
import json
import time
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

from src import filings, i18n, inbox, message, render, sections, telegram, trading_days, universe, users as users_mod
from src.paths import CONFIG, DATA, DOCS, ROOT
from src.sections import (baseline, breadth, deep_dive, earnings, heatmap, movers, ongoing, prediction, sectors,
                          slow_movers, snapshot)
from src.sources import prices

STATE = DATA / "state.json"
SCHEDULE = CONFIG / "deep_dive_schedule.yaml"


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config():
    return load_yaml(CONFIG / "tickers.yaml")


def load_state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def new_context(date_str, config=None, state=None, weekday=None, unofficial=False, dry_run=True):
    """date_str is the trading day the edition covers (editions are keyed by trading day, not run date)."""
    return {"config": config or load_config(), "config_thresholds": load_yaml(CONFIG / "thresholds.yaml"),
            "schedule": load_yaml(SCHEDULE), "state": state if state is not None else {}, "date": date_str,
            "expected_trading_day": date_str, "weekday": weekday, "unofficial": unofficial, "dry_run": dry_run}


def scan_filings(ctx):
    """8-K scan for every constituent. A failure is reported on the sections that use it, not raised."""
    ctx["filings_8k"], ctx["filings_error"] = None, None
    if ctx.get("universe") is None:
        ctx["filings_error"] = "universe unavailable"
        return
    try:
        u = ctx["universe"]
        ctx["filings_8k"] = filings.scan_8k(u["constituents"], u["closes"].index, ctx["as_of"])
    except Exception as e:  # noqa: BLE001
        ctx["filings_error"] = f"{type(e).__name__}: {e}"


def load_universe(ctx):
    """One batched fetch shared by heatmap, movers and slow movers. A failure is reported, not raised."""
    try:
        ctx["universe"] = universe.load(ctx["config"])
        ctx["universe_error"] = None
        return ctx["universe"]["timing"]
    except Exception as e:  # noqa: BLE001
        ctx["universe"] = None
        ctx["universe_error"] = f"{type(e).__name__}: {e}"
        return {}


def needs_universe(build_fn):
    def wrapped(ctx):
        if ctx.get("universe") is None:
            raise RuntimeError("universe unavailable: " + (ctx.get("universe_error") or "unknown"))
        if not ctx.get("as_of"):
            from src.sections.common import last_trading_day
            ctx["as_of"] = last_trading_day(ctx["universe"]["closes"], anchor=ctx["universe"]["benchmark"]).date().isoformat()
        return build_fn(ctx)
    return wrapped


def build_day(date_str, config=None, state=None, ctx=None):
    """Fetch every source and build the day's JSON. Never raises for a single section (rule 5)."""
    ctx = ctx or new_context(date_str, config, state)
    now = datetime.now(timezone.utc)
    day = {"date": date_str, "built_at": now.strftime("%Y-%m-%d %H:%M UTC"), "built_at_iso": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "as_of": None, "unofficial": bool(ctx.get("unofficial")), "sections": {}, "timing": {}}
    day["sections"]["snapshot"] = sections.run(snapshot.build, ctx)
    day["sections"]["sectors"] = sections.run(sectors.build, ctx)
    sec = day["sections"]["sectors"]
    ctx["sector_moves"] = {r["key"]: r.get("chg_1d") for r in sec.get("rows", [])}
    day["timing"] = load_universe(ctx)
    day["sections"]["breadth"] = sections.run(needs_universe(breadth.build), ctx)
    t0 = time.time()
    if ctx.get("universe") is not None and not ctx.get("as_of"):
        from src.sections.common import last_trading_day
        ctx["as_of"] = last_trading_day(ctx["universe"]["closes"], anchor=ctx["universe"]["benchmark"]).date().isoformat()
    scan_filings(ctx)
    day["timing"]["filings_s"] = round(time.time() - t0, 1)
    day["sections"]["earnings"] = sections.run(needs_universe(earnings.build), ctx)
    day["sections"]["heatmap"] = sections.run(needs_universe(heatmap.build), ctx)
    day["sections"]["movers"] = sections.run(needs_universe(movers.build), ctx)
    day["sections"]["slow_movers"] = sections.run(needs_universe(slow_movers.build), ctx)
    ctx["new_alerts_today"] = day["sections"]["slow_movers"].get("new_alerts", {})
    day["sections"]["ongoing"] = sections.run(needs_universe(ongoing.build), ctx)
    day["sections"]["deep_dive"] = sections.run(needs_universe(deep_dive.build), ctx)
    day["sections"]["prediction"] = sections.run(prediction.build, ctx) if ctx.get("as_of") else {"error": "no trading day"}
    day["as_of"] = ctx.get("as_of") or sec.get("as_of")
    if day["as_of"] and day["as_of"] != day["date"]:
        day["date"] = day["as_of"]  # the edition is keyed by the trading day actually covered
    day["delivery_date"] = trading_days.delivery_date(day["date"]) if day["date"] else None
    return day


def apply_state(day, state):
    """Record each ticker's last alert (cooldown and escalation) and queue alerted tickers for the deep dive."""
    sm = day["sections"].get("slow_movers", {})
    if "error" in sm:
        return
    state.setdefault("slow_mover_alerts", {}).update(sm.get("new_alerts", {}))
    save_state(state)
    sched = load_yaml(SCHEDULE)
    queue = sched.setdefault("queue", []) or []
    for f in sm.get("alerts", []):
        if f["ticker"] not in queue and f["ticker"] not in [s["ticker"] for s in sched["schedule"]]:
            queue.append(f["ticker"])
    sched["queue"] = queue
    SCHEDULE.write_text(yaml.safe_dump(sched, sort_keys=False, allow_unicode=True), encoding="utf-8")


def save_day(day):
    path = DATA / "daily" / f"{day['date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(day, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def write_messages(day):
    """Pre-render every Telegram message variant to docs/messages/<trading day>/ and docs/messages/latest/,
    plus manifest.json (edition, built_at, variants) that the Worker's send cron reads."""
    written = []
    variants = message.all_messages(day)
    built_iso = day.get("built_at_iso")
    if not built_iso and day.get("built_at"):  # editions saved before built_at_iso existed
        built_iso = datetime.strptime(day["built_at"], "%Y-%m-%d %H:%M UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {"edition": day["date"], "built_at": built_iso, "unofficial": bool(day.get("unofficial")),
                "variants": sorted(v[:-4] for v in variants), "heatmap": f"en/heatmap.png?v={day['date']}"}
    for folder in (DOCS / "messages" / day["date"], DOCS / "messages" / "latest"):
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in variants.items():
            (folder / name).write_text(text, encoding="utf-8")
            written.append(folder / name)
        (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        written.append(folder / "manifest.json")
    return written


def alert_owner(text):
    """Telegram message to the owner (OWNER_CHAT_ID). Never raises: alerts are best effort."""
    try:
        chat_id = users_mod.owner_chat_id()
        if chat_id:
            telegram.send_message(chat_id, text[:4000])
            return True
        print("alert skipped: OWNER_CHAT_ID is not set")
    except Exception as e:  # noqa: BLE001
        print(f"alert failed: {type(e).__name__}: {e}")
    return False


def sync_inbox(state):
    """Pull commands and languages from the Worker. A failure is printed, never fatal."""
    try:
        users = users_mod.load_users()
    except Exception:  # noqa: BLE001
        users = None
    try:
        summary = inbox.sync(state, users)
        print(f"Inbox: {summary}")
    except Exception as e:  # noqa: BLE001
        print(f"Inbox sync skipped: {type(e).__name__}: {e}")


def build_and_publish(trading_day, state, dry_run, unofficial=False, weekday=None):
    """Build the edition for a trading day, save JSON, render pages and messages. Returns the day."""
    if unofficial:
        prices.INTRADAY_FILL_DATE = trading_day
    try:
        ctx = new_context(trading_day, state=state, weekday=weekday, unofficial=unofficial, dry_run=dry_run)
        day = build_day(trading_day, ctx=ctx)
    finally:
        prices.INTRADAY_FILL_DATE = None
    path = save_day(day)
    print(f"Saved {path.relative_to(ROOT)}  timing={day['timing']}")
    report(day)
    for p in render.write_pages(day):
        print(f"Wrote {p.relative_to(ROOT)}")
    for p in write_messages(day):
        print(f"Wrote {p.relative_to(ROOT)}")
    state["latest_edition"] = day["date"]
    return day


def report(day):
    for name, sec in day["sections"].items():
        status = "FAILED: " + sec["error"] if "error" in sec else "ok"
        if sec.get("errors"):
            status = "partial: " + "; ".join(e["message"] for e in sec["errors"])
        print(f"  {name}: {status}")


def run_scheduled(final=None):
    """One hourly attempt: build the expected trading day once its official close is available.

    Attempts run at 22:30, 23:30, 00:30, 01:30 and 02:30 UTC. The last attempt builds from the last
    intraday bar when the close is still missing, marks everything unofficial and alerts the owner.
    """
    now = datetime.now(timezone.utc)
    trading_day = trading_days.expected_trading_day(now)
    state = load_state()
    built = state.setdefault("built", {})
    if built.get(trading_day, {}).get("official"):
        print(f"{trading_day} already built officially, nothing to do")
        return
    if final is None:
        final = now.hour >= 2 and now.hour < 12
    sync_inbox(state)
    available, detail = trading_days.close_available(trading_day)
    print(f"close for {trading_day}: available={available} {detail}")
    if not available and not final:
        print("official close not available yet, trying again next hour")
        save_state(state)
        return
    if not available and built.get(trading_day):
        print(f"{trading_day} already built unofficially and the close is still missing, nothing to do")
        return
    day = build_and_publish(trading_day, state, dry_run=False, unofficial=not available)
    apply_state(day, state)
    built[trading_day] = {"at": now.strftime("%Y-%m-%d %H:%M UTC"), "official": available}
    save_state(state)
    if not available:
        alert_owner(f"⚠️ Brief for {trading_day} built from intraday bars: the official close was not available "
                    f"by 02:30 UTC ({detail}). All prices are marked unofficial.")


def send_to(user, day, state=None):
    """Send the user's variant. Simple mode is not live yet: those users get the launch note once."""
    variant = users_mod.variant_of(user)
    if user["mode"] == "simple":
        noted = (state or {}).setdefault("soon_note_sent", {})
        if noted.get(user["id"]):
            return "skipped (launch note already sent)"
        telegram.send_message(user["chat_id"], i18n.load(user["lang"])["simple_soon"])
        noted[user["id"]] = day["date"]
        return "sent launch note for"
    text = message.full_message(day, "en")
    telegram.send_message(user["chat_id"], text)
    png = DOCS / "en" / "heatmap.png"
    if png.exists() and "error" not in day["sections"].get("heatmap", {}):
        telegram.send_photo(user["chat_id"], png, caption=f"S&P 500 · {day['date']}")
    return f"sent {variant}"


def load_day(date_str):
    path = DATA / "daily" / f"{date_str}.json"
    if not path.exists():
        raise SystemExit(f"No saved JSON for {date_str} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_baseline():
    ctx = new_context(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    timing = load_universe(ctx)
    base = sections.run(needs_universe(baseline.build), ctx)
    if "error" in base:
        raise SystemExit("baseline failed: " + base["error"])
    out = render.write_baseline(base)
    print(f"Wrote {out.relative_to(ROOT)} (as of {base['as_of']}, timing {timing})")
    for r, rows in base["by_rule"].items():
        print(f"  {r:<10} {len(rows):>3}  {' '.join(x['ticker'] for x in rows[:12])}{' ...' if len(rows) > 12 else ''}")


def main(argv=None):
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Build and send the morning market brief.")
    parser.add_argument("--dry-run", action="store_true", help="build locally, send nothing, do not touch state")
    parser.add_argument("--date", help="rebuild a past day from saved JSON (YYYY-MM-DD)")
    parser.add_argument("--baseline", action="store_true", help="write the one-time baseline watchlist page")
    parser.add_argument("--weekday", type=int, choices=range(7), help="build the deep dive chunk for this weekday (0=Monday)")
    parser.add_argument("--scheduled", action="store_true", help="hourly build attempt: build once the official close is available")
    parser.add_argument("--final", action="store_true", help="with --scheduled: last attempt, build unofficially if needed")
    parser.add_argument("--send-now", metavar="USER_ID", help="send the latest edition to one user immediately (test)")
    args = parser.parse_args(argv)

    if args.baseline:
        run_baseline()
        return
    if args.scheduled:
        try:
            run_scheduled(final=True if args.final else None)
        except Exception as e:  # noqa: BLE001
            alert_owner(f"❌ Build crashed: {type(e).__name__}: {e}")
            raise
        return
    if args.send_now:
        state = load_state()
        day = load_day(args.date or state.get("latest_edition"))
        user = next(u for u in users_mod.load_users() if u["id"] == args.send_now)
        print(send_to(user, day, state), day["date"], "to", user["id"])
        return

    state = load_state()
    if args.date:
        day = load_day(args.date)
        print(f"Loaded saved JSON for trading day {args.date}")
        report(day)
        for p in render.write_pages(day):
            print(f"Wrote {p.relative_to(ROOT)}")
        for p in write_messages(day):
            print(f"Wrote {p.relative_to(ROOT)}")
    else:
        trading_day = trading_days.expected_trading_day()
        available, detail = trading_days.close_available(trading_day)
        print(f"trading day {trading_day}: official close available={available} {detail}")
        day = build_and_publish(trading_day, state, dry_run=args.dry_run, unofficial=not available, weekday=args.weekday)
        if not args.dry_run:
            apply_state(day, state)
            save_state(state)
            print("Updated data/state.json and the deep dive queue.")
    if args.dry_run:
        print("Dry run: nothing sent, state.json untouched.")


if __name__ == "__main__":
    main()
