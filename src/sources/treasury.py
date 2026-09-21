"""US Treasury daily par yield curve. The only file that touches home.treasury.gov. Same-day data."""
import io
from datetime import date

import pandas as pd
import requests

from src.retry import retry

CSV_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
    "&field_tdr_date_value={year}&page&_format=csv"
)
PAGE_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "TextView?type=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
UA = {"User-Agent": "morning-market-brief (personal, non-commercial)"}
TIMEOUT = 30


def page_url(year=None):
    return PAGE_URL.format(year=year or date.today().year)


def _fetch_year(year):
    resp = requests.get(CSV_URL.format(year=year), headers=UA, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.text


def parse_csv(text):
    """Parse the Treasury CSV into a DataFrame indexed by date, columns like '2 Yr', '10 Yr'."""
    df = pd.read_csv(io.StringIO(text))
    if "Date" not in df.columns:
        raise RuntimeError("Treasury CSV has no Date column")
    df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
    df = df.set_index("Date").sort_index()
    df.index.name = "date"
    return df.astype("float64")


def get_yields(start):
    """Return the par yield curve from start (YYYY-MM-DD) to today, one row per business day."""
    start = pd.Timestamp(start)
    frames = [parse_csv(retry(_fetch_year, y)) for y in range(start.year, date.today().year + 1)]
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[df.index >= start]
