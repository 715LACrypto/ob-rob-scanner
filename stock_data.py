"""
Pulls real stock price history via yfinance, used as a proxy for the
tokenized stock contracts on BingX (e.g. NCSKTSLA2USD-USDT tracks real TSLA).

The tokenized version is built to mirror the real stock's price, so this
lets us test how the strategy would have performed during real bull periods
(2021, etc.) that the tokenized contracts themselves don't have data for.

Needs: pip install yfinance --break-system-packages
Needs real internet access - run on Render, not in this sandbox.

Stock data only comes in daily (1d) candles going back far enough for this -
intraday history from Yahoo only goes back ~60 days, so we use daily bars
for this test instead of 4h. That changes the bar-count math slightly (a
"bar" here = 1 day instead of 4h) but the strategy logic itself is identical.
"""

import yfinance as yf
import pandas as pd


def fetch_full_history(ticker: str, start: str = "2015-01-01", end: str = None) -> pd.DataFrame:
    """
    Returns a DataFrame with columns: time, open, high, low, close
    (time = integer epoch ms, matching the crypto data format so the same
    backtest function works unchanged).
    """
    data = yf.download(ticker, start=start, end=end, interval="1d", progress=False, auto_adjust=True)
    if data is None or len(data) == 0:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])

    data = data.reset_index()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [c[0] for c in data.columns]

    df = pd.DataFrame({
        "time": (pd.to_datetime(data["Date"]).astype("int64") // 1_000_000),
        "open": data["Open"].astype(float),
        "high": data["High"].astype(float),
        "low": data["Low"].astype(float),
        "close": data["Close"].astype(float),
    })
    df = df.sort_values("time").reset_index(drop=True)
    return df
