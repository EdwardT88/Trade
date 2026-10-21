"""Swing breakout trend following for XAUUSD (H4 Donchian breakout + EMA trend filter + ATR chandelier stop).

RESEARCH RESULT: WEAK / NOT STATISTICALLY ESTABLISHED. Positive point estimates on dev and on 2024, but the
edge cannot be told apart from zero with the ~3 trades/month this produces:
    dev 2022-2023 (no limits, default spread + 5%/yr swap): 80 trades, avg +0.156R, SE 0.223 (t 0.7), PF 1.14
    2024 validation (run once, not revised):               39 trades, avg +0.280R, SE 0.322 (t 0.9), PF 1.41
    the 50 dev parameter sets averaged only +0.02R (H4 weekend-hold sets +0.05R); removing the best 3 trades
    makes either period negative; 2024 profit came from longs (+0.95R) while shorts lost (-0.59R).
Closing on Friday (fri_close=True) loses on dev (-0.08R): all of the profit comes from trades held > 10 days.

Idea: when a completed H4 (or H1) bar CLOSES beyond the highest high / lowest low of the previous
`lookback` bars, in the direction of a slower trend filter, enter at the next M1 open. Initial stop
`sl_atr` x ATR. Chandelier trailing stop `trail_atr` x ATR (ATR frozen at entry) behind the best price
since entry, active from entry when be_r=0 (default; the trail only rises above the initial stop once
the trade is (trail_atr - sl_atr) ATR in profit). With be_r>0 the stop first goes to entry + be_lock_r R
at +be_r R and only then starts trailing. No profit target. Time stop after `max_hold_days`; optional
flat on Friday.

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

MQL5 port (all bar-by-bar; DEFAULT_PARAMS):
- on each new H4 bar (server time GMT+2/+3): c = close[1], up = max(high[2..21]), dn = min(low[2..21]),
  ATR = iATR(H4, 14)[1], E = iMA(H4, 50, EMA, close)[1].
- only when flat: long if c > up and c > E; short if c < dn and c < E. Fill at market (first tick of the new bar).
- SL = entry -/+ 2.0*ATR, no TP. On every new M1 bar: best = max(best, high of the closed M1 bar)
  (shorts: min(best, low + spread)); SL = max(SL, best - 5.0*ATR)  (shorts: min(SL, best + 5.0*ATR)).
- close at market 14 calendar days after entry. Positions are held over weekends (fri_close=False).
- if fri_close: close on Friday at fri_exit_h of the data clock (= server time - 2 h, i.e. 22:00 server) and
  open no new trades on Friday at/after fri_cutoff_h (data clock).
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
    be_r=0.0,              # at +be_r R: stop to entry + be_lock_r R and trailing starts (0 = trail from entry, no lock)
    be_lock_r=0.1,
    trail_atr=5.0,         # chandelier: stop = best price since entry - trail_atr x ATR(at entry), only ever tightened
    max_hold_days=14,      # calendar days (the 2-week cap)
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
                     atr_len=14, sl_atr=2.0, be_r=0.0, be_lock_r=0.1, trail_atr=5.0, max_hold_days=14,
                     fri_close=False, fri_exit_h=20, fri_cutoff_h=12, sides="both", max_atr_pct=0.0) -> Signals:
    t = ns(m1.index)
    n_m1 = len(t)
    # bar clock = New York wall time + 5 h + bar_offset_h (bar_offset_h=2 -> NY-close server time, GMT+2/+3);
    # data/ is true UTC (see backtest/data.py), so derive New York wall time explicitly
    t_clock = ns(m1.index.tz_convert("America/New_York").tz_localize(None)) + 5 * _NS_H
    b = _bars(m1, t_clock, int(tf_min), bar_offset_h)
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
        d = _bars(m1, t_clock, 1440, bar_offset_h)
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

    # --- exits: time stop (first M1 bar at/after entry + max_hold_days; after a gap that is the reopen,
    # as in an EA) and optionally Friday flat (if the market is already closed at that time -- holiday /
    # early close -- exit at the open of the last M1 bar before the gap instead of holding into the reopen)
    t_hold = t_entry + int(round(max_hold_days * 24)) * _NS_H
    exit_idx = np.searchsorted(t, t_hold)
    exit_idx = np.where(exit_idx >= n_m1, n_m1, exit_idx)
    keep = np.ones(len(entry), bool)
    if fri_close:
        dow = ent_ts.dayofweek.to_numpy().astype(np.int64)
        hr = ent_ts.hour.to_numpy()
        # Sunday-reopen entries belong to the coming week: (4 - 6) % 7 = 5 days -> that Friday
        t_fri = ns(ent_ts.normalize()) + ((4 - dow) % 7) * 24 * _NS_H + int(fri_exit_h) * _NS_H
        fx = np.searchsorted(t, t_fri)
        late = (fx < n_m1) & (t[np.minimum(fx, n_m1 - 1)] - t_fri > 5 * _NS_MIN)
        fx = np.where(late, fx - 1, fx)
        exit_idx = np.minimum(exit_idx, fx)
        keep &= ~((dow == 4) & (hr >= fri_cutoff_h))
    exit_idx = np.where(exit_idx >= n_m1, -1, exit_idx)  # beyond the data: the engine closes at end of data
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
