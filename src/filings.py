"""8-K scan across the S&P 500, paired to trading days by acceptance time.

Accepted after 4pm ET counts toward the next trading day's move; before the close counts
toward the same day. Submissions come from edgar.py (cached for the run, rate limited).
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from src.sources import edgar

ET = ZoneInfo("America/New_York")
CLOSE = time(16, 0)


def accepted_et(iso_utc):
    """'2026-09-18T16:05:12.000Z' -> aware datetime in New York."""
    dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    return dt.astimezone(ET)


def trading_day_for(iso_utc, trading_days):
    """The trading day whose close-to-close move a filing belongs to, or None if not yet known."""
    et = accepted_et(iso_utc)
    candidate = et.date() if et.time() <= CLOSE else et.date() + timedelta(days=1)
    idx = pd.DatetimeIndex(trading_days).searchsorted(pd.Timestamp(candidate))
    if idx >= len(trading_days):
        return None
    return pd.Timestamp(trading_days[idx]).date().isoformat()


def label_items(codes):
    labels = edgar.settings()["items"]
    return [{"code": c, "label": labels.get(c, "item " + c)} for c in codes]


def scan_8k(constituents, trading_days, as_of, lookback_days=7):
    """{ticker: [8-K filings whose trading day is as_of]} for every constituent, plus per-ticker errors.

    Raises only when every request fails (for example a missing contact email or an EDGAR outage).
    """
    as_of = pd.Timestamp(as_of)
    since = (as_of - pd.Timedelta(days=lookback_days)).date().isoformat()
    by_ticker, errors, total = {}, {}, 0
    for rec in constituents.to_dict(orient="records"):
        t, cik = rec["ticker"], rec["cik"]
        try:
            filings = edgar.get_recent_filings(cik, forms=("8-K", "8-K/A"))
        except Exception as e:  # noqa: BLE001
            errors[t] = f"{type(e).__name__}: {e}"
            if "EDGAR_CONTACT_EMAIL" in str(e):
                raise
            continue
        hits = []
        for f in filings:
            if f["filingDate"] < since:
                break
            if not f["acceptanceDateTime"]:
                continue
            day = trading_day_for(f["acceptanceDateTime"], trading_days)
            if day != as_of.date().isoformat():
                continue
            hits.append({"form": f["form"], "accession": f["accessionNumber"], "cik": cik,
                         "accepted_et": accepted_et(f["acceptanceDateTime"]).strftime("%Y-%m-%d %H:%M ET"),
                         "trading_day": day, "items": label_items(f["items"]), "codes": f["items"],
                         "url": f["url"], "index_url": f["index_url"], "name": rec["name"]})
        if hits:
            by_ticker[t] = hits
            total += len(hits)
    if errors and len(errors) == len(constituents):
        raise RuntimeError(f"every submissions request failed, first error: {next(iter(errors.values()))}")
    return {"as_of": as_of.date().isoformat(), "by_ticker": by_ticker, "errors": errors, "count": total}
