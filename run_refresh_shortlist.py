"""
Refreshed backtest of the narrowed coin list, using TODAY as the end date instead
of whenever the original 1156-coin sweep was run. Same window start (2024-01-01),
just extended forward to catch anything that's happened since - including any
recent strong bullish move - so we can see if it changed the numbers.

Uses the real, verified symbol names (confirmed against BingX's live symbol list).

Run this on Render - it needs real internet access to BingX.
"""

import time
from datetime import datetime, timezone
import pandas as pd

from bingx_data import fetch_full_history
from ob_rob_strategy import run_ob_rob_backtest, summarize_trades

SYMBOLS = [
    "DOT-USDT", "IOTA-USDT", "YFI-USDT",
    "WLFI-USDT", "WLFI-USDC",
    "0G-USDT", "GRAMTON-USDT",
    "NCSKTSLA2USD-USDT", "NCSKQCOM2USD-USDT", "NCSKSKHYNIX2USD-USDT",
]

INTERVAL = "4h"
START_DATE = "2024-01-01"


def to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def main():
    start_ms = to_ms(START_DATE)
    end_ms = int(time.time() * 1000)

    results = []
    for idx, symbol in enumerate(SYMBOLS):
        print(f"[{idx+1}/{len(SYMBOLS)}] {symbol} ...", end=" ")
        try:
            df = fetch_full_history(symbol, interval=INTERVAL, start_ms=start_ms, end_ms=end_ms)
            if len(df) < 50:
                print("skipped (not enough history)")
                results.append({"symbol": symbol, "status": "insufficient_history"})
                continue

            df = df.reset_index(drop=True)
            df["time"] = df.index

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

        time.sleep(0.3)

    print("\n===== REFRESHED RESULTS (copy this whole block) =====")
    print("symbol,status,num_trades,num_closed,wins,losses,win_rate,total_R,profit_factor,candles_tested")
    for r in results:
        if r.get("status") == "ok":
            print(f"{r['symbol']},{r['status']},{r.get('num_trades')},{r.get('num_closed')},{r.get('wins')},{r.get('losses')},{r.get('win_rate')},{r.get('total_R')},{r.get('profit_factor')},{r.get('candles_tested')}")
        else:
            print(f"{r['symbol']},{r['status']},,,,,,,,")


if __name__ == "__main__":
    main()
