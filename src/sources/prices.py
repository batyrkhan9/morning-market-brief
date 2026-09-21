"""Price data. Currently backed by yfinance (unofficial; expect breakage, swap here only)."""


def get_prices(tickers, period):
    """Return a DataFrame of closes indexed by date, one column per ticker."""
    raise NotImplementedError
