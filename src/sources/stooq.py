"""Stooq daily CSV. The only file that touches stooq.com. Used as a second source for the S&P 500
anchor only: does the official close for a trading day exist yet."""
import io

import pandas as pd
import requests

from src.retry import retry

URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
UA = {"User-Agent": "morning-market-brief (personal, non-commercial)"}
SYMBOLS = {"^GSPC": "^spx"}


def _fetch(symbol):
    resp = requests.get(URL.format(symbol=symbol), headers=UA, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_csv(text):
    df = pd.read_csv(io.StringIO(text))
    if "Date" not in df.columns or "Close" not in df.columns:
        raise RuntimeError("Stooq CSV has no Date/Close columns (rate limited or empty)")
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date")["Close"].astype("float64")


def get_daily(ticker="^GSPC"):
    """Daily closes for a Yahoo-style ticker mapped to Stooq's symbol."""
    return parse_csv(retry(_fetch, SYMBOLS.get(ticker, ticker.lower())))


def close_on(ticker, date):
    """The close on `date` or None when Stooq does not have that day yet."""
    s = get_daily(ticker)
    d = pd.Timestamp(date)
    return float(s.loc[d]) if d in s.index else None
