"""Swing breakout trend following for XAUUSD (H4 Donchian breakout + trend filter + ATR trailing stop).

Idea: when a completed H4 (or H1) bar CLOSES beyond the highest high / lowest low of the previous
`lookback` bars, in the direction of a slower trend filter, enter at the next M1 open. Initial stop
`sl_atr` x ATR. Once the trade is `be_r` R in profit the stop goes to entry + `be_lock_r` R and from
then on trails `trail_atr` x ATR behind the best price reached since entry (chandelier stop with the
ATR frozen at entry). No profit target. Time stop after `max_hold_days`; optional flat on Friday.

Bars are built in BROKER SERVER TIME, not UTC: most MT5 gold brokers run GMT+2 / GMT+3 (New York
close), so H4 and D1 bars start at 17:00 New York time. In the data clock used here (HistData,
loaded as "UTC", whose daily break is always 22:00-23:00) that is a fixed +2 h offset:
`bar_offset_h=2` -> H4 bars open at 22,02,06,10,14,18 and D1 bars at 22:00 of the data clock.
An HTF bar is complete when the first M1 bar of the next HTF bar arrives; that M1 bar's open is the
fill (exactly what an EA sees on the first tick of a new bar).

Conventions (same as strategies/example_ema_pullback.py):
- indicators on completed bars only (MT5 definitions from backtest/indicators.py)
- a signal decided on a bar's close fills at the open of the first M1 bar after that bar
- all distances are $ from the fill price, expressed as multiples of ATR(atr_len) of the signal TF

MQL5 port (all bar-by-bar):
- on each new H4 bar (server time): c = close[1], up = max(high[2..lookback+1]), dn = min(low[2..lookback+1]),
  ATR = iATR(H4, atr_len)[1], trend filter on bar 1 (see `trend` below).
- long if c > up and trend up, short if c < dn and trend down; only when flat.
- SL = entry -/+ sl_atr*ATR. On every new M1 bar: best = max(best, high of closed M1 bar) (shorts: min low + spread);
  if best >= entry + be_r*R: SL = max(SL, entry + be_lock_r*R) and from then on SL = max(SL, best - trail_atr*ATR).
- close after max_hold_days calendar days; if fri_close: close on Friday at fri_exit_h (data clock = server - 2 h)
  and open no new trades on Friday at/after fri_cutoff_h.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import Signals, ns
from backtest.indicators import atr, ema

DEFAULT_PARAMS = dict(
    tf_min=240,            # signal timeframe in minutes (240 = H4, 60 = H1)
    bar_offset_h=2,        # HTF bar alignment: data clock + offset = server clock (2 -> NY-close server)
    lookback=20,           # Donchian breakout: close beyond the high/low of the previous `lookback` bars
    trend="ema",           # 'none' | 'ema' (close vs EMA) | 'ema_slope' (close vs EMA and EMA rising/falling) | 'd1_ema'
    trend_len=50,          # EMA length (signal TF bars, or D1 bars for 'd1_ema')
    slope_bars=6,          # 'ema_slope': EMA[t] vs EMA[t - slope_bars]
    atr_len=14,
    sl_atr=2.0,            # initial stop, x ATR
    be_r=1.0,              # at +be_r R: stop to entry + be_lock_r R and trailing starts (0 = trail from entry, no lock)
    be_lock_r=0.1,
    trail_atr=3.0,         # trailing distance x ATR (0 = off)
    max_hold_days=10,      # calendar days
    fri_close=False,       # True: flat on Friday at fri_exit_h, no new entries on Friday from fri_cutoff_h
    fri_exit_h=20,
    fri_cutoff_h=12,
    sides="both",          # 'both' | 'long' | 'short'
    max_atr_pct=0.0,       # skip if ATR/price*100 above this (0 = off)
)

_NS_MIN = 60 * 10**9
_NS_H = 60 * _NS_MIN


def _bars(m1: pd.DataFrame, t: np.ndarray, minutes: int, offset_h: float) -> dict:
    """OHLC bars of `minutes` built from M1 in a shifted clock. `end` = index of the first M1 bar after
    the bar (where a decision on its close fills; == len(m1) for the last bar)."""
    period = minutes * _NS_MIN
    bucket = (t + int(offset_h * _NS_H)) // period
    starts = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    ends = np.r_[starts[1:], len(t)]
    h = np.maximum.reduceat(m1["high"].to_numpy(float), starts)
    lo = np.minimum.reduceat(m1["low"].to_numpy(float), starts)
    o = m1["open"].to_numpy(float)[starts]
    c = m1["close"].to_numpy(float)[ends - 1]
    return dict(open=o, high=h, low=lo, close=c, start=starts, end=ends)


def generate_signals(m1: pd.DataFrame, tf_min=240, bar_offset_h=2, lookback=20, trend="ema", trend_len=50, slope_bars=6,
                     atr_len=14, sl_atr=2.0, be_r=1.0, be_lock_r=0.1, trail_atr=3.0, max_hold_days=10,
                     fri_close=False, fri_exit_h=20, fri_cutoff_h=12, sides="both", max_atr_pct=0.0) -> Signals:
    t = ns(m1.index)
    n_m1 = len(t)
    b = _bars(m1, t, int(tf_min), bar_offset_h)
    h, lo, c, end = b["high"], b["low"], b["close"], b["end"]
    nb = len(c)

    # Donchian channel of the PREVIOUS `lookback` bars (excludes the signal bar)
    hh = pd.Series(h).rolling(lookback).max().shift(1).to_numpy()
    ll = pd.Series(lo).rolling(lookback).min().shift(1).to_numpy()
    a = atr(h, lo, c, atr_len)

    if trend == "none":
        t_up = np.ones(nb, bool)
        t_dn = np.ones(nb, bool)
    elif trend in ("ema", "ema_slope"):
        e = ema(c, trend_len)
        t_up, t_dn = c > e, c < e
        if trend == "ema_slope":
            prev = np.r_[np.full(slope_bars, np.nan), e[:-slope_bars]]
            t_up &= e > prev
            t_dn &= e < prev
        t_up[:trend_len] = False
        t_dn[:trend_len] = False
    elif trend == "d1_ema":
        d = _bars(m1, t, 1440, bar_offset_h)
        de = ema(d["close"], trend_len)
        d_up = d["close"] > de
        d_dn = d["close"] < de
        d_up[:trend_len] = False
        d_dn[:trend_len] = False
        # last D1 bar completed at the signal bar's close: d.end <= end
        pos = np.searchsorted(d["end"], end, side="right") - 1
        ok = pos >= 0
        t_up = np.zeros(nb, bool)
        t_dn = np.zeros(nb, bool)
        t_up[ok] = d_up[pos[ok]]
        t_dn[ok] = d_dn[pos[ok]]
    else:
        raise ValueError(trend)

    valid = np.isfinite(hh) & np.isfinite(ll) & np.isfinite(a) & (a > 0) & (end < n_m1)
    if max_atr_pct > 0:
        valid &= a / c * 100 <= max_atr_pct
    up = valid & (c > hh) & t_up
    dn = valid & (c < ll) & t_dn
    if sides == "long":
        dn[:] = False
    elif sides == "short":
        up[:] = False
    sig = up | dn

    entry = end[sig]
    direction = np.where(up[sig], 1, -1)
    sl = sl_atr * a[sig]
    atr_e = a[sig]

    # after a weekend / holiday gap the fill is simply the reopen (what an EA does on the first new tick)
    t_entry = t[entry]
    ent_ts = pd.to_datetime(t_entry, utc=True)

    # --- exits: time stop and (optionally) Friday flat
    t_exit = t_entry + int(max_hold_days * 24) * _NS_H
    keep = np.ones(len(entry), bool)
    if fri_close:
        dow = ent_ts.dayofweek.to_numpy()
        hr = ent_ts.hour.to_numpy()
        day0 = ns(ent_ts.normalize())
        fri = day0 + ((4 - dow) % 7) * 24 * _NS_H + int(fri_exit_h) * _NS_H
        # Saturday/Sunday entries (Sunday reopen) belong to the coming week: (4 - 6) % 7 = 5 days -> that Friday
        t_exit = np.minimum(t_exit, fri)
        keep &= ~((dow == 4) & (hr >= fri_cutoff_h))
    exit_idx = np.searchsorted(t, t_exit)
    # if the market is closed at the target time (holiday / early close), exit at the open of the last bar before the gap
    clipped = np.minimum(exit_idx, n_m1 - 1)
    late = (exit_idx < n_m1) & (t[clipped] - t_exit > 5 * _NS_MIN)
    exit_idx = np.where(late, exit_idx - 1, exit_idx)
    exit_idx = np.where(exit_idx >= n_m1, -1, exit_idx)  # beyond data: engine closes at end of data
    keep &= (exit_idx == -1) | (exit_idx > entry)

    entry, direction, sl, atr_e, exit_idx = entry[keep], direction[keep], sl[keep], atr_e[keep], exit_idx[keep]
    n = len(entry)
    if be_r > 0:
        be_trig = np.full(n, float(be_r))
        be_off = be_lock_r * sl
    else:  # trailing active from entry, no breakeven lock (offset -sl never moves the stop by itself)
        be_trig = np.full(n, 1e-9)
        be_off = -sl
    trail = trail_atr * atr_e
    return Signals(entry, direction, sl, np.zeros(n), exit_idx=exit_idx, be_trigger_r=be_trig, be_offset=be_off,
                   trail_dist=trail, tag=np.where(direction > 0, 1, 2))
