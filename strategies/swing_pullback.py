"""Swing pullback-in-trend for XAUUSD (research module; full log in results/swing_pullback_dev.md).

RESEARCH RESULT: MARGINAL / UNPROVEN CANDIDATE. Positive after spread + 5%/yr swap on dev 2022-2023
(+0.55 R/trade, n=69, SE 0.17, in-sample after ~39 combos) and on 2024 (+0.27 R/trade, n=45, SE 0.23,
t ~ 1.1, not significant alone). Only ~3-4 trades/month. Longs carry it (dev +0.85, 2024 +0.63);
shorts were +0.23 on dev but -0.46 on 2024 (15 trades). In 2024 the RSI pullback timing did NOT beat
random entries in the trend direction with the same exits (random +0.20 R, p = 0.33), so most of the
2024 profit came from "H4 trend + hold until Friday" in a strongly trending gold year.

Idea: trade only in the direction of the H4 trend, buy dips / sell rallies on H1, hold for days
behind an ATR stop and an ATR trailing stop, flat every Friday 20:00 UTC.

Final rules (DEFAULT_PARAMS):
  trend    H4 bars, last completed bar: long  if close > EMA(40) and EMA(40) > EMA(40) 6 bars ago
                                         short if close < EMA(40) and EMA(40) < EMA(40) 6 bars ago
  entry    on the close of an H1 bar: long when RSI(14) crosses back up through 40
           (RSI[prev] < 40 <= RSI[now]); short when it crosses down through 60. Fill at the next open.
  stop     2.0 * ATR(14) of the last completed H4 bar (ATR = SMA of true range, MT5 iATR), fixed $ at entry
  trailing chandelier with a fixed $ distance set at entry: every M1 bar,
           stop = max(stop, highest bid since entry - 3.0 * ATR_H4_at_entry)   (mirror for shorts, ask lows);
           it only starts tightening once price is 1 ATR (0.5 R) in profit and never loosens
  time     close all at Friday 20:00 UTC (or at the last bar before an earlier market close);
           max hold 10 calendar days (never binding with the Friday close)
  filters  no new entries Friday >= 12:00 UTC; no fills 21:00-23:59 UTC (rollover / reopen spreads);
           one position at a time (signals while in a position are ignored); no TP, no breakeven

Conventions (same as strategies/example_ema_pullback.py):
- every indicator is computed on completed bars only (bars are UTC-aligned, labelled by open time;
  shifting the H4 grid by 2 h to mimic GMT+2 servers changes little: +0.54 vs +0.55 R on dev)
- a signal decided on an H1 bar's close fills at the open of the first M1 bar at/after that close;
  if that bar is more than 5 min late (daily break / weekend / data hole) the signal is dropped
- distances (sl / trail) are $ from the fill price, expressed as multiples of ATR at the signal

Research-only options kept for reproducibility: pb_mode 'ema' (EMA-touch pullback; weak, +0.09 R) and
'none' (benchmark: enter whenever flat in the trend direction), sl_mode 'swing', be_r, tp_r, sides,
friday_close=False (weekend hold), htf_offset_h.
"""
import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr, ema, rsi

DEFAULT_PARAMS = dict(
    trend_tf="4h", trend_len=40, slope_bars=6,
    entry_tf="1h", pb_mode="rsi", rsi_len=14, rsi_lo=40, fast=20, pb_bars=5,
    atr_tf="4h", atr_len=14, sl_mode="atr", sl_atr=2.0, swing_bars=10, sl_min_atr=1.0,
    trail_atr=3.0, trail_start_r=0.0, be_r=0.0, be_off_r=0.1, tp_r=0.0,
    max_hold_days=10, friday_close=True, fri_close_utc=20, fri_last_entry_utc=12,
    skip_hours_utc=(21, 22, 23), sides="both", htf_offset_h=0,
)

_NS_MIN = 60 * 10**9


def _resample(m1, rule, offset_h):
    if not offset_h:
        return resample(m1, rule)
    agg = m1.resample(rule, label="left", closed="left", offset=pd.Timedelta(hours=offset_h)).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    agg.index = agg.index.as_unit("ns")
    return agg


def generate_signals(m1: pd.DataFrame, trend_tf="4h", trend_len=40, slope_bars=6,
                     entry_tf="1h", pb_mode="rsi", rsi_len=14, rsi_lo=40, fast=20, pb_bars=5,
                     atr_tf="4h", atr_len=14, sl_mode="atr", sl_atr=2.0, swing_bars=10, sl_min_atr=1.0,
                     trail_atr=3.0, trail_start_r=0.0, be_r=0.0, be_off_r=0.1, tp_r=0.0,
                     max_hold_days=10, friday_close=True, fri_close_utc=20, fri_last_entry_utc=12,
                     skip_hours_utc=(21, 22, 23), sides="both", htf_offset_h=0) -> Signals:
    eb = resample(m1, entry_tf)
    o, h, l, c = (eb[k].to_numpy() for k in ("open", "high", "low", "close"))
    close_t = pd.DatetimeIndex(eb.index + pd.Timedelta(entry_tf))  # time at which the entry bar is complete

    # --- trend on the higher timeframe (last completed bar at the entry-bar close)
    ht = _resample(m1, trend_tf, htf_offset_h)
    hc = ht["close"].to_numpy()
    he = ema(hc, trend_len)
    h_up = (hc > he) & (he > np.roll(he, slope_bars))
    h_dn = (hc < he) & (he < np.roll(he, slope_bars))
    warm = trend_len + slope_bars
    h_up[:warm] = False
    h_dn[:warm] = False
    trend = align_htf_to_m1(close_t, ht.index, trend_tf, h_up.astype(float) - h_dn.astype(float))

    # --- volatility yardstick (ATR of the last completed atr_tf bar)
    if atr_tf == entry_tf:
        a = atr(h, l, c, atr_len)
    else:
        at = ht if (atr_tf == trend_tf) else _resample(m1, atr_tf, htf_offset_h)
        a = align_htf_to_m1(close_t, at.index, atr_tf, atr(at["high"], at["low"], at["close"], atr_len))

    # --- pullback + resumption trigger on the entry timeframe
    if pb_mode == "rsi":
        r = rsi(c, rsi_len)
        pr = np.roll(r, 1)
        up = (trend > 0) & (pr < rsi_lo) & (r >= rsi_lo)
        dn = (trend < 0) & (pr > 100 - rsi_lo) & (r <= 100 - rsi_lo)
        warm_e = rsi_len + 2
    elif pb_mode == "ema":
        ef = ema(c, fast)
        touched_lo = pd.Series(l - ef).rolling(pb_bars).min().to_numpy() <= 0
        touched_hi = pd.Series(h - ef).rolling(pb_bars).max().to_numpy() >= 0
        prev_h, prev_l = np.roll(h, 1), np.roll(l, 1)
        up = (trend > 0) & touched_lo & (c > ef) & (c > prev_h)
        dn = (trend < 0) & touched_hi & (c < ef) & (c < prev_l)
        warm_e = max(fast, pb_bars) + 2
    elif pb_mode == "none":  # diagnostic benchmark: enter whenever flat and the trend agrees (no pullback)
        up, dn = trend > 0, trend < 0
        warm_e = 2
    else:
        raise ValueError(pb_mode)
    if sides == "long":
        dn[:] = False
    elif sides == "short":
        up[:] = False

    sig = (up | dn) & np.isfinite(a) & (a > 0)
    sig[:warm_e] = False
    if friday_close:
        late_fri = (close_t.dayofweek == 4) & (close_t.hour >= fri_last_entry_utc)
        sig &= ~np.asarray(late_fri) & np.asarray(close_t.dayofweek < 5)

    t_m1 = ns(m1.index)
    entry_all = htf_close_to_m1_entry(m1.index, eb.index, entry_tf)
    cand = np.flatnonzero(sig)
    entry = entry_all[cand]
    ok = entry < len(m1)
    cand, entry = cand[ok], entry[ok]
    # fill right after the signal bar only, and never inside the rollover / reopen hours
    ok = (t_m1[entry] - ns(close_t[cand]) <= 5 * _NS_MIN) & ~np.isin(m1.index[entry].hour, skip_hours_utc)
    cand, entry = cand[ok], entry[ok]

    direction = np.where(up[cand], 1, -1)
    av = a[cand]
    if sl_mode == "atr":
        sl = sl_atr * av
    elif sl_mode == "swing":
        # beyond the extreme of the last swing_bars entry bars plus 0.5 ATR, clipped to [sl_min_atr, sl_atr] ATR
        lo_n = pd.Series(l).rolling(swing_bars).min().to_numpy()[cand]
        hi_n = pd.Series(h).rolling(swing_bars).max().to_numpy()[cand]
        dist = np.where(direction > 0, c[cand] - lo_n, hi_n - c[cand]) + 0.5 * av
        sl = np.clip(dist, sl_min_atr * av, sl_atr * av)
    else:
        raise ValueError(sl_mode)

    # --- exit time: max hold, and optionally Friday close
    t_entry = t_m1[entry]
    t_exit = t_entry + int(max_hold_days * 86400) * 10**9
    if friday_close:
        ent_ts = m1.index[entry]
        days_to_fri = (4 - ent_ts.dayofweek) % 7
        fri = ent_ts.normalize() + pd.to_timedelta(days_to_fri, unit="D") + pd.Timedelta(hours=fri_close_utc)
        t_exit = np.minimum(t_exit, ns(fri))
    exit_idx = np.searchsorted(t_m1, t_exit)
    # if the market is closed at the exit time (early close / data hole), exit at the last bar before the gap
    late = (exit_idx >= len(m1)) | (t_m1[np.minimum(exit_idx, len(m1) - 1)] - t_exit > 5 * _NS_MIN)
    if friday_close:
        exit_idx = np.where(late, exit_idx - 1, exit_idx)
    exit_idx = np.where(exit_idx >= len(m1), -1, exit_idx)
    good = (exit_idx == -1) | (exit_idx > entry)
    entry, direction, sl, av, exit_idx = entry[good], direction[good], sl[good], av[good], exit_idx[good]

    n = len(entry)
    trail = np.full(n, trail_atr) * av if trail_atr > 0 else np.zeros(n)
    if be_r > 0:
        be_trig = np.full(n, be_r)
        be_off = be_off_r * sl
    elif trail_atr > 0:
        # trailing must be "armed" through the breakeven mechanism; arm it without moving the stop
        be_trig = np.full(n, max(trail_start_r, 1e-6))
        be_off = -sl
    else:
        be_trig = np.zeros(n)
        be_off = np.zeros(n)
    return Signals(entry, direction, sl, tp_r * sl, exit_idx=exit_idx,
                   be_trigger_r=be_trig, be_offset=be_off, trail_dist=trail)
