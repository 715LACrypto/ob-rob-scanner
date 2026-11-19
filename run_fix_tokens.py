"""
Reruns ONLY the tokenized stocks / commodities / indices that got short BingX history
(or no data) the first time because their BingX name didn't match a Yahoo ticker.

Usage on Render:   python run_fix_tokens.py
Needs run_full_universe_backtest.py in the same folder. Nothing in it is changed.
"""

import time
import run_full_universe_backtest as rfu

TICKER_MAP = {
    "NCCO1OILBRENT2USD-USDT": "BZ=F",
    "NCCO1OILWTI2USD-USDT": "CL=F",
    "NCCO7241NATGAS2USD-USDT": "NG=F",
    "NCCO724COPPER2USD-USDT": "HG=F",
    "NCSIDOWJONES2USD-USDT": "^DJI",
    "NCSIDXY2USD-USDT": "DX-Y.NYB",
    "NCSIKOSPI2USD-USDT": "^KS11",
    "NCSINASDAQ1002USD-USDT": "^NDX",
    "NCSIRUSSELL20002USD-USDT": "^RUT",
    "NCSISP5002USD-USDT": "^GSPC",
    "NCSIGER2USD-USDT": "^GDAXI",
    "NCSINIFTY52USD-USDT": "^NSEI",
    "NCSINIFTYBK2USD-USDT": "^NSEBANK",
    "NCSKADVANTEST2USD-USDT": "6857.T",
    "NCSKBRKB2USD-USDT": "BRK-B",
    "NCSKCISCO2USD-USDT": "CSCO",
    "NCSKHANMI2USD-USDT": "042700.KS",
    "NCSKHYUNDAI2USD-USDT": "005380.KS",
    "NCSKKIOXIA2USD-USDT": "285A.T",
    "NCSKKODEX2002USD-USDT": "069500.KS",
    "NCSKLASERTEC2USD-USDT": "6920.T",
    "NCSKLGELE2USD-USDT": "066570.KS",
    "NCSKMURATA2USD-USDT": "6981.T",
    "NCSKNAVER2USD-USDT": "035420.KS",
    "NCSKNETFLIX2USD-USDT": "NFLX",
    "NCSKNUGTUSDT-USDT": "NUGT",
    "NCSKPAYP2USD-USDT": "PYPL",
    "NCSKSAMSUNG2USD-USDT": "005930.KS",
    "NCSKSAMSUNGEM2USD-USDT": "009150.KS",
    "NCSKSATLUSDT-USDT": "SATL",
    "NCSKSITMUSDT-USDT": "SITM",
    "NCSKSOFTBANK2JPY-USDT": "9984.T",
    "NCSKSOXS12USD-USDT": "SOXS",
    "NCSKTBTUSDT-USDT": "TBT",
    "NCSKTMFUSDT-USDT": "TMF",
    "NCSKAXONUSDT-USDT": "AXON",
    "NCSKBOILUSDT-USDT": "BOIL",
    "NCSKBUDUSDT-USDT": "BUD",
}

RETRY_AS_IS = [
    "NCSKAAOX2USD-USDT", "NCSKCOHX2USD-USDT", "NCSKDISK2USD-USDT", "NCSKEUV2USD-USDT",
    "NCSKFPS2USD-USDT", "NCSKFRVO2USD-USDT", "NCSKKVUE2USD-USDT", "NCSKLITX2USD-USDT",
    "NCSKMRNX2USD-USDT", "NCSKPURR2USD-USDT",
    "OPENEDEN-USDT", "TA-USDT",
]

_orig_stock_ticker = rfu.stock_ticker
rfu.stock_ticker = lambda sym: TICKER_MAP.get(sym) or _orig_stock_ticker(sym)


def main():
    symbols = list(TICKER_MAP) + RETRY_AS_IS
    print(f"Rerunning {len(symbols)} symbols", flush=True)
    rows = []
    for i, sym in enumerate(symbols, 1):
        try:
            rfu.run_symbol(sym, rows)
        except Exception as e:
            print(f"  {sym}: FAILED {type(e).__name__}: {e}", flush=True)
        time.sleep(1.0)
        if i % 10 == 0:
            print(f"--- progress {i}/{len(symbols)} ---", flush=True)

    print("\n===== FULL RESULTS (copy everything below) =====")
    print(",".join(rfu.COLS))
    for r in rows:
        print(",".join(str(r.get(c, "")) for c in rfu.COLS))
    print("===== END =====")


if __name__ == "__main__":
    main()
