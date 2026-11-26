"""
OB -> ROB SHORT live trading bot for BingX perpetual futures.

Run it on Render as a Cron Job every 15 minutes:   */15 * * * *
Command:   python run_live_bot.py
Read-only connection test:   python run_live_bot.py check

It is stateless. Every run it:
  1. pulls the latest closed 4h candles for each approved coin,
  2. re-runs the strategy to find live setups (ROBs),
  3. places 3 limit SELL orders (top / mid / bottom of the OB candle) with the stop loss
     and take profit attached, for new setups, within the risk limits,
  4. cancels orders for setups that have expired or finished,
  5. checks every open short has a stop loss (adds one if missing).

Settings come from Render Environment variables (all optional except the two keys):
  BINGX_API_KEY, BINGX_API_SECRET   your BingX API key (trading permission, NO withdrawals)
  DRY_RUN            "1" (default) = log only, place nothing.  Set to "0" for REAL orders.
  RISK_PCT           % of account equity risked per setup in total (default 1.0). Split over 3 entries.
  MAX_OPEN_SETUPS    max setups open at once (default 4)
  LEVERAGE           leverage set on each coin, isolated margin (default 5)
  INCLUDE_TIER_B     "1" = also trade the Tier B watch list (default 0)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   optional, sends a message for every action
"""

import os
import sys
import json
import time
import hmac
import hashlib
import math
import traceback
import requests
import pandas as pd

# ------------------------------------------------------------------ settings
BASE = "https://open-api.bingx.com"
API_KEY = os.environ.get("BINGX_API_KEY", "").strip()
API_SECRET = os.environ.get("BINGX_API_SECRET", "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "1") != "0"
RISK_PCT = float(os.environ.get("RISK_PCT", "1.0")) / 100.0
MAX_OPEN_SETUPS = int(os.environ.get("MAX_OPEN_SETUPS", "4"))
LEVERAGE = int(os.environ.get("LEVERAGE", "5"))          # only used if AUTO_LEVERAGE=0
AUTO_LEVERAGE = os.environ.get("AUTO_LEVERAGE", "1") == "1"
MAX_LEVERAGE = int(os.environ.get("MAX_LEVERAGE", "20"))  # hard cap for auto leverage
INCLUDE_TIER_B = os.environ.get("INCLUDE_TIER_B", "1") == "1"
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# strategy rules (same as the backtest)
MIN_BARS, MAX_BARS, MIN_RISK = 10, 60, 0.02
CANDLE_MS = 4 * 3600 * 1000
ENTRY_LABELS = ("top", "mid", "bottom")

# Approved list, strongest evidence first. Edit freely.
TIER_A = ["ILV-USDT", "XLM-USDT", "ZK-USDT", "NEO-USDT", "AEVO-USDT",
          "LUNC-USDT", "QNT-USDT", "RVN-USDT", "YFI-USDT"]
TIER_B = ["WLFI-USDT", "POLYX-USDT", "CGPT-USDT", "ZIL-USDT", "0G-USDT", "ATH-USDT",
          "MANA-USDT", "NEAR-USDT", "PI-USDT", "STRK-USDT", "1000SHIB-USDT", "ONDO-USDT",
          "BTC-USDT", "ROSE-USDT", "XAI-USDT", "IMX-USDT", "1000PEPE-USDT", "MINA-USDT",
          "CAKE-USDT", "DOT-USDT", "F-USDT", "TURBO-USDT", "AVNT-USDT", "DEEP-USDT",
          "XPIN-USDT", "TAO-USDT"]


def approved_list():
    return TIER_A + (TIER_B if INCLUDE_TIER_B else [])


# ------------------------------------------------------------------ helpers
def now_ms():
    return int(time.time() * 1000)


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())} UTC] {msg}", flush=True)


def notify(msg):
    log("NOTIFY: " + msg)
    if TG_TOKEN and TG_CHAT:
        try:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": TG_CHAT, "text": msg}, timeout=10)
        except Exception as e:
            log(f"telegram failed: {e}")


class ApiError(Exception):
    pass


def api(method, path, params=None, auth=True):
    """Signed BingX request. Returns the 'data' part of the response."""
    params = dict(params or {})
    if auth:
        params["timestamp"] = now_ms()
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
    if auth:
        sig = hmac.new(API_SECRET.encode(), qs.encode(), hashlib.sha256).hexdigest()
        qs += f"&signature={sig}"
    headers = {"X-BX-APIKEY": API_KEY} if auth else {}
    resp = requests.request(method, f"{BASE}{path}?{qs}", headers=headers, timeout=15)
    try:
        body = resp.json()
    except Exception:
        raise ApiError(f"{path}: non-JSON response (HTTP {resp.status_code}): {resp.text[:200]}")
    code = body.get("code", 0)
    if code != 0:
        raise ApiError(f"{path}: code {code}: {body.get('msg')}")
    return body.get("data")


# ------------------------------------------------------------------ market data
def fetch_closed_candles(symbol, limit=500):
    data = api("GET", "/openApi/swap/v3/quote/klines",
               {"symbol": symbol, "interval": "4h", "limit": limit}, auth=False)
    if not data:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close"])
    df = pd.DataFrame(data)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)
    df["time"] = df["time"].astype("int64")
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    # drop the candle that is still forming
    df = df[df["time"] + CANDLE_MS <= now_ms()].reset_index(drop=True)
    return df[["time", "open", "high", "low", "close"]]


# ------------------------------------------------------------------ strategy state machine
def scan_series(df, skip_activation_fill=True):
    """
    Same logic as ob_rob_strategy.run_ob_rob_backtest, but returns the ROBs that are
    still live at the last candle. With skip_activation_fill=True (live mode) an entry
    cannot fill on the candle that confirms the setup, because a real order can only be
    placed after that candle closes. With False it reproduces the backtest exactly.
    """
    o, h, l, c, t = (df[k].values for k in ("open", "high", "low", "close", "time"))
    growing, pending, active, trades = [], [], [], []
    n = len(df)
    for i in range(n):
        for gr in growing[:]:
            if c[i] > o[i]:
                gr["len"] += 1
                gr["ext"] = max(gr["ext"], h[i])
                gr["last"] = i
            else:
                if gr["len"] >= 2 and gr["ext"] - gr["ob_high"] >= gr["size"]:
                    pending.append(dict(ob_high=gr["ob_high"], ob_low=gr["ob_low"], size=gr["size"],
                                        c2_high=gr["ext"], ob_idx=gr["ob_idx"], ob_time=gr["ob_time"],
                                        c2_idx=gr["last"], dist=False, streak=0))
                growing.remove(gr)
        if i >= 1:
            ob_open, ob_close, ob_high, ob_low = o[i - 1], c[i - 1], h[i - 1], l[i - 1]
            size = ob_high - ob_low
            if ob_close < ob_open and c[i] > o[i] and size > 0:
                growing.append(dict(ob_high=ob_high, ob_low=ob_low, size=size, ob_idx=i - 1,
                                    ob_time=int(t[i - 1]), len=1, ext=h[i], last=i))
        for ps in pending[:]:
            if i > ps["c2_idx"]:
                if not ps["dist"] and (ps["ob_low"] - l[i]) >= ps["size"]:
                    ps["dist"] = True
                ps["streak"] = ps["streak"] + 1 if c[i] < ps["ob_low"] else 0
                if ps["dist"] and ps["streak"] >= 2:
                    sl = ps["c2_high"]
                    tp = ps["ob_low"] - (ps["c2_high"] - ps["ob_low"])
                    prices = {"top": ps["ob_high"], "bottom": ps["ob_low"],
                              "mid": (ps["ob_high"] + ps["ob_low"]) / 2.0}
                    active.append(dict(ob_idx=ps["ob_idx"], ob_time=ps["ob_time"], sl=sl, tp=tp,
                                       prices=prices,
                                       pct={k: abs(p - sl) / p for k, p in prices.items()},
                                       touched={k: False for k in ENTRY_LABELS},
                                       open=[], resolved=False, first_fill=None, act_idx=i))
                    pending.remove(ps)
        for rob in active[:]:
            if rob["resolved"]:
                continue
            bars = i - rob["ob_idx"]
            if not (skip_activation_fill and rob["act_idx"] == i):
                for label in ("top", "mid", "bottom"):
                    price = rob["prices"][label]
                    if not rob["touched"][label] and l[i] <= price <= h[i] and i > rob["ob_idx"]:
                        rob["touched"][label] = True
                        if MIN_BARS < bars <= MAX_BARS and rob["pct"][label] > MIN_RISK:
                            if rob["first_fill"] is None:
                                rob["first_fill"] = i
                            trades.append(dict(ob_idx=rob["ob_idx"], label=label, entry=price,
                                               sl=rob["sl"], tp=rob["tp"], fill_idx=i, outcome=None))
                            rob["open"].append(label)
            if rob["open"] and not rob["resolved"]:
                hit_tp = l[i] <= rob["tp"] <= h[i]
                hit_sl = l[i] <= rob["sl"] <= h[i]
                if hit_tp or hit_sl:
                    outcome = "SL" if hit_sl else "TP"
                    for tr in trades:
                        if tr["ob_idx"] == rob["ob_idx"] and tr["label"] in rob["open"] and tr["outcome"] is None:
                            tr["outcome"] = outcome
                    rob["resolved"] = True
            if not rob["resolved"]:
                if rob["first_fill"] is None:
                    if bars > MAX_BARS + 5:
                        rob["resolved"] = True
                elif i - rob["first_fill"] > MAX_BARS + 5:
                    rob["resolved"] = True
        active = [r for r in active if not r["resolved"]]
    return trades, active, n


def desired_entries(rob, last_idx):
    """Entries that should have a resting limit order right now."""
    bars_next = (last_idx + 1) - rob["ob_idx"]
    out = []
    if not (MIN_BARS < bars_next <= MAX_BARS):
        return out
    for label in ENTRY_LABELS:
        if not rob["touched"][label] and rob["pct"][label] > MIN_RISK:
            out.append(label)
    return out


def make_cid(symbol, ob_time, label):
    base = "".join(ch for ch in symbol.split("-")[0] if ch.isalnum())
    return f"OR{base}{ob_time}{label[0]}"


# ------------------------------------------------------------------ account / exchange
def get_contracts():
    data = api("GET", "/openApi/swap/v2/quote/contracts", auth=False)
    return {d["symbol"]: d for d in data}


def get_equity():
    data = api("GET", "/openApi/swap/v2/user/balance")
    bal = data["balance"] if isinstance(data, dict) and "balance" in data else data
    if isinstance(bal, list):
        bal = [b for b in bal if b.get("asset") == "USDT"][0]
    return float(bal.get("equity") or bal.get("balance"))


def is_hedge_mode():
    data = api("GET", "/openApi/swap/v1/positionSide/dual")
    return str(data.get("dualSidePosition")).lower() == "true"


def get_open_orders():
    data = api("GET", "/openApi/swap/v2/trade/openOrders")
    return (data or {}).get("orders", []) if isinstance(data, dict) else (data or [])


def get_positions():
    data = api("GET", "/openApi/swap/v2/user/positions")
    return data or []


def get_recent_cids(symbol, days=12):
    """Every client order id we have ever placed on this symbol recently (any status)."""
    out = set()
    end = now_ms()
    left = days
    while left > 0:                      # BingX allows max 7 days per query
        span = min(left, 6)
        start = end - span * 86400 * 1000
        data = api("GET", "/openApi/swap/v2/trade/allOrders",
                   {"symbol": symbol, "startTime": start, "endTime": end, "limit": 500})
        orders = (data or {}).get("orders", []) if isinstance(data, dict) else (data or [])
        out |= {str(o.get("clientOrderID") or o.get("clientOrderId") or "") for o in orders}
        end = start
        left -= span
    return out - {""}


def order_cid(o):
    return str(o.get("clientOrderID") or o.get("clientOrderId") or "")


def fmt(x, prec):
    return f"{x:.{prec}f}"


def floor_qty(q, prec):
    f = 10 ** prec
    return math.floor(q * f + 1e-9) / f


def place_entry(symbol, rob, label, equity, spec, hedge):
    pprec = int(spec.get("pricePrecision", 4))
    qprec = int(spec.get("quantityPrecision", 0))
    entry = round(rob["prices"][label], pprec)
    sl = round(rob["sl"], pprec)
    tp = round(rob["tp"], pprec)
    risk_per_unit = abs(entry - sl)
    if risk_per_unit <= 0:
        return False, "zero stop distance"
    qty = floor_qty((equity * RISK_PCT / 3.0) / risk_per_unit, qprec)
    min_qty = float(spec.get("tradeMinQuantity", 0) or 0)
    min_usdt = float(spec.get("tradeMinUSDT", 0) or 0)
    if qty <= 0 or qty < min_qty or qty * entry < min_usdt:
        return False, f"size too small (qty {qty}, min {min_qty}, min usdt {min_usdt})"
    cid = make_cid(symbol, rob["ob_time"], label)
    params = {
        "symbol": symbol, "side": "SELL", "positionSide": "SHORT" if hedge else "BOTH",
        "type": "LIMIT", "quantity": fmt(qty, qprec), "price": fmt(entry, pprec),
        "timeInForce": "GTC", "clientOrderID": cid,
        "stopLoss": json.dumps({"type": "STOP_MARKET", "stopPrice": sl, "price": sl,
                                "workingType": "MARK_PRICE"}, separators=(",", ":")),
        "takeProfit": json.dumps({"type": "TAKE_PROFIT_MARKET", "stopPrice": tp, "price": tp,
                                  "workingType": "MARK_PRICE"}, separators=(",", ":")),
    }
    desc = f"{symbol} SELL LIMIT {label} qty {fmt(qty, qprec)} @ {fmt(entry, pprec)}  SL {sl}  TP {tp}  [{cid}]"
    if DRY_RUN:
        log("DRY RUN, would place: " + desc)
        return True, desc
    api("POST", "/openApi/swap/v2/trade/order", params)
    return True, desc


def pick_leverage(rob, labels, equity):
    """Leverage for one setup. Enough to afford the positions, never so high that
    liquidation (about 0.8/leverage away) would come before the stop loss."""
    sl = rob["sl"]
    total_notional = 0.0
    worst_stop_frac = 0.0
    for lb in labels:
        entry = rob["prices"][lb]
        dist = abs(entry - sl)
        if dist <= 0:
            continue
        total_notional += (equity * RISK_PCT / 3.0) * entry / dist
        worst_stop_frac = max(worst_stop_frac, dist / entry)
    if total_notional <= 0:
        return None, "no valid entries"
    margin_budget = equity / max(MAX_OPEN_SETUPS, 1)      # leave room for other open setups
    needed = max(1, math.ceil(total_notional / margin_budget))
    safe_max = max(1, min(MAX_LEVERAGE, int(0.8 / worst_stop_frac)))
    if needed > safe_max:
        return None, (f"needs {needed}x to afford (position ${total_notional:.0f}) but only "
                      f"{safe_max}x is safe for a {worst_stop_frac*100:.1f}% stop")
    return needed, f"{needed}x (position ${total_notional:.0f}, widest stop {worst_stop_frac*100:.1f}%, safe max {safe_max}x)"


def ensure_margin_and_leverage(symbol, hedge, leverage=None):
    leverage = leverage or LEVERAGE
    for path, p in (("/openApi/swap/v2/trade/marginType", {"symbol": symbol, "marginType": "ISOLATED"}),
                    ("/openApi/swap/v2/trade/leverage",
                     {"symbol": symbol, "side": "SHORT" if hedge else "BOTH", "leverage": leverage})):
        try:
            api("POST", path, p)
        except Exception as e:
            log(f"  note: {path} for {symbol}: {e}")


# ------------------------------------------------------------------ main run
def run():
    log(f"=== run start | DRY_RUN={DRY_RUN} RISK_PCT={RISK_PCT*100:.2f}% MAX_OPEN={MAX_OPEN_SETUPS} "
        f"coins={len(approved_list())} ===")
    contracts = get_contracts()
    equity = get_equity()
    hedge = is_hedge_mode()
    open_orders = get_open_orders()
    positions = get_positions()
    log(f"equity {equity:.2f} USDT | hedge mode: {hedge} | open orders: {len(open_orders)} | positions: {len(positions)}")

    # 1. scan every approved coin
    setups = []          # (priority, symbol, rob, last_idx)
    desired_cids = set()
    cid_info = {}
    for rank, symbol in enumerate(approved_list()):
        if symbol not in contracts:
            log(f"  {symbol}: not listed on BingX perpetuals, skipped")
            continue
        try:
            df = fetch_closed_candles(symbol)
            if len(df) < 120:
                log(f"  {symbol}: only {len(df)} candles, skipped")
                continue
            _, robs, n = scan_series(df, skip_activation_fill=True)
            last_idx = n - 1
            for rob in robs:
                want = desired_entries(rob, last_idx)
                for label in want:
                    cid = make_cid(symbol, rob["ob_time"], label)
                    desired_cids.add(cid)
                    cid_info[cid] = (symbol, rob["ob_time"], label)
                setups.append((rank, symbol, rob, last_idx, want))
            if robs:
                log(f"  {symbol}: {len(robs)} live setup(s)")
        except Exception as e:
            log(f"  {symbol}: scan failed: {e}")
        time.sleep(0.15)

    # 2. cancel our stale orders
    ours_open = [o for o in open_orders if order_cid(o).startswith("OR")
                 and o.get("symbol") in approved_list()]
    for o in ours_open:
        if order_cid(o) not in desired_cids:
            msg = f"cancel stale order {o.get('symbol')} {order_cid(o)} @ {o.get('price')}"
            if DRY_RUN:
                log("DRY RUN, would " + msg)
            else:
                try:
                    api("DELETE", "/openApi/swap/v2/trade/order",
                        {"symbol": o["symbol"], "orderId": o["orderId"]})
                    notify("Cancelled: " + msg)
                except Exception as e:
                    log(f"  cancel failed: {e}")

    # 3. which setups already occupy a slot
    open_cids = {order_cid(o) for o in ours_open}
    occupied = 0
    for rank, symbol, rob, last_idx, want in setups:
        has_pos = bool(rob["open"])
        has_ord = any(make_cid(symbol, rob["ob_time"], lb) in open_cids for lb in ENTRY_LABELS)
        if has_pos or has_ord:
            occupied += 1
    log(f"setups occupying a slot: {occupied} / {MAX_OPEN_SETUPS}")

    # 4. place orders for new setups (best-ranked coins first)
    for rank, symbol, rob, last_idx, want in sorted(setups, key=lambda s: s[0]):
        if not want:
            continue
        cids = {lb: make_cid(symbol, rob["ob_time"], lb) for lb in want}
        try:
            placed_before = get_recent_cids(symbol)
        except Exception as e:
            notify(f"Could not check order history for {symbol}, NOT placing (safety): {e}")
            continue
        todo = [lb for lb in want if cids[lb] not in placed_before]
        if not todo:
            continue
        already_in = bool(rob["open"]) or any(
            make_cid(symbol, rob["ob_time"], lb) in placed_before for lb in ENTRY_LABELS)
        if not already_in:
            if occupied >= MAX_OPEN_SETUPS:
                log(f"  {symbol}: new setup skipped, already at max open setups ({MAX_OPEN_SETUPS})")
                continue
            occupied += 1
        lev = LEVERAGE
        if AUTO_LEVERAGE:
            lev, why = pick_leverage(rob, todo, equity)
            if lev is None:
                notify(f"{symbol}: setup skipped, {why}")
                if not already_in:
                    occupied -= 1
                continue
            log(f"  {symbol}: leverage {why}")
        if not DRY_RUN:
            ensure_margin_and_leverage(symbol, hedge, lev)
        for lb in todo:
            try:
                ok, desc = place_entry(symbol, rob, lb, equity, contracts[symbol], hedge)
                if ok:
                    notify(("[DRY RUN] " if DRY_RUN else "") + "New order: " + desc)
                else:
                    log(f"  {symbol} {lb}: not placed: {desc}")
            except Exception as e:
                notify(f"ORDER FAILED {symbol} {lb}: {e}")

    # 5. make sure every open short has a stop loss
    protect_positions(setups, positions, hedge, contracts)
    log("=== run end ===")


def protect_positions(setups, positions, hedge, contracts):
    shorts = {}
    for p in positions:
        amt = float(p.get("positionAmt") or 0)
        side = str(p.get("positionSide", "")).upper()
        if amt != 0 and (side == "SHORT" or (side == "BOTH" and amt < 0)):
            shorts[p["symbol"]] = abs(amt)
    if not shorts:
        return
    try:
        orders = get_open_orders()
    except Exception as e:
        log(f"  protect: could not read orders: {e}")
        return
    for symbol, amt in shorts.items():
        if symbol not in approved_list():
            continue
        stops = [o for o in orders if o.get("symbol") == symbol and "STOP" in str(o.get("type", "")).upper()]
        if stops:
            continue
        rob = next((s[2] for s in setups if s[1] == symbol and s[2]["open"]), None)
        if rob is None:
            notify(f"WARNING: open short on {symbol} has NO stop order and no live setup found. Check it by hand.")
            continue
        pprec = int(contracts[symbol].get("pricePrecision", 4))
        sl = round(rob["sl"], pprec)
        tp = round(rob["tp"], pprec)
        for typ, price in (("STOP_MARKET", sl), ("TAKE_PROFIT_MARKET", tp)):
            params = {"symbol": symbol, "side": "BUY", "positionSide": "SHORT" if hedge else "BOTH",
                      "type": typ, "stopPrice": fmt(price, pprec), "quantity": amt,
                      "workingType": "MARK_PRICE"}
            if not hedge:
                params["reduceOnly"] = "true"
            if DRY_RUN:
                log(f"DRY RUN, would add missing {typ} on {symbol} @ {price}")
            else:
                try:
                    api("POST", "/openApi/swap/v2/trade/order", params)
                    notify(f"Added missing {typ} on {symbol} @ {price}")
                except Exception as e:
                    notify(f"COULD NOT add {typ} on {symbol}: {e}")


# ------------------------------------------------------------------ read-only connection test
def check():
    log("=== CONNECTION CHECK (read-only, places nothing) ===")
    log(f"API key set: {bool(API_KEY)} | secret set: {bool(API_SECRET)} | DRY_RUN={DRY_RUN}")
    tests = [
        ("contracts (public)", lambda: len(get_contracts())),
        ("balance / equity", get_equity),
        ("position mode (hedge?)", is_hedge_mode),
        ("open orders", lambda: len(get_open_orders())),
        ("positions", lambda: len(get_positions())),
        ("order history (allOrders)", lambda: len(get_recent_cids("BTC-USDT"))),
        ("4h candles ILV-USDT", lambda: len(fetch_closed_candles("ILV-USDT"))),
    ]
    for name, fn in tests:
        try:
            log(f"OK    {name}: {fn()}")
        except Exception as e:
            log(f"FAIL  {name}: {e}")
    contracts = {}
    try:
        contracts = get_contracts()
    except Exception:
        pass
    for s in approved_list():
        spec = contracts.get(s)
        log(f"  {s}: {'listed' if spec else 'NOT LISTED'}" +
            (f" | price decimals {spec.get('pricePrecision')} qty decimals {spec.get('quantityPrecision')} "
             f"min qty {spec.get('tradeMinQuantity')}" if spec else ""))
    log("=== check done ===")


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "check":
            check()
        else:
            if not API_KEY or not API_SECRET:
                raise SystemExit("BINGX_API_KEY and BINGX_API_SECRET are not set in Render Environment.")
            run()
    except SystemExit:
        raise
    except Exception as e:
        traceback.print_exc()
        notify(f"BOT ERROR: {e}")
        raise
