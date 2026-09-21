"""Entry point. Supports --dry-run, --date YYYY-MM-DD and --baseline."""
import argparse
import json
import time
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

from src import filings, render, sections, universe
from src.paths import CONFIG, DATA, ROOT
from src.sections import baseline, breadth, deep_dive, earnings, heatmap, movers, sectors, slow_movers, snapshot

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


def new_context(date_str, config=None, state=None, weekday=None):
    return {"config": config or load_config(), "config_thresholds": load_yaml(CONFIG / "thresholds.yaml"),
            "schedule": load_yaml(SCHEDULE), "state": state if state is not None else {}, "date": date_str,
            "weekday": weekday}


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
    day = {"date": date_str, "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "as_of": None, "sections": {}, "timing": {}}
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
    day["sections"]["deep_dive"] = sections.run(needs_universe(deep_dive.build), ctx)
    day["as_of"] = ctx.get("as_of") or sec.get("as_of")
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
    args = parser.parse_args(argv)

    if args.baseline:
        run_baseline()
        return

    state = load_state()
    if args.date:
        day = load_day(args.date)
        print(f"Loaded saved JSON for {args.date}")
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day = build_day(date_str, ctx=new_context(date_str, state=state, weekday=args.weekday))
        path = save_day(day)
        print(f"Saved {path.relative_to(ROOT)}  timing={day['timing']}")

    for name, sec in day["sections"].items():
        status = "FAILED: " + sec["error"] if "error" in sec else "ok"
        if sec.get("errors"):
            status = "partial: " + "; ".join(e["message"] for e in sec["errors"])
        print(f"  {name}: {status}")

    for p in render.write_pages(day):
        print(f"Wrote {p.relative_to(ROOT)}")

    if args.dry_run:
        print("Dry run: nothing sent, state.json untouched.")
    else:
        if not args.date:
            apply_state(day, state)
            print("Updated data/state.json and the deep dive queue.")
        print("Sending is not implemented yet (milestone 4). Nothing sent.")


if __name__ == "__main__":
    main()
