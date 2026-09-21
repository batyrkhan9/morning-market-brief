"""S&P 500 constituents from the Wikipedia table. The only file that touches Wikipedia.

Cached weekly in data/constituents.json (committed). Columns: ticker, name, sector, cik.
Dots become dashes for Yahoo (BRK.B -> BRK-B).
"""
import io
import json
from datetime import datetime, timezone

import pandas as pd
import requests

from src.paths import DATA
from src.retry import retry

URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
UA = {"User-Agent": "morning-market-brief (personal, non-commercial)"}
CACHE = DATA / "constituents.json"
MAX_AGE_DAYS = 7
COLUMNS = ["ticker", "name", "sector", "cik"]


def _fetch():
    resp = requests.get(URL, headers=UA, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_html(html):
    """Parse the first table of the Wikipedia page into a DataFrame with COLUMNS."""
    tables = pd.read_html(io.StringIO(html))
    table = next((t for t in tables if "Symbol" in t.columns and "CIK" in t.columns), None)
    if table is None:
        raise RuntimeError("Wikipedia page has no table with Symbol and CIK columns")
    df = pd.DataFrame({
        "ticker": table["Symbol"].astype(str).str.strip().str.replace(".", "-", regex=False),
        "name": table["Security"].astype(str).str.strip(),
        "sector": table["GICS Sector"].astype(str).str.strip(),
        "cik": table["CIK"].astype(int).astype(str).str.zfill(10),
    })
    df = df.drop_duplicates("ticker").reset_index(drop=True)
    if len(df) < 480:
        raise RuntimeError(f"Wikipedia table looks wrong: only {len(df)} rows")
    return df


def _age_days(fetched_at):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(fetched_at)).total_seconds() / 86400


def load_cache(path=CACHE):
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(payload["rows"], columns=COLUMNS)
    df.attrs["fetched_at"] = payload["fetched_at"]
    return df


def save_cache(df, path=CACHE):
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {"fetched_at": fetched_at, "source": URL, "rows": df[COLUMNS].to_dict(orient="records")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    df.attrs["fetched_at"] = fetched_at


def get_sp500(force=False, cache_path=CACHE):
    """Return a DataFrame (ticker, name, sector, cik). Uses the weekly cache when fresh.

    If the fetch fails and a stale cache exists, the stale cache is returned with attrs["stale"]=True.
    """
    cached = load_cache(cache_path)
    if cached is not None and not force and _age_days(cached.attrs["fetched_at"]) < MAX_AGE_DAYS:
        return cached
    try:
        df = parse_html(retry(_fetch))
        save_cache(df, cache_path)
        return df
    except Exception:
        if cached is not None:
            cached.attrs["stale"] = True
            return cached
        raise
