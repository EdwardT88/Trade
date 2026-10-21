"""Template strategy: M5 EMA pullback in the direction of the M15 trend, London/NY hours only.

Shows the conventions every strategy must follow:
- compute indicators on completed bars only
- a signal decided at an M5 bar's close fills at the first M1 bar at/after that close
- distances (sl/tp) are in $ from the fill price
"""
import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr, ema

DEFAULT_PARAMS = dict(
    fast=20, slow=50, trend_tf="15min", trend_len=50, atr_len=14,
    sl_atr=1.5, tp_r=1.5, be_r=0.0, max_hold_min=90,
    hours_utc=(7, 16),
)


def generate_signals(m1: pd.DataFrame, fast=20, slow=50, trend_tf="15min", trend_len=50, atr_len=14,
                     sl_atr=1.5, tp_r=1.5, be_r=0.0, max_hold_min=90, hours_utc=(7, 16)) -> Signals:
    m5 = resample(m1, "5min")
    c = m5["close"].to_numpy()
    ef, es = ema(c, fast), ema(c, slow)
    a = atr(m5["high"], m5["low"], c, atr_len)

    ht = resample(m1, trend_tf)
    ht_ema = ema(ht["close"].to_numpy(), trend_len)
    # trend of the last *completed* HTF bar, sampled at each M5 close (= M5 open + 5min)
    m5_close_times = m5.index + pd.Timedelta("5min")
    trend_ref = align_htf_to_m1(pd.DatetimeIndex(m5_close_times), ht.index, trend_tf, ht["close"].to_numpy() - ht_ema)

    lo, hi = hours_utc
    hrs = m5_close_times.hour
    in_hours = (hrs >= lo) & (hrs < hi)
    prev_c = np.roll(c, 1)
    up = (trend_ref > 0) & (ef > es) & (m5["low"].to_numpy() <= ef) & (c > ef) & (prev_c <= np.roll(ef, 1))
    dn = (trend_ref < 0) & (ef < es) & (m5["high"].to_numpy() >= ef) & (c < ef) & (prev_c >= np.roll(ef, 1))
    sig = (up | dn) & in_hours & np.isfinite(a)
    sig[:slow] = False

    entry = htf_close_to_m1_entry(m1.index, m5.index, "5min")[sig]
    direction = np.where(up[sig], 1, -1)
    sl = sl_atr * a[sig]
    keep = entry < len(m1)
    entry, direction, sl = entry[keep], direction[keep], sl[keep]
    exit_idx = np.searchsorted(ns(m1.index), ns(m1.index[entry] + pd.Timedelta(minutes=max_hold_min)))
    return Signals(entry, direction, sl, tp_r * sl, exit_idx=exit_idx,
                   be_trigger_r=np.full(len(entry), be_r), be_offset=np.full(len(entry), 0.1))
