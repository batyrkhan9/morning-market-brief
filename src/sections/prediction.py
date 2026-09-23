"""Section: predictions. Ends every brief: open predictions, scored today, running hit rate."""
from src import scoring


def build(ctx):
    preds = scoring.load()
    as_of = ctx["as_of"]
    scored_now = scoring.score(preds, as_of)
    if scored_now and not ctx.get("dry_run"):
        scoring.save(preds)
    rate = scoring.hit_rate(preds)
    done = [p for p in preds if p.get("status") in ("right", "wrong")]
    return {"as_of": as_of, "open": [p for p in preds if p.get("status") == "open"],
            "scored_today": [p for p in preds if p.get("scored_on") == as_of],
            "recent": sorted(done, key=lambda p: p.get("scored_on", ""), reverse=True)[:10],
            "hit_rate": None if rate is None else f"{rate * 100:.0f}% ({sum(1 for p in done if p['status'] == 'right')}/{len(done)})",
            "total": len(preds), "scored_now": len(scored_now)}
