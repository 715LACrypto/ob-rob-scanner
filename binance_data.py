"""
Pulls historical candle (kline) data from Binance's public API.

Same idea as bingx_data.py, but Binance has much longer history - most major
coins go back to when they first listed (some to 2017-2020), which BingX's
perpetual futures contracts don't have.

This will NOT work run locally in this sandbox (restricted network) - it
needs to run somewhere with normal internet access (e.g. Render), same as
the BingX scripts.

Public endpoint, no API key needed for historical market data:
    GET https://api.binance.com/api/v3/klines
"""

import time
import requests
import pandas as pd

BASE_URL = "https://api.binance.com/api/v3/klines"

# Binance interval strings: 1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M
BINANCE_LIMIT = 1000  # max candles per call


def fetch_klines(symbol: str, interval: str = "4h", start_ms: int = None,
                  end_ms: int = None, limit: int = BINANCE_LIMIT) -> pd.DataFrame:
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_ms:
        params["startTime"] = start_ms
    if end_ms:
        params["endTime"] = end_ms

    resp = requests.get(BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "quote_vol", "trades", "taker_base", "taker_quote", "ignore"
    ])
    df = df[["time", "open", "high", "low", "close", "volume"]]
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["time"] = df["time"].astype("int64")
    df = df.sort_values("time").reset_index(drop=True)
    return df


def fetch_full_history(symbol: str, interval: str = "4h",
                        start_ms: int = None, end_ms: int = None,
                        pause_sec: float = 0.25) -> pd.DataFrame:
    """
    Paginate FORWARD from start_ms (or from the coin's actual listing date if
    start_ms is very old / None) up to end_ms, since Binance's API pages
    forward from startTime rather than backward from endTime.

    If start_ms is None, we pass a very early timestamp (2015) and Binance
    will just return data starting from whenever the symbol actually began
    trading - giving us the full available history automatically (as close
    to ICO/listing as this data source can get).
    """
    if end_ms is None:
        end_ms = int(time.time() * 1000)
    if start_ms is None:
        start_ms = int(pd.Timestamp("2015-01-01", tz="UTC").timestamp() * 1000)

    all_frames = []
    cursor_start = start_ms
    max_pages = 200  # generous safety cap
    prev_latest = None

    for _ in range(max_pages):
        df = fetch_klines(symbol, interval=interval, start_ms=cursor_start, end_ms=end_ms)
        if df.empty:
            break
        all_frames.append(df)
        latest = int(df["time"].max())

        if prev_latest is not None and latest <= prev_latest:
            break
        prev_latest = latest

        if latest >= end_ms:
            break
        cursor_start = latest + 1
        time.sleep(pause_sec)

    if not all_frames:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    full = pd.concat(all_frames).drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    return full
