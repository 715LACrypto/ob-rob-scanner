"""
Searches BingX's live symbol list for anything containing "GRAM" so we can
find the real symbol name instead of guessing again. Run this on Render.
"""

from bingx_data import get_all_symbols


def main():
    symbols = get_all_symbols()
    print(f"total symbols: {len(symbols)}")
    matches = [s for s in symbols if "GRAM" in s.upper()]
    print(f"matches containing GRAM: {matches}")


if __name__ == "__main__":
    main()
