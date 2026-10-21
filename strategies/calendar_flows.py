"""Calendar / time-of-day flows on FX M15 bars: fixed clock entries and exits with an ATR protective stop.

FINAL RULE (the only component on in DEFAULT_PARAMS): "me_mtd", month-end flow continuation into the London
4pm WM/Reuters fix on the JPY crosses USDJPY, EURJPY, GBPJPY, AUDJPY.
  * Day: the last London business day of the month = the last Mon-Fri of the month; in May and August, if that day
    is a Monday it is the UK bank holiday (last Monday of the month), so the Friday before is used instead.
  * At 12:00 London time (Europe/London, DST-aware), at the open of the M15 bar starting 12:00:
        mtd = close of the M15 bar ending 12:00  -  open of the first M15 bar of the calendar month (UTC)
    BUY if mtd > 0, SELL if mtd < 0 (trade WITH the month-to-date move).
  * Stop: 3.0 x ATR(24) of H1 bars (MT5 iATR, SMA of true range), from the last completed H1 bar (11:00-12:00).
    No target, no trailing, no breakeven.
  * Exit: at the open of the M15 bar starting 16:00 London (at the 4pm fix), if the stop was not hit.
  Mechanism: month-end hedge rebalancing at the 4pm fix. Foreign holders of hedged Japanese equities sell more JPY
  after a month in which Japanese stocks rose (JPY crosses tend to rise with the Nikkei), and the reverse after a
  falling month. On dev this was specific to the month-end day: the same rule on the 1-3 business days before
  month-end and on the first day of the next month earned about zero.

Components that were researched and are OFF by default (each one only trades the pairs listed for it):
  * "eur_morning": SELL EURUSD from `eur_entry` to `eur_exit` London time on every weekday (EUR weakens during
    European hours; Breedon & Ranaldo 2013). Real gross effect (about 3 pips) but too small after cent spreads.
  * "me_fix": month-end post-fix reversal. At 16:00 London, fade move = close(bar ending 16:00) -
    close(bar ending `me_lookback`) if |move| >= me_min_move_atr * ATR, and exit at `me_exit`. Weak on dev.
  * "gotobi": BUY USDJPY from `gotobi_entry_utc` to `gotobi_exit_utc` on gotobi days (5/10/15/20/25 and the last
    day of the month, moved back to Friday when on a weekend) into the 09:55 JST Tokyo fix. About zero on 2013-2019.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.data import resample
from backtest.engine import Signals, align_htf_to_m1, ns
from backtest.indicators import atr

DEFAULT_PARAMS = dict(
    eur_on=False, eur_pairs=("EURUSD",), eur_entry="09:00", eur_exit="13:00",
    me_on=False, me_pairs=("EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF"),
    me_lookback="14:00", me_entry="16:00", me_exit="18:00", me_min_move_atr=0.0,
    mtd_on=True, mtd_pairs=("USDJPY", "EURJPY", "GBPJPY", "AUDJPY"), mtd_entry="12:00", mtd_exit="16:00", mtd_min_atr=0.0,
    gotobi_on=False, gotobi_pairs=("USDJPY",), gotobi_entry_utc="00:00", gotobi_exit_utc="00:45",
    atr_n=24, sl_atr=3.0,
)

TAG_EUR, TAG_ME, TAG_GOTOBI, TAG_MTD = 1, 2, 3, 4


def _days(index: pd.DatetimeIndex, tz: str) -> pd.DatetimeIndex:
    loc = index.tz_convert(tz)
    d0 = loc[0].normalize().tz_localize(None) - pd.Timedelta(days=1)
    d1 = loc[-1].normalize().tz_localize(None) + pd.Timedelta(days=1)
    d = pd.date_range(d0, d1, freq="D")
    return d[d.dayofweek < 5]


def _at(days: pd.DatetimeIndex, hhmm: str, tz: str) -> pd.DatetimeIndex:
    """Wall-clock time hhmm in `tz` on each date, as UTC (NaT if it does not exist)."""
    t = days + pd.Timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[3:5]))
    return t.tz_localize(tz, nonexistent="NaT", ambiguous="NaT").tz_convert("UTC")


def _bar_at(index: pd.DatetimeIndex, times: pd.DatetimeIndex) -> np.ndarray:
    """Index of the bar whose open time equals each time, -1 if there is no such bar."""
    t = ns(index)
    q = ns(times.fillna(pd.Timestamp(0, tz="UTC")))
    pos = np.searchsorted(t, q, side="left")
    ok = (pos < len(t)) & ~times.isna()
    ok[ok] = t[pos[ok]] == q[ok]
    return np.where(ok, pos, -1)


def last_london_business_days(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Last Mon-Fri of each month, skipping the UK late-May / summer bank holidays (last Monday of May / Aug)."""
    out = []
    for m in pd.date_range(days[0].replace(day=1), days[-1], freq="MS"):
        e = m + pd.offsets.MonthEnd(0)
        while e.dayofweek >= 5:
            e -= pd.Timedelta(days=1)
        if e.month in (5, 8) and e.dayofweek == 0:
            e -= pd.Timedelta(days=3)
        out.append(e)
    return pd.DatetimeIndex(out)


def gotobi_days(days: pd.DatetimeIndex) -> pd.DatetimeIndex:
    out = set()
    for m in pd.date_range(days[0].replace(day=1), days[-1], freq="MS"):
        for c in [m + pd.Timedelta(days=d - 1) for d in (5, 10, 15, 20, 25)] + [m + pd.offsets.MonthEnd(0)]:
            while c.dayofweek >= 5:
                c -= pd.Timedelta(days=1)
            out.add(c)
    return pd.DatetimeIndex(sorted(out))


def generate_signals(bars: pd.DataFrame, sym: str = "", eur_on=False, eur_pairs=("EURUSD",), eur_entry="09:00",
                     eur_exit="13:00", me_on=False, me_pairs=DEFAULT_PARAMS["me_pairs"], me_lookback="14:00",
                     me_entry="16:00", me_exit="18:00", me_min_move_atr=0.0, mtd_on=True,
                     mtd_pairs=DEFAULT_PARAMS["mtd_pairs"], mtd_entry="12:00", mtd_exit="16:00", mtd_min_atr=0.0,
                     gotobi_on=False,
                     gotobi_pairs=("USDJPY",), gotobi_entry_utc="00:00", gotobi_exit_utc="00:45",
                     atr_n=24, sl_atr=3.0) -> Signals:
    idx = bars.index
    if len(idx) == 0:
        return Signals.empty()
    h1 = resample(bars, "1h")
    a_h1 = atr(h1["high"], h1["low"], h1["close"].to_numpy(), atr_n)
    a_bar = align_htf_to_m1(idx, h1.index, "1h", a_h1)  # ATR of the last completed H1 bar, per M15 bar
    close = bars["close"].to_numpy(float)

    E, X, Dn, A, T = [], [], [], [], []

    def add(entry, exit_, direction, tag):
        ok = (entry >= 0) & (exit_ > entry)
        entry, exit_, direction = entry[ok], exit_[ok], np.broadcast_to(direction, ok.shape)[ok]
        a = a_bar[entry]
        good = np.isfinite(a) & (a > 0)
        E.append(entry[good]); X.append(exit_[good]); Dn.append(direction[good]); A.append(a[good])
        T.append(np.full(good.sum(), tag))

    lon = _days(idx, "Europe/London")
    if eur_on and sym in eur_pairs:
        add(_bar_at(idx, _at(lon, eur_entry, "Europe/London")), _bar_at(idx, _at(lon, eur_exit, "Europe/London")),
            np.int64(-1), TAG_EUR)

    if me_on and sym in me_pairs:
        me = last_london_business_days(lon)
        ent = _bar_at(idx, _at(me, me_entry, "Europe/London"))
        lb = _bar_at(idx, _at(me, me_lookback, "Europe/London"))
        ex = _bar_at(idx, _at(me, me_exit, "Europe/London"))
        ok = (ent > 0) & (lb > 0) & (ex > ent)
        ent, lb, ex = ent[ok], lb[ok], ex[ok]
        move = close[ent - 1] - close[lb - 1]  # close of the bar ending at entry time minus close of the bar ending at lookback time
        a = a_bar[ent]
        take = np.isfinite(a) & (np.abs(move) >= me_min_move_atr * a) & (move != 0)
        add(ent[take], ex[take], -np.sign(move[take]).astype(np.int64), TAG_ME)

    if mtd_on and sym in mtd_pairs:
        me = last_london_business_days(lon)
        ent = _bar_at(idx, _at(me, mtd_entry, "Europe/London"))
        ex = _bar_at(idx, _at(me, mtd_exit, "Europe/London"))
        ok = (ent > 0) & (ex > ent)
        ent, ex = ent[ok], ex[ok]
        # open of the first bar of the calendar month (UTC) that contains the entry bar
        month = idx.year.to_numpy() * 12 + idx.month.to_numpy()
        first = np.r_[True, month[1:] != month[:-1]]
        first_pos = np.maximum.accumulate(np.where(first, np.arange(len(idx)), 0))
        mopen = bars["open"].to_numpy(float)[first_pos[ent]]
        mtd = close[ent - 1] - mopen
        a = a_bar[ent]
        take = np.isfinite(a) & (np.abs(mtd) >= mtd_min_atr * a) & (mtd != 0)
        add(ent[take], ex[take], np.sign(mtd[take]).astype(np.int64), TAG_MTD)

    if gotobi_on and sym in gotobi_pairs:
        g = gotobi_days(_days(idx, "UTC"))
        add(_bar_at(idx, _at(g, gotobi_entry_utc, "UTC")), _bar_at(idx, _at(g, gotobi_exit_utc, "UTC")),
            np.int64(1), TAG_GOTOBI)

    if not E:
        return Signals.empty()
    entry = np.concatenate(E)
    a = np.concatenate(A)
    sl = sl_atr * a
    return Signals(entry, np.concatenate(Dn), sl, np.zeros_like(sl), exit_idx=np.concatenate(X),
                   tag=np.concatenate(T))
