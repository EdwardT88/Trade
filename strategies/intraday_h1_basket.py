"""Intraday H1 basket: multi-pair news-shock continuation (the "momentum" side of the momentum/reversal dichotomy).

Research log and results: results/intraday_h1_basket_dev.md. Verdict: marginal. Strong on dev 2013-2019, weak and
not statistically significant on validation 2020-2022 (and only after one disclosed revision, the peer filter).

Final rules (DEFAULT_PARAMS), applied independently to every instrument of the basket (PAIRS), one position each:
- Timeframe H1, all times below are bar CLOSE times. Volatility yardstick: ATR(120) on H1 (MT5 iATR = simple
  average of true range over the last 120 H1 bars, about 5 trading days, so it does not depend on the hour of day).
- Shock: move = close[0] - close[1] of the H1 bar that just closed (the previous H1 bar must open exactly 1 h
  earlier, i.e. no weekend gap). Shock if |move| > thr_atr (4.0) * ATR(120).
- Peer confirmation: at the same H1 close, at least min_peers (1) OTHER FX pair from FX_PEERS must also show
  |close[0] - close[1]| > peer_thr (4.0) * its own ATR(120) (direction of the peer move does not matter).
  Gold uses the 10 FX pairs as peers. A shock in a single pair only (a local liquidity spike) is not traded.
- Entry: market order at the open of the next bar, in the direction of the shock. No trend filter.
- Blocked entries: H1 closes from 16:00 to 18:59 New York time (daily rollover, wide spreads), Saturday/Sunday
  New York time (so the Sunday-evening open is skipped), Friday from 12:00 New York.
- Stop: sl_atr (2.0) * ATR(120) from the fill. Target: tp_r (2.0) * stop distance. Time exit: hold_h (12) hours
  after entry, and in any case at Friday 16:00 New York (no weekend holding). No breakeven/trailing.
- EURCHF is not traded (excluded on dev: SNB-managed currency, highest spread/ATR); if run on it anyway,
  signals before eurchf_from are dropped (2011-2015 peg and its removal on 2015-01-15).

Peer data: the module reads the peers' M15 files from data/markets (or peer_dir): <SYM>_m15_2012_2022.parquet and,
if present, <SYM>_m15_2026.parquet. It warns when fewer than 3 peers cover the bars being evaluated.

The "reversal" mode (RSI(2) fade in the direction of the D1 trend) and the confirm_h / trend_mode switches are
kept only to reproduce the dev comparisons.
"""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, htf_close_to_m1_entry, ns
from backtest.indicators import atr, ema, rsi

NY = "America/New_York"
H = 3600 * 10**9

# pair set chosen on dev 2013-2019: the 11 FX pairs minus EURCHF, plus gold
PAIRS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "XAUUSD"]

DEFAULT_PARAMS = dict(
    mode="momentum",      # "momentum" (continuation after a large H1 move) or "reversal" (RSI(2) fade with D1 trend)
    lookback_h=1, thr_atr=4.0,          # momentum: |close - close[lookback_h]| > thr_atr * ATR(atr_len)
    confirm_h=1,                        # momentum: ... on this many consecutive H1 closes
    rsi_lo=10.0,                        # reversal: RSI(2) < lo (long) / > 100 - lo (short)
    trend_len=20, trend_mode=0,         # D1 EMA trend filter: 0 off, 1 with trend only, -1 against trend only
    atr_len=120, sl_atr=2.0, tp_r=2.0, hold_h=12,
    no_entry_ny=(16, 19),               # no entries when the signal H1 close is in [16:00, 19:00) New York
    fri_last_entry_ny=12, fri_flat_ny=16,
    eurchf_from="2015-03-01",
    min_peers=1, peer_thr=4.0,          # cross-pair confirmation: >= min_peers OTHER basket FX pairs with
                                        # |close[0]-close[1]| > peer_thr * ATR(atr_len) at the same H1 close (0 = off)
    peer_dir=None,                      # directory with the peers' M15 parquet files (None = data/markets)
)

FX_PEERS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY"]
_PEER_Z: dict = {}


def _shock_z(h1: pd.DataFrame, atr_len: int) -> pd.Series:
    """(close[0] - close[1]) / ATR(atr_len) on H1, NaN across gaps; indexed by H1 open time."""
    c = h1["close"].to_numpy()
    a = atr(h1["high"].to_numpy(), h1["low"].to_numpy(), c, atr_len)
    t = ns(h1.index)
    z = np.full(len(c), np.nan)
    z[1:] = (c[1:] - c[:-1]) / a[1:]
    z[1:][(t[1:] - t[:-1]) != H] = np.nan
    return pd.Series(z, index=h1.index)


def _peer_z(peer: str, atr_len: int, peer_dir=None) -> pd.Series:
    """Shock z-series of a peer pair over all M15 data on disk (2012-2022 file plus a 2026 sample if present)."""
    key = (peer, atr_len, str(peer_dir))
    if key not in _PEER_Z:
        from backtest.markets import MARKETS
        root = Path(peer_dir) if peer_dir else MARKETS
        parts = []
        for f in (root / f"{peer}_m15_2012_2022.parquet", root / f"{peer}_m15_2026.parquet"):
            if f.exists():
                df = pd.read_parquet(f)
                df.index = pd.DatetimeIndex(df.index).as_unit("ns")
                parts.append(_shock_z(resample(df, "1h"), atr_len))
        _PEER_Z[key] = pd.concat(parts) if parts else pd.Series(dtype=float)
    return _PEER_Z[key]


def _peer_count(h1_index: pd.DatetimeIndex, sym: str, atr_len: int, thr: float, peer_dir=None) -> np.ndarray:
    n = np.zeros(len(h1_index), int)
    covered = 0
    for peer in FX_PEERS:
        if peer == sym:
            continue
        z = _peer_z(peer, atr_len, peer_dir).reindex(h1_index).to_numpy()
        covered += int(np.isfinite(z).mean() > 0.5) if len(z) else 0
        n += (np.abs(np.nan_to_num(z)) > thr).astype(int)
    if covered < 3:
        warnings.warn(f"intraday_h1_basket: only {covered} peer pairs have data for {sym}'s bars; "
                      "the peer filter will block most signals (set peer_dir).")
    return n


def _d1_trend(h1: pd.DataFrame, n: int) -> np.ndarray:
    """+1/-1: last completed New-York-close D1 close vs EMA(n) of D1 closes, mapped to each H1 bar."""
    ny = h1.index.tz_convert(NY)
    day = (ny + pd.Timedelta(hours=7)).normalize().tz_localize(None)  # trading day ends 17:00 New York
    dc = h1["close"].groupby(day).last()
    tr = np.sign(dc.to_numpy() - ema(dc.to_numpy(), n))
    prev = pd.Series(tr, index=dc.index).shift(1)  # previous completed day
    return prev.reindex(day).to_numpy()


def generate_signals(bars: pd.DataFrame, sym: str = "", **kw) -> Signals:
    p = {**DEFAULT_PARAMS, **kw}
    h1 = resample(bars, "1h")
    c = h1["close"].to_numpy()
    a = atr(h1["high"].to_numpy(), h1["low"].to_numpy(), c, int(p["atr_len"]))
    t = ns(h1.index)
    close_t = pd.DatetimeIndex(h1.index + pd.Timedelta("1h"))
    ny = close_t.tz_convert(NY)

    if p["mode"] == "momentum":
        L = int(p["lookback_h"])
        mv = np.full(len(c), np.nan)
        mv[L:] = c[L:] - c[:-L]
        contig = np.zeros(len(c), bool)
        contig[L:] = (t[L:] - t[:-L]) == L * H
        z = mv / a
        d = np.where(contig & (z > p["thr_atr"]), 1, np.where(contig & (z < -p["thr_atr"]), -1, 0))
        for j in range(1, int(p["confirm_h"])):  # condition must hold on `confirm_h` consecutive H1 closes
            prev = np.zeros(len(d), int)
            prev[j:] = d[:-j]
            gap_ok = np.zeros(len(d), bool)
            gap_ok[j:] = (t[j:] - t[:-j]) == j * H
            d = np.where((prev == d) & gap_ok, d, 0)
    else:
        r = rsi(c, 2)
        d = np.where(r < p["rsi_lo"], 1, np.where(r > 100 - p["rsi_lo"], -1, 0))
    if p["mode"] == "momentum" and p["min_peers"] > 0:
        npeer = _peer_count(h1.index, sym, int(p["atr_len"]), p["peer_thr"], p["peer_dir"])
        d = np.where(npeer >= p["min_peers"], d, 0)
    if p["trend_mode"] != 0 or p["mode"] != "momentum":
        tr = _d1_trend(h1, p["trend_len"])
        want = tr if p["mode"] != "momentum" else tr * p["trend_mode"]
        d = np.where(d == want, d, 0)

    hr = ny.hour.to_numpy()
    lo_h, hi_h = p["no_entry_ny"]
    ok = np.isfinite(a) & (a > 0) & ~((hr >= lo_h) & (hr < hi_h))
    dow = ny.dayofweek.to_numpy()
    ok &= ~((dow == 4) & (hr >= p["fri_last_entry_ny"])) & (dow < 5)
    if sym == "EURCHF" and p["eurchf_from"]:
        ok &= close_t >= pd.Timestamp(p["eurchf_from"], tz="UTC")
    sig = (d != 0) & ok

    entry = htf_close_to_m1_entry(bars.index, h1.index, "1h")[sig]
    direction = d[sig]
    sl = p["sl_atr"] * a[sig]
    keep = entry < len(bars)
    entry, direction, sl = entry[keep], direction[keep], sl[keep]
    et = bars.index[entry]
    limit = ns(et + pd.Timedelta(hours=p["hold_h"]))
    # flat by Friday fri_flat_ny New York of the entry week
    etn = et.tz_convert(NY)
    fri = (etn.normalize() + pd.to_timedelta((4 - etn.dayofweek) % 7, unit="D")).tz_localize(None)
    fri = ns((fri + pd.Timedelta(hours=p["fri_flat_ny"])).tz_localize(NY))
    limit = np.minimum(limit, fri)
    exit_idx = np.searchsorted(ns(bars.index), limit)
    v = exit_idx > entry
    entry, direction, sl, exit_idx = entry[v], direction[v], sl[v], exit_idx[v]
    return Signals(entry, direction, sl, p["tp_r"] * sl, exit_idx=exit_idx)
