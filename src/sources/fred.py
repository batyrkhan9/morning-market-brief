"""FRED API. The only file that touches FRED. Needs FRED_API_KEY in the environment."""
import os

import pandas as pd
import requests

from src.retry import retry

BASE = "https://api.stlouisfed.org/fred"
TIMEOUT = 30


def series_url(series_id):
    """Human page for a series, used as the source link."""
    return f"https://fred.stlouisfed.org/series/{series_id}"


def _fetch(series_id, start):
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY is not set")
    resp = requests.get(
        f"{BASE}/series/observations",
        params={
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
            "observation_start": str(start),
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def parse_observations(payload, series_id):
    """Turn a FRED observations payload into a float Series. '.' means missing and is dropped."""
    if "observations" not in payload:
        raise RuntimeError(f"FRED error for {series_id}: {payload.get('error_message', payload)}")
    rows = [(o["date"], o["value"]) for o in payload["observations"] if o["value"] != "."]
    if not rows:
        raise RuntimeError(f"FRED returned no observations for {series_id}")
    s = pd.Series(
        [float(v) for _, v in rows],
        index=pd.to_datetime([d for d, _ in rows]),
        name=series_id,
        dtype="float64",
    )
    s.index.name = "date"
    return s


def get_series(series_id, start):
    """Return a pandas Series of observations for series_id from the start date (YYYY-MM-DD)."""
    payload = retry(_fetch, series_id, start)
    return parse_observations(payload, series_id)
