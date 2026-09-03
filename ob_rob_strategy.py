"""
OB -> ROB Strategy 2 (SHORT, dynamic) - Python port of the Pine Script v5 strategy.

Rules (locked in with user):
1. OB candle = a bearish candle immediately followed by 2+ consecutive bullish candles.
2. That bullish run becomes a "pending setup" if its highest high clears the OB candle's
   high by at least the OB candle's own size (obSize = obHigh - obLow). Measured the moment
   the bullish run breaks (a bearish candle appears).
3. Pending setup activates into a live ROB once BOTH of these become true (can overlap):
   a) distance: low drops below obLow by >= obSize (one-time trigger, stays true forever after)
   b) two consecutive candle CLOSES below obLow (resets to 0 if a close comes in above obLow)
4. On activation:
   SL = high of the impulsive bullish run (runExtreme)
   TP = obLow - (runExtreme - obLow)   [measured move mirrored below the OB]
   Entries: top = obHigh, mid = (obHigh+obLow)/2, bottom = obLow
5. Each entry only counts as a REAL trade if, when touched:
   - bars since OB (bar_index - obIdx) is > s2MinBars (10) and <= s2MaxBars (60)
   - risk% = abs(entry - SL) / entry > s2MinRisk (0.02)
6. All entries touched before any resolution count (even multiple in the same candle).
   The instant ANY filled entry's trade hits TP or SL, the whole ROB is closed - no further
   entries can fire on it afterward.
7. Edge case (rare): if an entry fill and a TP/SL hit occur within the same candle, we assume
   the entry fill happens first (i.e. entries within a candle are resolved before checking
   TP/SL touches in that same candle).
8. A pending/active ROB is abandoned if bars since OB exceeds s2MaxBars + 5 with no resolution.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd


@dataclass
class Trade:
    ob_idx: int
    ob_time: object
    entry_label: str      # "top", "mid", "bottom"
    entry_price: float
    sl: float
    tp: float
    fill_idx: int
    fill_time: object
    bars_from_ob: int
    risk_pct: float
    outcome: Optional[str] = None   # "TP", "SL", or None if still open at end of data
    exit_idx: Optional[int] = None
    exit_time: object = None
    pnl_r: Optional[float] = None   # in R multiples (risk-normalized), TP=+1R by construction (1:1 measured move... but not exactly, see note)


@dataclass
class GrowingRun:
    ob_high: float
    ob_low: float
    ob_size: float
    ob_idx: int
    ob_time: object
    run_len: int
    run_extreme: float
    last_idx: int


@dataclass
class PendingSetup:
    ob_high: float
    ob_low: float
    ob_size: float
    c2_high: float          # run_extreme at time pending setup was created
    ob_idx: int
    ob_time: object
    c2_idx: int
    distance_flag: bool = False
    streak: int = 0


@dataclass
class ActiveROB:
    ob_idx: int
    ob_time: object
    sl: float
    tp: float
    entry_top: float
    entry_mid: float
    entry_bottom: float
    pct_top: float
    pct_mid: float
    pct_bottom: float
    top_filled: bool = False
    mid_filled: bool = False
    bottom_filled: bool = False
    resolved: bool = False
    # track open trades per entry so we know when TP/SL happens
    open_entries: List[str] = field(default_factory=list)


def run_ob_rob_backtest(
    df: pd.DataFrame,
    min_bars: int = 10,
    max_bars: int = 60,
    min_risk: float = 0.02,
) -> List[Trade]:
    """
    df must have columns: ['time','open','high','low','close'], sorted ascending by time,
    with a default RangeIndex (0..n-1) matching Pine's bar_index.

    Returns a list of Trade objects (one per entry that actually fired).
    """
    growing_runs: List[GrowingRun] = []
    pending_setups: List[PendingSetup] = []
    active_robs: List[ActiveROB] = []
    trades: List[Trade] = []

    n = len(df)
    o = df['open'].values
    h = df['high'].values
    l = df['low'].values
    c = df['close'].values
    t = df['time'].values

    for i in range(n):
        # ---- 1. update growing bullish runs ----
        for gr in growing_runs[:]:
            same_direction = c[i] > o[i]
            if same_direction:
                gr.run_len += 1
                gr.run_extreme = max(gr.run_extreme, h[i])
                gr.last_idx = i
            else:
                if gr.run_len >= 2:
                    imbalance = gr.run_extreme - gr.ob_high
                    if imbalance >= gr.ob_size:
                        pending_setups.append(PendingSetup(
                            ob_high=gr.ob_high, ob_low=gr.ob_low, ob_size=gr.ob_size,
                            c2_high=gr.run_extreme, ob_idx=gr.ob_idx, ob_time=gr.ob_time,
                            c2_idx=gr.last_idx
                        ))
                growing_runs.remove(gr)

        # ---- 2. detect new OB candle (bearish[i-1] -> bullish[i]) ----
        if i >= 1:
            ob_open, ob_close, ob_high, ob_low = o[i-1], c[i-1], h[i-1], l[i-1]
            ob_size = ob_high - ob_low
            if ob_close < ob_open and c[i] > o[i] and ob_size > 0:
                growing_runs.append(GrowingRun(
                    ob_high=ob_high, ob_low=ob_low, ob_size=ob_size,
                    ob_idx=i-1, ob_time=t[i-1], run_len=1, run_extreme=h[i], last_idx=i
                ))

        # ---- 3. progress pending setups toward activation ----
        for ps in pending_setups[:]:
            if i > ps.c2_idx:
                if not ps.distance_flag and (ps.ob_low - l[i]) >= ps.ob_size:
                    ps.distance_flag = True
                if c[i] < ps.ob_low:
                    ps.streak += 1
                else:
                    ps.streak = 0

                if ps.distance_flag and ps.streak >= 2:
                    sl = ps.c2_high
                    tp = ps.ob_low - (ps.c2_high - ps.ob_low)
                    entry_top = ps.ob_high
                    entry_bottom = ps.ob_low
                    entry_mid = (ps.ob_high + ps.ob_low) / 2.0
                    pct_top = abs(entry_top - sl) / entry_top
                    pct_mid = abs(entry_mid - sl) / entry_mid
                    pct_bottom = abs(entry_bottom - sl) / entry_bottom

                    active_robs.append(ActiveROB(
                        ob_idx=ps.ob_idx, ob_time=ps.ob_time, sl=sl, tp=tp,
                        entry_top=entry_top, entry_mid=entry_mid, entry_bottom=entry_bottom,
                        pct_top=pct_top, pct_mid=pct_mid, pct_bottom=pct_bottom
                    ))
                    pending_setups.remove(ps)

        # ---- 4. process active ROBs: entry fills first, then TP/SL checks (same-candle rule) ----
        for rob in active_robs[:]:
            if rob.resolved:
                continue

            bars_from_ob = i - rob.ob_idx
            if bars_from_ob <= rob.ob_idx:  # no-op guard, kept for clarity
                pass

            # --- entry fills (checked before TP/SL within this same candle) ---
            for label, price, pct in (
                ("top", rob.entry_top, rob.pct_top),
                ("mid", rob.entry_mid, rob.pct_mid),
                ("bottom", rob.entry_bottom, rob.pct_bottom),
            ):
                already = {"top": rob.top_filled, "mid": rob.mid_filled, "bottom": rob.bottom_filled}[label]
                if not already and l[i] <= price <= h[i] and i > rob.ob_idx:
                    if label == "top":
                        rob.top_filled = True
                    elif label == "mid":
                        rob.mid_filled = True
                    else:
                        rob.bottom_filled = True

                    if min_bars < bars_from_ob <= max_bars and pct > min_risk:
                        trades.append(Trade(
                            ob_idx=rob.ob_idx, ob_time=rob.ob_time, entry_label=label,
                            entry_price=price, sl=rob.sl, tp=rob.tp, fill_idx=i, fill_time=t[i],
                            bars_from_ob=bars_from_ob, risk_pct=pct
                        ))
                        rob.open_entries.append(label)

            # --- TP / SL check for any currently open trades on this ROB ---
            if rob.open_entries and not rob.resolved:
                hit_tp = l[i] <= rob.tp <= h[i]
                hit_sl = l[i] <= rob.sl <= h[i]
                # short trade: price falling to tp = win, price rising to sl = loss
                if hit_tp or hit_sl:
                    outcome = "SL" if hit_sl else "TP"  # if both touched same candle, conservative: SL wins
                    for tr in trades:
                        if tr.ob_idx == rob.ob_idx and tr.entry_label in rob.open_entries and tr.outcome is None:
                            tr.outcome = outcome
                            tr.exit_idx = i
                            tr.exit_time = t[i]
                            risk_dist = abs(tr.entry_price - tr.sl)
                            reward_dist = abs(tr.entry_price - tr.tp)
                            tr.pnl_r = (reward_dist / risk_dist) if outcome == "TP" else -1.0
                    rob.resolved = True

            # --- abandon if too old ---
            if not rob.resolved and bars_from_ob > max_bars + 5:
                rob.resolved = True

        active_robs = [r for r in active_robs if not r.resolved]

    return trades


def summarize_trades(trades: List[Trade]) -> dict:
    closed = [t for t in trades if t.outcome is not None]
    if not closed:
        return {"num_trades": len(trades), "num_closed": 0}
    wins = [t for t in closed if t.outcome == "TP"]
    losses = [t for t in closed if t.outcome == "SL"]
    total_r = sum(t.pnl_r for t in closed)
    gross_win = sum(t.pnl_r for t in wins)
    gross_loss = abs(sum(t.pnl_r for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else float('inf')
    return {
        "num_trades": len(trades),
        "num_closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) if closed else 0,
        "total_R": total_r,
        "profit_factor": profit_factor,
    }
