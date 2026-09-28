"""
Step 1: Pull BingX's LIVE, current symbol list and match it to our 14 target coins
by name, so we get real, verified symbol strings instead of guessed ones.

Step 2: Re-run the same OB->ROB strategy on those verified symbols, but over an
OLDER time window instead of Jan 2024-present, to check if the edge holds up in
a different market regime (not just a different date range).

Run this on Render, same as before - it needs real internet access to BingX.
"""

import time
from datetime import datetime, timezone
from bingx_data import get_all_symbols, fetch_full_history
from ob_rob_strategy import run_ob_rob_backtest, summarize_trades

TARGETS = {
    "DOT": "crypto", "IOTA": "crypto", "YFI": "crypto",
    "WLFI": "crypto",
    "0G": "crypto", "GRAMTON": "crypto",
    "TSLA": "tokenized_stock", "QCOM": "tokenized_stock", "SKHYNIX": "tokenized_stock",
}

def find_real_symbols():
    live_symbols = get_all_symbols()
    print(f"Live symbol count from BingX right now: {len(live_symbols)}")
    matches = {}
    for key in TARGETS:
        found = [s for s in live_symbols if key.upper() in s.upper()]
        matches[key] = found
        print(f"Search term '{key}': found {found}")
    return matches

OLDER_START = "2021-01-01"
OLDER_END = "2022-12-31"

def to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)

def run_older_period_test(symbol):
    start_ms = to_ms(OLDER_START)
    end_ms = to_ms(OLDER_END)
    df = fetch_full_history(symbol, interval="4h", start_ms=start_ms, end_ms=end_ms)
    if df is None or len(df) < 100:
        return {"symbol": symbol, "status": "insufficient_history_for_older_period", "candles_found": 0 if df is None else len(df)}
    df = df.reset_index(drop=True)
    df["time"] = df.index
    trades = run_ob_rob_backtest(df)
    summary = summarize_trades(trades)
    summary["symbol"] = symbol
    summary["status"] = "ok"
    summary["candles_tested"] = len(df)
    return summary

if __name__ == "__main__":
    print("=== STEP 1: Verifying real current symbol names ===")
    matches = find_real_symbols()

    print("\n=== STEP 2: Running backtest on older period (2021-01-01 to 2022-12-31) ===")
    results = []
    for key, symbols in matches.items():
        for sym in symbols:
            print(f"Testing {sym} on older period...")
            try:
                r = run_older_period_test(sym)
                results.append(r)
                print(f"  -> {r}")
            except Exception as e:
                print(f"  -> ERROR: {e}")
            time.sleep(1)

    print("\n===== OLDER-PERIOD RESULTS (copy this whole block) =====")
    print("symbol,status,num_trades,num_closed,wins,losses,win_rate,total_R,profit_factor,avg_R_per_trade,max_drawdown_R,candles_tested")
    for r in results:
        if r.get("status") == "ok":
            print(f"{r['symbol']},{r['status']},{r.get('num_trades')},{r.get('num_closed')},{r.get('wins')},{r.get('losses')},{r.get('win_rate')},{r.get('total_R')},{r.get('profit_factor')},{r.get('avg_R_per_trade')},{r.get('max_drawdown_R')},{r.get('candles_tested')}")
        else:
            print(f"{r['symbol']},{r['status']},,,,,,,,,,{r.get('candles_found')}")
