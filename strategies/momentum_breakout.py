"""Momentum breakout scalp: M5 Donchian breakout with volatility expansion during the New York morning.

VERDICT: not viable. ~0 R/trade on dev 2022-23 (+0.013), -0.012 R on 2024 validation, -0.047 R under
stress costs. See results/momentum_breakout_dev.md.

Rules (all decided on completed M5 bars, filled at the next M1 open):
- Donchian channel = highest high / lowest low of the previous `donchian_n` completed M5 bars
  (the signal bar itself is excluded).
- Long when the M5 close is above the channel high; short when it is below the channel low.
  With fresh_only=True, the previous M5 close must still have been inside its own channel
  (only the first close outside the channel counts, not every bar of a run).
- Volatility expansion: ATR(vol_fast)/ATR(vol_slow) on M5 >= vol_ratio (0 = filter off).
- Optional HTF trend filter (trend_mode=1): last completed H1 close above EMA(trend_len) for
  longs and below it for shorts.
- Session: the signal bar's CLOSE time, in New York local time (America/New_York, DST-aware),
  must be in [session_ny[0], session_ny[1]) hours.
- Stop = sl_atr * ATR(atr_len) of the M5 signal bar, target = tp_r * stop, time exit after
  max_hold_min minutes, and a hard flat time of flat_ny (NY local), which is always before
  21:00 UTC. One position at a time (the engine skips signals while a trade is open).

Data clock: data/xauusd_m1.parquet is stamped New York wall-clock + 5h (the 08:30 ET news
spike sits at 13:30 all year), so data_clock="ny+5" converts index -> NY time by subtracting
5h. For true-UTC data (or an EA working from TimeGMT()) use data_clock="utc", which converts
with zoneinfo America/New_York.
"""
import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr, ema, rolling_max, rolling_min

DEFAULT_PARAMS = dict(
    tf="5min", donchian_n=48, fresh_only=False,
    atr_len=14, vol_fast=5, vol_slow=50, vol_ratio=1.2,
    trend_mode=0, trend_tf="1h", trend_len=50,
    session_ny=(9.0, 12.0), flat_ny=15.5, data_clock="ny+5",
    sl_atr=2.0, tp_r=1.5, be_r=0.0, trail_atr=0.0, max_hold_min=60,
)


def ny_hours(times: pd.DatetimeIndex, data_clock: str) -> np.ndarray:
    """New York local clock time (fractional hours) for timestamps on the given data clock."""
    if data_clock == "ny+5":
        loc = pd.DatetimeIndex(times).tz_convert("UTC").tz_localize(None) - pd.Timedelta(hours=5)
    elif data_clock == "utc":
        loc = pd.DatetimeIndex(times).tz_convert("America/New_York")
    else:
        raise ValueError(f"unknown data_clock {data_clock!r}")
    return np.asarray(loc.hour + loc.minute / 60.0, dtype=float)


def ny_dates(times: pd.DatetimeIndex, data_clock: str) -> np.ndarray:
    if data_clock == "ny+5":
        loc = pd.DatetimeIndex(times).tz_convert("UTC").tz_localize(None) - pd.Timedelta(hours=5)
    else:
        loc = pd.DatetimeIndex(times).tz_convert("America/New_York").tz_localize(None)
    return loc.normalize().to_numpy()


def flat_instant(dates: np.ndarray, flat_ny: float, data_clock: str) -> pd.DatetimeIndex:
    """Data-clock timestamp of flat_ny (NY local hours) on each NY-local date."""
    loc = pd.DatetimeIndex(dates) + pd.Timedelta(minutes=round(flat_ny * 60))
    if data_clock == "ny+5":
        return (loc + pd.Timedelta(hours=5)).tz_localize("UTC")
    return loc.tz_localize("America/New_York", ambiguous="NaT", nonexistent="shift_forward").tz_convert("UTC")


def generate_signals(m1: pd.DataFrame, tf="5min", donchian_n=24, fresh_only=False,
                     atr_len=14, vol_fast=5, vol_slow=50, vol_ratio=0.0,
                     trend_mode=0, trend_tf="1h", trend_len=50,
                     session_ny=(8.0, 12.0), flat_ny=15.5, data_clock="ny+5",
                     sl_atr=2.0, tp_r=1.5, be_r=0.0, trail_atr=0.0, max_hold_min=60) -> Signals:
    b = resample(m1, tf)
    if len(b) < max(donchian_n, vol_slow, atr_len) + 2:
        return Signals.empty()
    h, lo, c = (b[k].to_numpy() for k in ("high", "low", "close"))
    a = atr(h, lo, c, atr_len)
    ratio = atr(h, lo, c, vol_fast) / atr(h, lo, c, vol_slow)

    # channel of the previous donchian_n bars (exclude the signal bar)
    ch_hi = np.roll(rolling_max(h, donchian_n), 1)
    ch_lo = np.roll(rolling_min(lo, donchian_n), 1)
    ch_hi[0] = ch_lo[0] = np.nan
    up = c > ch_hi
    dn = c < ch_lo
    if fresh_only:
        prev_c = np.roll(c, 1)
        up &= ~(prev_c > np.roll(ch_hi, 1))
        dn &= ~(prev_c < np.roll(ch_lo, 1))

    close_times = pd.DatetimeIndex(b.index + pd.Timedelta(tf))
    if trend_mode:
        ht = resample(m1, trend_tf)
        hc = ht["close"].to_numpy()
        tr = align_htf_to_m1(close_times, ht.index, trend_tf, hc - ema(hc, trend_len))
        up &= tr > 0
        dn &= tr < 0

    hrs = ny_hours(close_times, data_clock)
    s0, s1 = session_ny
    in_sess = (hrs >= s0) & (hrs < s1)
    vol_ok = ratio >= vol_ratio if vol_ratio > 0 else np.isfinite(ratio)
    sig = (up | dn) & in_sess & vol_ok & np.isfinite(a) & np.isfinite(ratio) & (a > 0)

    entry = htf_close_to_m1_entry(m1.index, b.index, tf)[sig]
    direction = np.where(up[sig], 1, -1)
    sl = sl_atr * a[sig]
    trail = trail_atr * a[sig]
    keep = entry < len(m1)
    entry, direction, sl, trail = entry[keep], direction[keep], sl[keep], trail[keep]
    if len(entry) == 0:
        return Signals.empty()

    t_entry = m1.index[entry]
    t_exit = t_entry + pd.Timedelta(minutes=max_hold_min)
    t_flat = flat_instant(ny_dates(t_entry, data_clock), flat_ny, data_clock)
    t_exit = pd.DatetimeIndex(np.minimum(ns(t_exit), ns(t_flat))).tz_localize("UTC")
    exit_idx = np.searchsorted(ns(m1.index), ns(t_exit))
    ok = exit_idx > entry
    n = int(ok.sum())
    return Signals(entry[ok], direction[ok], sl[ok], tp_r * sl[ok], exit_idx=exit_idx[ok],
                   be_trigger_r=np.full(n, be_r), be_offset=0.1 * sl[ok] * (be_r > 0),
                   trail_dist=trail[ok])
