"""
Trade-by-trade log for NCSKBB2USD-USDT specifically, with REAL dates on every
trade - so we can directly compare against what TradingView's own strategy
tester shows, instead of comparing summary totals.

Run this on Render - it needs real internet access to BingX.
"""

import time
from datetime import datetime, timezone
import pandas as pd

from bingx_data import fetch_full_history
from ob_rob_strategy import run_ob_rob_backtest

SYMBOL = "NCSKBB2USD-USDT"
INTERVAL = "4h"
START_DATE = "2024-01-01"


def to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def main():
    start_ms = to_ms(START_DATE)
    end_ms = int(time.time() * 1000)

    df = fetch_full_history(SYMBOL, interval=INTERVAL, start_ms=start_ms, end_ms=end_ms)
    print(f"Candles fetched: {len(df)}")
    if len(df) == 0:
        print("No data returned.")
        return

    df = df.reset_index(drop=True)
    df["time"] = df.index

    real_times = fetch_full_history(SYMBOL, interval=INTERVAL, start_ms=start_ms, end_ms=end_ms)
    real_times = real_times.reset_index(drop=True)

    trades = run_ob_rob_backtest(df)
    print(f"\nTotal trade objects: {len(trades)}")

    print("\n===== FULL TRADE LOG for NCSKBB2USD-USDT (copy this whole block) =====")
    print("ob_bar,entry_label,entry_price,sl,tp,fill_bar,fill_date,bars_from_ob,outcome,exit_bar,exit_date,pnl_r")
    for t in trades:
        fill_date = pd.to_datetime(real_times.loc[t.fill_idx, "time"], unit="ms") if t.fill_idx < len(real_times) else None
        exit_date = pd.to_datetime(real_times.loc[t.exit_idx, "time"], unit="ms") if t.exit_idx is not None and t.exit_idx < len(real_times) else None
        print(f"{t.ob_idx},{t.entry_label},{t.entry_price},{t.sl},{t.tp},{t.fill_idx},{fill_date},{t.bars_from_ob},{t.outcome},{t.exit_idx},{exit_date},{t.pnl_r}")


if __name__ == "__main__":
    main()
