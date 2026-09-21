"""Annual series from EDGAR company facts. Pure functions, no network.

Annual = form 10-K, fp FY, and for flow metrics a period of about one year. The latest filed value
per period wins (restatements). Periods are labeled by fiscal year end date, since fiscal years differ.
"""
from datetime import date


def _parse(d):
    return date.fromisoformat(d)


def annual_series(facts, tag, unit=None):
    """{fiscal_year_end (ISO date): value} for one tag. `tag` may be 'dei:Name' or a us-gaap name."""
    taxonomy, name = ("dei", tag[4:]) if tag.startswith("dei:") else ("us-gaap", tag)
    entry = facts.get("facts", {}).get(taxonomy, {}).get(name)
    if not entry:
        return {}
    units = entry.get("units", {})
    if unit is None:
        unit = next((u for u in ("USD", "shares", "pure") if u in units), next(iter(units), None))
    rows = units.get(unit, [])
    best = {}
    for r in rows:
        if r.get("form") not in ("10-K", "10-K/A", "10-KT") or r.get("fp") != "FY" or "end" not in r:
            continue
        if "start" in r:
            days = (_parse(r["end"]) - _parse(r["start"])).days
            if not 350 <= days <= 380:
                continue
        end = r["end"]
        if end not in best or r.get("filed", "") > best[end].get("filed", ""):
            best[end] = r
    return {end: float(r["val"]) for end, r in best.items()}


def stitched(facts, candidates, unit=None):
    """Merge candidate tags period by period; the first candidate with a value for a period wins.
    Returns ({end: value}, {end: tag used})."""
    merged, used = {}, {}
    for tag in candidates:
        for end, val in annual_series(facts, tag, unit).items():
            if end not in merged:
                merged[end], used[end] = val, tag
    return merged, used


def _last_n(series, n):
    return dict(sorted(series.items())[-n:])


def metrics(facts, candidates, years=10):
    """Revenue, gross margin, operating margin, net income, long term debt, shares for the last N fiscal years.

    Returns {metric: {"periods": [...], "values": [...], "unit": ..., "tags": {...}} or None when unavailable}.
    """
    out = {}
    rev, rev_tags = stitched(facts, candidates["revenue"])
    rev = _last_n(rev, years)
    periods = sorted(rev)

    def pack(series, unit, tags, keep=periods):
        vals = [series.get(p) for p in keep]
        if not any(v is not None for v in vals):
            return None
        return {"periods": keep, "values": vals, "unit": unit, "tags": sorted(set(tags.values()))}

    out["revenue"] = pack(rev, "USD", rev_tags) if periods else None
    gp, gp_tags = stitched(facts, candidates["gross_profit"])
    cost, cost_tags = stitched(facts, candidates["cost_of_revenue"])
    gm = {}
    for p in periods:
        if p in gp and rev.get(p):
            gm[p] = gp[p] / rev[p] * 100
        elif p in cost and rev.get(p):
            gm[p] = (rev[p] - cost[p]) / rev[p] * 100
    out["gross_margin"] = pack(gm, "%", {**gp_tags, **cost_tags}) if gm else None
    oi, oi_tags = stitched(facts, candidates["operating_income"])
    om = {p: oi[p] / rev[p] * 100 for p in periods if p in oi and rev.get(p)}
    out["operating_margin"] = pack(om, "%", oi_tags) if om else None
    ni, ni_tags = stitched(facts, candidates["net_income"])
    out["net_income"] = pack(_last_n(ni, years), "USD", ni_tags, keep=periods or sorted(_last_n(ni, years)))
    debt, debt_tags = stitched(facts, candidates["long_term_debt"])
    out["long_term_debt"] = pack(_last_n(debt, years), "USD", debt_tags, keep=periods or sorted(_last_n(debt, years)))
    sh, sh_tags = stitched(facts, candidates["shares"], unit="shares")
    out["shares"] = pack(_last_n(sh, years), "shares", sh_tags, keep=periods or sorted(_last_n(sh, years)))
    return out
