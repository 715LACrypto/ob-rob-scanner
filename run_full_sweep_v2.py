"""
Full sweep across ALL BingX symbols, with drawdown and weekly-frequency added
on top of the original profit factor / win rate metrics.

Unlike run_batch_backtest.py (first sweep), this version also computes, per coin:
  - max_drawdown_R: the worst peak-to-trough losing stretch, in R
  - trades_per_week: how often valid setups actually occur
  - consistency_score: avg R per trade / volatility of trade outcomes
    (higher = steady edge, not one lucky trade carrying the whole record)

Drawdown/frequency are calculated INSIDE this script per coin, and only a
summary row per coin is output - not every individual trade - so the result
stays a manageable size even across all ~1150+ coins.

This only works with real internet access (Render), not from a local sandbox.
"""

import time
import statistics
from datetime import datetime, timezone
import pandas as pd

from bingx_data import fetch_full_history, get_all_symbols
from ob_rob_strategy import run_ob_rob_backtest

INTERVAL = "4h"
START_DATE = "2024-01-01"


def to_ms(date_str: str) -> int:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def calc_metrics(trades):
    closed = [t for t in trades if t.outcome is not None]
    if not closed:
        return None

    closed_sorted = sorted(closed, key=lambda t: t.exit_time)

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in closed_sorted:
        equity += t.pnl_r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    wins = [t for t in closed if t.outcome == "TP"]
    losses = [t for t in closed if t.outcome == "SL"]
    total_r = sum(t.pnl_r for t in closed)
    gross_win = sum(t.pnl_r for t in wins)
    gross_loss = abs(sum(t.pnl_r for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float('inf')

    exit_times = [pd.to_datetime(t.exit_time, unit="ms") for t in closed]
    date_range_days = max((max(exit_times) - min(exit_times)).days, 1)
    weeks_spanned = max(date_range_days / 7, 1)
    trades_per_week = len(closed) / weeks_spanned

    r_values = [t.pnl_r for t in closed]
    avg_r = total_r / len(closed)
    std_r = statistics.stdev(r_values) if len(r_values) > 1 else 0
    consistency = (avg_r / std_r) if std_r > 0 else 0

    return {
        "num_trades": len(trades),
        "num_closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed),
        "total_R": total_r,
        "profit_factor": profit_factor,
        "avg_R_per_trade": avg_r,
        "max_drawdown_R": max_dd,
        "trades_per_week": trades_per_week,
        "consistency_score": consistency,
    }


def main():
    start_ms = to_ms(START_DATE)
    end_ms = int(time.time() * 1000)

    print("Fetching full symbol list from BingX...")
    symbols = get_all_symbols()
    print(f"Testing {len(symbols)} symbols from {START_DATE} to now, with drawdown + frequency analysis.")

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
            trades = run_ob_rob_backtest(df)
            metrics = calc_metrics(trades)

            if metrics is None:
                print("done (0 closed trades)")
                results.append({"symbol": symbol, "status": "no_closed_trades"})
                continue

            metrics["symbol"] = symbol
            metrics["status"] = "ok"
            metrics["candles_tested"] = len(df)
            results.append(metrics)
            print(f"done ({metrics['num_closed']} closed, max_dd={metrics['max_drawdown_R']:.1f}R, {metrics['trades_per_week']:.2f}/wk)")

        except Exception as e:
            print(f"error: {e}")
            results.append({"symbol": symbol, "status": f"error: {e}"})

        time.sleep(0.3)

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("profit_factor", ascending=False, na_position="last")
    results_df.to_csv("results_with_drawdown.csv", index=False)

    print("\n===== FULL RESULTS WITH DRAWDOWN (copy everything between the START/END markers) =====")
    print("=====CSV_START=====")
    print(results_df.to_csv(index=False))
    print("=====CSV_END=====")


if __name__ == "__main__":
    main()
