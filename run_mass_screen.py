"""
Screens every BingX symbol (not just the 14), using each symbol's FULL
available BingX history (not just 2024-present), same bull/bear split as
before, and the same statistical rigor used for the original 14-coin list:
a binomial significance test per symbol, then Benjamini-Hochberg correction
across ALL symbols tested (so we don't just find noise by testing 1000+
coins at once - some will look good by pure chance).

Only symbols that are BOTH statistically significant AND actually
profitable (PF > 1.2, enough trades) get printed - otherwise the output
for 1239 symbols would be unreadable.

Runs in BATCHES by index range, since 1239 symbols in one go will likely
time out on Render. Usage:

    python run_mass_screen.py <start_index> <end_index>

Example: python run_mass_screen.py 0 150
Then:    python run_mass_screen.py 150 300
...and so on until you've covered all symbols (the script prints the
total count on first run so you know how many batches you need).

Run this on Render.
"""

import sys
import time
import math
import statistics
import pandas as pd

from bingx_data import get_all_symbols, fetch_full_history
from ob_rob_strategy import run_ob_rob_backtest


MIN_CANDLES = 500       # skip symbols with barely any history
MIN_CLOSED_TRADES = 30  # too few trades = can't trust the number
PF_BAR = 1.2             # below this, not worth real money regardless of significance
ALPHA = 0.05             # significance level for BH correction


def binomial_p_value(wins, n, p0):
    """One-sided p-value: probability of seeing >= wins successes out of n
    trials if the true win rate were only p0 (breakeven). Uses normal
    approximation (fine for n >= ~20, which MIN_CLOSED_TRADES already ensures)."""
    if n == 0:
        return 1.0
    mean = n * p0
    var = n * p0 * (1 - p0)
    if var <= 0:
        return 1.0
    z = (wins - 0.5 - mean) / math.sqrt(var)  # continuity correction
    # one-sided upper tail p-value from z, via erfc
    p = 0.5 * math.erfc(z / math.sqrt(2))
    return max(min(p, 1.0), 0.0)


def analyze_symbol(symbol):
    try:
        df = fetch_full_history(symbol, interval="4h")
    except Exception as e:
        return None
    if df is None or len(df) < MIN_CANDLES:
        return None

    df = df.reset_index(drop=True)
    trades = run_ob_rob_backtest(df)
    closed = [t for t in trades if t.outcome is not None]
    if len(closed) < MIN_CLOSED_TRADES:
        return None

    wins = [t for t in closed if t.outcome == "TP"]
    losses = [t for t in closed if t.outcome == "SL"]
    win_rate = len(wins) / len(closed)
    total_r = sum(t.pnl_r for t in closed)
    gross_win = sum(t.pnl_r for t in wins)
    gross_loss = abs(sum(t.pnl_r for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float('inf')

    avg_win_r = (gross_win / len(wins)) if wins else 0
    breakeven_win_rate = 1 / (1 + avg_win_r) if avg_win_r > 0 else 1.0
    p_value = binomial_p_value(len(wins), len(closed), breakeven_win_rate)

    return {
        "symbol": symbol,
        "candles": len(df),
        "closed": len(closed),
        "win_rate": round(win_rate, 3),
        "total_R": round(total_r, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else 999,
        "breakeven_win_rate": round(breakeven_win_rate, 3),
        "p_value": p_value,
    }


def benjamini_hochberg(results, alpha=ALPHA):
    """Standard BH correction across all p-values. Returns the results that
    survive at the given false-discovery rate."""
    m = len(results)
    if m == 0:
        return []
    sorted_results = sorted(results, key=lambda r: r["p_value"])
    survivors = []
    max_rank_passed = 0
    for i, r in enumerate(sorted_results):
        rank = i + 1
        threshold = (rank / m) * alpha
        if r["p_value"] <= threshold:
            max_rank_passed = rank
    for i, r in enumerate(sorted_results[:max_rank_passed]):
        survivors.append(r)
    return survivors


def main():
    if len(sys.argv) != 3:
        print("Usage: python run_mass_screen.py <start_index> <end_index>")
        sys.exit(1)
    start_idx = int(sys.argv[1])
    end_idx = int(sys.argv[2])

    all_symbols = get_all_symbols()
    print(f"total BingX symbols: {len(all_symbols)}")
    batch = all_symbols[start_idx:end_idx]
    print(f"this batch: index {start_idx} to {end_idx} ({len(batch)} symbols)")

    all_results = []
    for i, symbol in enumerate(batch):
        result = analyze_symbol(symbol)
        if result:
            all_results.append(result)
        if (i + 1) % 25 == 0:
            print(f"  ...progress: {i+1}/{len(batch)} screened, {len(all_results)} passed the basic filters so far")
        time.sleep(0.3)

    print(f"\nsymbols with enough data and trades to test: {len(all_results)}")

    survivors = benjamini_hochberg(all_results)
    print(f"survive significance correction: {len(survivors)}")

    real_candidates = [r for r in survivors if r["profit_factor"] >= PF_BAR]
    real_candidates.sort(key=lambda r: r["profit_factor"], reverse=True)

    print(f"\n===== REAL CANDIDATES (significant AND profit factor >= {PF_BAR}) =====")
    if not real_candidates:
        print("none in this batch")
    for r in real_candidates:
        print(r)


if __name__ == "__main__":
    main()
