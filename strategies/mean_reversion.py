"""Mean-reversion scalp (draft, under research)."""
from zoneinfo import ZoneInfo  # noqa: F401

import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr, bbands, ema, rolling_max, rolling_min, rsi

DEFAULT_PARAMS = dict(
    tf="5min", setup="bb", bb_len=20, bb_k=2.0, sweep_len=48, rsi_len=14, rsi_lo=30.0,
    atr_len=14, trend_tf="1h", trend_len=50, trend_mode="none", trend_flat_atr=1.0,
    vol_len=0, vol_max=0.0,
    hours=(7, 12), hours_tz="UTC",
    sl_mode="extreme", sl_buf_atr=0.3, sl_atr=2.0, min_sl_atr=1.0, max_sl_atr=4.0, ext_bars=2,
    tp_r=1.0, max_hold_min=60, flat_utc=(20, 45), max_per_day=8,
)


def generate_signals(m1: pd.DataFrame, tf="5min", setup="bb", bb_len=20, bb_k=2.0, sweep_len=48, rsi_len=14,
                     rsi_lo=30.0, st_len=6, st_k=4.0, confirm=False, cooldown=0, atr_len=14, trend_tf="1h", trend_len=50, trend_mode="none", trend_flat_atr=1.0,
                     vol_len=0, vol_max=0.0, hours=(7, 12), hours_tz="UTC",
                     sl_mode="extreme", sl_buf_atr=0.3, sl_atr=2.0, min_sl_atr=1.0, max_sl_atr=4.0, ext_bars=2,
                     tp_r=1.0, max_hold_min=60, flat_utc=(20, 45), max_per_day=8) -> Signals:
    b = resample(m1, tf)
    o, h, l, c = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    a = atr(h, l, c, atr_len)
    close_t = pd.DatetimeIndex(b.index + pd.Timedelta(tf))

    if setup == "bb":
        lo, mid, up = bbands(c, bb_len, bb_k)
        long_ = (l < lo) & (c > lo)
        short = (h > up) & (c < up)
    elif setup == "bbprev":
        lo, mid, up = bbands(c, bb_len, bb_k)
        long_ = (np.roll(c, 1) < np.roll(lo, 1)) & (c > lo)
        short = (np.roll(c, 1) > np.roll(up, 1)) & (c < up)
    elif setup == "sweep":
        ph = np.roll(rolling_max(h, sweep_len), 1)
        pl = np.roll(rolling_min(l, sweep_len), 1)
        long_ = (l < pl) & (c > pl)
        short = (h > ph) & (c < ph)
    elif setup == "rsi":
        r = rsi(c, rsi_len)
        rp = np.roll(r, 1)
        long_ = (rp < rsi_lo) & (r >= rsi_lo)
        short = (rp > 100 - rsi_lo) & (r <= 100 - rsi_lo)
    elif setup == "stretch":
        unit = np.roll(a, st_len)          # ATR measured before the move
        mv = (c - np.roll(c, st_len)) / unit
        long_ = mv < -st_k
        short = mv > st_k
    else:
        raise ValueError(setup)
    if setup != "stretch":
        unit = a
    if confirm:
        long_ &= c > o
        short &= c < o
    a = unit

    ok = np.isfinite(a) & (a > 0)
    # session window on the signal bar's close time
    if hours_tz == "UTC":
        hr = close_t.hour.to_numpy() + close_t.minute.to_numpy() / 60.0
    else:
        lt = close_t.tz_convert(hours_tz)
        hr = lt.hour.to_numpy() + lt.minute.to_numpy() / 60.0
    ok &= (hr >= hours[0]) & (hr < hours[1])

    if trend_mode != "none":
        ht = resample(m1, trend_tf)
        hc = ht["close"].to_numpy(float)
        dist = (hc - ema(hc, trend_len)) / atr(ht["high"], ht["low"], hc, 14)
        d_ref = align_htf_to_m1(close_t, ht.index, trend_tf, dist)
        if trend_mode == "with":
            long_ &= d_ref > 0
            short &= d_ref < 0
        elif trend_mode == "flat":
            ok &= np.abs(d_ref) < trend_flat_atr
        ok &= np.isfinite(d_ref)
    if vol_len and vol_max > 0:
        ok &= a < vol_max * atr(h, l, c, vol_len)

    sig = (long_ | short) & ok
    sig[: max(bb_len, sweep_len, 50)] = False
    k = np.flatnonzero(sig)
    if cooldown > 0 and len(k):
        dk = np.where(long_[k], 1, -1)
        last = {1: -10**9, -1: -10**9}
        keepc = np.zeros(len(k), bool)
        for i, (kk, dd_) in enumerate(zip(k, dk)):
            if kk - last[dd_] > cooldown:
                keepc[i] = True
                last[dd_] = kk
        k = k[keepc]
    d = np.where(long_[k], 1, -1)
    entry = htf_close_to_m1_entry(m1.index, b.index, tf)[k]
    keep = entry < len(m1)
    k, d, entry = k[keep], d[keep], entry[keep]
    # stale signals across a data gap (weekend / holiday) are dropped
    fresh = ns(m1.index[entry]) - ns(close_t[k]) <= 5 * 60 * 10**9
    k, d, entry = k[fresh], d[fresh], entry[fresh]

    O1 = m1["open"].to_numpy(float)
    px = O1[entry]
    ak = a[k]
    if sl_mode == "extreme":
        ext_lo = rolling_min(l, ext_bars)[k]
        ext_hi = rolling_max(h, ext_bars)[k]
        sl = np.where(d > 0, px - ext_lo, ext_hi - px) + sl_buf_atr * ak
    else:
        sl = sl_atr * ak
    sl = np.maximum(sl, min_sl_atr * ak)
    good = sl <= max_sl_atr * ak

    t = ns(m1.index)
    MIN = 60 * 10**9
    t_e = t[entry]
    day0 = t_e - t_e % (86_400 * 10**9)
    t_flat = day0 + (flat_utc[0] * 60 + flat_utc[1]) * MIN
    good &= t_e < t_flat - 5 * MIN
    k, d, entry, sl, t_e, t_flat = k[good], d[good], entry[good], sl[good], t_e[good], t_flat[good]
    if max_per_day < 1000 and len(entry):
        dd = t_e // (86_400 * 10**9)
        cnt = pd.Series(1, index=dd).groupby(level=0).cumcount().to_numpy()
        m = cnt < max_per_day
        k, d, entry, sl, t_e, t_flat = k[m], d[m], entry[m], sl[m], t_e[m], t_flat[m]
    t_x = np.minimum(t_e + max_hold_min * MIN, t_flat)
    exit_idx = np.searchsorted(t, t_x, side="left")
    # if the market closes early (gap after t_x), exit at the last bar before the gap
    nxt = np.minimum(exit_idx, len(t) - 1)
    gap = (exit_idx >= len(t)) | (t[nxt] - t_x > 30 * MIN)
    exit_idx = np.where(gap, np.maximum(exit_idx - 1, entry + 1), exit_idx)
    return Signals(entry, d, sl, tp_r * sl, exit_idx=exit_idx)
