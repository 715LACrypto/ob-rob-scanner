"""
Full professional backtest on EVERY BingX symbol (crypto + tokenized stocks/commodities/indices),
using the furthest-back price history available for each one.

Usage on Render:   python run_full_universe_backtest.py <start> <end>
  e.g.             python run_full_universe_backtest.py 0 100
Run in chunks of ~100 symbols. Each chunk prints a CSV block at the end AND
streams one CSV line per row as it goes, so nothing is lost if a job dies.

Data source per symbol (the one with the most history wins):
  crypto            -> Binance spot (4h) vs BingX perp (4h): whichever has more candles
  tokenized stocks  -> real stock via yfinance (daily, full history since IPO);
                       falls back to BingX 4h if yfinance has nothing
  commodities/index -> real futures/index via yfinance (daily); falls back to BingX 4h

Bull / bear split:
  MA = 200 real days. 1200 bars on 4h data, 200 bars on daily data.
  Close above its own MA = bull, below = bear. Each trade is tagged by the regime
  on its OB candle (same convention as the earlier approved-coin backtest).
  Trades in the first 200 days of a coin's history have no MA yet: they count in ALL only.

Sizing: every entry counts as 1R (as requested).
No fees / slippage / funding are modelled.
"""

import sys
import time
import statistics
import pandas as pd

from ob_rob_strategy import run_ob_rob_backtest

MS_PER_YEAR = 365.25 * 24 * 3600 * 1000

COLS = ["symbol", "source", "timeframe", "candles", "years_of_history", "regime",
        "num_closed", "wins", "losses", "win_rate", "total_R", "profit_factor",
        "avg_R_per_trade", "max_drawdown_R", "max_consec_losses", "largest_win_R",
        "largest_loss_R", "trades_per_week", "consistency_score", "recovery_factor"]

# tokenized-stock / commodity / index name -> yfinance ticker
SPECIAL_TICKERS = {
    "SKHYNIX": "000660.KS",
    "OILBRENT": "BZ=F", "OILWTI": "CL=F", "HEATINGOIL": "HO=F",
    "PALLADIUM": "PA=F", "XAG": "SI=F", "XPT": "PL=F", "XAU": "GC=F",
    "NATGAS": "NG=F", "COPPER": "HG=F",
    "NIKKEI225": "^N225",
}


def calc_metrics(trades):
    closed = [t for t in trades if t.outcome is not None]
    if not closed:
        return None
    closed_sorted = sorted(closed, key=lambda t: t.exit_time)
    equity = peak = max_dd = 0.0
    consec = max_consec = 0
    for t in closed_sorted:
        equity += t.pnl_r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
        if t.outcome == "SL":
            consec += 1
            max_consec = max(max_consec, consec)
        else:
            consec = 0
    wins = [t for t in closed if t.outcome == "TP"]
    losses = [t for t in closed if t.outcome == "SL"]
    total_r = sum(t.pnl_r for t in closed)
    gross_win = sum(t.pnl_r for t in wins)
    gross_loss = abs(sum(t.pnl_r for t in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    exit_times = [pd.to_datetime(t.exit_time, unit="ms") for t in closed]
    days = max((max(exit_times) - min(exit_times)).days, 1)
    weeks = max(days / 7, 1)
    r_vals = [t.pnl_r for t in closed]
    avg_r = total_r / len(closed)
    std_r = statistics.stdev(r_vals) if len(r_vals) > 1 else 0
    return {
        "num_closed": len(closed), "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(closed), 3),
        "total_R": round(total_r, 2),
        "profit_factor": round(pf, 2) if pf != float("inf") else "inf",
        "avg_R_per_trade": round(avg_r, 3),
        "max_drawdown_R": round(max_dd, 2),
        "max_consec_losses": max_consec,
        "largest_win_R": round(max((t.pnl_r for t in wins), default=0), 2),
        "largest_loss_R": round(min((t.pnl_r for t in losses), default=0), 2),
        "trades_per_week": round(len(closed) / weeks, 2),
        "consistency_score": round(avg_r / std_r, 3) if std_r > 0 else 0,
        "recovery_factor": round(total_r / max_dd, 2) if max_dd > 0 else "inf",
    }


def regime_labels(df, ma_period):
    close = pd.Series(df["close"].values)
    ma = close.rolling(window=ma_period, min_periods=ma_period).mean().values
    cv = close.values
    out = []
    for i in range(len(df)):
        if pd.isna(ma[i]):
            out.append(None)
        else:
            out.append("bull" if cv[i] > ma[i] else "bear")
    return out


# ---------------- data loading ----------------

def binance_candidates(bingx_symbol):
    base, quote = bingx_symbol.rsplit("-", 1)
    names = [base + quote]
    for pre in ("1000000", "10000", "1000"):
        if base.startswith(pre):
            names.append(base[len(pre):] + quote)
    return names


def load_crypto(bingx_symbol):
    """Return (df, source, timeframe, ma_period) with the most history available."""
    from bingx_data import fetch_full_history as fetch_bingx
    from binance_data import fetch_full_history as fetch_binance

    best = None
    try:
        d = fetch_bingx(bingx_symbol, interval="4h")
        if len(d):
            best = (d, "BingX perp", "4h", 1200)
    except Exception as e:
        print(f"    bingx fetch failed: {e}", flush=True)

    for name in binance_candidates(bingx_symbol):
        try:
            d = fetch_binance(name, interval="4h")
        except Exception:
            continue
        if len(d) and (best is None or len(d) > len(best[0])):
            best = (d, f"Binance spot {name}", "4h", 1200)
            break
    return best


def stock_ticker(bingx_symbol):
    """NCSKTSLA2USD-USDT -> TSLA, NCCOXAG2USD-USDT -> XAG etc."""
    core = bingx_symbol.split("-")[0]
    core = core[4:]                      # drop NCSK / NCCO / NCSI
    if core.endswith("2USD"):
        core = core[:-4]
    return core


def load_traditional(bingx_symbol):
    from stock_data import fetch_full_history as fetch_stock
    from bingx_data import fetch_full_history as fetch_bingx

    name = stock_ticker(bingx_symbol)
    ticker = SPECIAL_TICKERS.get(name, name)
    try:
        d = fetch_stock(ticker, start="1970-01-01")
        if len(d) >= 250:
            return (d, f"yfinance {ticker}", "1d", 200)
    except Exception as e:
        print(f"    yfinance failed for {ticker}: {e}", flush=True)
    d = fetch_bingx(bingx_symbol, interval="4h")
    if len(d):
        return (d, "BingX perp (no stock history found)", "4h", 1200)
    return None


def is_traditional(sym):
    return sym.startswith(("NCSK", "NCCO", "NCSI"))


# ---------------- run ----------------

def run_symbol(sym, out_rows):
    loaded = load_traditional(sym) if is_traditional(sym) else load_crypto(sym)
    if loaded is None:
        print(f"  {sym}: NO DATA", flush=True)
        return
    df, source, tf, ma_period = loaded
    df = df.reset_index(drop=True)
    years = round((df["time"].iloc[-1] - df["time"].iloc[0]) / MS_PER_YEAR, 2)
    regimes = regime_labels(df, ma_period)
    trades = run_ob_rob_backtest(df)
    sets = (("ALL", trades),
            ("BULL", [t for t in trades if regimes[t.ob_idx] == "bull"]),
            ("BEAR", [t for t in trades if regimes[t.ob_idx] == "bear"]))
    print(f"  {sym}: {len(df)} candles, {years}y, {source}, {len(trades)} entries", flush=True)
    for name, ts in sets:
        m = calc_metrics(ts) or {}
        row = {"symbol": sym, "source": source, "timeframe": tf, "candles": len(df),
               "years_of_history": years, "regime": name}
        row.update(m)
        if not m:
            row["num_closed"] = 0
        out_rows.append(row)
        print("ROW," + ",".join(str(row.get(c, "")) for c in COLS), flush=True)


def main():
    from bingx_data import get_all_symbols
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    symbols = sorted(get_all_symbols())
    print(f"Total BingX symbols: {len(symbols)}. This chunk: {start} to {end}", flush=True)
    chunk = symbols[start:end]
    rows = []
    for i, sym in enumerate(chunk, 1):
        try:
            run_symbol(sym, rows)
        except Exception as e:
            print(f"  {sym}: FAILED {type(e).__name__}: {e}", flush=True)
        time.sleep(0.2)
        if i % 10 == 0:
            print(f"--- progress {i}/{len(chunk)} ---", flush=True)

    print("\n===== FULL RESULTS (copy everything below) =====")
    print(",".join(COLS))
    for r in rows:
        print(",".join(str(r.get(c, "")) for c in COLS))
    print("===== END =====")


if __name__ == "__main__":
    main()
