"""
Batch backtest runner.

This is the piece that actually does the work end to end:
  1. Get the list of coins to test (either all BingX symbols, or a fixed list you give it)
  2. For each coin, pull its historical price candles from BingX
  3. Run the OB->ROB strategy logic against that coin's history
  4. Record the results (win rate, profit factor, total trades) for that coin
  5. Once every coin is done, save one big results table

This only works when run somewhere with real internet access (e.g. on Render) -
it will NOT successfully reach BingX from this sandbox.

HOW TO RUN (once deployed):
    python run_batch_backtest.py

Output: results.csv - one row per coin, with its backtest performance.
"""

import time
from datetime import datetime, timezone
import pandas as pd

from bingx_data import get_all_symbols, fetch_full_history
from ob_rob_strategy import run_ob_rob_backtest, summarize_trades

# ---- SETTINGS: adjust these as needed ----
INTERVAL = "4h"
START_DATE = "2024-01-01"   # fixed start date, same for every coin (fixes the
                            # "inconsistent timelines" problem from TradingView)
END_DATE = None             # None = up to now
MAX_COINS = None            # None = all available symbols, or set a number to limit
                            # for a quick test run (e.g. 20) before doing the full 300+


def to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def main():
    start_ms = to_ms(START_DATE)
    end_ms = to_ms(END_DATE) if END_DATE else int(time.time() * 1000)

    print("Fetching symbol list from BingX...")
    symbols = get_all_symbols()
    if MAX_COINS:
        symbols = symbols[:MAX_COINS]
    print(f"Testing {len(symbols)} symbols from {START_DATE} to now.")

    results = []

    for idx, symbol in enumerate(symbols):
        print(f"[{idx+1}/{len(symbols)}] {symbol} ...", end=" ")
        try:
            df = fetch_full_history(symbol, interval=INTERVAL, start_ms=start_ms, end_ms=end_ms)
            if len(df) < 50:
                print("skipped (not enough history)")
                results.append({"symbol": symbol, "status": "insufficient_history"})
                continue

            df = df.reset_index(drop=True)
            df["time"] = df.index  # bar_index-equivalent for the strategy function

            trades = run_ob_rob_backtest(df)
            summary = summarize_trades(trades)
            summary["symbol"] = symbol
            summary["status"] = "ok"
            summary["candles_tested"] = len(df)
            results.append(summary)
            print(f"done ({summary.get('num_closed', 0)} closed trades)")

        except Exception as e:
            print(f"error: {e}")
            results.append({"symbol": symbol, "status": f"error: {e}"})

        time.sleep(0.3)  # be polite to BingX's rate limit

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("profit_factor", ascending=False, na_position="last")
    results_df.to_csv("results.csv", index=False)
    print("\nSaved results.csv")
    print(results_df.head(20))


if __name__ == "__main__":
    main()
