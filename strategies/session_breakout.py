"""Session-open breakouts of the pre-session range (London / New York), FX M15 and XAUUSD H1.

RESEARCH STATUS: MARGINAL, NOT ROBUST (see results/session_breakout_dev.md). Plain Asian-range / London /
New York breakouts and their fades have ~0 R gross edge on 11 FX pairs (2013-2019) and lose 0.06-0.40 R
per trade after cent-account costs. The frozen final choice (DEFAULT_PARAMS on GBPUSD + GBPJPY) is
+0.06 R/trade on dev and validation at base cost (dev+val t = 2.05) but only +0.01 R on validation at
1.5x costs, lost -0.17 R/trade through 2021 and depends on a few volatility-shock days.

Final rules (DEFAULT_PARAMS), for an MQL5 port, all times Europe/London local (DST-aware):
  - opening range = high/low of the M15 bars 08:00-08:45 (i.e. 08:00-09:00 London)
  - trend = sign(close - EMA(close,100)) of the H1 bar 08:00-09:00 (completed at 09:00)
  - from 09:00 to 12:00, the first M15 bar that CLOSES above the range high (below the low) triggers
    a market buy (sell) at the next bar open, only if that direction equals the trend; only the FIRST
    close beyond either side counts (if it is against the trend there is no trade that day); one trade
    per pair per day, no re-entry
  - stop = opposite side of the range, distance d = |bid at entry - level|, SL = fill -/+ d; skip if
    d is not within 0.25-4.0 x H1 ATR(24) (SMA of true range) of the 08:00 H1 bar; no target
  - close at 16:00 London if still open

generate_signals(bars, sym=..., **params) -> Signals; `bars` are the market's native bars
(FX: M15 UTC; XAUUSD: H1 before 2022, M1 from 2022). Decisions are taken on completed bars of the
signal timeframe `tf` (M15 for FX, H1 for gold) and filled at the next native bar open.

Clock: every session time is local wall-clock time in `tz` (Europe/London or America/New_York),
converted with zoneinfo, so DST is handled. An MQL5 port should convert TimeGMT() to the same
local time (or hard-code the UK/US DST rules).

Per local trading day (Mon-Fri):
  range   = high/low of the signal-tf bars with local open time in [range_start, range_end)
  ATR     = H1 ATR(atr_len) (simple average of true range, MT5 iATR) of the last H1 bar completed
            at range_end; the range is used only if min_w_atr <= width / ATR <= max_w_atr
  window  = signal-tf bars with local open time in [range_end, range_end + window_min)
  mode "bo":    first close beyond the range (+ buf_atr * ATR) -> enter in the break direction
  mode "fade":  first close beyond the range -> enter against the break (only breaks in the window)
  mode "reclaim": first close beyond the range, then a close back inside the range within
                reclaim_bars bars -> enter back into the range
  stop    sl_mode "opp": opposite side of the range; "mid": range midpoint; "atr": sl_atr * ATR;
          "ext" (fades): beyond the extreme reached since range_end + sl_buf_atr * ATR.
          Distance measured from the bid open of the entry bar; trade skipped unless
          min_sl_atr <= stop / ATR <= max_sl_atr.
  target  tp_r * stop (0 = none); optional breakeven at be_r R then trail by trail_atr * ATR
  exit    flat at local time `flat` at the latest (market close at that bar's open)
  trend   optional: trade only in the direction of sign(H1 close - H1 EMA(trend_ema)) at range_end
  At most one trade per day per session (the engine also allows one position per pair at a time).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, htf_close_to_m1_entry, ns
from backtest.indicators import atr, ema

# Final choice, frozen on dev 2013-2019 before validation: London first-hour opening-range breakout
# in the direction of the H1 EMA(100) trend, stop at the opposite side of the range, no target,
# flat at 16:00 London. Pair set chosen on dev: GBPUSD, GBPJPY (see results/session_breakout_dev.md).
PAIRS = ["GBPUSD", "GBPJPY"]

DEFAULT_PARAMS = dict(
    tz="Europe/London",
    range_start="08:00", range_end="09:00",   # opening range = first hour of the London session (local time)
    window_min=180,                            # entries allowed 09:00-12:00 London
    flat="16:00",                              # close any open trade at 16:00 London
    mode="bo",                                 # "bo", "fade" or "reclaim"
    buf_atr=0.0,
    min_w_atr=0.0, max_w_atr=99.0,
    sl_mode="opp", sl_atr=1.0, sl_buf_atr=0.1,
    min_sl_atr=0.25, max_sl_atr=4.0,
    tp_r=0.0,                                  # no fixed target: exit by stop or at `flat`
    be_r=0.0, trail_atr=0.0,
    reclaim_bars=4,
    atr_len=24,
    side="both",                               # "both", "long", "short"
    trend_ema=100,                             # only trade breaks in the direction of sign(H1 close - H1 EMA(100))
    tf=None,                                   # signal timeframe; None -> 15min for FX, 1h for XAUUSD
)


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def generate_signals(bars: pd.DataFrame, sym: str = "", tz="Europe/London", range_start="00:00", range_end="07:00",
                     window_min=240, flat="16:00", mode="bo", buf_atr=0.0, min_w_atr=0.0, max_w_atr=99.0,
                     sl_mode="opp", sl_atr=1.0, sl_buf_atr=0.1, min_sl_atr=0.25, max_sl_atr=4.0, tp_r=1.0,
                     be_r=0.0, trail_atr=0.0, reclaim_bars=4, atr_len=24, side="both", trend_ema=0,
                     tf=None) -> Signals:
    if tf is None:
        tf = "1h" if sym.startswith("XAU") else "15min"
    tf_min = int(pd.Timedelta(tf).total_seconds() // 60)
    s = resample(bars, tf)
    if len(s) < 100:
        return Signals.empty()
    rs, re_, fl = _minutes(range_start), _minutes(range_end), _minutes(flat)
    we = re_ + int(window_min)

    lt = s.index.tz_convert(tz)
    lmin = (lt.hour * 60 + lt.minute).to_numpy()
    dkey = (lt.year * 10000 + lt.month * 100 + lt.day).to_numpy()
    dow = lt.dayofweek.to_numpy()
    o = s["open"].to_numpy(float)
    h = s["high"].to_numpy(float)
    lo = s["low"].to_numpy(float)
    c = s["close"].to_numpy(float)

    h1 = resample(bars, "1h")
    a1 = atr(h1["high"], h1["low"], h1["close"], atr_len)
    # ATR of the last H1 bar completed at the open of each signal bar
    a_s = align_htf_to_m1(s.index, h1.index, "1h", a1)
    if trend_ema > 0:
        h1c = h1["close"].to_numpy(float)
        tr_s = align_htf_to_m1(s.index, h1.index, "1h", np.sign(h1c - ema(h1c, int(trend_ema))))

    entry_of = htf_close_to_m1_entry(bars.index, s.index, tf)  # native bar where a signal on s-bar k fills
    nopen = bars["open"].to_numpy(float)
    nidx_ns = ns(bars.index)
    n_native = len(bars)

    # flat instant per local day (UTC ns), computed with zoneinfo via pandas
    chg = np.flatnonzero(np.diff(dkey)) + 1
    starts = np.r_[0, chg]
    ends = np.r_[chg, len(s)]
    day_ts = pd.DatetimeIndex(lt[starts].normalize())
    flat_ns = ns((day_ts.tz_localize(None) + pd.Timedelta(minutes=fl)).tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
                 .tz_convert("UTC"))

    need = max(1, int(0.8 * (re_ - rs) / tf_min))
    E, D, SL, TP, X, TG = [], [], [], [], [], []
    for di, (a, b) in enumerate(zip(starts, ends)):
        if dow[a] >= 5:
            continue
        lm = lmin[a:b]
        rmask = (lm >= rs) & (lm < re_)
        if rmask.sum() < need:
            continue
        ri = np.flatnonzero(rmask) + a
        rh, rl = h[ri].max(), lo[ri].min()
        wsel = np.flatnonzero((lm >= re_) & (lm < we) & (lm + tf_min <= fl)) + a
        if len(wsel) == 0:
            continue
        A = a_s[wsel[0]]
        if not (np.isfinite(A) and A > 0):
            continue
        w = (rh - rl) / A
        if w < min_w_atr or w > max_w_atr:
            continue
        up = c[wsel] > rh + buf_atr * A
        dn = c[wsel] < rl - buf_atr * A
        hit = np.flatnonzero(up | dn)
        if len(hit) == 0:
            continue
        k = wsel[hit[0]]
        bdir = 1 if up[hit[0]] else -1
        if mode == "bo":
            d = bdir
            sk = k
        elif mode == "fade":
            d = -bdir
            sk = k
        elif mode == "reclaim":
            # extreme since range end, then first close back inside the range within reclaim_bars bars
            sk = -1
            ext = h[k] if bdir > 0 else lo[k]
            for j in range(k + 1, min(k + 1 + int(reclaim_bars), b)):
                if lmin[j] + tf_min > fl or lmin[j] >= we + tf_min * int(reclaim_bars):
                    break
                ext = max(ext, h[j]) if bdir > 0 else min(ext, lo[j])
                if rl <= c[j] <= rh:
                    sk = j
                    break
            if sk < 0:
                continue
            d = -bdir
        else:
            raise ValueError(mode)
        if side == "long" and d < 0 or side == "short" and d > 0:
            continue
        if trend_ema > 0 and tr_s[wsel[0]] != d:      # trend of the last H1 bar completed at range_end
            continue
        ei = entry_of[sk]
        if ei >= n_native or nidx_ns[ei] >= flat_ns[di]:   # NaT flat (never at these hours) -> iNaT -> skipped
            continue
        px = nopen[ei]
        if sl_mode == "opp":
            sl = (px - rl) if d > 0 else (rh - px)
        elif sl_mode == "mid":
            mid = 0.5 * (rh + rl)
            sl = (px - mid) if d > 0 else (mid - px)
        elif sl_mode == "atr":
            sl = sl_atr * A
        elif sl_mode == "ext":
            ex = ext if mode == "reclaim" else (h[k] if bdir > 0 else lo[k])
            sl = ((px - ex) if d > 0 else (ex - px)) + sl_buf_atr * A
        else:
            raise ValueError(sl_mode)
        if not (min_sl_atr * A <= sl <= max_sl_atr * A):
            continue
        xi = int(np.searchsorted(nidx_ns, flat_ns[di], side="left"))
        E.append(ei)
        D.append(d)
        SL.append(sl)
        TP.append(tp_r * sl if tp_r > 0 else 0.0)
        X.append(xi)
        TG.append(A)
    if not E:
        return Signals.empty()
    E = np.asarray(E, np.int64)
    A_arr = np.asarray(TG, float)
    n = len(E)
    return Signals(
        entry_idx=E, direction=np.asarray(D, np.int64), sl_dist=np.asarray(SL), tp_dist=np.asarray(TP),
        exit_idx=np.asarray(X, np.int64),
        be_trigger_r=np.full(n, float(be_r)), be_offset=np.zeros(n),
        trail_dist=np.full(n, float(trail_atr)) * A_arr if trail_atr > 0 else np.zeros(n),
    )
