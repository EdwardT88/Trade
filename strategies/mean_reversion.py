"""Mean-reversion scalp for XAUUSD: fade a failed break of the previous day's high/low, on quiet days only.

Final rules (setup="pdhl", the DEFAULT_PARAMS):

  Timeframes / indicators (all on completed bars, all times UTC)
  - Signal bars: M5. Volatility unit: ATR(14) of H1 (MT5 iATR = simple average of true range), value of
    the last *completed* H1 bar at the M5 close.
  - Reference levels: PDH / PDL = high / low of the previous full UTC trading day (a "full" day has >= 12 hours
    of quotes, so the 1-hour Sunday-evening stub is ignored; Monday uses Friday).
  - Regime filter ("quiet day"): today's range so far (UTC day, from 00:00 up to and including the signal bar)
    must be <= max_day_rng x D1 ATR(14), where D1 ATR(14) is the simple average true range of the last 14
    completed full UTC days. Days that have already travelled more than an average day are trend/news days.

  Entry (session window: M5 bars that close between 07:00 and 20:00 UTC)
  - Short: during the window an M5 bar trades above PDH (the "pierce"); the first M5 bar that then CLOSES
    back below PDH is the signal (it may be the pierce bar itself). Long: mirror image at PDL.
    The pierce must happen inside the window (the state resets outside it).
  - At most one signal per side per UTC day (so at most 2 trades/day); one position at a time.
  - Enter at market at the open of the next M1 bar (= right after the M5 close).

  Exit
  - Stop: beyond the extreme reached since the pierce: dist = |entry - extreme| + 0.3 x ATR_H1,
    floored at 1.0 x ATR_H1. Skip the trade if dist > 2.0 x ATR_H1.
  - Target: 1.5 x stop distance (fixed R).
  - Time exit: 90 minutes after entry, and in any case flat at 20:45 UTC (before the 21:00 rollover; on
    Fridays this is before the weekend close).

Other setups ("bb", "sweep", "rsi", "stretch") are the screening variants from the research log
(results/mean_reversion_dev.md). They are kept only for reproducibility; all of them were negative after costs.
"""
import numpy as np
import pandas as pd
from numba import njit

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr, bbands, ema, rolling_max, rolling_min, rsi

DEFAULT_PARAMS = dict(
    setup="pdhl",            # previous-day high/low failed-break fade
    tf="5min",               # signal timeframe
    unit_tf="1h", atr_len=14,  # volatility unit = H1 ATR(14)
    hours=(7, 20),           # signal bar must close in [07:00, 20:00) UTC
    max_day_rng=1.0,         # quiet-day filter: day range so far <= 1.0 x D1 ATR(14)  (0 = off)
    sl_buf_atr=0.3,          # stop = beyond the sweep extreme + 0.3 ATR ...
    min_sl_atr=1.0,          # ... but at least 1.0 ATR
    max_sl_atr=2.0,          # skip if the stop would exceed 2.0 ATR
    tp_r=1.5,                # target = 1.5 x stop
    max_hold_min=90,         # time exit
    flat_utc=(20, 45),       # never hold past 20:45 UTC
)


@njit(cache=True)
def _level_sweeps(h, l, c, lvl_hi, lvl_lo, day, active):
    """First close back inside a frozen daily level after it was pierced, per side per day.
    Returns (bar index, direction, extreme since the pierce)."""
    n = h.shape[0]
    ks = np.empty(n, np.int64)
    ds = np.empty(n, np.int64)
    xs = np.empty(n)
    m = 0
    cur = -1
    ph = False
    pl = False
    xh = 0.0
    xl = 0.0
    done_h = False
    done_l = False
    for k in range(n):
        if day[k] != cur:
            cur = day[k]
            ph = pl = False
            done_h = done_l = False
        if not active[k] or not np.isfinite(lvl_hi[k]):
            ph = pl = False
            continue
        if not done_h:
            if h[k] > lvl_hi[k]:
                xh = h[k] if not ph else max(xh, h[k])
                ph = True
            if ph and c[k] < lvl_hi[k]:
                ks[m] = k
                ds[m] = -1
                xs[m] = xh
                m += 1
                done_h = True
        if not done_l:
            if l[k] < lvl_lo[k]:
                xl = l[k] if not pl else min(xl, l[k])
                pl = True
            if pl and c[k] > lvl_lo[k]:
                ks[m] = k
                ds[m] = 1
                xs[m] = xl
                m += 1
                done_l = True
    return ks[:m], ds[:m], xs[:m]


def _full_days(m1: pd.DataFrame) -> pd.DataFrame:
    """UTC daily bars with >= 12 hours of quotes (drops Sunday-evening stubs and holiday fragments)."""
    d1 = resample(m1, "1D")
    cnt = m1["close"].resample("1D").count().reindex(d1.index).fillna(0).to_numpy()
    return d1[cnt >= 12 * 60]


def _prev_day_pos(d1: pd.DataFrame, bar_day: np.ndarray) -> np.ndarray:
    """Index into d1 of the last full day strictly before each bar's UTC day (-1 = none)."""
    return np.searchsorted(ns(d1.index), bar_day, side="left") - 1


def generate_signals(m1: pd.DataFrame, setup="pdhl", tf="5min", unit_tf="1h", atr_len=14, hours=(7, 20),
                     max_day_rng=1.0, sl_buf_atr=0.3, min_sl_atr=1.0, max_sl_atr=2.0, tp_r=1.5,
                     max_hold_min=90, flat_utc=(20, 45),
                     # screening-only options (research log)
                     bb_len=20, bb_k=2.0, sweep_len=48, rsi_len=14, rsi_lo=30.0, st_len=6, st_k=4.0,
                     ext_bars=2, cooldown=0, trend_tf="1h", trend_len=50, trend_mode="none", trend_flat_atr=1.0,
                     hours_tz="UTC", max_per_day=1000) -> Signals:
    b = resample(m1, tf)
    o, h, l, c = (b[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    close_t = pd.DatetimeIndex(b.index + pd.Timedelta(tf))
    bar_day = ns((close_t - pd.Timedelta("1ns")).floor("D"))  # a bar closing at 00:00 belongs to the old day
    a_sig = atr(h, l, c, atr_len)
    if unit_tf is None or unit_tf == tf:
        unit = a_sig
    else:
        ut = resample(m1, unit_tf)
        unit = align_htf_to_m1(close_t, ut.index, unit_tf, atr(ut["high"], ut["low"], ut["close"], atr_len))

    if hours_tz == "UTC":
        hr = close_t.hour.to_numpy() + close_t.minute.to_numpy() / 60.0
    else:  # DST-aware local clock, e.g. "Europe/London"
        lt = close_t.tz_convert(hours_tz)
        hr = lt.hour.to_numpy() + lt.minute.to_numpy() / 60.0
    in_hours = (hr >= hours[0]) & (hr < hours[1])

    n = len(c)
    ext = np.full(n, np.nan)  # stop reference (extreme) per signal bar
    if setup == "pdhl":
        d1 = _full_days(m1)
        pos = _prev_day_pos(d1, bar_day)
        lh = np.where(pos >= 0, d1["high"].to_numpy()[np.maximum(pos, 0)], np.nan)
        ll = np.where(pos >= 0, d1["low"].to_numpy()[np.maximum(pos, 0)], np.nan)
        ks, ds, xs = _level_sweeps(h, l, c, lh, ll, bar_day, in_hours)
        long_ = np.zeros(n, bool)
        short = np.zeros(n, bool)
        long_[ks[ds > 0]] = True
        short[ks[ds < 0]] = True
        ext[ks] = xs
    else:
        if setup == "bb":          # Bollinger pierce and close back inside
            lo, _, up = bbands(c, bb_len, bb_k)
            long_ = (l < lo) & (c > lo)
            short = (h > up) & (c < up)
        elif setup == "sweep":     # rolling-range sweep and close back inside
            ph = np.roll(rolling_max(h, sweep_len), 1)
            pl = np.roll(rolling_min(l, sweep_len), 1)
            long_ = (l < pl) & (c > pl)
            short = (h > ph) & (c < ph)
        elif setup == "rsi":       # RSI crosses back from an extreme
            r = rsi(c, rsi_len)
            rp = np.roll(r, 1)
            long_ = (rp < rsi_lo) & (r >= rsi_lo)
            short = (rp > 100 - rsi_lo) & (r <= 100 - rsi_lo)
        elif setup == "stretch":   # move over st_len bars > st_k x (pre-move) ATR
            u0 = np.roll(a_sig, st_len)
            mv = (c - np.roll(c, st_len)) / u0
            long_ = mv < -st_k
            short = mv > st_k
            unit = u0 if unit_tf is None or unit_tf == tf else unit
        else:
            raise ValueError(setup)
        ext = np.where(long_, rolling_min(l, ext_bars), rolling_max(h, ext_bars))

    ok = np.isfinite(unit) & (unit > 0) & in_hours
    if trend_mode != "none":
        ht = resample(m1, trend_tf)
        hc = ht["close"].to_numpy(float)
        dist = (hc - ema(hc, trend_len)) / atr(ht["high"], ht["low"], hc, 14)
        d_ref = align_htf_to_m1(close_t, ht.index, trend_tf, dist)
        if trend_mode == "with":     # only fade in the direction of the HTF trend
            long_ &= d_ref > 0
            short &= d_ref < 0
        elif trend_mode == "flat":   # only when the HTF is not stretched
            ok &= np.abs(d_ref) < trend_flat_atr
        ok &= np.isfinite(d_ref)
    if max_day_rng > 0:
        d1 = _full_days(m1)
        d_atr = atr(d1["high"], d1["low"], d1["close"], 14)
        pos = _prev_day_pos(d1, bar_day)
        da = np.where(pos >= 0, d_atr[np.maximum(pos, 0)], np.nan)
        g = pd.DataFrame({"h": h, "l": l, "d": bar_day})
        rng = (g.groupby("d")["h"].cummax() - g.groupby("d")["l"].cummin()).to_numpy()
        ok &= np.isfinite(da) & (rng <= max_day_rng * da)

    sig = (long_ | short) & ok
    sig[: max(bb_len, 50) if setup != "sweep" else max(sweep_len, 50)] = False
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

    px = m1["open"].to_numpy(float)[entry]
    uk = unit[k]
    sl = (px - ext[k]) * d + sl_buf_atr * uk
    sl = np.maximum(sl, min_sl_atr * uk)
    good = np.isfinite(sl) & (sl <= max_sl_atr * uk)

    t = ns(m1.index)
    MIN = 60 * 10**9
    t_e = t[entry]
    day0 = t_e - t_e % (86_400 * 10**9)
    t_flat = day0 + (flat_utc[0] * 60 + flat_utc[1]) * MIN
    good &= t_e < t_flat - 5 * MIN
    k, d, entry, sl, t_e, t_flat = k[good], d[good], entry[good], sl[good], t_e[good], t_flat[good]
    if max_per_day < 1000 and len(entry):
        cnt = pd.Series(1, index=t_e // (86_400 * 10**9)).groupby(level=0).cumcount().to_numpy()
        m = cnt < max_per_day
        k, d, entry, sl, t_e, t_flat = k[m], d[m], entry[m], sl[m], t_e[m], t_flat[m]
    t_x = np.minimum(t_e + max_hold_min * MIN, t_flat)
    exit_idx = np.searchsorted(t, t_x, side="left")
    # if the market closes early (gap after t_x), exit at the last bar before the gap
    nxt = np.minimum(exit_idx, len(t) - 1)
    gap = (exit_idx >= len(t)) | (t[nxt] - t_x > 30 * MIN)
    exit_idx = np.where(gap, np.maximum(exit_idx - 1, entry + 1), exit_idx)
    return Signals(entry, d, sl, tp_r * sl, exit_idx=exit_idx)
