"""Moving-average regime swing strategy for XAUUSD: H4 EMA(50/200) regime, enter on the regime flip and
re-enter on reclaims of EMA(20) while the regime persists, ATR stop + ATR chandelier trail, flat on Friday.

RESEARCH RESULT: WEAK / NOT STATISTICALLY ESTABLISHED (see results/swing_ma_regime_dev.md).
    dev 2022-2023 (no limits, default spread + 5%/yr swap): 103 trades, +0.191R, SE 0.111 (t 1.7), PF 1.51
    2024 validation (run once, not revised):               56 trades, +0.127R, SE 0.170 (t 0.7), PF 1.22
    2024 longs +0.35R (41) / shorts -0.49R (15); random entries in the regime direction with the same exits
    did as well as the reclaim trigger in 2024 (p = 0.33), so the 2024 profit is mostly "be long gold in 2024".
    46 parameter combos were tried on dev.

RULES (DEFAULT_PARAMS; all on completed bars, everything bar by bar)
- Bars: H4 in BROKER SERVER TIME of a New-York-close broker (GMT+2 winter / GMT+3 summer: H4 bars open at
  00,04,08,12,16,20 server = 17:00 New York + 4k h). See _server_clock for how this is derived from the data.
- Regime (H4, last completed bar): up if EMA(50) > EMA(200), down if EMA(50) < EMA(200).
- Entries, only when flat (one position at a time), decided at an H4 close, filled at the next tick:
    flip:    the regime turned up on this bar (EMA50 crossed above EMA200)            -> buy
    reclaim: regime up, H4 close > EMA(20) and previous H4 close <= its EMA(20)        -> buy
    shorts are the mirror image.
- Initial stop: 2.0 x ATR(14, H4) of the signal bar (MT5 iATR = SMA of true range). No take-profit.
- Trailing (every M1 bar): stop = max(stop, highest bid since entry - 3.0 x ATR_entry); shorts:
  stop = min(stop, lowest ask since entry + 3.0 x ATR_entry). Starts tightening after +1 ATR (+0.5 R). Never loosens.
- Exits: stop / trail; regime no longer agrees at an H4 close (EMA50 back through EMA200: rare);
  Friday 20:00 UTC (data clock) close-all; 10 calendar days max (never binding with the Friday close).
- Filters: no new entries Friday >= 12:00 UTC; fills or signal exits that would fall within 15 min of the
  daily reopen wait until reopen + 15 min (spreads are wide then).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import Signals, ns
from backtest.indicators import atr, ema

DEFAULT_PARAMS = dict(
    tf_min=240,            # signal / execution timeframe in minutes (240 = H4)
    regime_tf_min=240,     # regime timeframe (240 = H4, 1440 = D1)
    grid_shift_h=0,        # shift of the bar grid against the broker server clock (robustness tests only)
    fast=50,               # regime: EMA(fast) vs EMA(slow) on the regime TF
    slow=200,
    regime="cross",        # 'cross': EMA(fast) > EMA(slow) is up; 'price': close > EMA(slow) is up
    triggers="flip+reclaim",  # '+'-joined subset of: flip | kc | reclaim | state
    band_len=20,           # signal-TF EMA used by kc / reclaim / state triggers and the 'band' exit
    kc_k=1.0,              # Keltner band = EMA(band_len) +/- kc_k * ATR(signal TF)  (kc / state triggers only)
    atr_len=14,
    sl_atr=2.0,            # initial stop, x ATR(signal TF) at entry
    trail_atr=3.0,         # chandelier: stop = best price since entry - trail_atr * ATR_entry (0 = off)
    be_r=0.0,              # >0: at +be_r R stop to entry + be_lock_r R, trailing only after that
    be_lock_r=0.1,
    exit_on="flip",        # 'none' | 'flip' (regime no longer agrees) | 'band' (signal-TF close back through EMA(band_len))
    max_hold_days=10,      # calendar days
    fri_close=True,        # flat on Friday at fri_exit_h (data clock), no new entries Friday from fri_cutoff_h
    fri_exit_h=20,
    fri_cutoff_h=12,
    reopen_delay_min=15,   # fills / signal exits within N min after the daily reopen wait until reopen + N min
    sides="both",          # 'both' | 'long' | 'short'
)

_NS_MIN = 60 * 10**9
_NS_H = 60 * _NS_MIN


def _server_clock(t: np.ndarray) -> np.ndarray:
    """Broker server clock (New York wall time + 7 h: 17:00 NY close = 00:00 server) for every M1 bar, in ns.

    The M1 index is either true UTC or HistData's fixed clock (New York wall time + 5 h all year, which is what
    data/xauusd_m1.parquet used when this was written). The two only differ while US daylight saving is on.
    Decide from where the daily trading break starts: 17:00 New York in true UTC, 22:00 in the fixed clock."""
    if len(t) < 2:
        return t + 2 * _NS_H
    gap = np.diff(t)
    i = np.flatnonzero((gap >= 30 * _NS_MIN) & (gap <= 180 * _NS_MIN))
    if len(i) == 0:
        return t + 2 * _NS_H
    ny = ns(pd.DatetimeIndex(pd.to_datetime(t, utc=True)).tz_convert("America/New_York").tz_localize(None))
    fixed_hits = np.mean(((t[i] + _NS_MIN) // _NS_H) % 24 == 22)   # break start in the data clock
    utc_hits = np.mean(((ny[i] + _NS_MIN) // _NS_H) % 24 == 17)    # break start in New York time if t is UTC
    return ny + 7 * _NS_H if utc_hits > fixed_hits + 0.02 else t + 2 * _NS_H


def _bars(m1: pd.DataFrame, clock: np.ndarray, minutes: int) -> dict:
    """OHLC bars of `minutes` built from M1 on `clock` (ns). `end` = index of the first M1 bar after
    the bar (where a decision on its close fills; == len(m1) for the last bar)."""
    period = minutes * _NS_MIN
    bucket = clock // period
    starts = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    ends = np.r_[starts[1:], len(clock)]
    h = np.maximum.reduceat(m1["high"].to_numpy(float), starts)
    lo = np.minimum.reduceat(m1["low"].to_numpy(float), starts)
    o = m1["open"].to_numpy(float)[starts]
    c = m1["close"].to_numpy(float)[ends - 1]
    return dict(open=o, high=h, low=lo, close=c, start=starts, end=ends)


def _regime(c: np.ndarray, fast: int, slow: int, kind: str):
    es = ema(c, slow)
    if kind == "cross":
        ef = ema(c, fast)
        up, dn = ef > es, ef < es
    elif kind == "price":
        up, dn = c > es, c < es
    else:
        raise ValueError(kind)
    warm = max(fast, slow)
    up[:warm] = False
    dn[:warm] = False
    return up, dn


def _reopen_bars(t: np.ndarray, server: np.ndarray) -> np.ndarray:
    """M1 indices of the daily / weekly reopen: first bar after a >= 30 min gap that resumes between
    22:00 and 02:59 server time (other intraday holes in the data are not reopens)."""
    gap = np.diff(t)
    i = np.flatnonzero(gap >= 30 * _NS_MIN) + 1
    hr = (server[i] // _NS_H) % 24
    return i[(hr >= 22) | (hr <= 2)]


def _delay_reopen(idx: np.ndarray, t: np.ndarray, reopen: np.ndarray, delay_min: int) -> np.ndarray:
    """Move M1 indices that fall within `delay_min` minutes after a reopen to the first bar at/after reopen + delay."""
    if delay_min <= 0 or len(idx) == 0 or len(reopen) == 0:
        return idx
    n = len(t)
    out = idx.copy()
    ok = idx < n
    k = np.searchsorted(reopen, idx, side="right") - 1
    ok &= k >= 0
    r = reopen[np.maximum(k, 0)]
    target = t[r] + delay_min * _NS_MIN
    hit = ok & (t[np.minimum(idx, n - 1)] < target)
    out[hit] = np.searchsorted(t, target[hit])
    return out


def _next_event(events: np.ndarray, after: np.ndarray, nb: int) -> np.ndarray:
    """For each bar position in `after`, the first bar > it where `events` is True (nb if none)."""
    ev = np.flatnonzero(events)
    k = np.searchsorted(ev, after, side="right")
    return np.where(k < len(ev), ev[np.minimum(k, len(ev) - 1)], nb)


def generate_signals(m1: pd.DataFrame, tf_min=240, regime_tf_min=240, grid_shift_h=0, fast=50, slow=200, regime="cross",
                     triggers="flip+reclaim", band_len=20, kc_k=1.0, atr_len=14, sl_atr=2.0, trail_atr=3.0, be_r=0.0,
                     be_lock_r=0.1, exit_on="flip", max_hold_days=10, fri_close=True, fri_exit_h=20, fri_cutoff_h=12,
                     reopen_delay_min=15, sides="both") -> Signals:
    t = ns(m1.index)
    n_m1 = len(t)
    if n_m1 == 0:
        return Signals.empty()
    server = _server_clock(t)
    grid = server + int(round(grid_shift_h * _NS_H))
    reopen = _reopen_bars(t, server)
    b = _bars(m1, grid, int(tf_min))
    h, lo, c, end = b["high"], b["low"], b["close"], b["end"]
    nb = len(c)
    a = atr(h, lo, c, atr_len)

    # ---- regime (last completed regime-TF bar at each signal-TF close)
    if int(regime_tf_min) == int(tf_min):
        r_up, r_dn = _regime(c, fast, slow, regime)
    else:
        rb = _bars(m1, grid, int(regime_tf_min))
        ru, rd = _regime(rb["close"], fast, slow, regime)
        pos = np.searchsorted(rb["end"], end, side="right") - 1
        ok = pos >= 0
        r_up = np.zeros(nb, bool)
        r_dn = np.zeros(nb, bool)
        r_up[ok] = ru[pos[ok]]
        r_dn[ok] = rd[pos[ok]]

    # ---- entry triggers on the signal TF (bar b decided at its close)
    eb = ema(c, band_len)
    up_band = eb + kc_k * a
    dn_band = eb - kc_k * a
    prev = lambda x: np.r_[np.nan, x[:-1]]  # noqa: E731
    trig = set(triggers.split("+"))
    unknown = trig - {"flip", "kc", "reclaim", "state"}
    if unknown:
        raise ValueError(unknown)
    long_t = np.zeros(nb, bool)
    short_t = np.zeros(nb, bool)
    code = np.zeros(nb, np.int64)  # trigger code of the bar (first matching in this order): 1 flip, 2 kc, 3 reclaim, 4 state

    def add(lt, st, k):
        new = (lt | st) & (code == 0)
        code[new] = k
        long_t[:] |= lt
        short_t[:] |= st

    if "flip" in trig:
        add(r_up & ~np.r_[False, r_up[:-1]], r_dn & ~np.r_[False, r_dn[:-1]], 1)
    if "kc" in trig:
        add(r_up & (c > up_band) & (prev(c) <= prev(up_band)), r_dn & (c < dn_band) & (prev(c) >= prev(dn_band)), 2)
    if "reclaim" in trig:
        add(r_up & (c > eb) & (prev(c) <= prev(eb)), r_dn & (c < eb) & (prev(c) >= prev(eb)), 3)
    if "state" in trig:  # enter whenever flat while the regime agrees and price is beyond the band
        add(r_up & (c > up_band), r_dn & (c < dn_band), 4)
    valid = np.isfinite(a) & (a > 0) & np.isfinite(eb) & (end < n_m1)
    valid[: max(atr_len, band_len)] = False
    long_t &= valid
    short_t &= valid
    if sides == "long":
        short_t[:] = False
    elif sides == "short":
        long_t[:] = False
    long_t &= ~short_t  # (cannot both be true with a single regime, kept for safety)
    sig = long_t | short_t
    bars_i = np.flatnonzero(sig)
    direction = np.where(long_t[sig], 1, -1)
    atr_e = a[sig]
    tag = code[sig] * 10 + np.where(direction > 0, 1, 2)  # e.g. 11 = flip long, 32 = reclaim short

    # ---- entry fill: first M1 after the bar close; +1 M1 bar when signal-based exits exist so that a
    # stop-and-reverse exit (at the same M1 bar) is processed before the new entry
    entry = end[bars_i] + (1 if exit_on != "none" else 0)
    entry = _delay_reopen(entry, t, reopen, reopen_delay_min)

    # ---- exits
    t_entry = t[np.minimum(entry, n_m1 - 1)]
    exit_idx = np.searchsorted(t, t_entry + int(round(max_hold_days * 24)) * _NS_H)
    if exit_on != "none":
        if exit_on == "flip":
            ex_long, ex_short = ~r_up, ~r_dn
        elif exit_on == "band":
            ex_long, ex_short = c < eb, c > eb
        else:
            raise ValueError(exit_on)
        nxt = np.where(direction > 0, _next_event(ex_long, bars_i, nb), _next_event(ex_short, bars_i, nb))
        has = nxt < nb
        sx = np.full(len(bars_i), n_m1, np.int64)
        sx[has] = _delay_reopen(end[nxt[has]], t, reopen, reopen_delay_min)
        exit_idx = np.minimum(exit_idx, sx)
    keep = entry < n_m1
    ent_ts = pd.to_datetime(t_entry, utc=True)
    if fri_close:
        dow = ent_ts.dayofweek.to_numpy().astype(np.int64)
        hr = ent_ts.hour.to_numpy()
        # Sunday-reopen entries belong to the coming week: (4 - 6) % 7 = 5 days -> that Friday
        t_fri = ns(ent_ts.normalize()) + ((4 - dow) % 7) * 24 * _NS_H + int(fri_exit_h) * _NS_H
        fx = np.searchsorted(t, t_fri)
        # market already closed at that time (holiday / early close): exit at the last bar before the gap
        late = (fx < n_m1) & (t[np.minimum(fx, n_m1 - 1)] - t_fri > 5 * _NS_MIN)
        fx = np.where(late, fx - 1, fx)
        exit_idx = np.minimum(exit_idx, fx)
        keep &= ~((dow == 4) & (hr >= fri_cutoff_h))
    exit_idx = np.where(exit_idx >= n_m1, -1, exit_idx)  # beyond the data: engine closes at end of data
    keep &= (exit_idx == -1) | (exit_idx > entry)

    entry, direction, atr_e, exit_idx, tag = entry[keep], direction[keep], atr_e[keep], exit_idx[keep], tag[keep]
    n = len(entry)
    sl = sl_atr * atr_e
    if be_r > 0:
        be_trig = np.full(n, float(be_r))
        be_off = be_lock_r * sl
    elif trail_atr > 0:  # trailing active from entry, no breakeven lock (offset -sl never moves the stop itself)
        be_trig = np.full(n, 1e-9)
        be_off = -sl
    else:
        be_trig = np.zeros(n)
        be_off = np.zeros(n)
    trail = trail_atr * atr_e if trail_atr > 0 else np.zeros(n)
    return Signals(entry, direction, sl, np.zeros(n), exit_idx=exit_idx, be_trigger_r=be_trig, be_offset=be_off,
                   trail_dist=trail, tag=tag)
