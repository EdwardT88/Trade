"""Indicators that match MetaTrader 5's built-in definitions, so Python research ports 1:1 to MQL5.

- ema:  iMA(MODE_EMA)  alpha = 2/(n+1), seeded with the first value
- sma:  iMA(MODE_SMA)
- atr:  iATR           simple moving average of true range (NOT Wilder smoothing)
- rsi:  iRSI           Wilder smoothing seeded with a simple average
- bbands: iBands       SMA +/- k * population standard deviation

All functions take/return numpy arrays (or pandas Series) and never look ahead:
value[t] only uses data up to and including bar t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit


def ema(x, n: int) -> np.ndarray:
    return pd.Series(np.asarray(x, dtype=float)).ewm(span=n, adjust=False).mean().to_numpy()


def sma(x, n: int) -> np.ndarray:
    return pd.Series(np.asarray(x, dtype=float)).rolling(n).mean().to_numpy()


def true_range(high, low, close) -> np.ndarray:
    high, low, close = (np.asarray(a, dtype=float) for a in (high, low, close))
    prev = np.roll(close, 1)
    prev[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    tr[0] = high[0] - low[0]
    return tr


def atr(high, low, close, n: int = 14) -> np.ndarray:
    return sma(true_range(high, low, close), n)


@njit(cache=True)
def _rsi_wilder(close, n):
    out = np.full(close.shape[0], np.nan)
    if close.shape[0] <= n:
        return out
    gain = 0.0
    loss = 0.0
    for i in range(1, n + 1):
        d = close[i] - close[i - 1]
        if d > 0:
            gain += d
        else:
            loss -= d
    gain /= n
    loss /= n
    out[n] = 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)
    for i in range(n + 1, close.shape[0]):
        d = close[i] - close[i - 1]
        g = d if d > 0 else 0.0
        l_ = -d if d < 0 else 0.0
        gain = (gain * (n - 1) + g) / n
        loss = (loss * (n - 1) + l_) / n
        out[i] = 100.0 if loss == 0 else 100.0 - 100.0 / (1.0 + gain / loss)
    return out


def rsi(close, n: int = 14) -> np.ndarray:
    return _rsi_wilder(np.asarray(close, dtype=float), n)


def bbands(close, n: int = 20, k: float = 2.0):
    s = pd.Series(np.asarray(close, dtype=float))
    mid = s.rolling(n).mean()
    sd = s.rolling(n).std(ddof=0)
    return (mid - k * sd).to_numpy(), mid.to_numpy(), (mid + k * sd).to_numpy()


def rolling_max(x, n: int) -> np.ndarray:
    return pd.Series(np.asarray(x, dtype=float)).rolling(n).max().to_numpy()


def rolling_min(x, n: int) -> np.ndarray:
    return pd.Series(np.asarray(x, dtype=float)).rolling(n).min().to_numpy()
