"""Swing pullback-in-trend for XAUUSD (research module, see results/swing_pullback_dev.md).

Idea: trade only in the direction of the H4 trend, buy dips / sell rallies on H1, hold for days
behind an ATR stop and an ATR trailing stop, never longer than max_hold_days.

Conventions (same as strategies/example_ema_pullback.py):
- every indicator is computed on completed bars only (bars are UTC-aligned, labelled by open time)
- a signal decided on an H1 bar's close fills at the open of the first M1 bar at/after that close;
  if that bar is more than 5 min late (daily break / weekend / data hole) the signal is dropped
- distances (sl / trail) are $ from the fill price, expressed as multiples of ATR at the signal

Rules (defaults in DEFAULT_PARAMS):
  trend   (H4, last completed bar): long  if close > EMA(trend_len) and EMA rising over slope_bars bars
                                    short if close < EMA(trend_len) and EMA falling over slope_bars bars
  pullback trigger (H1 close), pb_mode:
     'rsi'  long when RSI(rsi_len) crosses back up through rsi_lo (prev < rsi_lo <= now);
            short when it crosses down through 100 - rsi_lo
     'ema'  long when some bar of the last pb_bars H1 bars traded at/below EMA(fast) and the current
            bar closes above EMA(fast) and above the previous bar's high (mirror for shorts)
  stop     sl_atr * ATR(atr_len) of the last completed atr_tf bar, fixed at entry
  trailing chandelier: once the best price since entry is trail_start_r * stop beyond the fill,
           stop = max(stop, best_price - trail_atr * ATR_at_entry), updated every M1 bar
           (trail_start_r = 0: trailing from the first bar; the stop never loosens)
  breakeven optional: be_r > 0 moves the stop to fill + be_off_r * stop once +be_r R is reached
  time     close at max_hold_days after entry; friday_close=True also closes everything at
           Friday fri_close_utc:00 UTC and takes no new entries on Friday at/after fri_last_entry_utc
  filters  no fills in skip_hours_utc (daily rollover, wide spreads); cooldown_h between signals
"""
import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr, ema, rsi

DEFAULT_PARAMS = dict(
    trend_tf="4h", trend_len=50, slope_bars=6,
    entry_tf="1h", pb_mode="rsi", rsi_len=14, rsi_lo=40, fast=20, pb_bars=5,
    atr_tf="4h", atr_len=14, sl_atr=2.0,
    trail_atr=3.0, trail_start_r=0.0, be_r=0.0, be_off_r=0.1, tp_r=0.0,
    max_hold_days=10, friday_close=True, fri_close_utc=20, fri_last_entry_utc=12,
    skip_hours_utc=(21, 22, 23), cooldown_h=0, sides="both", htf_offset_h=0,
)

_NS_MIN = 60 * 10**9


def _resample(m1, rule, offset_h):
    if not offset_h:
        return resample(m1, rule)
    agg = m1.resample(rule, label="left", closed="left", offset=pd.Timedelta(hours=offset_h)).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    agg.index = agg.index.as_unit("ns")
    return agg


def _next_true_after(cond_times_ns: np.ndarray, t_ns: np.ndarray) -> np.ndarray:
    """For each t, the first time in the sorted array cond_times_ns strictly after t (int64 max if none)."""
    pos = np.searchsorted(cond_times_ns, t_ns, side="right")
    out = np.full(len(t_ns), np.iinfo(np.int64).max, dtype=np.int64)
    ok = pos < len(cond_times_ns)
    out[ok] = cond_times_ns[pos[ok]]
    return out


def generate_signals(m1: pd.DataFrame, trend_tf="4h", trend_len=50, slope_bars=6,
                     entry_tf="1h", pb_mode="rsi", rsi_len=14, rsi_lo=40, fast=20, pb_bars=5,
                     atr_tf="4h", atr_len=14, sl_atr=2.0,
                     trail_atr=3.0, trail_start_r=0.0, be_r=0.0, be_off_r=0.1, tp_r=0.0,
                     max_hold_days=10, friday_close=True, fri_close_utc=20, fri_last_entry_utc=12,
                     skip_hours_utc=(21, 22, 23), cooldown_h=0, sides="both", htf_offset_h=0) -> Signals:
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
    if cooldown_h > 0 and len(cand):
        keep = np.zeros(len(cand), bool)
        last = -np.inf
        te = t_m1[entry]
        for k in range(len(cand)):
            if te[k] - last >= cooldown_h * 60 * _NS_MIN:
                keep[k] = True
                last = te[k]
        cand, entry = cand[keep], entry[keep]

    direction = np.where(up[cand], 1, -1)
    av = a[cand]
    sl = sl_atr * av

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
