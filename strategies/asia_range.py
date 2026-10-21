"""Asian-range play around the London open (intraday XAUUSD scalper).

Draft under research -- see results/asia_range_dev.md for the log.

Two setups on the range built during the Asian session (true-UTC Tokyo hours up to the London open):
- "bo"   breakout continuation: first completed M5 close beyond the range (+ buffer) after the London open
- "fade" liquidity sweep / false breakout: price trades beyond the range, then an M5 bar closes back
         inside -> trade back into the range, stop beyond the sweep extreme.

DATA CLOCK. The bundled parquet is stamped "New York wall-clock + 5h", not true UTC: the 17:00 ET daily
break sits at 22:00 and the 08:30 ET news spike at 13:30 all year round, so in US summer time every
timestamp is 1h ahead of true UTC. Session times are therefore computed in true UTC / local exchange time
with zoneinfo and then mapped onto the data's clock (`data_clock="ny+5"`). Use `data_clock="utc"` for a
feed that is really UTC (e.g. an MQL5 port that works from TimeGMT()).
"""
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr

MIN = 60 * 10**9
TAG_BO, TAG_FADE = 1, 2

DEFAULT_PARAMS = dict(
    mode="fade",             # "bo", "fade" or "both"
    asia_start_utc=0,        # range starts at 00:00 true UTC (Tokyo 09:00, no DST)
    window_min=180,          # trade signals from the London open (08:00 Europe/London) for 180 minutes
    atr_tf="1h", atr_len=24,  # volatility yardstick: H1 ATR(24) of the last H1 bar completed before the London open
    min_w_atr=0.0, max_w_atr=99.0,  # range-width filter in ATR units
    # breakout
    bo_buf_atr=0.0,          # M5 close must exceed the range by this many ATR
    bo_sl_atr=1.0,           # breakout stop distance in ATR
    # fade
    sweep_min_atr=0.0,       # high must exceed the range by more than this to count as a sweep
    max_ext_atr=1.0,         # if price ran further than this beyond the range it is a real breakout: no fade
    max_sweep_bars=6,        # the M5 close back inside must come within this many M5 bars of the first sweep bar
    sl_buf_atr=0.1,          # fade stop = sweep extreme + buffer
    min_sl_atr=0.25, max_sl_atr=1.5,
    tp_r=1.5,                # target = tp_r x stop distance
    max_hold_min=90,         # time exit
    flat_utc=(20, 50),       # never hold past 20:50 true UTC
    data_clock="ny+5",
)


def _data_clock(utc_ns: np.ndarray, clock: str) -> np.ndarray:
    """Map true-UTC instants (int64 ns) onto the timestamps used by the price data."""
    if clock == "utc":
        return np.asarray(utc_ns, dtype=np.int64)
    if clock != "ny+5":
        raise ValueError(clock)
    di = pd.to_datetime(np.asarray(utc_ns, dtype=np.int64), unit="ns", utc=True)
    loc = di.tz_convert("America/New_York").tz_localize(None) + pd.Timedelta(hours=5)
    return ns(loc)


def _day_events(dates, asia_start_utc, window_min, flat_utc, clock):
    """Per weekday: asia range start/end, trade window end, flat time (all on the data clock, int64 ns)."""
    lon = ZoneInfo("Europe/London")
    d = [x for x in dates if x.dayofweek < 5]
    lo_utc = np.array([pd.Timestamp(year=x.year, month=x.month, day=x.day, hour=8, tz=lon).tz_convert("UTC").value
                       for x in d], dtype=np.int64)
    midnight = np.array([pd.Timestamp(year=x.year, month=x.month, day=x.day, tz="UTC").value for x in d], dtype=np.int64)
    a0 = midnight + int(asia_start_utc * 60) * MIN
    fl = midnight + (flat_utc[0] * 60 + flat_utc[1]) * MIN
    w1 = lo_utc + window_min * MIN
    return tuple(_data_clock(v, clock) for v in (a0, lo_utc, w1, fl))


def generate_signals(m1: pd.DataFrame, mode="fade", asia_start_utc=0, window_min=180, atr_tf="1h", atr_len=24,
                     min_w_atr=0.0, max_w_atr=99.0, bo_buf_atr=0.0, bo_sl_atr=1.0,
                     sweep_min_atr=0.0, max_ext_atr=1.0, max_sweep_bars=6, sl_buf_atr=0.1,
                     min_sl_atr=0.25, max_sl_atr=1.5, tp_r=1.5, max_hold_min=90, flat_utc=(20, 50),
                     data_clock="ny+5") -> Signals:
    idx = m1.index
    t = ns(idx)
    n = len(t)
    H = m1["high"].to_numpy(float)
    L = m1["low"].to_numpy(float)

    m5 = resample(m1, "5min")
    o5 = ns(m5.index)
    ct5 = o5 + 5 * MIN
    h5, l5, c5 = (m5[k].to_numpy(float) for k in ("high", "low", "close"))
    ent5 = htf_close_to_m1_entry(idx, m5.index, "5min")

    ht = resample(m1, atr_tf)
    a_ht = atr(ht["high"], ht["low"], ht["close"], atr_len)

    dates = pd.DatetimeIndex(idx.normalize().unique())
    a0, lo_t, w1, fl = _day_events(dates, asia_start_utc, window_min, flat_utc, data_clock)
    # ATR of the last HTF bar completed at the London open
    A = align_htf_to_m1(pd.DatetimeIndex(pd.to_datetime(lo_t, unit="ns", utc=True)), ht.index, atr_tf, a_ht)

    do_bo = mode in ("bo", "both")
    do_fade = mode in ("fade", "both")
    rows = []

    def emit(k, d, sl, tag, t_flat):
        ei = int(ent5[k])
        if ei >= n or t[ei] >= t_flat or not np.isfinite(sl) or sl <= 0:
            return
        t_exit = min(t[ei] + max_hold_min * MIN, t_flat)
        xi = int(np.searchsorted(t, t_exit, side="left"))
        rows.append((ei, d, sl, tp_r * sl, xi, tag))

    for di in range(len(a0)):
        s, e = np.searchsorted(t, [a0[di], lo_t[di]])
        exp_bars = (lo_t[di] - a0[di]) // MIN
        if e - s < 0.8 * exp_bars or e >= n:
            continue
        a = A[di]
        if not np.isfinite(a) or a <= 0:
            continue
        hi, lo = H[s:e].max(), L[s:e].min()
        w = hi - lo
        if w < min_w_atr * a or w > max_w_atr * a:
            continue
        k0 = int(np.searchsorted(o5, lo_t[di], side="left"))
        k1 = int(np.searchsorted(ct5, w1[di], side="right"))
        if k1 <= k0 or k0 < 1:
            continue
        t_flat = fl[di]

        if do_bo:
            lvl_up, lvl_dn = hi + bo_buf_atr * a, lo - bo_buf_atr * a
            done_up = done_dn = False
            for k in range(k0, k1):
                if not done_up and c5[k] > lvl_up and c5[k - 1] <= lvl_up:
                    emit(k, 1, bo_sl_atr * a, TAG_BO, t_flat)
                    done_up = True
                if not done_dn and c5[k] < lvl_dn and c5[k - 1] >= lvl_dn:
                    emit(k, -1, bo_sl_atr * a, TAG_BO, t_flat)
                    done_dn = True

        if do_fade:
            # short after a sweep of the Asian high, long after a sweep of the Asian low
            for d, lvl in ((-1, hi), (1, lo)):
                armed_k = -1
                ext = lvl
                for k in range(k0, k1):
                    beyond = (h5[k] - lvl) if d < 0 else (lvl - l5[k])
                    if armed_k < 0 and beyond > sweep_min_atr * a:
                        armed_k = k
                    if armed_k < 0:
                        continue
                    ext = max(ext, h5[k]) if d < 0 else min(ext, l5[k])
                    if k - armed_k > max_sweep_bars:
                        break
                    if abs(ext - lvl) > max_ext_atr * a:
                        break
                    inside = c5[k] < lvl if d < 0 else c5[k] > lvl
                    if inside:
                        stop = ext + d * -1 * sl_buf_atr * a  # beyond the extreme
                        sl = (stop - c5[k]) * -d
                        if sl > max_sl_atr * a:
                            break
                        emit(k, d, max(sl, min_sl_atr * a), TAG_FADE, t_flat)
                        break

    if not rows:
        return Signals.empty()
    r = np.array(rows, dtype=float)
    r = r[np.argsort(r[:, 0], kind="stable")]
    return Signals(r[:, 0].astype(np.int64), r[:, 1].astype(np.int64), r[:, 2], r[:, 3],
                   exit_idx=r[:, 4].astype(np.int64), tag=r[:, 5].astype(np.int64))
