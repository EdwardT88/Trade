"""Trade management for the gold swing EA (cluster study): weekend hold, profit-conditional extension of the
3-day cap, stale-trade exit, partial take-profit + runner, re-entry / cooldown after a stop-out, Turtle add-on.

Question: does changing what the EA does AFTER (or right around) an entry raise the $50 account's return,
judged by the rules of results/MM_RESEARCH_PLAN.md (beat fixed 3% on dev 2013-19 AND on validation_sum,
never ruined, max DD reported, also compared with the ladder 5/3/2)?

Method
- Entries, initial stop (2 x ATR(H4)), chandelier trail (3 x ATR) and the base time exits (3-day cap, Friday
  20:00 UTC) are exactly those of strategies/swing_pullback (max_hold_days=3) = mql5/GoldSwingCent.mq5.
- `_msim` below is a numba group simulator on the same bars and cost model as backtest/engine.py (bid data,
  longs pay the spread on entry, shorts on exit, stop before target inside a bar, $0.05 slippage on stop/time
  exits, swap 5%/yr per unit from its own fill, x3 Wednesdays). With every option off it reproduces
  scripts/mm_sim.get_trades() trade for trade (checked by `--stage check`).
- Each trade's R = group P&L / initial risk of the first unit (continuous sizing), so the trades feed straight
  into mm_sim.simulate() for the $50 account at fixed 2%, fixed 3% and the ladder 5/3/2.
- Extended trades block new entries (one position / group at a time), as in the EA.

Protocol: every combo below was evaluated on dev 2013-2019 only (`--stage dev`); the frozen finals were then
run once on every period (`--stage final`). Log: results/mm_management.md.

    python scripts/mm_management.py               # check + dev sweep + final table
    python scripts/mm_management.py --stage dev   # what was used to choose the finals (dev only)
    python scripts/mm_management.py --stage final

MQL5 notes (all options use only the open position's state, the bar clock and completed H4 bars):
- weekend hold: at Friday 20:00 UTC, if the position is long and Bid - entry >= min_r x R, do not close; move the
  SL to max(SL, entry + lock x R), keep the chandelier, close at Monday/Tuesday 20:00 UTC (OnTimer catch-up).
- cap extension: at the 72 h cap, if open P&L >= min_r x R (and the last completed H4 bar still has the trend
  state of the position), move SL to max(SL, entry + lock x R) and keep the position until the Friday close.
- stale exit: at entry + N hours, close if the highest Bid since entry (Ask low for shorts) never reached
  entry + m x R.
- partial + runner: two positions of half size; #1 has TP = entry + tp1 x R; once #1 is closed by its TP, #2 gets
  SL = entry + lock x R and is exempt from the cap / Friday close until base exit + run_days.
- re-entry: after an SL exit (loss), for re_window hours, also accept an RSI cross of re_rsi (instead of 40) in the
  same direction while the H4 trend still agrees; one re-entry per stop-out. Cooldown: ignore signals for N hours.
- Turtle add: buy-stop (sell-stop) at last fill +/- add_atr x ATR; on fill every stop goes to max(SL, fill -
  add_stop_atr x ATR); add lots are cut so that the open risk of all units to that stop <= 1.5 x the first risk.
"""
from __future__ import annotations

import argparse
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data import resample  # noqa: E402
from backtest.engine import EXIT_NAMES, align_htf_to_m1, ns  # noqa: E402
from backtest.indicators import ema  # noqa: E402
from backtest.markets import cost_model, keep_entries_from  # noqa: E402
from mm_sim import PERIODS, _bars, fixed, get_trades, ladder, simulate  # noqa: E402
from strategies import swing_pullback as S  # noqa: E402

EA = {**S.DEFAULT_PARAMS, "max_hold_days": 3}
DEV_START = pd.Timestamp("2013-01-01", tz="UTC")
DEV_MID = pd.Timestamp("2016-07-01", tz="UTC")
DEV_END = pd.Timestamp("2020-01-01", tz="UTC")
NAMES = {**EXIT_NAMES, 7: "stale"}

OPT = dict(
    wk_on=0, wk_min_r=1.0, wk_lock_r=0.5, wk_long_only=1, wk_hours=96,       # weekend hold (96 h = Tue 20:00)
    ext_on=0, ext_min_r=0.0, ext_lock_r=0.0, ext_trend=1, ext_fri=1, ext_days=4,  # extension of the 72 h cap
    stale_h=0.0, stale_mfe_r=0.5,                                             # stale-trade exit
    tp1_r=0.0, tp1_frac=0.5, run_on=1, run_lock_r=0.5, run_long_only=1, run_days=5,  # partial TP + runner
    add_atr=0.0, add_frac=1.0, add_max=1, add_stop_atr=2.0, max_group_risk=1.5,  # Turtle add-on
    re_rsi=0, re_window_h=48.0, cooldown_h=0.0,                               # re-entry / cooldown
)


# ------------------------------------------------------------------------------------------ simulator

@njit(cache=True)
def _msim(o, h, l, c, spread, tns, roll_cum, swap_rate, slip, trend,
          s_idx, s_dir, s_sl, s_trail, s_tag, s_x0, s_kind, s_ext_end, s_ext_fri, s_wk_end, s_run_end,
          wk_on, wk_min_r, wk_lock_r, wk_long_only,
          ext_on, ext_min_r, ext_lock_r, ext_trend,
          stale_ns, stale_mfe_r,
          tp1_r, tp1_frac, run_on, run_lock_r, run_long_only,
          add_atr, add_frac, add_max, add_stop_atr, max_group_risk, sl_atr,
          re_on, re_window_ns, cooldown_ns):
    n = o.shape[0]
    m = s_idx.shape[0]
    status = np.zeros(m, np.int64)
    exit_i = np.full(m, -1, np.int64)
    r_out = np.zeros(m)
    reason = np.zeros(m, np.int64)
    n_add = np.zeros(m, np.int64)
    tp1_hit = np.zeros(m, np.int64)
    ext_flag = np.zeros(m, np.int64)    # 1 weekend hold, 2 cap extension, 3 runner, 4 extension then weekend
    mfe_out = np.zeros(m)
    swap_out = np.zeros(m)
    u_ent = np.zeros(4)                 # 0 first unit (runner part), 1 first unit's TP part, 2-3 adds
    u_sz = np.zeros(4)
    u_i = np.zeros(4, np.int64)
    u_open = np.zeros(4, np.bool_)

    busy_until = -1
    last_exit = -1
    last_dir = 0
    last_sl = False
    last_tag = 1
    for k in range(m):
        i = s_idx[k]
        if i < 0 or i >= n:
            status[k] = 8
            continue
        if i <= busy_until:
            status[k] = 1
            continue
        dirn = s_dir[k]
        tag = s_tag[k]
        if tag == 1:
            if not (re_on and last_tag == 0 and last_sl and last_dir == dirn and last_exit >= 0
                    and tns[i] - tns[last_exit] <= re_window_ns):
                status[k] = 9
                continue
        elif cooldown_ns > 0 and last_sl and last_exit >= 0 and tns[i] - tns[last_exit] < cooldown_ns:
            status[k] = 10
            continue
        sl = s_sl[k]
        atr_n = sl / sl_atr
        trail = s_trail[k]
        ent = o[i] + spread[i] if dirn > 0 else o[i]
        r1 = sl + slip
        f_tp = tp1_frac if tp1_r > 0 else 0.0
        u_ent[0] = ent
        u_sz[0] = 1.0 - f_tp
        u_i[0] = i
        u_open[0] = True
        u_ent[1] = ent
        u_sz[1] = f_tp
        u_i[1] = i
        u_open[1] = f_tp > 0
        for u in range(2, 4):
            u_open[u] = False
            u_sz[u] = 0.0
        realized = 0.0
        swap_tot = 0.0
        sl_px = ent - dirn * sl
        tp1_px = ent + dirn * tp1_r * sl
        best = ent
        moved = False
        end = s_x0[k] if s_x0[k] > i else n
        phase = 0
        stale_done = stale_ns <= 0
        nadd = 0
        add_ref = ent
        j = i
        xp = np.nan
        rsn = 0
        while True:
            if j >= end:
                if end >= n:
                    j = n - 1
                    xp = c[n - 1] if dirn > 0 else c[n - 1] + spread[n - 1]
                    rsn = 6
                    break
                # ---- time exit reached: keep the position under one of the continuation rules?
                xo = o[j] if dirn > 0 else o[j] + spread[j]
                pr = dirn * (xo - ent) / sl
                cont = False
                new_end = -1
                lock = 0.0
                flag = 0
                nphase = 9
                if phase == 0:
                    if run_on and tp1_r > 0 and tp1_hit[k] == 1 and (run_long_only == 0 or dirn > 0):
                        new_end, lock, flag, cont = s_run_end[k], run_lock_r, 3, True
                    elif s_kind[k] == 1 and wk_on and (wk_long_only == 0 or dirn > 0) and pr >= wk_min_r:
                        new_end, lock, flag, cont = s_wk_end[k], wk_lock_r, 1, True
                    elif s_kind[k] == 0 and ext_on and pr >= ext_min_r and (ext_trend == 0 or trend[j] == dirn):
                        new_end, lock, flag, cont = s_ext_end[k], ext_lock_r, 2, True
                        if s_ext_fri[k]:
                            nphase = 1
                elif phase == 1:
                    if wk_on and (wk_long_only == 0 or dirn > 0) and pr >= wk_min_r:
                        new_end, lock, flag, cont = s_wk_end[k], wk_lock_r, 4, True
                if new_end < 0:
                    new_end = n
                if cont and new_end > j:
                    end = new_end
                    phase = nphase
                    ext_flag[k] = flag
                    lk = ent + dirn * lock * sl
                    if dirn * (lk - sl_px) > 0:
                        sl_px = lk
                    # fall through: bar j is processed normally (exits at its open if already through the lock)
                else:
                    xp = xo - dirn * slip
                    rsn = 3
                    break
            oj = o[j]
            hj = h[j]
            lj = l[j]
            spj = spread[j]
            if dirn > 0:
                xo, xh, xl = oj, hj, lj                     # exit side (bid)
                eo, ef = oj + spj, hj + spj                 # entry side (ask): open, favourable extreme
                adv, fav = lj, hj
            else:
                xo, xh, xl = oj + spj, hj + spj, lj + spj   # exit side (ask)
                eo, ef = oj, lj                             # entry side (bid)
                adv, fav = hj + spj, lj + spj
            # 1) stop gapped at the open
            if j > i and dirn * (xo - sl_px) <= 0:
                xp = xo - dirn * slip
                rsn = 1
                break
            # 2) stale-trade exit, once, at the first bar opening >= stale_h after the fill
            if not stale_done and tns[j] - tns[i] >= stale_ns:
                stale_done = True
                if dirn * (best - ent) < stale_mfe_r * sl:
                    xp = xo - dirn * slip
                    rsn = 7
                    break
            # 3) partial TP gapped at the open
            if j > i and u_open[1] and dirn * (xo - tp1_px) >= 0:
                sw = u_sz[1] * (roll_cum[j] - roll_cum[u_i[1]]) * swap_rate * u_ent[1]
                realized += dirn * (xo - u_ent[1]) * u_sz[1] - sw
                swap_tot += sw
                u_open[1] = False
                tp1_hit[k] = 1
                lk = ent + dirn * run_lock_r * sl
                if dirn * (lk - sl_px) > 0:
                    sl_px = lk
            # 4) stop inside the bar (checked before any target: pessimistic)
            if dirn * (adv - sl_px) <= 0:
                xp = sl_px - dirn * slip
                rsn = 1
                break
            # 5) partial TP inside the bar (limit order); the runner's lock applies from the next bar
            if u_open[1] and dirn * (fav - tp1_px) >= 0:
                sw = u_sz[1] * (roll_cum[j] - roll_cum[u_i[1]]) * swap_rate * u_ent[1]
                realized += dirn * (tp1_px - u_ent[1]) * u_sz[1] - sw
                swap_tot += sw
                u_open[1] = False
                tp1_hit[k] = 1
                lk = ent + dirn * run_lock_r * sl
                if dirn * (lk - sl_px) > 0:
                    sl_px = lk
            # 6) Turtle add: stop order at last fill + add_atr * ATR (entry-side price)
            if add_atr > 0 and nadd < add_max:
                trig = add_ref + dirn * add_atr * atr_n
                fill = np.nan
                if j > i and dirn * (eo - trig) >= 0:
                    fill = eo + dirn * slip
                elif dirn * (ef - trig) >= 0:
                    fill = trig + dirn * slip
                if fill == fill:
                    new_sl = fill - dirn * add_stop_atr * atr_n
                    if dirn * (new_sl - sl_px) < 0:
                        new_sl = sl_px
                    open_risk = 0.0
                    for u in range(4):
                        if u_open[u]:
                            ru = dirn * (u_ent[u] - new_sl) + slip
                            if ru > 0:
                                open_risk += ru * u_sz[u]
                    per_add = dirn * (fill - new_sl) + slip
                    allowed = max_group_risk * r1 - open_risk
                    sz_add = 0.0
                    if per_add > 0 and allowed > 0:
                        sz_add = min(add_frac, allowed / per_add)
                    if sz_add >= 0.1:
                        u = 2 + nadd
                        u_ent[u] = fill
                        u_sz[u] = sz_add
                        u_i[u] = j
                        u_open[u] = True
                        sl_px = new_sl
                        nadd += 1
                        add_ref = fill
                        n_add[k] = nadd
                        # pessimistic: if this bar also reached the new common stop, assume it was hit after the fill
                        if dirn * (adv - sl_px) <= 0:
                            xp = sl_px - dirn * slip
                            rsn = 1
                            break
                    else:
                        nadd = add_max   # risk cap leaves no room: stop trying
            # 7) chandelier trail from the best exit-side price (effective from the next bar)
            if dirn * (fav - best) > 0:
                best = fav
            if trail > 0:
                if not moved and dirn * (best - ent) >= 1e-6 * sl:
                    moved = True
                if moved and dirn * ((best - dirn * trail) - sl_px) > 0:
                    sl_px = best - dirn * trail
            j += 1
        if rsn == 1 and moved and dirn * (sl_px - ent) > -1e-9:
            rsn = 5
        p = realized
        for u in range(4):
            if u_open[u]:
                sw = u_sz[u] * (roll_cum[j] - roll_cum[u_i[u]]) * swap_rate * u_ent[u]
                p += (xp - u_ent[u]) * dirn * u_sz[u] - sw
                swap_tot += sw
        status[k] = 0
        exit_i[k] = j
        r_out[k] = p / r1
        reason[k] = rsn
        mfe_out[k] = dirn * (best - ent) / sl
        swap_out[k] = swap_tot / r1
        busy_until = j
        last_exit = j
        last_dir = dirn
        last_sl = rsn == 1
        last_tag = tag
    return status, exit_i, r_out, reason, n_add, tp1_hit, ext_flag, mfe_out, swap_out


# ------------------------------------------------------------------------------------------ inputs

def _to_idx(t_m1: np.ndarray, t: np.ndarray, before_gap: bool) -> np.ndarray:
    """Bar index for each time: first bar at/after t; with before_gap, the last bar before a closed market
    (as swing_pullback does for the Friday close). len(t_m1) -> -1."""
    n = len(t_m1)
    idx = np.searchsorted(t_m1, t)
    if before_gap:
        late = (idx >= n) | (t_m1[np.minimum(idx, n - 1)] - t > 5 * 60 * 10**9)
        idx = np.where(late, idx - 1, idx)
    else:   # never carry a position across a data hole (the 2026-01..03 gap): exit at the last bar before it
        hole = (idx < n) & (idx > 0) & (t_m1[np.minimum(idx, n - 1)] - t > 4 * 86400 * 10**9)
        idx = np.where(hole, idx - 1, idx)
    return np.where(idx >= n, -1, idx)


@lru_cache(maxsize=4)
def _market(swap: float, stress: float):
    bars = _bars()
    cost = cost_model("XAUUSD", stress=stress, swap_annual_pct=swap)
    c = bars["close"].to_numpy(float)
    arr = dict(o=bars["open"].to_numpy(float), h=bars["high"].to_numpy(float), l=bars["low"].to_numpy(float), c=c,
               spread=cost.spread_array(c, bars.index), tns=ns(bars.index), roll_cum=cost.rollover_cum(bars.index),
               swap_rate=float(cost.swap_annual_pct) / 100.0 / 365.0, slip=float(cost.slippage_stop))
    # H4 trend state of the last completed H4 bar at each bar's open (the EA's trend filter)
    ht = resample(bars, EA["trend_tf"])
    hc = ht["close"].to_numpy()
    he = ema(hc, EA["trend_len"])
    up = (hc > he) & (he > np.roll(he, EA["slope_bars"]))
    dn = (hc < he) & (he < np.roll(he, EA["slope_bars"]))
    warm = EA["trend_len"] + EA["slope_bars"]
    up[:warm] = False
    dn[:warm] = False
    tr = align_htf_to_m1(bars.index, ht.index, EA["trend_tf"], up.astype(float) - dn.astype(float))
    arr["trend"] = np.nan_to_num(tr).astype(np.int64)
    return arr


@lru_cache(maxsize=8)
def _signals(re_rsi: int):
    """EA signals (tag 0) plus, if re_rsi, the re-entry candidates (RSI cross of re_rsi / 100 - re_rsi, tag 1)."""
    bars = _bars()
    parts = [(keep_entries_from(S.generate_signals(bars, **EA), bars.index, "2013-01-01"), 0)]
    if re_rsi:
        parts.append((keep_entries_from(S.generate_signals(bars, **{**EA, "rsi_lo": re_rsi}), bars.index,
                                        "2013-01-01"), 1))
    f = {k: np.concatenate([getattr(s, k) for s, _ in parts]) for k in ("entry_idx", "direction", "sl_dist",
                                                                         "exit_idx", "trail_dist")}
    f["tag"] = np.concatenate([np.full(len(s.entry_idx), g, np.int64) for s, g in parts])
    order = np.lexsort((f["tag"], f["entry_idx"]))
    return {k: v[order] for k, v in f.items()}


def _times(sig: dict, ext_days: float, ext_fri: int, wk_hours: float, run_days: float):
    bars = _bars()
    t_m1 = ns(bars.index)
    ent = bars.index[sig["entry_idx"]]
    fri = ent.normalize() + pd.to_timedelta((4 - ent.dayofweek) % 7, unit="D") + pd.Timedelta(hours=EA["fri_close_utc"])
    cap = ent + pd.Timedelta(days=EA["max_hold_days"])
    x0 = sig["exit_idx"]
    kind = np.where(x0 < 0, 2, np.where(ns(fri) <= ns(cap), 1, 0))
    t_ext = cap + pd.Timedelta(days=ext_days)
    if ext_fri:
        ext_is_fri = ns(t_ext) >= ns(fri)
        t_ext_end = np.where(ext_is_fri, ns(fri), ns(t_ext))
        ext_end = np.where(ext_is_fri, _to_idx(t_m1, t_ext_end, True), _to_idx(t_m1, t_ext_end, False))
    else:
        ext_is_fri = np.zeros(len(x0), bool)
        ext_end = _to_idx(t_m1, ns(t_ext), False)
    wk_end = _to_idx(t_m1, ns(fri + pd.Timedelta(hours=wk_hours)), False)
    t_x0 = np.where(x0 >= 0, t_m1[np.maximum(x0, 0)], 0)
    run_end = np.where(x0 >= 0, _to_idx(t_m1, t_x0 + int(run_days * 86400e9), False), -1)
    return kind.astype(np.int64), ext_end.astype(np.int64), ext_is_fri, wk_end.astype(np.int64), run_end.astype(np.int64)


def run(opts: dict | None = None, swap: float = 5.0, stress: float = 1.0) -> pd.DataFrame:
    """Trades (one row per group) 2013-2026 for the management options `opts` (see OPT)."""
    p = {**OPT, **(opts or {})}
    bad = set(p) - set(OPT)
    if bad:
        raise TypeError(f"unknown options {sorted(bad)}")
    mk = _market(float(swap), float(stress))
    sig = _signals(int(p["re_rsi"]))
    kind, ext_end, ext_fri, wk_end, run_end = _times(sig, p["ext_days"], p["ext_fri"], p["wk_hours"], p["run_days"])
    hns = 3600 * 10**9
    out = _msim(mk["o"], mk["h"], mk["l"], mk["c"], mk["spread"], mk["tns"], mk["roll_cum"], mk["swap_rate"],
                mk["slip"], mk["trend"],
                sig["entry_idx"], sig["direction"], sig["sl_dist"], sig["trail_dist"], sig["tag"], sig["exit_idx"],
                kind, ext_end, ext_fri, wk_end, run_end,
                bool(p["wk_on"]), float(p["wk_min_r"]), float(p["wk_lock_r"]), int(p["wk_long_only"]),
                bool(p["ext_on"]), float(p["ext_min_r"]), float(p["ext_lock_r"]), int(p["ext_trend"]),
                int(p["stale_h"] * hns), float(p["stale_mfe_r"]),
                float(p["tp1_r"]), float(p["tp1_frac"]), bool(p["run_on"]), float(p["run_lock_r"]),
                int(p["run_long_only"]),
                float(p["add_atr"]), float(p["add_frac"]), int(p["add_max"]), float(p["add_stop_atr"]),
                float(p["max_group_risk"]), float(EA["sl_atr"]),
                bool(p["re_rsi"]), int(p["re_window_h"] * hns), int(p["cooldown_h"] * hns))
    status, exit_i, r, reason, n_add, tp1, ext, mfe, swp = out
    tk = status == 0
    idx = _bars().index
    return pd.DataFrame({
        "entry_time": idx[sig["entry_idx"][tk]], "exit_time": idx[exit_i[tk]], "direction": sig["direction"][tk],
        "sl_dist": sig["sl_dist"][tk], "r": r[tk], "exit_reason": pd.Series(reason[tk]).map(NAMES).to_numpy(),
        "tag": sig["tag"][tk], "n_add": n_add[tk], "tp1_hit": tp1[tk], "ext": ext[tk], "mfe_r": mfe[tk],
        "swap_r": swp[tk]}).reset_index(drop=True)


# ------------------------------------------------------------------------------------------ evaluation

def r_line(t: pd.DataFrame) -> dict:
    r = t["r"].to_numpy()
    if len(r) == 0:
        return {"n": 0, "avg_r": float("nan"), "se": float("nan"), "sum_r": 0.0}
    se = r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 1 else float("nan")
    return {"n": len(r), "avg_r": round(float(r.mean()), 3), "se": round(float(se), 3), "sum_r": round(float(r.sum()), 1)}


def dev_eval(t: pd.DataFrame) -> dict:
    d = t[(t["entry_time"] >= DEV_START) & (t["entry_time"] < DEV_END)]
    h1, h2 = d[d["entry_time"] < DEV_MID], d[d["entry_time"] >= DEV_MID]
    a2, a3, lad = simulate(d, fixed(0.02)), simulate(d, fixed(0.03)), simulate(d, ladder())
    return {**r_line(d), "avg_h1": r_line(h1)["avg_r"], "avg_h2": r_line(h2)["avg_r"],
            "usd2": a2["total"], "dd2": a2["max_dd_pct"], "usd3": a3["total"], "dd3": a3["max_dd_pct"],
            "lad": lad["total"], "dd_lad": lad["max_dd_pct"], "ext": int((d["ext"] > 0).sum()),
            "adds": int(d["n_add"].sum()), "tp1": int(d["tp1_hit"].sum()), "stale": int((d["exit_reason"] == "stale").sum()),
            "re": int((d["tag"] == 1).sum())}


def full_eval(t: pd.DataFrame) -> dict:
    """Every period from a fresh $50 (mm_sim periods) + the whole history, at fixed 2%, fixed 3% and the ladder."""
    out = {}
    for name, (s, e) in PERIODS.items():
        m = t[(t["entry_time"] >= pd.Timestamp(s, tz="UTC")) & (t["entry_time"] < pd.Timestamp(e, tz="UTC"))]
        out[name] = {**r_line(m), **{k: simulate(m, pol) for k, pol in
                                     (("f2", fixed(0.02)), ("f3", fixed(0.03)), ("lad", ladder()))}}
    out["all_2013_2026"] = {**r_line(t), **{k: simulate(t, pol) for k, pol in
                                           (("f2", fixed(0.02)), ("f3", fixed(0.03)), ("lad", ladder()))}}
    for k in ("f2", "f3", "lad"):
        out[f"val_sum_{k}"] = round(sum(out[p][k]["total"] for p in ("val_2020_2021", "val_2022_2025", "val_2026")), 2)
    return out


# ------------------------------------------------------------------------------------------ the dev grid
# Written before any dev result was seen; 40 combos in the first round (family winners combined in round 2).

GRID: dict[str, dict] = {
    # W: weekend hold at Friday 20:00 only when in profit (lock = new SL in R, wk_hours 72 = Mon 20:00, 96 = Tue)
    "W1 wkd long >=1R lock .5 ->Tue": dict(wk_on=1, wk_min_r=1.0, wk_lock_r=0.5, wk_hours=96),
    "W2 wkd long >=.5R lock .5 ->Tue": dict(wk_on=1, wk_min_r=0.5, wk_lock_r=0.5, wk_hours=96),
    "W3 wkd long >=1.5R lock .5 ->Tue": dict(wk_on=1, wk_min_r=1.5, wk_lock_r=0.5, wk_hours=96),
    "W4 wkd long >=1R lock .5 ->Mon": dict(wk_on=1, wk_min_r=1.0, wk_lock_r=0.5, wk_hours=72),
    "W5 wkd long >=.5R lock .5 ->Mon": dict(wk_on=1, wk_min_r=0.5, wk_lock_r=0.5, wk_hours=72),
    "W6 wkd long >=1.5R lock .5 ->Mon": dict(wk_on=1, wk_min_r=1.5, wk_lock_r=0.5, wk_hours=72),
    "W7 wkd long >=1R lock .25 ->Tue": dict(wk_on=1, wk_min_r=1.0, wk_lock_r=0.25, wk_hours=96),
    "W8 wkd both >=1R lock .5 ->Tue": dict(wk_on=1, wk_min_r=1.0, wk_lock_r=0.5, wk_hours=96, wk_long_only=0),
    # X: at the 72 h cap keep a trade in profit (and H4 trend still aligned) until the Friday close, SL to BE
    "X1 cap ext >=0R trend ->Fri": dict(ext_on=1, ext_min_r=0.0),
    "X2 cap ext >=.5R trend ->Fri": dict(ext_on=1, ext_min_r=0.5),
    "X3 cap ext >=1R trend ->Fri": dict(ext_on=1, ext_min_r=1.0),
    "X4 cap ext >=0R any ->Fri": dict(ext_on=1, ext_min_r=0.0, ext_trend=0),
    "X5 cap ext >=.5R any ->Fri": dict(ext_on=1, ext_min_r=0.5, ext_trend=0),
    "X6 cap ext >=1R any ->Fri": dict(ext_on=1, ext_min_r=1.0, ext_trend=0),
    "X7 cap ext >=0R trend +2d thru wkd": dict(ext_on=1, ext_min_r=0.0, ext_fri=0, ext_days=2),
    "X8 cap ext >=0R trend +4d thru wkd": dict(ext_on=1, ext_min_r=0.0, ext_fri=0, ext_days=4),
    # S: stale exit (close at N h if the max favourable excursion is still < m R)
    "S1 stale 24h mfe<.5R": dict(stale_h=24, stale_mfe_r=0.5),
    "S2 stale 36h mfe<.5R": dict(stale_h=36, stale_mfe_r=0.5),
    "S3 stale 48h mfe<.5R": dict(stale_h=48, stale_mfe_r=0.5),
    "S4 stale 24h mfe<.3R": dict(stale_h=24, stale_mfe_r=0.3),
    "S5 stale 36h mfe<.3R": dict(stale_h=36, stale_mfe_r=0.3),
    "S6 stale 12h mfe<.3R": dict(stale_h=12, stale_mfe_r=0.3),
    # P: half off at +tp1 R, the rest to entry + lock; runner exempt from cap/Friday for run_days after the base exit
    "P1 1/2@1.5R lock .5 runner long +5d": dict(tp1_r=1.5),
    "P2 1/2@1R lock .5 runner long +5d": dict(tp1_r=1.0),
    "P3 1/2@2R lock .5 runner long +5d": dict(tp1_r=2.0),
    "P4 1/2@1.5R lock .5 runner both +5d": dict(tp1_r=1.5, run_long_only=0),
    "P5 1/2@1.5R lock .5 no runner": dict(tp1_r=1.5, run_on=0),
    "P6 1/2@1.5R lock 0 runner long +5d": dict(tp1_r=1.5, run_lock_r=0.0),
    # R: re-entry after a stop-out (RSI cross of re_rsi instead of 40, same direction, trend aligned) / cooldown
    "R1 re-entry rsi35 48h": dict(re_rsi=35, re_window_h=48),
    "R2 re-entry rsi45 48h": dict(re_rsi=45, re_window_h=48),
    "R3 re-entry rsi30 48h": dict(re_rsi=30, re_window_h=48),
    "R4 re-entry rsi35 24h": dict(re_rsi=35, re_window_h=24),
    "R5 cooldown 24h after SL": dict(cooldown_h=24),
    "R6 cooldown 12h after SL": dict(cooldown_h=12),
    # T: Turtle add-on (stop order at last fill + k ATR; all stops to fill - 2 ATR; group risk <= 1.5 R)
    "T1 add 1.0x @+1ATR max1": dict(add_atr=1.0, add_frac=1.0, add_max=1),
    "T2 add 0.5x @+1ATR max1": dict(add_atr=1.0, add_frac=0.5, add_max=1),
    "T3 add 1.0x @+1.5ATR max1": dict(add_atr=1.5, add_frac=1.0, add_max=1),
    "T4 add 0.5x @+1ATR max2": dict(add_atr=1.0, add_frac=0.5, add_max=2),
    "T5 add 1.0x @+1ATR max2": dict(add_atr=1.0, add_frac=1.0, add_max=2),
    "T6 add 0.5x @+0.5ATR max2": dict(add_atr=0.5, add_frac=0.5, add_max=2),
}

# Round 2 (written after round 1, dev only): combinations of the family winners. Pre-set pass rule for a family
# winner: dev avg R, $ @2% and $ @3% above the EA, and avg R above the EA in BOTH dev halves; no isolated peak.
#   W1 passes (W2/W7 same plateau; Monday exits and >=1.5R weaker)  X1 passes (higher min_r and weekend-crossing
#   weaker; the H4-trend condition never binds: every cap exit in profit still had the trend)  R2 passes (R3 too,
#   R1 neutral: only 7-14 re-entries, treat as fragile)  T2, T4, T6, T1 pass (T6 best $, T2 lowest DD; T3 fails)
#   S (only S3, isolated), P (none) and cooldowns (none) fail.
_W1, _X1 = GRID["W1 wkd long >=1R lock .5 ->Tue"], GRID["X1 cap ext >=0R trend ->Fri"]
_R2, _T2, _T6 = GRID["R2 re-entry rsi45 48h"], GRID["T2 add 0.5x @+1ATR max1"], GRID["T6 add 0.5x @+0.5ATR max2"]
GRID2: dict[str, dict] = {
    "C1 W1+X1": {**_W1, **_X1},
    "C2 W1+R2": {**_W1, **_R2},
    "C3 W1+T2": {**_W1, **_T2},
    "C4 X1+T2": {**_X1, **_T2},
    "C5 W1+X1+R2": {**_W1, **_X1, **_R2},
    "C6 W1+X1+T2": {**_W1, **_X1, **_T2},
    "C7 W1+X1+R2+T2": {**_W1, **_X1, **_R2, **_T2},
    "C8 W1+X1+R2+T6": {**_W1, **_X1, **_R2, **_T6},
}

# Frozen finals (chosen from the dev tables only, before any validation number was seen); each is run once on every
# period. PRIMARY (declared in advance) = C7, the full stack with the conservative add (dev @3% $137.21, DD 52%;
# C8 with T6 scored more on dev but with DD 63%). The others are there to show which component holds up; a pick made
# among them after seeing validation would NOT be a validated result.
FINALS: dict[str, dict] = {
    "W1 weekend hold (long >=1R, lock .5R, ->Tue 20:00)": _W1,
    "X1 cap extension (>=0R -> Friday close, SL to BE)": _X1,
    "R2 re-entry after SL (RSI 45/55, 48 h)": _R2,
    "T2 Turtle add 0.5x at +1 ATR": _T2,
    "C1 = W1+X1 (time exits only)": GRID2["C1 W1+X1"],
    "C5 = W1+X1+R2 (no add)": GRID2["C5 W1+X1+R2"],
    "C7 = W1+X1+R2+T2 (PRIMARY)": GRID2["C7 W1+X1+R2+T2"],
}


def fmt_dev(name: str, d: dict) -> str:
    return (f"| {name} | {d['n']} | {d['avg_r']:+.3f} | {d['se']:.3f} | {d['avg_h1']:+.3f} | {d['avg_h2']:+.3f} | "
            f"{d['usd2']:.2f} ({d['dd2']:.0f}%) | {d['usd3']:.2f} ({d['dd3']:.0f}%) | {d['lad']:.2f} ({d['dd_lad']:.0f}%) | "
            f"{d['ext'] or ''}{'x' if d['ext'] else ''} {d['adds'] or ''}{'a' if d['adds'] else ''} "
            f"{d['tp1'] or ''}{'tp' if d['tp1'] else ''} {d['stale'] or ''}{'s' if d['stale'] else ''} "
            f"{d['re'] or ''}{'re' if d['re'] else ''} |")


def stage_check():
    ref = get_trades()
    mine = run({})
    same_n = len(ref) == len(mine)
    ok = same_n and (ref["entry_time"].to_numpy() == mine["entry_time"].to_numpy()).all() \
        and np.allclose(ref["r"].to_numpy(), mine["r"].to_numpy(), atol=1e-9) \
        and (ref["exit_reason"].to_numpy() == mine["exit_reason"].to_numpy()).all()
    print(f"check: simulator with all options off vs mm_sim.get_trades(): n {len(mine)} vs {len(ref)}, "
          f"identical={ok}" + ("" if ok else f" max|dR|={np.abs(ref['r'].to_numpy()[:len(mine)] - mine['r'].to_numpy()[:len(ref)]).max():.2e}"))
    ref0, mine0 = get_trades(swap=0.0), run({}, swap=0.0)
    print(f"check (swap-free): identical={len(ref0) == len(mine0) and np.allclose(ref0['r'], mine0['r'], atol=1e-9)}")
    return ok


def stage_dev(grid: dict[str, dict], title: str):
    print(f"\n## {title} (dev 2013-2019 only; $50 from fresh, DD in brackets)")
    print("| combo | n | avg R | SE | avg R 13-16H1 | avg R 16H2-19 | $ @2% | $ @3% | $ ladder | events |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    print(fmt_dev("EA (baseline)", dev_eval(run({}))))
    res = {}
    for name, opts in grid.items():
        res[name] = dev_eval(run(opts))
        print(fmt_dev(name, res[name]))
    return res


def stage_final():
    base = full_eval(run({}))
    rows = [("EA (fixed-risk references: f3 = fixed 3%, lad = ladder 5/3/2)", {}, base)]
    for name, opts in FINALS.items():
        rows.append((name, opts, full_eval(run(opts))))
    per = list(PERIODS) + ["all_2013_2026"]
    print("\n## Final candidates, run once on every period ($50 fresh per period; DD in brackets)")
    print("| candidate | " + " | ".join(per) + " | val_sum @2% | val_sum @3% | val_sum ladder |")
    print("|---|" + "---|" * (len(per) + 3))
    for name, _, ev in rows:
        cells = [f"{ev[p]['avg_r']:+.3f} n{ev[p]['n']}" for p in per]
        print(f"| {name} avg R | " + " | ".join(cells) + " | | | |")
        for k, lab in (("f2", "@2%"), ("f3", "@3%"), ("lad", "ladder")):
            cells = [f"{ev[p][k]['total']:.2f} ({ev[p][k]['max_dd_pct']:.0f}%){' RUIN' if ev[p][k]['ruined'] else ''}"
                     for p in per]
            print(f"| {name} {lab} | " + " | ".join(cells) + f" | {ev['val_sum_f2'] if k == 'f2' else ''} | "
                  f"{ev['val_sum_f3'] if k == 'f3' else ''} | {ev['val_sum_lad'] if k == 'lad' else ''} |")
    print("\n## Verdict (rule: beat fixed 3% EA on dev AND validation_sum at 3%, never ruined)")
    b3d, b3v = base["dev_2013_2019"]["f3"]["total"], base["val_sum_f3"]
    bld, blv = base["dev_2013_2019"]["lad"]["total"], base["val_sum_lad"]
    for name, _, ev in rows[1:]:
        d3, v3 = ev["dev_2013_2019"]["f3"]["total"], ev["val_sum_f3"]
        ruined = any(ev[p][k]["ruined"] for p in per for k in ("f2", "f3", "lad"))
        better = d3 > b3d and v3 > b3v and not ruined
        print(f"- {name}: @3% dev {d3:.2f} vs {b3d:.2f}, val_sum {v3:.2f} vs {b3v:.2f}, all {ev['all_2013_2026']['f3']['total']:.2f} "
              f"(DD {ev['all_2013_2026']['f3']['max_dd_pct']:.0f}%), ruined={ruined} -> {'BETTER' if better else 'not better'}; "
              f"ladder dev {ev['dev_2013_2019']['lad']['total']:.2f} vs {bld:.2f}, val_sum {ev['val_sum_lad']:.2f} vs {blv:.2f}")
    # cost sensitivity of the same frozen rules (information only, nothing is chosen from it)
    print("\n## Cost sensitivity (same frozen rules): @3% dev / val_sum / all, and avg R all")
    print("| candidate | swap 5% (base) | swap-free (Exness ID) | stress 1.5x spread+slip |")
    print("|---|---|---|---|")
    for name, opts, _ in rows:
        cells = []
        for sw, st in ((5.0, 1.0), (0.0, 1.0), (5.0, 1.5)):
            ev = full_eval(run(opts, swap=sw, stress=st))
            cells.append(f"{ev['dev_2013_2019']['f3']['total']:.2f} / {ev['val_sum_f3']:.2f} / "
                         f"{ev['all_2013_2026']['f3']['total']:.2f} ({ev['all_2013_2026']['avg_r']:+.3f})")
        print(f"| {name.split(' (')[0]} | " + " | ".join(cells) + " |")
    # per-year view (information only, after the once-only run): where does the difference come from?
    tr = {"EA": run({})} | {name.split(" ")[0]: run(opts) for name, opts in FINALS.items()}
    sums = pd.DataFrame({k: v.groupby(v["entry_time"].dt.year)["r"].sum() for k, v in tr.items()})
    diff = sums.drop(columns="EA").sub(sums["EA"], axis=0)
    print("\n## Sum of R per year minus the EA's (swap 5%); last rows: years better, t of the yearly differences")
    print(diff.round(1).to_string())
    print("years better: " + ", ".join(f"{k} {int((diff[k] > 0).sum())}/{len(diff)}" for k in diff))
    print("t (yearly): " + ", ".join(f"{k} {diff[k].mean() / (diff[k].std(ddof=1) / np.sqrt(len(diff))):.2f}" for k in diff))
    return base, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=("all", "check", "dev", "final"))
    a = ap.parse_args()
    if a.stage in ("all", "check"):
        stage_check()
    if a.stage in ("all", "dev"):
        stage_dev(GRID, "Round 1: single ideas")
        if GRID2:
            stage_dev(GRID2, "Round 2: combinations of family winners")
        print(f"\ncombos evaluated on dev: {len(GRID) + len(GRID2)}")
    if a.stage in ("all", "final") and FINALS:
        stage_final()


if __name__ == "__main__":
    main()
