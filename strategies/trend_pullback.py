"""Trend pullback scalp for XAUUSD (research module, see results/trend_pullback_dev.md).

Idea: trade only in the direction of the higher-timeframe trend, wait for a short pullback on M5
into the fast EMA, and enter when an M5 bar closes back in the trend direction through the
previous bar's extreme (micro-structure break). ATR stop, fixed R target, hard time stop and
flat before the 21:00 UTC rollover.

Conventions (same as strategies/example_ema_pullback.py):
- every indicator is computed on completed bars only
- a signal decided on an M5 bar's close fills at the open of the first M1 bar at/after that close
- distances (sl/tp/trail) are $ from the fill price, expressed as multiples of ATR
"""
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr, ema, rolling_max, rolling_min, rsi

DEFAULT_PARAMS = dict(
    trend_tf="1h", trend_len=50, trend_slope_bars=3,   # HTF trend: close vs EMA and EMA slope
    mom_bars=120,                                       # optional: also require sign(HTF close - close[mom_bars]) (0 = off)
    entry_tf="5min",                                    # pullback / trigger timeframe
    fast=20, slow=50,                                   # entry-TF EMAs: fast = pullback line, fast>slow = entry-TF trend
    pb_mode="ema",                                      # 'ema': touch of fast EMA then close through prev bar extreme
                                                        # 'rsi': RSI(rsi_len) crosses back out of the dip zone
    pb_bars=6,                                          # pullback must touch the fast EMA within this many M5 bars
    rsi_len=14, rsi_lo=40,                              # rsi mode: long when RSI crosses up through rsi_lo (short: 100-rsi_lo)
    atr_tf="15min", atr_len=14, sl_atr=1.5,             # stop = sl_atr * ATR(atr_tf)
    tp_r=1.5, be_r=0.0, max_hold_min=90,
    session="day",                                      # 'london', 'ny', 'both', 'day'
    flat_utc=(20, 55),                                  # force flat at this UTC time (before rollover)
)

# Session windows in LOCAL exchange time (DST-aware via zoneinfo). Signal bar CLOSE time must be inside.
SESSIONS = {
    "london": [("Europe/London", (8, 0), (12, 0))],
    "ny": [("America/New_York", (8, 0), (12, 0))],
    "both": [("Europe/London", (8, 0), (12, 0)), ("America/New_York", (8, 0), (12, 0))],
    "day": [("UTC", (7, 0), (19, 0))],
}


def _in_session(times_utc: pd.DatetimeIndex, session: str) -> np.ndarray:
    ok = np.zeros(len(times_utc), dtype=bool)
    for tz, (h0, m0), (h1, m1_) in SESSIONS[session]:
        loc = times_utc.tz_convert(ZoneInfo(tz))
        mins = loc.hour * 60 + loc.minute
        ok |= (mins >= h0 * 60 + m0) & (mins < h1 * 60 + m1_)
    return ok & (times_utc.dayofweek < 5)


def generate_signals(m1: pd.DataFrame, trend_tf="1h", trend_len=50, trend_slope_bars=3, mom_bars=0, entry_tf="5min", fast=20, slow=50,
                     pb_mode="ema", pb_bars=6, rsi_len=14, rsi_lo=40, atr_tf="15min", atr_len=14, sl_atr=1.5, tp_r=1.5, be_r=0.0,
                     max_hold_min=90, session="ny", flat_utc=(20, 55)) -> Signals:
    m5 = resample(m1, entry_tf)  # entry timeframe bars (M5 by default)
    o, h, l, c = (m5[k].to_numpy() for k in ("open", "high", "low", "close"))
    close_t = pd.DatetimeIndex(m5.index + pd.Timedelta(entry_tf))  # time at which the entry-TF bar is complete

    # --- higher-timeframe trend (last completed HTF bar at the M5 close)
    ht = resample(m1, trend_tf)
    hc = ht["close"].to_numpy()
    he = ema(hc, trend_len)
    h_up = (hc > he) & (he > np.roll(he, trend_slope_bars))
    h_dn = (hc < he) & (he < np.roll(he, trend_slope_bars))
    if mom_bars > 0:  # multi-day momentum agrees with the HTF trend
        mom = hc - np.roll(hc, mom_bars)
        h_up &= mom > 0
        h_dn &= mom < 0
    warm = max(trend_len, mom_bars, trend_slope_bars)
    h_up[:warm] = False
    h_dn[:warm] = False
    trend = align_htf_to_m1(close_t, ht.index, trend_tf, h_up.astype(float) - h_dn.astype(float))

    # --- stop distance from ATR of atr_tf (completed bar)
    if atr_tf == entry_tf:
        a = atr(h, l, c, atr_len)
    else:
        at = resample(m1, atr_tf)
        a = align_htf_to_m1(close_t, at.index, atr_tf, atr(at["high"], at["low"], at["close"], atr_len))

    # --- M5 pullback + resumption trigger
    ef, es = ema(c, fast), ema(c, slow)
    touched_lo = rolling_min(l - ef, pb_bars) <= 0      # some bar in the window traded at/below the fast EMA
    touched_hi = rolling_max(h - ef, pb_bars) >= 0
    prev_h, prev_l = np.roll(h, 1), np.roll(l, 1)
    if pb_mode == "ema":
        up = (trend > 0) & (ef > es) & touched_lo & (c > ef) & (c > o) & (c > prev_h)
        dn = (trend < 0) & (ef < es) & touched_hi & (c < ef) & (c < o) & (c < prev_l)
    else:  # 'rsi'
        r = rsi(c, rsi_len)
        pr = np.roll(r, 1)
        up = (trend > 0) & (ef > es) & (pr < rsi_lo) & (r >= rsi_lo)
        dn = (trend < 0) & (ef < es) & (pr > 100 - rsi_lo) & (r <= 100 - rsi_lo)

    sig = (up | dn) & _in_session(close_t, session) & np.isfinite(a) & (a > 0)
    sig[: max(slow, pb_bars) + 1] = False

    t_m1 = ns(m1.index)
    entry = htf_close_to_m1_entry(m1.index, m5.index, entry_tf)[sig]
    direction = np.where(up[sig], 1, -1)
    sl = sl_atr * a[sig]
    keep = entry < len(m1)
    entry, direction, sl = entry[keep], direction[keep], sl[keep]
    # fill must happen right after the signal bar (no fills after a data gap / market close)
    keep = t_m1[entry] - ns(close_t[sig][keep]) <= 5 * 60 * 10**9
    entry, direction, sl = entry[keep], direction[keep], sl[keep]

    # --- exits: time stop, and always flat at flat_utc on the entry day (never across rollover/weekend)
    t_entry = m1.index[entry]
    t_flat = t_entry.normalize() + pd.Timedelta(hours=flat_utc[0], minutes=flat_utc[1])
    t_exit = np.minimum(ns(t_entry + pd.Timedelta(minutes=max_hold_min)), ns(t_flat))
    exit_idx = np.searchsorted(t_m1, t_exit)
    # if the market closed early (gap before t_exit), exit at the open of the last bar before the gap
    late = (exit_idx >= len(m1)) | (t_m1[np.minimum(exit_idx, len(m1) - 1)] - t_exit > 5 * 60 * 10**9)
    exit_idx = np.where(late, exit_idx - 1, exit_idx)
    ok = (ns(t_entry) < ns(t_flat)) & (exit_idx > entry)
    entry, direction, sl, exit_idx = entry[ok], direction[ok], sl[ok], exit_idx[ok]
    n = len(entry)
    return Signals(entry, direction, sl, tp_r * sl, exit_idx=exit_idx,
                   be_trigger_r=np.full(n, be_r), be_offset=0.1 * sl if be_r > 0 else np.zeros(n))
