"""Price data. The only file that touches yfinance (unofficial; expect breakage, swap here only)."""
import time
import warnings

import pandas as pd
import yfinance as yf

from src.retry import retry


def _download(tickers, period):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(
            list(tickers), period=period, auto_adjust=False, progress=False, threads=True
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


INTRADAY_FILL_DATE = None  # set by main for an unofficial build: fill this day's close from the last intraday bar


def _intraday_last(tickers):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(list(tickers), period="1d", interval="5m", auto_adjust=False, progress=False, threads=True)
    if df is None or df.empty:
        raise RuntimeError("no intraday bars")
    closes = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]]
    if not isinstance(df.columns, pd.MultiIndex):
        closes.columns = list(tickers)
    return closes.ffill().iloc[-1]


def get_prices(tickers, period="2y"):
    """Return a DataFrame of split-adjusted daily closes (Yahoo's "Close", not "Adj Close").

    Changes computed from these match what Yahoo and Google display: price only, no dividends.
    Index = date, one column per ticker. Tickers with no data at all are in DataFrame.attrs["missing"].
    When INTRADAY_FILL_DATE is set and the official close for that day is missing, the last intraday
    bar is used instead and DataFrame.attrs["unofficial"] lists the tickers filled that way.
    """
    closes = retry(_download, tuple(tickers), period)
    if INTRADAY_FILL_DATE:
        d = pd.Timestamp(INTRADAY_FILL_DATE)
        if d not in closes.index:
            closes.loc[d] = float("nan")
            closes = closes.sort_index()
        missing = [t for t in closes.columns if pd.isna(closes.loc[d, t])]
        if missing:
            try:
                last = retry(_intraday_last, tuple(missing))
                for t in missing:
                    if t in last.index and pd.notna(last[t]):
                        closes.loc[d, t] = float(last[t])
                closes.attrs["unofficial"] = [t for t in missing if pd.notna(closes.loc[d, t])]
            except Exception:  # noqa: BLE001 - fall back to whatever the daily bars have
                pass
        if closes.loc[d].isna().all():
            closes = closes.drop(index=d)
    return closes


def get_market_caps(tickers, pause=0.05):
    """Return {ticker: market cap in USD or None}. One quote call per ticker, so cache the result."""
    caps = {}
    for t in tickers:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                caps[t] = float(yf.Ticker(t).fast_info["marketCap"])
        except Exception:  # noqa: BLE001 - one bad ticker must not break the batch
            caps[t] = None
        time.sleep(pause)
    return caps
