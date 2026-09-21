"""Price data. The only file that touches yfinance (unofficial; expect breakage, swap here only)."""
import warnings

import pandas as pd
import yfinance as yf

from src.retry import retry


def _download(tickers, period):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(
            list(tickers), period=period, auto_adjust=False, progress=False, threads=False
        )
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned no data for {list(tickers)}")
    closes = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]]
    if not isinstance(df.columns, pd.MultiIndex):
        closes.columns = list(tickers)
    closes = closes.copy()
    closes.index = pd.to_datetime(closes.index).tz_localize(None).normalize()
    closes.index.name = "date"
    missing = [t for t in tickers if t not in closes.columns or closes[t].dropna().empty]
    if missing:
        closes.attrs["missing"] = missing
    return closes


def get_prices(tickers, period="2y"):
    """Return a DataFrame of daily closes: index = date, one column per ticker.

    Tickers with no data at all are listed in DataFrame.attrs["missing"].
    """
    return retry(_download, tuple(tickers), period)
