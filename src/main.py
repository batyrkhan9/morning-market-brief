"""Entry point. Supports --dry-run and --date YYYY-MM-DD."""
import argparse
import json
from datetime import datetime, timezone

import yaml
from dotenv import load_dotenv

from src import render, sections
from src.paths import CONFIG, DATA, ROOT
from src.sections import sectors, snapshot


def load_config():
    with open(CONFIG / "tickers.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_day(date_str, config=None):
    """Fetch every source and build the day's JSON. Never raises for a single section (rule 5)."""
    ctx = {"config": config or load_config(), "date": date_str}
    day = {
        "date": date_str,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "as_of": None,
        "sections": {},
    }
    day["sections"]["snapshot"] = sections.run(snapshot.build, ctx)
    day["sections"]["sectors"] = sections.run(sectors.build, ctx)
    day["as_of"] = ctx.get("as_of") or day["sections"]["sectors"].get("as_of")
    return day


def save_day(day):
    path = DATA / "daily" / f"{day['date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(day, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_day(date_str):
    path = DATA / "daily" / f"{date_str}.json"
    if not path.exists():
        raise SystemExit(f"No saved JSON for {date_str} at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None):
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Build and send the morning market brief.")
    parser.add_argument("--dry-run", action="store_true", help="build locally, send nothing")
    parser.add_argument("--date", help="rebuild a past day from saved JSON (YYYY-MM-DD)")
    args = parser.parse_args(argv)

    if args.date:
        day = load_day(args.date)
        print(f"Loaded saved JSON for {args.date}")
    else:
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day = build_day(date_str)
        path = save_day(day)
        print(f"Saved {path.relative_to(ROOT)}")

    for name, sec in day["sections"].items():
        status = "FAILED: " + sec["error"] if "error" in sec else "ok"
        if sec.get("errors"):
            status = "partial: " + "; ".join(e["message"] for e in sec["errors"])
        print(f"  {name}: {status}")

    for p in render.write_pages(day):
        print(f"Wrote {p.relative_to(ROOT)}")

    if args.dry_run:
        print("Dry run: nothing sent.")
    else:
        print("Sending is not implemented yet (milestone 4). Nothing sent.")


if __name__ == "__main__":
    main()
