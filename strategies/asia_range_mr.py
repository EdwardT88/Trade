"""asia_range_mr: Asian-session ("night") mean reversion of the late New York move, FX M15.

VERDICT: NOT VIABLE. Dev 2013-2019 +0.136 R (t 5.9); validation 2020-2022/03 -0.025 R (t -0.7), stress -0.069 R.
Kept as the frozen, documented research choice; do not trade it.

Idea (structural): after ~15:00 New York (CME FX futures settle at 14:00 Chicago = 15:00 New York, the
London desks are gone, US cash equities close at 16:00) FX liquidity thins out. Price moves made in that
thin window into the Asian open are disproportionately liquidity noise and tend to retrace during the
quiet Asian night. The strategy fades a large 15:00 -> 19:00 New York move at the Asian open and holds it
until just before Frankfurt/London (07:00 London), with a fixed ATR stop from the start.

Rules (bars: M15, labelled by OPEN time; all clocks DST-aware via zoneinfo):
  * Evaluate once per New York weekday evening Mon-Thu (Friday evening the market is closed, Sunday has
    no 15:00 bar) at the close of the M15 bar that ends at 19:00 America/New_York
    (= 00:00 Europe/London almost all year; 30 min after the engine's x3 rollover-spread window ends).
  * move = close(bar ending 19:00 NY) - close(bar ending 15:00 NY);  A = ATR(96) on M15 (SMA of TR,
    i.e. MT5 iATR(M15, 96)) at the 19:00 bar.  Skip if either bar is missing.
  * If |move| >= thr * A: enter AGAINST the move at the open of the 19:00 NY bar (market order).
  * Stop: sl_atr * A from the fill, set at entry (never widened). No take-profit (tp_frac = 0).
  * Exit: at the open of the first bar at/after 07:00 Europe/London (cap hold_h hours). Never holds
    across 17:00 New York, so no swap is paid.
  * One position per pair; no averaging, grid or martingale.
  * EURCHF before 2015-02-01 (SNB floor era) is ignored; EURCHF is not in the chosen pair set anyway.
Chosen pairs (dev only, by the pre-stated cost filter spread / Asian M15 ATR < ~0.32):
  EURUSD, GBPUSD, USDJPY, AUDUSD, EURJPY, GBPJPY, AUDJPY.
Research log: results/asia_range_mr_dev.md
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import Signals, ns
from backtest.indicators import atr

PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY", "GBPJPY", "AUDJPY"]

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
    if n < 2:
        return Signals.empty()
    o = bars["open"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    lo = bars["low"].to_numpy(float)
    c = bars["close"].to_numpy(float)
    a = atr(h, lo, c, atr_n)

    # New York calendar days, Mon-Thu evenings
    d0, d1 = (x.tz_convert("America/New_York").tz_localize(None).normalize() for x in (idx[0], idx[-1]))
    ny_days = pd.date_range(d0, d1, freq="D")
    ny_days = ny_days[ny_days.dayofweek <= 3]
    sig_t = _local(ny_days, signal_ny, "America/New_York")   # signal = close of the bar ending here
    look_t = _local(ny_days, look_ny, "America/New_York")
    ok = ~(sig_t.isna() | look_t.isna())
    sig_t, look_t = sig_t[ok], look_t[ok]
    # bar whose CLOSE time is sig_t / look_t  -> open time = close - 15 min
    t = np.searchsorted(tn, ns(sig_t - BAR))
    k = np.searchsorted(tn, ns(look_t - BAR))
    good = (t < n - 1) & (k < n)
    t, k, sig_t, look_t = t[good], k[good], sig_t[good], look_t[good]
    good = (tn[t] == ns(sig_t - BAR)) & (tn[k] == ns(look_t - BAR)) & (tn[t + 1] == ns(sig_t))
    t, k = t[good], k[good]
    if sym == "EURCHF":
        keep = idx[t + 1] >= PEG_END
        t, k = t[keep], k[keep]

    move = c[t] - c[k]
    mv = move / a[t]
    take = np.isfinite(mv) & (np.abs(mv) >= thr)
    t, move = t[take], move[take]
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
