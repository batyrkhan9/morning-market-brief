"""SEC EDGAR. The only file that touches sec.gov (directly and through edgartools).

Every request carries a User-Agent with EDGAR_CONTACT_EMAIL, stays under the rate limit, and
submissions are cached for the run.
"""
import json
import os
import re
import threading
import time

import requests
import yaml

from src.paths import CONFIG
from src.retry import retry

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}"
TIMEOUT = 30

_cache = {}
_lock = threading.Lock()
_last = [0.0]
_settings = None


def settings():
    global _settings
    if _settings is None:
        with open(CONFIG / "edgar.yaml", encoding="utf-8") as f:
            _settings = yaml.safe_load(f)
    return _settings


def contact_email():
    email = os.environ.get("EDGAR_CONTACT_EMAIL", "").strip()
    if not email or "@" not in email:
        raise RuntimeError("EDGAR_CONTACT_EMAIL is not set (EDGAR requires a contact email in the User-Agent)")
    return email


def headers():
    return {"User-Agent": f"morning-market-brief personal non-commercial {contact_email()}",
            "Accept-Encoding": "gzip, deflate"}


def _throttle():
    with _lock:
        gap = 1.0 / settings()["rate_limit_per_second"]
        wait = gap - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def _get(url, as_json=True):
    _throttle()
    resp = requests.get(url, headers=headers(), timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json() if as_json else resp.text


def cached_get(url, as_json=True):
    """GET with the run cache, so a submissions file is fetched at most once per run."""
    if url in _cache:
        return _cache[url]
    contact_email()  # fail fast, before any retry, when the email is missing
    data = retry(_get, url, as_json)
    _cache[url] = data
    return data


def clear_cache():
    _cache.clear()


def pad(cik):
    return str(int(cik)).zfill(10)


def get_submissions(cik):
    """The submissions JSON: company info plus filings.recent arrays. Cached for the run."""
    return cached_get(SUBMISSIONS.format(cik=pad(cik)))


def get_recent_filings(cik, forms=None, limit=None):
    """Recent filings as a list of dicts (newest first), optionally filtered by form type."""
    sub = get_submissions(cik)
    rec = sub.get("filings", {}).get("recent", {})
    keys = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form", "primaryDocument",
            "primaryDocDescription", "items"]
    n = len(rec.get("accessionNumber", []))
    out = []
    for i in range(n):
        row = {k: (rec.get(k) or [None] * n)[i] for k in keys}
        if forms and row["form"] not in forms:
            continue
        row["cik"] = pad(cik)
        row["items"] = [x.strip() for x in (row["items"] or "").split(",") if x.strip()]
        row["url"] = filing_doc_url(cik, row["accessionNumber"], row["primaryDocument"])
        row["index_url"] = filing_index_url(cik, row["accessionNumber"])
        out.append(row)
        if limit and len(out) >= limit:
            break
    return out


def files_10k(cik):
    """True when the company files 10-Ks (US domestic filer); ADRs file 20-F or 40-F."""
    return any(f["form"] in ("10-K", "10-K405", "10-KT") for f in get_recent_filings(cik))


def filing_doc_url(cik, accession, primary_doc):
    base = ARCHIVE.format(cik_int=int(cik), acc_nodash=accession.replace("-", ""))
    return f"{base}/{primary_doc}" if primary_doc else filing_index_url(cik, accession)


def filing_index_url(cik, accession):
    base = ARCHIVE.format(cik_int=int(cik), acc_nodash=accession.replace("-", ""))
    return f"{base}/{accession}-index.htm"


def get_exhibit_url(cik, accession, pattern=r"99[-_.]?1|ex-?99|press"):
    """URL of the press release exhibit (EX-99.1) inside a filing, or the filing index when not found."""
    base = ARCHIVE.format(cik_int=int(cik), acc_nodash=accession.replace("-", ""))
    try:
        idx = cached_get(base + "/index.json")
        names = [it["name"] for it in idx.get("directory", {}).get("item", [])]
        for name in names:
            if re.search(pattern, name, re.I) and name.lower().endswith((".htm", ".html")):
                return f"{base}/{name}"
    except Exception:  # noqa: BLE001 - the index page always exists
        pass
    return filing_index_url(cik, accession)


def get_document_text(url):
    """Plain text of an EDGAR HTML document (tags stripped, whitespace collapsed)."""
    html = cached_get(url, as_json=False)
    return html_to_text(html)


def html_to_text(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>", "\n", html)
    html = re.sub(r"(?i)</p>|</div>|</tr>|</li>|</h\d>|</table>", "\n\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;|&[a-z]+;", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_company_facts(cik):
    """The XBRL company facts JSON (all tags, all periods). Large: several MB for big companies."""
    return cached_get(COMPANY_FACTS.format(cik=pad(cik)))


def get_ticker_map():
    """{TICKER: cik} for every SEC registrant with a ticker, including ADRs (20-F filers)."""
    data = cached_get(COMPANY_TICKERS)
    return {v["ticker"].upper().replace(".", "-"): pad(v["cik_str"]) for v in data.values()}


def get_10k_sections(cik, items=("1", "1A", "7")):
    """Text of 10-K Items 1, 1A and 7 from the latest 10-K via edgartools.

    Returns {"filing": {...}, "sections": {"1": text or None, ...}, "errors": {"1": reason, ...}}.
    Parsing fails on some filings; callers show the filing link and the reason.
    """
    import edgar as edgartools  # the package installs as `edgar`

    edgartools.set_identity(f"morning-market-brief {contact_email()}")
    latest = get_recent_filings(cik, forms=("10-K",), limit=1)
    if not latest:
        raise RuntimeError("no 10-K filing found")
    meta = latest[0]
    out = {"filing": {"accession": meta["accessionNumber"], "date": meta["filingDate"], "url": meta["url"],
                      "index_url": meta["index_url"]}, "sections": {}, "errors": {}}
    _throttle()
    filing = edgartools.get_by_accession_number(meta["accessionNumber"])
    tenk = filing.obj()
    for item in items:
        key = f"Item {item}"
        text = None
        try:
            text = tenk[key]
        except Exception as e:  # noqa: BLE001
            out["errors"][item] = f"{type(e).__name__}: {e}"
        if text is not None and not isinstance(text, str):
            text = str(text)
        text = (text or "").strip()
        if len(text) < 500:
            out["sections"][item] = None
            out["errors"].setdefault(item, f"parsed only {len(text)} characters")
        else:
            out["sections"][item] = text
    return out
