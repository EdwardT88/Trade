"""Template for multi-market strategies (used with scripts/eval_markets.py).

generate_signals(bars, sym=..., **params) receives the market's native bars (FX: M15, UTC) and returns Signals.
Rules here (illustration only, not a researched strategy): on the close of an H1 bar, fade an RSI(2) extreme
in the direction of the H4 EMA(50) trend, ATR(H1) stop, 1R target, exit after max_hold_h hours.
"""
import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr, ema, rsi

DEFAULT_PARAMS = dict(rsi_len=2, lo=10.0, sl_atr=1.5, tp_r=1.0, max_hold_h=8)


def generate_signals(bars: pd.DataFrame, sym: str = "", rsi_len=2, lo=10.0, sl_atr=1.5, tp_r=1.0, max_hold_h=8) -> Signals:
    h1 = resample(bars, "1h")
    c = h1["close"].to_numpy()
    r = rsi(c, rsi_len)
    a = atr(h1["high"], h1["low"], c, 14)
    h4 = resample(bars, "4h")
    close_t = pd.DatetimeIndex(h1.index + pd.Timedelta("1h"))
    trend = align_htf_to_m1(close_t, h4.index, "4h", h4["close"].to_numpy() - ema(h4["close"].to_numpy(), 50))
    up = (trend > 0) & (r < lo)
    dn = (trend < 0) & (r > 100 - lo)
    sig = (up | dn) & np.isfinite(a)
    entry = htf_close_to_m1_entry(bars.index, h1.index, "1h")[sig]
    d = np.where(up[sig], 1, -1)
    sl = sl_atr * a[sig]
    ok = entry < len(bars)
    entry, d, sl = entry[ok], d[ok], sl[ok]
    exit_idx = np.searchsorted(ns(bars.index), ns(bars.index[entry] + pd.Timedelta(hours=max_hold_h)))
    return Signals(entry, d, sl, tp_r * sl, exit_idx=exit_idx)
