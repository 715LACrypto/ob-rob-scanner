"""
Just tests GRAM-USDT on its own (the coin we had wrong as "GRANTOM").
Same metrics, same bull/bear split as the full test. Run this on Render.
"""

from run_full_professional_backtest import run_with_regime_split
from bingx_data import fetch_full_history as fetch_bingx


def main():
    results = []
    print("[GRAM-USDT]")
    df = fetch_bingx("GRAM-USDT", interval="4h")
    print(f"  candles: {len(df)}")
    run_with_regime_split(df, "GRAM-USDT", ma_period=1200, results=results)


if __name__ == "__main__":
    main()
