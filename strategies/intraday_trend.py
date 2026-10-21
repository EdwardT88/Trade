"""Intraday trend breakout: M15 Donchian breakout in the direction of the H4 trend, trailing stop,
flat before the daily rollover. Slower than a pure scalper so spread costs are a smaller share of each trade.

Rules (all on completed bars, UTC):
- Trend: H4 close vs EMA(trend_len) of H4 closes (last completed H4 bar). Long only above, short only below.
- Entry: M15 close breaks the highest high (long) / lowest low (short) of the previous `dc_len` M15 bars,
  during [start_hour, end_hour) UTC. Fill at the next M1 open.
- Stop: sl_atr * ATR(atr_len) on M15. Target: tp_r * stop (0 = none).
- Breakeven at +be_r R, then trail at trail_atr * ATR from the best price.
- Time exit: flat at flat_utc (hour, minute) the same day, or after max_hold_min.
"""
import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr, ema, rolling_max, rolling_min

DEFAULT_PARAMS = dict(
    tf="15min", trend_tf="4h", trend_len=50, dc_len=20, atr_len=14,
    sl_atr=1.5, tp_r=0.0, be_r=1.0, trail_atr=2.0, max_hold_min=480,
    start_hour=7, end_hour=17, flat_utc=(20, 50),
)


def generate_signals(m1: pd.DataFrame, tf="15min", trend_tf="4h", trend_len=50, dc_len=20, atr_len=14,
                     sl_atr=1.5, tp_r=0.0, be_r=1.0, trail_atr=2.0, max_hold_min=480,
                     start_hour=7, end_hour=17, flat_utc=(20, 50)) -> Signals:
    b = resample(m1, tf)
    c, h, lo = b["close"].to_numpy(), b["high"].to_numpy(), b["low"].to_numpy()
    a = atr(h, lo, c, atr_len)
    hh = np.roll(rolling_max(h, dc_len), 1)
    ll = np.roll(rolling_min(lo, dc_len), 1)
    hh[:dc_len + 1] = np.nan
    ll[:dc_len + 1] = np.nan

    t = resample(m1, trend_tf)
    trend = t["close"].to_numpy() - ema(t["close"].to_numpy(), trend_len)
    close_times = pd.DatetimeIndex(b.index + pd.Timedelta(tf))
    tr = align_htf_to_m1(close_times, t.index, trend_tf, trend)

    hrs = close_times.hour
    ok_time = (hrs >= start_hour) & (hrs < end_hour) & (close_times.dayofweek < 5)
    up = (c > hh) & (tr > 0) & ok_time & np.isfinite(a)
    dn = (c < ll) & (tr < 0) & ok_time & np.isfinite(a)
    sig = up | dn

    entry = htf_close_to_m1_entry(m1.index, b.index, tf)[sig]
    direction = np.where(up[sig], 1, -1)
    sl = sl_atr * a[sig]
    trail = trail_atr * a[sig]
    keep = entry < len(m1)
    entry, direction, sl, trail = entry[keep], direction[keep], sl[keep], trail[keep]

    et = m1.index[entry]
    flat = et.normalize() + pd.Timedelta(hours=flat_utc[0], minutes=flat_utc[1])
    limit = np.minimum(ns(flat), ns(et + pd.Timedelta(minutes=max_hold_min)))
    exit_idx = np.searchsorted(ns(m1.index), limit)
    n = len(entry)
    return Signals(entry, direction, sl, tp_r * sl, exit_idx=exit_idx,
                   be_trigger_r=np.full(n, be_r), be_offset=0.05 * sl, trail_dist=trail)
