"""Gold swing pullback (the deployed GoldSwingCent EA) + a long-term REGIME / DIRECTION / VOLATILITY filter.

RESEARCH RESULT: NOT ACCEPTED (fails the results/TWEAK_PLAN.md rule on validation). Log: results/gold_regime_dev.md.
Final rule chosen on dev 2013-2019 only (39 combos): skip a base signal when the volatility of the last completed
D1 bar, ATR(D1,14)/close, is in the bottom 30% of the last 250 D1 bars (percentile rank < 30).
    $50 account, 2% risk:  dev $79.24 (base $56.41) | 2020-21 $43.71 (41.95) | 2022-25 $78.50 (122.45) | 2026 $46.70 (46.70)
    $50 account, 3% risk:  dev $104.50 (62.08)      | 2020-21 $41.53 (40.35) | 2022-25 $98.84 (154.70) | 2026 $45.75 (45.75)
    Validation sum 2%: 168.91 vs 211.10 baseline; 3%: 186.12 vs 240.80 -> rejected. The dev pattern (low-vol trades
    -0.14 R) reversed in 2022-2025 (low-vol trades +0.58 R, n=43). Directional regime filters (D1 SMA/EMA 100-250,
    20-250 day momentum, W1 EMA, long-only-in-up-regime etc.) did not beat the baseline robustly even on dev.
    Recommendation: keep the deployed baseline; do not add this filter.

The base signals are exactly strategies/swing_pullback.py with max_hold_days=3 (H4 EMA40 trend with slope, H1 RSI(14)
cross back through 40/60, stop 2xATR(H4), chandelier trail 3xATR, Friday 20:00 UTC flat, 3-day max hold). This module
only REMOVES base signals according to a daily/weekly regime known at the signal time (last completed D1 / W1 bar),
before the one-position-at-a-time engine runs, so a removed signal frees the slot for a later one exactly as an EA
with the filter would.

MQL5 port of the final filter (for reference only, since it was rejected): on a new signal, CopyBuffer(iATR(_Symbol,
PERIOD_D1,14)) and CopyClose(PERIOD_D1) for shifts 1..250; x_k = atr_k/close_k; pct = 100 * count(x_k <= x_1)/250;
skip the signal if pct < 30. D1 = broker day (New-York close, 17:00 NY), as modelled here; regime="none" by default.

D1 bars follow a New-York-close broker (GMT+2/+3 server): a day runs 17:00 -> 17:00 New York, no Sunday bar. W1 bars
are Monday..Friday of those days. Indicators are MT5 definitions (backtest/indicators.py). Before 250+14 D1 bars of
history exist (all of 2013 in this data set) the filter is unknown and lets every signal through (nan_pass).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import Signals, ns
from backtest.indicators import atr, ema, sma
from strategies import swing_pullback as base

BASE_PARAMS = {**base.DEFAULT_PARAMS, "max_hold_days": 3}

REGIME_DEFAULTS = dict(
    regime="none",       # 'none' | 'ma' (D1 close vs MA) | 'mom' (D1 close vs close N days ago) | 'w1' (W1 close vs EMA)
    ma_type="sma",       # 'sma' | 'ema'  (regime='ma')
    ma_len=200,          # D1 bars (regime='ma'); weeks (regime='w1')
    mom_days=60,         # regime='mom'
    slope_days=0,        # >0: regime='ma' also needs MA slope over this many D1 bars in the same direction
    band_atr=0.0,        # >0: no trades while |close - MA| < band_atr * ATR(D1,14) (regime='ma')
    reg_use="with",      # 'with': long only in up-regime, short only in down-regime
                         # 'no_short_up': only blocks shorts in an up-regime (longs always allowed)
                         # 'no_long_down': only blocks longs in a down-regime
    vol_lb=250,          # >0: volatility regime filter on ATR(D1,14)/close, percentile over vol_lb D1 bars
    vol_lo=30.0,         # skip when percentile < vol_lo  (0..100)
    vol_hi=100.0,        # skip when percentile > vol_hi
    vol_mode="pct",      # 'pct': percentile rank of ATR(D1,14)/close over vol_lb D1 bars
                         # 'ratio': ATR(D1,14) / ATR(D1,vol_lb) (MT5 iATR, $), skip when < vol_ratio_min
    vol_ratio_min=0.0,
    nan_pass=True,       # regime unknown (warm-up): True lets the base signal through
)

DEFAULT_PARAMS = {**BASE_PARAMS, **REGIME_DEFAULTS}

_NY = "America/New_York"


def daily_bars(m1: pd.DataFrame) -> pd.DataFrame:
    """D1 OHLC on a New-York-close clock. Index = UTC time at which the day is COMPLETE (17:00 NY)."""
    ny = m1.index.tz_convert(_NY).tz_localize(None)
    key = (ny + pd.Timedelta(hours=7)).normalize()
    g = m1.groupby(key.values)
    d = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                      "close": g["close"].last()})
    d = d[d.index.dayofweek < 5]  # a stray Saturday/Sunday label would only come from bad ticks
    done = (pd.DatetimeIndex(d.index) + pd.Timedelta(hours=17)).tz_localize(_NY, ambiguous="NaT",
                                                                              nonexistent="shift_forward")
    d.index = done.tz_convert("UTC").as_unit("ns")
    return d[~d.index.isna()]


def weekly_bars(d1: pd.DataFrame) -> pd.DataFrame:
    """W1 from D1 (completion-time index): a week is complete at its last D1 bar's completion time."""
    ny = d1.index.tz_convert(_NY).tz_localize(None) - pd.Timedelta(hours=17)  # back to the day label
    wk = (ny - pd.to_timedelta(ny.dayofweek, unit="D")).normalize()
    g = d1.groupby(wk.values)
    w = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                      "close": g["close"].last(), "done": g.apply(lambda x: x.index[-1])})
    w.index = pd.DatetimeIndex(w.pop("done")).as_unit("ns")
    return w


def _pct_rank(x: np.ndarray, n: int) -> np.ndarray:
    """Percentile (0..100) of x[t] within x[t-n+1..t] (fraction of window values <= x[t])."""
    s = pd.Series(x)
    return (s.rolling(n).apply(lambda v: (v <= v[-1]).mean() * 100.0, raw=True)).to_numpy()


def regime_features(m1: pd.DataFrame, ma_type="sma", ma_len=200, mom_days=60, slope_days=0,
                    vol_lb=0, regime="ma", vol_mode="pct", **_) -> pd.DataFrame:
    """Per completed D1 bar: dir (+1 up / -1 down / 0 neutral, NaN unknown), dist_atr and vol percentile."""
    d = daily_bars(m1)
    c = d["close"].to_numpy()
    a = atr(d["high"], d["low"], d["close"], 14)
    out = pd.DataFrame(index=d.index)
    if regime == "ma":
        m = (sma(c, ma_len) if ma_type == "sma" else ema(c, ma_len)).copy()
        if ma_type == "ema":
            m[:ma_len] = np.nan  # EMA needs a warm-up like the SMA before it is trusted
        dr = np.sign(c - m)
        if slope_days > 0:
            sl = np.sign(m - np.roll(m, slope_days))
            sl[:slope_days] = np.nan
            dr = np.where(sl == dr, dr, 0.0)
        out["dir"] = np.where(np.isfinite(m), dr, np.nan)
        out["dist_atr"] = (c - m) / a
    elif regime == "mom":
        prev = np.roll(c, mom_days)
        prev[:mom_days] = np.nan
        out["dir"] = np.sign(c - prev)
        out["dist_atr"] = (c - prev) / a
    elif regime == "w1":
        w = weekly_bars(d)
        wc = w["close"].to_numpy()
        we = ema(wc, ma_len).copy()
        we[:ma_len] = np.nan
        wdir = pd.Series(np.where(np.isfinite(we), np.sign(wc - we), np.nan), index=w.index)
        pos = np.searchsorted(ns(w.index), ns(d.index), side="right") - 1
        out["dir"] = np.where(pos >= 0, wdir.to_numpy()[np.maximum(pos, 0)], np.nan)
        out["dist_atr"] = np.nan
    else:
        out["dir"] = np.nan
        out["dist_atr"] = np.nan
    if vol_lb > 0 and vol_mode == "ratio":
        out["vol_pct"] = a / atr(d["high"], d["low"], d["close"], vol_lb)
    else:
        out["vol_pct"] = _pct_rank(a / c, vol_lb) if vol_lb > 0 else np.nan
    return out


def _at(feat: pd.DataFrame, t_ns: np.ndarray, col: str) -> np.ndarray:
    """Value of the last D1 bar completed at or before each time (no look-ahead)."""
    pos = np.searchsorted(ns(feat.index), t_ns, side="right") - 1
    v = feat[col].to_numpy(float)
    return np.where(pos >= 0, v[np.maximum(pos, 0)], np.nan)


def regime_mask(m1: pd.DataFrame, sig: Signals, regime="none", reg_use="with", band_atr=0.0,
                vol_lb=0, vol_lo=0.0, vol_hi=100.0, vol_mode="pct", vol_ratio_min=0.0, nan_pass=True,
                **kw) -> np.ndarray:
    """Boolean keep-mask over sig rows."""
    keep = np.ones(len(sig.entry_idx), bool)
    if regime == "none" and vol_lb <= 0:
        return keep
    feat = regime_features(m1, regime=regime, vol_lb=vol_lb, vol_mode=vol_mode, **kw)
    t = ns(m1.index)[sig.entry_idx]
    dirn = sig.direction
    if regime != "none":
        rd = _at(feat, t, "dir")
        known = np.isfinite(rd)
        if band_atr > 0:
            dist = _at(feat, t, "dist_atr")
            rd = np.where(np.abs(dist) < band_atr, 0.0, rd)
        if reg_use == "with":
            ok = rd == dirn
        elif reg_use == "no_short_up":
            ok = ~((rd > 0) & (dirn < 0))
        elif reg_use == "no_long_down":
            ok = ~((rd < 0) & (dirn > 0))
        else:
            raise ValueError(reg_use)
        keep &= np.where(known, ok, nan_pass)
    if vol_lb > 0:
        vp = _at(feat, t, "vol_pct")
        vok = (vp >= vol_ratio_min) if vol_mode == "ratio" else (vp >= vol_lo) & (vp <= vol_hi)
        keep &= np.where(np.isfinite(vp), vok, nan_pass)
    return keep


def _subset(sig: Signals, keep: np.ndarray) -> Signals:
    for f in ("entry_idx", "direction", "sl_dist", "tp_dist", "exit_idx", "be_trigger_r", "be_offset", "trail_dist", "tag"):
        v = getattr(sig, f)
        if v is not None:
            setattr(sig, f, np.asarray(v)[keep])
    return sig


def generate_signals(bars: pd.DataFrame, sym: str = "XAUUSD", **params) -> Signals:
    p = {**DEFAULT_PARAMS, **params}
    bp = {k: p[k] for k in BASE_PARAMS}
    rp = {k: p[k] for k in REGIME_DEFAULTS}
    sig = base.generate_signals(bars, **bp).finalize()
    return _subset(sig, regime_mask(bars, sig, **rp))
