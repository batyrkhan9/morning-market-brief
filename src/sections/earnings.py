"""Section: earnings. S&P 500 companies whose 8-K with Item 2.02 (results of operations) belongs to
the last trading day, with the stock's move and a link to the press release exhibit."""
from src.sections.common import last_on_or_before
from src.sources import edgar


def build(ctx):
    scan = ctx.get("filings_8k")
    if scan is None:
        raise RuntimeError("8-K scan unavailable: " + (ctx.get("filings_error") or "unknown"))
    closes = ctx["universe"]["closes"]
    as_of = ctx["as_of"]
    rows = []
    for t, filings in scan["by_ticker"].items():
        for f in filings:
            if "2.02" not in f["codes"]:
                continue
            chg = None
            if t in closes.columns:
                s = closes[t].dropna()
                d0, v0 = last_on_or_before(s, as_of)
                prev = s[s.index < d0] if d0 is not None else s.iloc[0:0]
                if d0 is not None and not prev.empty:
                    chg = (v0 / float(prev.iloc[-1]) - 1) * 100
            try:
                exhibit = edgar.get_exhibit_url(f["cik"], f["accession"])
            except Exception:  # noqa: BLE001
                exhibit = f["index_url"]
            rows.append({"ticker": t, "name": f["name"], "chg_1d": chg, "accepted_et": f["accepted_et"],
                         "exhibit_url": exhibit, "index_url": f["index_url"], "items": f["items"],
                         "source_url": "https://finance.yahoo.com/quote/" + t})
    rows.sort(key=lambda r: (r["chg_1d"] is None, -abs(r["chg_1d"] or 0)))
    return {"as_of": as_of, "rows": rows, "scanned": scan["count"], "scan_errors": len(scan["errors"])}
