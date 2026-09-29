"""
Settle the BB confusion with real data instead of guessing:
1. Is NCSKBB2USD-USDT (the one in the final 14-coin list) still a live symbol on BingX?
2. What does BBUS-USDT (the one on Logan's actual chart) backtest to?

Run this on Render - it needs real internet access to BingX.
"""

import time
from datetime import datetime, timezone
from bingx_data import get_all_symbols, fetch_full_history
from ob_rob_strategy import run_ob_rob_backtest, summarize_trades

INTERVAL = "4h"
START_DATE = "2024-01-01"


def to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def main():
    live_symbols = get_all_symbols()
    print(f"Live symbol count from BingX right now: {len(live_symbols)}")

    print(f"\nIs NCSKBB2USD-USDT still live? {'YES' if 'NCSKBB2USD-USDT' in live_symbols else 'NO - NOT FOUND, likely delisted/renamed'}")

    all_bb = [s for s in live_symbols if "BB" in s.upper()]
    print(f"\nAll symbols currently containing 'BB': {all_bb}")

    start_ms = to_ms(START_DATE)
    end_ms = int(time.time() * 1000)

    for symbol in ["BBUS-USDT"]:
        print(f"\nTesting {symbol} ...")
        try:
            df = fetch_full_history(symbol, interval=INTERVAL, start_ms=start_ms, end_ms=end_ms)
            if df is None or len(df) < 50:
                print(f"  -> not enough history ({0 if df is None else len(df)} candles)")
                continue
            df = df.reset_index(drop=True)
            df["time"] = df.index
            trades = run_ob_rob_backtest(df)
            summary = summarize_trades(trades)
            summary["symbol"] = symbol
            summary["candles_tested"] = len(df)
            print(f"  -> {summary}")
        except Exception as e:
            print(f"  -> ERROR: {e}")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
