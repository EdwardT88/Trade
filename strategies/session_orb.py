"""Session opening-range breakout (ORB) scalper for XAUUSD.

Draft under research -- see results/session_orb_dev.md for the log.
"""
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr

# session name -> (IANA zone, local hour, local minute)
SESSIONS = {
    "london": ("Europe/London", 8, 0),      # 07:00 UTC (BST) / 08:00 UTC (GMT)
    "comex": ("America/New_York", 8, 20),   # 12:20 UTC (EDT) / 13:20 UTC (EST)
    "ny": ("America/New_York", 9, 30),      # 13:30 UTC (EDT) / 14:30 UTC (EST)
}

DEFAULT_PARAMS = dict(
    sessions=("london", "ny"),
    or_min=15,               # opening range = first N minutes after the session open
    confirm_tf="1min",       # breakout = a completed bar of this TF closes beyond the range
    entry_window_min=60,     # breakout must be confirmed within this many minutes after the range ends
    buffer_atr=0.0,          # close must exceed the range by this many ATR
    atr_tf="1h", atr_len=24,  # volatility yardstick (last completed bar at range end)
    min_or_atr=0.25, max_or_atr=1.5,  # range width filter, in ATR
    sl_mode="opposite",      # "opposite" | "mid" | "atr"
    sl_atr=0.5,              # stop distance when sl_mode == "atr"
    sl_buf_atr=0.0,          # extra distance beyond the structural stop level
    max_sl_atr=1.0,          # skip the trade if the stop is wider than this (in ATR)
    min_sl_atr=0.1,          # floor for the stop distance (in ATR)
    tp_r=1.5,
    max_hold_min=90,
    flat_utc=(20, 50),       # never hold past this UTC clock time
    be_r=0.0, be_offset_atr=0.0,
    entry_mode="break",      # "break": enter after the breakout close; "retest": wait for a pullback to the level
    retest_tol_atr=0.05,
)


def _session_opens(dates: pd.DatetimeIndex, zone: str, hh: int, mm: int) -> np.ndarray:
    tz = ZoneInfo(zone)
    out = []
    for d in dates:
        if d.dayofweek > 4:
            continue
        lt = pd.Timestamp(year=d.year, month=d.month, day=d.day, hour=hh, minute=mm, tz=tz)
        out.append(lt.tz_convert("UTC").as_unit("ns").value)
    return np.asarray(sorted(set(out)), dtype=np.int64)


def generate_signals(m1: pd.DataFrame, sessions=("london", "ny"), or_min=15, confirm_tf="1min",
                     entry_window_min=60, buffer_atr=0.0, atr_tf="1h", atr_len=24,
                     min_or_atr=0.25, max_or_atr=1.5, sl_mode="opposite", sl_atr=0.5, sl_buf_atr=0.0,
                     max_sl_atr=1.0, min_sl_atr=0.1, tp_r=1.5, max_hold_min=90, flat_utc=(20, 50),
                     be_r=0.0, be_offset_atr=0.0, entry_mode="break", retest_tol_atr=0.05) -> Signals:
    idx = m1.index
    t = ns(idx)
    n = len(t)
    H = m1["high"].to_numpy(float)
    L = m1["low"].to_numpy(float)
    O = m1["open"].to_numpy(float)
    C = m1["close"].to_numpy(float)

    ht = resample(m1, atr_tf)
    a_ht = atr(ht["high"], ht["low"], ht["close"], atr_len)
    A = align_htf_to_m1(idx, ht.index, atr_tf, a_ht)

    if confirm_tf in ("1min", "1T"):
        cf_close = m1["close"].to_numpy(float)
        cf_close_t = t + 60 * 10**9                      # bar close time
        cf_entry = np.arange(1, n + 1)                   # fill at next M1 open
    else:
        cf = resample(m1, confirm_tf)
        cf_close = cf["close"].to_numpy(float)
        cf_close_t = ns(cf.index + pd.Timedelta(confirm_tf))
        cf_entry = htf_close_to_m1_entry(idx, cf.index, confirm_tf)

    dates = pd.DatetimeIndex(idx.normalize().unique())
    MIN = 60 * 10**9
    rows = []
    for name in sessions:
        zone, hh, mm = SESSIONS[name]
        for t0 in _session_opens(dates, zone, hh, mm):
            t_or = t0 + or_min * MIN
            s, e = np.searchsorted(t, [t0, t_or])
            if e - s < 0.8 * or_min or e >= n:
                continue
            a = A[e]
            if not np.isfinite(a) or a <= 0:
                continue
            hi, lo = H[s:e].max(), L[s:e].min()
            w = hi - lo
            if w < min_or_atr * a or w > max_or_atr * a:
                continue
            day0 = t0 - t0 % (86_400 * 10**9)
            t_flat = day0 + (flat_utc[0] * 60 + flat_utc[1]) * MIN
            # completed confirm bars that close inside the entry window
            c0, c1 = np.searchsorted(cf_close_t, [t_or, t_or + entry_window_min * MIN], side="left")
            # include a bar closing exactly at the window end
            c1 = np.searchsorted(cf_close_t, t_or + entry_window_min * MIN, side="right")
            if c1 <= c0:
                continue
            cc = cf_close[c0:c1]
            buf = buffer_atr * a
            brk = np.flatnonzero((cc > hi + buf) | (cc < lo - buf))
            if brk.size == 0:
                continue
            k = c0 + brk[0]
            d = 1 if cf_close[k] > hi + buf else -1
            ei = int(cf_entry[k])
            if entry_mode == "retest":
                # M1 bars after the breakout, until the window end: cancel if a bar closes back inside the
                # range; enter after the first bar that touches the broken level and closes beyond it
                lvl = hi if d > 0 else lo
                j1 = int(np.searchsorted(t, t_or + entry_window_min * MIN, side="left"))
                tol = retest_tol_atr * a
                ei = -1
                for j in range(int(cf_entry[k]), min(j1, n)):
                    cj = C[j]
                    if (cj - lvl) * d <= 0:
                        break
                    if (d > 0 and L[j] <= lvl + tol) or (d < 0 and H[j] >= lvl - tol):
                        ei = j + 1
                        break
                if ei < 0:
                    continue
            if ei >= n or t[ei] >= t_flat:
                continue
            px = O[ei]
            if sl_mode == "opposite":
                lvl = lo if d > 0 else hi
                sl = (px - lvl) * d + sl_buf_atr * a
            elif sl_mode == "mid":
                lvl = 0.5 * (hi + lo)
                sl = (px - lvl) * d + sl_buf_atr * a
            else:
                sl = sl_atr * a
            if sl > max_sl_atr * a:
                continue
            sl = max(sl, min_sl_atr * a)
            t_exit = min(t[ei] + max_hold_min * MIN, t_flat)
            xi = int(np.searchsorted(t, t_exit, side="left"))
            rows.append((ei, d, sl, tp_r * sl, xi, be_offset_atr * a, SESSION_TAG[name]))

    if not rows:
        return Signals.empty()
    r = np.array(rows, dtype=float)
    order = np.argsort(r[:, 0], kind="stable")
    r = r[order]
    m = len(r)
    return Signals(r[:, 0].astype(np.int64), r[:, 1].astype(np.int64), r[:, 2], r[:, 3],
                   exit_idx=r[:, 4].astype(np.int64), be_trigger_r=np.full(m, be_r), be_offset=r[:, 5],
                   tag=r[:, 6].astype(np.int64))


SESSION_TAG = {"london": 1, "comex": 2, "ny": 3}
