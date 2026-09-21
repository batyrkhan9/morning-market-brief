"""Section: deep dive of the week. One company per week from config/deep_dive_schedule.yaml,
one chunk per day picked from the weekday. Each chunk is rendered on its own page."""
from datetime import date

import pandas as pd

from src import facts as facts_mod
from src.sources import edgar, fred, prices

CHUNKS = ["macro", "business", "numbers", "competitors", "earnings_release", "risk_factors", "mdna"]
MACRO_SERIES = [
    {"id": "DGS2", "label": "2 year yield", "unit": "%"},
    {"id": "DGS10", "label": "10 year yield", "unit": "%"},
    {"id": "T10Y2Y", "label": "10y minus 2y", "unit": "%"},
    {"id": "CPIAUCSL", "label": "CPI, year over year", "unit": "%", "transform": "yoy"},
    {"id": "UNRATE", "label": "Unemployment rate", "unit": "%"},
    {"id": "BAMLH0A0HYM2", "label": "High yield spread", "unit": "%"},
    {"id": "DTWEXBGS", "label": "Dollar index (broad)", "unit": "index"},
]
MAX_TEXT = 400_000


def week_entry(schedule, on_date):
    """(week number starting at 1, schedule entry) for a date. Past the schedule, the queue takes over."""
    start = pd.Timestamp(schedule["start_date"]).date()
    d = date.fromisoformat(str(on_date)[:10])
    week = (d - start).days // 7 + 1
    entries = schedule["schedule"]
    if 1 <= week <= len(entries):
        return week, entries[week - 1]
    queue = schedule.get("queue") or []
    idx = week - len(entries) - 1
    if 0 <= idx < len(queue):
        return week, {"ticker": queue[idx], "competitors": [], "sector": None, "from_queue": True}
    raise RuntimeError(f"no company scheduled for week {week}; add tickers to the queue")


def chunk_for(weekday):
    return CHUNKS[weekday]


def _note(errs, where, e):
    errs.append({"where": where, "message": f"{type(e).__name__}: {e}"})


def _weekly(s, years, as_of):
    start = pd.Timestamp(as_of) - pd.DateOffset(years=years)
    s = s[(s.index > start) & (s.index <= pd.Timestamp(as_of))].dropna()
    w = s.resample("W-FRI").last().dropna()
    return [d.date().isoformat() for d in w.index], [round(float(v), 4) for v in w]


def macro(ctx, entry, cik, errs):
    as_of = pd.Timestamp(ctx["as_of"])
    start = (as_of - pd.DateOffset(years=6)).date()
    charts, changes = [], []
    for m in MACRO_SERIES:
        try:
            s = fred.get_series(m["id"], start)
            if m.get("transform") == "yoy":
                s = (s.pct_change(12) * 100).dropna()
            dates, values = _weekly(s, 5, as_of)
            now, week_ago = s[s.index <= as_of], s[s.index <= as_of - pd.Timedelta(days=7)]
            changes.append({"id": m["id"], "label": m["label"], "unit": m["unit"],
                            "now": float(now.iloc[-1]), "now_date": now.index[-1].date().isoformat(),
                            "week_ago": float(week_ago.iloc[-1]) if not week_ago.empty else None,
                            "source_url": fred.series_url(m["id"])})
            charts.append({"id": m["id"], "label": m["label"], "unit": m["unit"], "dates": dates, "values": values})
        except Exception as e:  # noqa: BLE001
            _note(errs, m["id"], e)
    return {"charts": charts, "week_changes": changes,
            "notes": ["Economic releases scheduled this week arrive with the calendar section (milestone 7)."]}


def _sections(cik, item, errs):
    try:
        res = edgar.get_10k_sections(cik, items=(item,))
    except Exception as e:  # noqa: BLE001
        _note(errs, f"10-K item {item}", e)
        return {"text": None, "filing": None}
    text = res["sections"].get(item)
    if text is None:
        errs.append({"where": f"10-K item {item}", "message": res["errors"].get(item, "not parsed")})
    return {"text": text[:MAX_TEXT] if text else None, "filing": res["filing"], "chars": len(text or "")}


def business(ctx, entry, cik, errs):
    out = _sections(cik, "1", errs)
    out["notes"] = ["Segment revenue is not available from the company facts API; see the filing."]
    return out


def numbers(ctx, entry, cik, errs):
    out = {"metrics": None, "price": None}
    try:
        cands = edgar.settings()["facts"]
        out["metrics"] = facts_mod.metrics(edgar.get_company_facts(cik), cands)
        missing = [k for k, v in out["metrics"].items() if v is None]
        if missing:
            errs.append({"where": "company facts", "message": "not reported with the usual tags: " + ", ".join(missing)})
    except Exception as e:  # noqa: BLE001
        _note(errs, "company facts", e)
    try:
        s = prices.get_prices([entry["ticker"]], period="10y")[entry["ticker"]]
        dates, values = _weekly(s, 10, ctx["as_of"])
        out["price"] = {"dates": dates, "values": values}
    except Exception as e:  # noqa: BLE001
        _note(errs, "price history", e)
    return out


def competitors(ctx, entry, cik, errs):
    tickers = [entry["ticker"]] + list(entry.get("competitors") or [])
    out = {"tickers": tickers, "chart": None, "table": []}
    try:
        closes = prices.get_prices(tickers, period="6y")
        as_of = pd.Timestamp(ctx["as_of"])
        series = {}
        for t in tickers:
            if t in closes.columns and not closes[t].dropna().empty:
                d, v = _weekly(closes[t], 5, as_of)
                base = v[0] if v else None
                series[t] = {"dates": d, "values": [round(x / base * 100, 2) for x in v] if base else []}
        out["chart"] = series
    except Exception as e:  # noqa: BLE001
        _note(errs, "competitor prices", e)
    try:
        ticker_map = edgar.get_ticker_map()
    except Exception as e:  # noqa: BLE001
        _note(errs, "SEC ticker map", e)
        ticker_map = {}
    cands = edgar.settings()["facts"]
    for t in tickers:
        row = {"ticker": t, "cik": ticker_map.get(t), "files_10k": False, "revenue_growth": None,
               "operating_margin": None, "fiscal_year_end": None, "note": None}
        try:
            if not row["cik"]:
                row["note"] = "not an SEC registrant, price chart only"
            elif not edgar.files_10k(row["cik"]):
                row["note"] = "foreign filer (20-F or 40-F), price chart only"
            else:
                row["files_10k"] = True
                m = facts_mod.metrics(edgar.get_company_facts(row["cik"]), cands, years=3)
                rev = m.get("revenue")
                if rev and len(rev["values"]) >= 2 and rev["values"][-1] and rev["values"][-2]:
                    row["revenue_growth"] = (rev["values"][-1] / rev["values"][-2] - 1) * 100
                    row["fiscal_year_end"] = rev["periods"][-1]
                om = m.get("operating_margin")
                if om and om["values"] and om["values"][-1] is not None:
                    row["operating_margin"] = om["values"][-1]
        except Exception as e:  # noqa: BLE001
            row["note"] = f"{type(e).__name__}: {e}"
        out["table"].append(row)
    return out


def earnings_release(ctx, entry, cik, errs):
    out = {"filing": None, "exhibit_url": None, "text": None}
    try:
        latest = next((f for f in edgar.get_recent_filings(cik, forms=("8-K", "8-K/A")) if "2.02" in f["items"]), None)
        if latest is None:
            raise RuntimeError("no 8-K with Item 2.02 in recent filings")
        out["filing"] = {"date": latest["filingDate"], "url": latest["url"], "index_url": latest["index_url"],
                         "accession": latest["accessionNumber"]}
        out["exhibit_url"] = edgar.get_exhibit_url(cik, latest["accessionNumber"])
        if out["exhibit_url"] != latest["index_url"]:
            out["text"] = edgar.get_document_text(out["exhibit_url"])[:MAX_TEXT]
        else:
            errs.append({"where": "press release", "message": "exhibit 99.1 not found, see the filing index"})
    except Exception as e:  # noqa: BLE001
        _note(errs, "earnings release", e)
    return out


def risk_factors(ctx, entry, cik, errs):
    return _sections(cik, "1A", errs)


def mdna(ctx, entry, cik, errs):
    return _sections(cik, "7", errs)


BUILDERS = {"macro": macro, "business": business, "numbers": numbers, "competitors": competitors,
            "earnings_release": earnings_release, "risk_factors": risk_factors, "mdna": mdna}


def build(ctx):
    schedule = ctx["schedule"]
    week, entry = week_entry(schedule, ctx["date"])
    weekday = ctx.get("weekday")
    if weekday is None:
        weekday = date.fromisoformat(ctx["date"]).weekday()
    chunk = chunk_for(weekday)
    ticker = entry["ticker"]
    meta = ctx["universe"]["constituents"].set_index("ticker") if ctx.get("universe") else None
    name, sector, cik = ticker, entry.get("sector"), None
    if meta is not None and ticker in meta.index:
        name, sector, cik = meta.loc[ticker, "name"], meta.loc[ticker, "sector"], meta.loc[ticker, "cik"]
    errs = []
    if cik is None and chunk != "macro":
        try:
            cik = edgar.get_ticker_map().get(ticker)
        except Exception as e:  # noqa: BLE001
            _note(errs, "SEC ticker map", e)
    data = None
    if chunk != "macro" and cik is None:
        errs.append({"where": "company", "message": f"no CIK found for {ticker}"})
    else:
        data = BUILDERS[chunk](ctx, entry, cik, errs)
    return {"week": week, "ticker": ticker, "name": name, "sector": sector, "cik": cik,
            "competitors": list(entry.get("competitors") or []), "chunk": chunk, "weekday": weekday,
            "page": f"deep-dive/{ctx['date']}.html", "data": data, "errors": errs,
            "filing_search_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=10-K" if cik else None}
