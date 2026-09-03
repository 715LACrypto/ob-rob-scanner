"""
Pulls historical candle (kline) data from BingX's public API.

This will NOT work run locally in a sandbox with restricted network access -
it needs to run somewhere with normal internet access (e.g. Render).

BingX perpetual futures kline endpoint (public, no API key needed for historical
market data):
    GET https://open-api.bingx.com/openApi/swap/v3/quote/klines

Docs reference: symbol format like "BTC-USDT", interval like "4h", limit up to 1440
candles per call. For a long history (e.g. Jan 2024 - now on 4h candles), you need
to paginate backwards using the 'endTime' param since one call can't return years
of data in one shot.
"""

import time
import requests
import pandas as pd

BASE_URL = "https://open-api.bingx.com/openApi/swap/v3/quote/klines"


def get_all_symbols() -> list[str]:
    """Fetch the full list of tradable USDT-margined perpetual symbols on BingX."""
    url = "https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    symbols = [item["symbol"] for item in data.get("data", [])]
    return symbols


def fetch_klines(symbol: str, interval: str = "4h", start_ms: int = None, end_ms: int = None,
                  limit: int = 1440) -> pd.DataFrame:
    """
    Fetch one page of candles for a symbol. Returns a DataFrame with
    columns: time, open, high, low, close, volume (ascending by time).
    """
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_ms:
        params["startTime"] = start_ms
    if end_ms:
        params["endTime"] = end_ms

    resp = requests.get(BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    rows = payload.get("data", [])
    if not rows:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(rows)
    # BingX returns fields like: time, open, high, low, close, volume (names may vary
    # slightly - confirm against a live response once running on Render, since this
    # can't be tested from this sandbox).
    df = df.rename(columns={
        "time": "time", "open": "open", "high": "high", "low": "low",
        "close": "close", "volume": "volume"
    })
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df = df.sort_values("time").reset_index(drop=True)
    return df


def fetch_full_history(symbol: str, interval: str = "4h",
                        start_ms: int = None, end_ms: int = None,
                        pause_sec: float = 0.3) -> pd.DataFrame:
    """
    Paginate backwards from end_ms to start_ms to build a full historical dataset,
    since one API call only returns a limited number of candles.
    """
    if end_ms is None:
        end_ms = int(time.time() * 1000)

    all_frames = []
    cursor_end = end_ms

    while True:
        df = fetch_klines(symbol, interval=interval, end_ms=cursor_end)
        if df.empty:
            break
        all_frames.append(df)
        earliest = int(df["time"].min())
        if start_ms and earliest <= start_ms:
            break
        cursor_end = earliest - 1
        time.sleep(pause_sec)  # be polite to the rate limit

    if not all_frames:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    full = pd.concat(all_frames).drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    if start_ms:
        full = full[full["time"] >= start_ms].reset_index(drop=True)
    return full
