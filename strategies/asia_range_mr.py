"""asia_range_mr: Asian-session ("night") mean reversion of the late New York move, FX M15.

Draft under development (see results/asia_range_mr_dev.md).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import Signals, ns
from backtest.indicators import atr

DEFAULT_PARAMS = dict(atr_n=96, look_ny="15:00", signal_ny="19:00", thr=1.5, sl_atr=3.0, tp_frac=0.0,
                      hold_h=12.0, exit_london="07:00")

PEG_END = pd.Timestamp("2015-02-01", tz="UTC")  # EURCHF: SNB floor removed 2015-01-15; ignore the peg era
BAR = pd.Timedelta("15min")


def _hm(s: str):
    h, m = s.split(":")
    return int(h), int(m)


def _local(days: pd.DatetimeIndex, hm: str, tz: str) -> pd.DatetimeIndex:
    """UTC instants of local wall-clock time `hm` in `tz` on each local calendar day (DST-aware)."""
    h, m = _hm(hm)
    naive = pd.DatetimeIndex(days.tz_localize(None).normalize()) + pd.Timedelta(hours=h, minutes=m)
    return naive.tz_localize(tz, ambiguous="NaT", nonexistent="NaT").tz_convert("UTC")


def generate_signals(bars: pd.DataFrame, sym: str = "", atr_n=96, look_ny="15:00", signal_ny="19:00", thr=1.5,
                     sl_atr=3.0, tp_frac=0.0, hold_h=12.0, exit_london="07:00") -> Signals:
    idx = pd.DatetimeIndex(bars.index)
    tn = ns(idx)
    n = len(idx)
    o = bars["open"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    lo = bars["low"].to_numpy(float)
    c = bars["close"].to_numpy(float)
    a = atr(h, lo, c, atr_n)

    # New York calendar days (Mon-Thu evenings; Friday evening the market is closed, Sunday has no 15:00 bar)
    ny_days = pd.DatetimeIndex(np.unique(idx.tz_convert("America/New_York").normalize()))
    ny_days = ny_days[ny_days.dayofweek <= 3]
    sig_t = _local(ny_days, signal_ny, "America/New_York")   # signal = close of the bar ending here
    look_t = _local(ny_days, look_ny, "America/New_York")
    ok = ~(sig_t.isna() | look_t.isna())
    sig_t, look_t = sig_t[ok], look_t[ok]
    # bar whose CLOSE time is sig_t / look_t  -> open time = close - 15 min
    t = np.searchsorted(tn, ns(sig_t - BAR))
    k = np.searchsorted(tn, ns(look_t - BAR))
    good = (t < n - 1) & (k < n)
    t, k, sig_t = t[good], k[good], sig_t[good]
    good = (tn[t] == ns(sig_t - BAR)) & (tn[k] == ns(look_t[good] - BAR)) & (tn[t + 1] == ns(sig_t))
    t, k = t[good], k[good]
    if sym == "EURCHF":
        keep = idx[t + 1] >= PEG_END
        t, k = t[keep], k[keep]

    move = c[t] - c[k]
    mv = move / a[t]
    take = np.isfinite(mv) & (np.abs(mv) >= thr)
    t, k, move = t[take], k[take], move[take]
    if len(t) == 0:
        return Signals.empty()
    entry = t + 1
    d = -np.sign(move).astype(int)
    sl = sl_atr * a[t]
    tp = tp_frac * np.abs(move) if tp_frac > 0 else np.zeros(len(t))

    # time exit: earliest of entry + hold_h and the next exit_london wall-clock time
    et = idx[entry]
    ld_days = et.tz_convert("Europe/London").normalize()
    cand = _local(ld_days, exit_london, "Europe/London")
    cand = cand.where(cand > et, _local(ld_days + pd.Timedelta(days=1), exit_london, "Europe/London"))
    end_ns = np.minimum(ns(et + pd.Timedelta(hours=hold_h)), ns(cand))
    exit_idx = np.searchsorted(tn, end_ns, side="left")
    return Signals(entry, d, sl, tp, exit_idx=exit_idx)
