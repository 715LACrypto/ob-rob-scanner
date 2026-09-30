"""
The full, proper backtest - every metric a real trader/firm would check:

  - profit_factor, win_rate, total_R  (the basics, total_R = "total RR")
  - max_drawdown_R                    (worst losing stretch, peak to bottom)
  - consistency_score                 (avg R per trade / volatility of results)
  - trades_per_week                   (how often it actually fires)

Two things fixed from the last version:

1. TRUE full history for every asset - no arbitrary start date. Crypto pulls
   from whenever Binance actually has data (real listing date). Stocks pull
   from 1970 (Yahoo just returns whatever real history exists from the
   actual IPO onward - NVDA from 1999, QCOM from 1991, etc, not a guessed
   cutoff).

2. Bull vs bear is no longer assumed by calendar year (2021=bull, 2022=bear
   was a guess, not proof). Instead, EVERY candle is classified using that
   asset's OWN 200-day moving average: price above its own MA at that moment
   = bull period, below = bear period. Each trade is then sorted into
   "happened during a bull period" or "happened during a bear period" based
   on real price data at that exact moment, not an assumed year label.

Run this on Render.
"""

import time
import statistics
import pandas as pd

from ob_rob_strategy import run_ob_rob_backtest


def calc_metrics(trades):
    closed = [t for t in trades if t.outcome is not None]
    if not closed:
        return {"status": "no_closed_trades", "num_trades": len(trades), "num_closed": 0}

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
        "status": "ok",
        "num_trades": len(trades),
        "num_closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(closed), 3),
        "total_R": round(total_r, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float('inf') else "inf",
        "avg_R_per_trade": round(avg_r, 3),
        "max_drawdown_R": round(max_dd, 2),
        "trades_per_week": round(trades_per_week, 2),
        "consistency_score": round(consistency, 3),
    }


def classify_regime(df, ma_period):
    """
    Returns an array the same length as df: 'bull' where close is above its
    own rolling moving average at that point, 'bear' where below, None where
    there isn't enough history yet to compute the average.
    """
    ma = pd.Series(df['close'].values).rolling(window=ma_period, min_periods=ma_period).mean().values
    regime = []
    for i in range(len(df)):
        if pd.isna(ma[i]):
            regime.append(None)
        elif df['close'].values[i] > ma[i]:
            regime.append("bull")
        else:
            regime.append("bear")
    return regime


def run_with_regime_split(df, label, ma_period, results):
    df = df.reset_index(drop=True)
    regime = classify_regime(df, ma_period)

    all_trades = run_ob_rob_backtest(df)

    bull_trades = [t for t in all_trades if regime[t.ob_idx] == "bull"]
    bear_trades = [t for t in all_trades if regime[t.ob_idx] == "bear"]

    for name, trades in (("ALL (full history)", all_trades),
                          ("BULL periods only", bull_trades),
                          ("BEAR periods only", bear_trades)):
        m = calc_metrics(trades)
        m["label"] = label
        m["regime"] = name
        results.append(m)
        print(f"  {name}: {m}")


def main():
    results = []

    from binance_data import fetch_full_history as fetch_binance
    CRYPTO = {"DOT-USDT": "DOTUSDT", "YFI-USDT": "YFIUSDT", "IOTA-USDT": "IOTAUSDT"}
    print("===== CRYPTO (via Binance, true full history since listing) =====")
    for orig_symbol, binance_symbol in CRYPTO.items():
        print(f"\n[{orig_symbol}]")
        df = fetch_binance(binance_symbol, interval="4h")  # no start_ms = earliest available
        print(f"  candles: {len(df)}")
        run_with_regime_split(df, orig_symbol, ma_period=1200, results=results)  # 1200x4h = 200 days
        time.sleep(0.5)

    from stock_data import fetch_full_history as fetch_stock
    STOCKS = {
        "NCSKRDW2USD-USDT": "RDW", "NCSKNVD2USD-USDT": "NVDA", "NCSKBB2USD-USDT": "BB",
        "NCSKTTWO2USD-USDT": "TTWO", "NCSKQCOM2USD-USDT": "QCOM", "NCSKTSLA2USD-USDT": "TSLA",
        "NCSKSKHYNIX2USD-USDT": "000660.KS",
    }
    print("\n===== TOKENIZED STOCKS (via real stock price, true full history since IPO) =====")
    for orig_symbol, ticker in STOCKS.items():
        print(f"\n[{orig_symbol}] via {ticker}")
        df = fetch_stock(ticker, start="1970-01-01")  # Yahoo just returns from actual IPO onward
        print(f"  candles: {len(df)}")
        run_with_regime_split(df, orig_symbol, ma_period=200, results=results)  # daily bars = 200 real days
        time.sleep(0.5)

    print("\n===== FULL RESULTS TABLE (copy this whole block) =====")
    cols = ["label", "regime", "status", "num_trades", "num_closed", "wins", "losses",
            "win_rate", "total_R", "profit_factor", "avg_R_per_trade", "max_drawdown_R",
            "trades_per_week", "consistency_score"]
    print(",".join(cols))
    for r in results:
        print(",".join(str(r.get(c, "")) for c in cols))


if __name__ == "__main__":
    main()
