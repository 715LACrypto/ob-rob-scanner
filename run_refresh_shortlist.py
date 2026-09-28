"""
Refreshed backtest of the FULL 14-coin Benjamini-Hochberg survivor list, using
TODAY as the end date instead of whenever the original sweep was run. Same
start date (2024-01-01), extended forward to catch anything that's happened
since - including any recent strong bullish move.

Run this on Render - it needs real internet access to BingX.
"""

import time
from datetime import datetime, timezone
from bingx_data import get_all_symbols, fetch_full_history
from ob_rob_strategy import run_ob_rob_backtest, summarize_trades

SYMBOLS = [
    "NCSKRDW2USD-USDT", "NCSKNVD2USD-USDT", "NCSKBB2USD-USDT",
    "GRAMTON-USDT", "NCSKTTWO2USD-USDT",
    "NCSKSKHYNIX2USD-USDT", "NCSKQCOM2USD-USDT", "NCSKTSLA2USD-USDT",
    "WLFI-USDT", "0G-USDT", "WLFI-USDC",
    "YFI-USDT", "DOT-USDT", "IOTA-USDT",
]

INTERVAL = "4h"
START_DATE = "2024-01-01"


def to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def main():
    live_symbols = set(get_all_symbols())
    print(f"Live symbol count from BingX right now: {len(live_symbols)}")
    for s in SYMBOLS:
        print(f"  {s}: {'FOUND' if s in live_symbols else 'NOT FOUND ON BINGX RIGHT NOW'}")

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
