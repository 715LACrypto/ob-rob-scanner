"""
Tests the OB->ROB strategy against each coin/stock's FULL history since it
started trading (not just from 2024), so we can see how it handles a real
bull market like 2021 - not just the calmer 2024-2026 window BingX data is
limited to.

Two data sources, since BingX itself doesn't go back far enough:
  - Crypto coins that existed back then: pulled from Binance.
  - Tokenized stocks: pulled from the REAL underlying stock via Yahoo
    Finance, as a stand-in for the tokenized version.

Coins with no long history anywhere (WLFI, 0G, GRAMTON - all newer tokens)
are tested on whatever history they DO have, clearly labeled.

CAVEAT: stocks only have DAILY candles this far back, not 4h. The 10-60
bar / 65 bar rules mean something different on daily bars (weeks/months,
not days) than on 4h bars. Treat stock results as a rough directional
check, not a like-for-like number vs the crypto/BingX results.

Run this on Render.
"""

import time
from datetime import datetime, timezone
import pandas as pd

from ob_rob_strategy import run_ob_rob_backtest, summarize_trades

BULL_2021_START = "2021-01-01"
BULL_2021_END = "2021-12-31"


def to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


CRYPTO_SYMBOLS = {
    "DOT-USDT": "DOTUSDT",
    "YFI-USDT": "YFIUSDT",
    "IOTA-USDT": "IOTAUSDT",
}

CRYPTO_NO_2021 = {
    "WLFI-USDT": "WLFIUSDT",
    "0G-USDT": "0GUSDT",
    "GRAMTON-USDT": "GRAMTONUSDT",
}

STOCK_SYMBOLS = {
    "NCSKRDW2USD-USDT": "RDW",
    "NCSKNVD2USD-USDT": "NVDA",
    "NCSKBB2USD-USDT": "BB",
    "NCSKTTWO2USD-USDT": "TTWO",
    "NCSKQCOM2USD-USDT": "QCOM",
    "NCSKTSLA2USD-USDT": "TSLA",
    "NCSKSKHYNIX2USD-USDT": "000660.KS",
}


def run_one(df: pd.DataFrame, label: str) -> dict:
    if df is None or len(df) < 30:
        return {"label": label, "status": "not enough data", "candles": 0 if df is None else len(df)}
    df = df.reset_index(drop=True)
    trades = run_ob_rob_backtest(df)
    summary = summarize_trades(trades)
    summary["label"] = label
    summary["status"] = "ok"
    summary["candles"] = len(df)
    return summary


def slice_2021(df: pd.DataFrame) -> pd.DataFrame:
    start_ms = to_ms(BULL_2021_START)
    end_ms = to_ms(BULL_2021_END)
    return df[(df["time"] >= start_ms) & (df["time"] <= end_ms)].reset_index(drop=True)


def main():
    results = []

    from binance_data import fetch_full_history as fetch_binance

    print("\n===== CRYPTO: full history + 2021 bull run isolated =====")
    for orig_symbol, binance_symbol in CRYPTO_SYMBOLS.items():
        print(f"\n[{orig_symbol}] pulling full Binance history for {binance_symbol} ...")
        try:
            df = fetch_binance(binance_symbol, interval="4h")
            full_result = run_one(df, f"{orig_symbol} (full history)")
            print(f"  full history: {full_result}")
            results.append(full_result)

            df_2021 = slice_2021(df)
            bull_result = run_one(df_2021, f"{orig_symbol} (2021 bull run only)")
            print(f"  2021 bull run only: {bull_result}")
            results.append(bull_result)
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"label": orig_symbol, "status": f"error: {e}"})
        time.sleep(0.5)

    print("\n===== CRYPTO: newer coins, no 2021 data available, full history only =====")
    for orig_symbol, binance_symbol in CRYPTO_NO_2021.items():
        print(f"\n[{orig_symbol}] pulling full Binance history for {binance_symbol} ...")
        try:
            df = fetch_binance(binance_symbol, interval="4h")
            full_result = run_one(df, f"{orig_symbol} (full history, no 2021 data exists)")
            print(f"  {full_result}")
            results.append(full_result)
        except Exception as e:
            print(f"  ERROR (likely not on Binance / wrong symbol): {e}")
            results.append({"label": orig_symbol, "status": f"error: {e}"})
        time.sleep(0.5)

    print("\n===== TOKENIZED STOCKS (via real stock price, DAILY bars - see caveat at top of file) =====")
    from stock_data import fetch_full_history as fetch_stock
    for orig_symbol, ticker in STOCK_SYMBOLS.items():
        print(f"\n[{orig_symbol}] pulling full daily history for real stock {ticker} ...")
        try:
            df = fetch_stock(ticker, start="2015-01-01")
            full_result = run_one(df, f"{orig_symbol} via {ticker} (full history, DAILY bars)")
            print(f"  full history: {full_result}")
            results.append(full_result)

            df_2021 = slice_2021(df)
            bull_result = run_one(df_2021, f"{orig_symbol} via {ticker} (2021 bull run only, DAILY bars)")
            print(f"  2021 bull run only: {bull_result}")
            results.append(bull_result)
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"label": orig_symbol, "status": f"error: {e}"})
        time.sleep(0.5)

    print("\n===== FULL RESULTS TABLE (copy this whole block) =====")
    print("label,status,num_trades,num_closed,wins,losses,win_rate,total_R,profit_factor,candles")
    for r in results:
        print(",".join(str(r.get(k, "")) for k in
              ["label", "status", "num_trades", "num_closed", "wins", "losses", "win_rate", "total_R", "profit_factor", "candles"]))


if __name__ == "__main__":
    main()
