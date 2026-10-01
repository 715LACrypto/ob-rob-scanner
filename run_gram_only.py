"""
Just tests GRAMTON-USDT on its own.
Same metrics, same bull/bear split as the full test. Run this on Render.
"""

from run_full_professional_backtest import run_with_regime_split
from bingx_data import fetch_full_history as fetch_bingx


def main():
    results = []
    print("[GRAMTON-USDT]")
    df = fetch_bingx("GRAMTON-USDT", interval="4h")
    print(f"  candles: {len(df)}")
    run_with_regime_split(df, "GRAMTON-USDT", ma_period=1200, results=results)


if __name__ == "__main__":
    main()
