"""Trade management for the gold swing EA: exits, partial take-profit, early cut and pyramiding.

RESEARCH RESULT: REJECTED (results/gold_exits_dev.md). The final candidate (DEFAULT_PARAMS: chandelier
trail 2.5 x ATR instead of 3.0, plus ONE pyramid add of the same lots when an H1/M1 bar closes >= +1R,
both stops moved to the first entry price) beat the EA on dev 2013-2019 ($71.23 vs $56.41 at 2% risk,
$88.18 vs $62.08 at 3%), but lost on the validation sum ($184.56 vs $211.10 at 2%, $197.76 vs $240.80
at 3%). Keep the deployed EA's exits. Selected after 42 dev combos; validation was run once.

Entries and the initial stop are exactly those of strategies/swing_pullback (the deployed EA
mql5/GoldSwingCent.mq5): H4 EMA40 trend with slope, H1 RSI(14) cross back through 40/60, stop 2 x ATR(H4),
chandelier trail 3 x ATR, flat Friday 20:00 UTC, max hold 3 days. This module only changes what happens
AFTER the fill. Research log: results/gold_exits_dev.md.

Management options (all off = the baseline EA, bit-for-bit identical to backtest/engine.py):

  engine-native (passed through to swing_pullback, also understood by backtest/engine.py)
    trail_atr, trail_start_r, be_r, be_off_r, tp_r, max_hold_days, friday_close

  group options (need the simulator in this file, because the engine holds one position at a time)
    add_at_r      PYRAMID. When an H1/M1 bar closes with the trade >= add_at_r R in profit (bid for longs,
                  ask for shorts), buy/sell a second unit at the next bar's open. 0 = off. One add at most.
    add_frac      size of the add as a fraction of the first unit's lots (rounded DOWN to the lot step).
    add_lock_r    when the add is filled, the common stop of both units moves to entry1 + add_lock_r * R
                  (never loosened). Both units then share that stop and the chandelier trail.
                  If the price at the fill is already at/through that stop, the add is skipped.
    max_group_risk  the add is shrunk so that the open risk of the group to the common stop (each unit
                  counted >= 0, plus stop slippage) never exceeds this multiple of the first unit's
                  initial risk (1.5 = the owner's limit).
    tp1_r, tp1_frac, tp1_be   PARTIAL TP. Close tp1_frac of the first unit at +tp1_r R (limit order),
                  then (tp1_be) move the stop of the rest to the entry price. 0 = off.
    cut_h, cut_r  EARLY CUT. Once, at the first bar that opens >= cut_h hours after the fill, close the
                  trade at that open if it is below +cut_r R. 0 = off.

Simulator conventions (same as backtest/engine.py, pessimistic): bid data, longs pay the spread on entry,
shorts on exit; stop checked before targets inside a bar; stop / time exits pay $0.05 slippage; any stop
move computed from a bar takes effect from the next bar; the add decision uses a bar CLOSE and fills at
the NEXT bar's open (a market order, no intrabar trigger); swap 5%/yr per unit from its own fill bar,
x3 Wednesdays. Account rules identical to the engine (risk % of equity, half risk in a 10% drawdown,
daily -5% stop, 3 losses/day, hard stop at $35, min lot 0.01 oz, margin <= 50% of equity at 1:500).
One "trade" = the whole group; R = group P&L / initial risk of the first unit.

    python -m strategies.gold_exits --risk 2                                     # final candidate, all periods
    python -m strategies.gold_exits --params '{"trail_atr": 3.0, "add_at_r": 0}' --risk 2   # = the EA baseline
    python -m strategies.gold_exits --params '{"add_at_r": 0}' --periods dev_2013_2019
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

from backtest.engine import EXIT_NAMES, STATUS_NAMES, RiskConfig, Signals, ns
from strategies import swing_pullback as _sp

SP_KEYS = tuple(_sp.DEFAULT_PARAMS)
GROUP_DEFAULTS = dict(add_at_r=0.0, add_frac=1.0, add_lock_r=0.0, max_group_risk=1.5,
                      tp1_r=0.0, tp1_frac=0.5, tp1_be=True, cut_h=0.0, cut_r=0.0)

# final (rejected) candidate E5, see results/gold_exits_dev.md. The baseline EA is
# {**_sp.DEFAULT_PARAMS, "max_hold_days": 3} with all group options off (pass {"trail_atr": 3.0, "add_at_r": 0}).
# NOTE: scripts/gold_full_eval.py runs backtest/engine.py, which ignores the pyramid add; evaluate this module
# with `python -m strategies.gold_exits` (same output format, group simulator).
DEFAULT_PARAMS = {**_sp.DEFAULT_PARAMS, "max_hold_days": 3, **GROUP_DEFAULTS,
                  "trail_atr": 2.5, "add_at_r": 1.0, "add_frac": 1.0, "add_lock_r": 0.0}


def split_params(params: dict) -> tuple[dict, dict]:
    sp = {k: v for k, v in params.items() if k in SP_KEYS}
    gp = {**GROUP_DEFAULTS, **{k: v for k, v in params.items() if k in GROUP_DEFAULTS}}
    bad = set(params) - set(SP_KEYS) - set(GROUP_DEFAULTS)
    if bad:
        raise TypeError(f"unknown params {sorted(bad)}")
    return sp, gp


def group_active(gp: dict) -> bool:
    return gp["add_at_r"] > 0 or gp["tp1_r"] > 0 or gp["cut_h"] > 0


def generate_signals(bars: pd.DataFrame, sym: str = "XAUUSD", **params) -> Signals:
    """Entries / stop / engine-native exits of swing_pullback. The group options travel as `sig.group`;
    backtest/engine.py ignores them, so evaluate the group options with simulate() / evaluate() below."""
    sp, gp = split_params({**DEFAULT_PARAMS, **params})
    sig = _sp.generate_signals(bars, **sp)
    sig.group = gp
    return sig


# ----------------------------------------------------------------------------------- simulator

@njit(cache=True)
def _sim(open_, high, low, close, spread, day, tns,
         sig_idx, sig_dir, sig_sl, sig_tp, sig_exit, sig_be_r, sig_be_off, sig_trail,
         init_eq, risk_pct, reduced_risk_pct, dd_reduce_pct, max_risk_min_pct,
         min_size, size_step, daily_loss_pct, max_trades_day, max_consec_day,
         hard_stop_eq, leverage, slip, comm, roll_cum, swap_rate,
         add_at_r, add_frac, add_lock_r, max_group_risk, tp1_r, tp1_frac, tp1_be, cut_ns, cut_r):
    n = open_.shape[0]
    ns_ = sig_idx.shape[0]
    status = np.zeros(ns_, np.int64)
    exit_i = np.full(ns_, -1, np.int64)
    entry_px = np.full(ns_, np.nan)
    size = np.zeros(ns_)
    pnl = np.zeros(ns_)
    risk_amt = np.zeros(ns_)
    reason = np.zeros(ns_, np.int64)
    eq_after = np.full(ns_, np.nan)
    add_sz_out = np.zeros(ns_)
    add_pnl_out = np.zeros(ns_)
    tp1_out = np.zeros(ns_, np.int64)
    swap_out = np.zeros(ns_)

    u_ent = np.zeros(3)   # unit 0 = first unit (runner part), 1 = first unit's partial-TP part, 2 = add
    u_sz = np.zeros(3)
    u_i = np.zeros(3, np.int64)
    u_open = np.zeros(3, np.bool_)

    equity = init_eq
    peak = init_eq
    cur_day = -1
    day_start = init_eq
    day_pnl = 0.0
    day_trades = 0
    day_consec = 0
    busy_until = -1
    stopped = False

    for k in range(ns_):
        i = sig_idx[k]
        if i < 0 or i >= n:
            status[k] = 8
            continue
        if i <= busy_until:
            status[k] = 1
            continue
        d = day[i]
        if d != cur_day:
            cur_day = d
            day_start = equity
            day_pnl = 0.0
            day_trades = 0
            day_consec = 0
        if stopped or equity <= hard_stop_eq:
            stopped = True
            status[k] = 2
            continue
        if day_pnl <= -daily_loss_pct / 100.0 * day_start:
            status[k] = 3
            continue
        if day_consec >= max_consec_day:
            status[k] = 4
            continue
        if day_trades >= max_trades_day:
            status[k] = 5
            continue

        rp = risk_pct
        if equity < peak * (1.0 - dd_reduce_pct / 100.0):
            rp = reduced_risk_pct
        dirn = sig_dir[k]
        sl = sig_sl[k]
        tp = sig_tp[k]
        sp = spread[i]
        ent = open_[i] + sp if dirn > 0 else open_[i]
        per_oz = sl + slip + comm
        sz = np.floor((equity * rp / 100.0) / per_oz / size_step + 1e-9) * size_step
        if sz < min_size - 1e-12:
            if min_size * per_oz / equity * 100.0 <= max_risk_min_pct:
                sz = min_size
            else:
                status[k] = 6
                continue
        if sz * ent / leverage > equity * 0.5:
            status[k] = 7
            continue
        r_amt = sz * per_oz

        # units of the first position (optional partial-TP split, never rounds up)
        sz_tp = 0.0
        if tp1_r > 0:
            sz_tp = np.floor(sz * tp1_frac / size_step + 1e-9) * size_step
            if sz_tp < min_size - 1e-12 or sz - sz_tp < min_size - 1e-12:
                sz_tp = 0.0
        u_ent[0] = ent
        u_sz[0] = sz - sz_tp
        u_i[0] = i
        u_open[0] = True
        u_ent[1] = ent
        u_sz[1] = sz_tp
        u_i[1] = i
        u_open[1] = sz_tp > 0
        u_sz[2] = 0.0
        u_open[2] = False
        realized = 0.0
        swap_tot = 0.0

        sl_px = ent - dirn * sl
        tp_px = ent + dirn * tp
        has_tp = tp > 0
        tp1_px = ent + dirn * tp1_r * sl
        be_r = sig_be_r[k]
        be_px = ent + dirn * be_r * sl
        moved = False
        trail = sig_trail[k]
        best = ent
        end = sig_exit[k] if sig_exit[k] > i else n
        if end > n:
            end = n
        add_pending = False
        added = False
        cut_done = cut_ns <= 0
        j = i
        xp = np.nan
        rsn = 0
        while j < end:
            o = open_[j]
            h = high[j]
            lo = low[j]
            spj = spread[j]
            # exit-side prices of this bar: bid for longs, ask for shorts
            if dirn > 0:
                xo, xh, xl = o, h, lo
            else:
                xo, xh, xl = o + spj, h + spj, lo + spj
            # 1) pyramid add decided on the previous bar's close: market order at this open
            if add_pending:
                add_pending = False
                fill = o + spj if dirn > 0 else o
                lock = ent + dirn * add_lock_r * sl
                new_sl = sl_px
                if dirn * (lock - new_sl) > 0:
                    new_sl = lock
                if dirn * (xo - new_sl) > 0:
                    open_risk = 0.0
                    open_sz = 0.0
                    for u in range(2):
                        if u_open[u]:
                            ru = dirn * (u_ent[u] - new_sl) + slip + comm
                            if ru > 0:
                                open_risk += ru * u_sz[u]
                            open_sz += u_sz[u]
                    per_add = dirn * (fill - new_sl) + slip + comm
                    allowed = max_group_risk * r_amt - open_risk
                    sz_add = 0.0
                    if per_add > 0 and allowed > 0:
                        sz_add = min(add_frac * sz, allowed / per_add)
                        sz_add = np.floor(sz_add / size_step + 1e-9) * size_step
                    if sz_add >= min_size - 1e-12 and (open_sz + sz_add) * fill / leverage <= equity * 0.5:
                        u_ent[2] = fill
                        u_sz[2] = sz_add
                        u_i[2] = j
                        u_open[2] = True
                        added = True
                        sl_px = new_sl
            # 2) stop / target gaps at the open
            if j > i and dirn * (xo - sl_px) <= 0:
                xp = xo - dirn * slip
                rsn = 1
                break
            if j > i and has_tp and dirn * (xo - tp_px) >= 0:
                xp = xo
                rsn = 2
                break
            # 3) early cut: one check at the first bar opening cut_h hours after the fill
            if not cut_done and tns[j] - tns[i] >= cut_ns:
                cut_done = True
                if dirn * (xo - ent) < cut_r * sl:
                    xp = xo - dirn * slip
                    rsn = 3
                    break
            if j > i and u_open[1] and dirn * (xo - tp1_px) >= 0:
                realized += dirn * (xo - u_ent[1]) * u_sz[1] - comm * u_sz[1]
                sw = u_sz[1] * (roll_cum[j] - roll_cum[u_i[1]]) * swap_rate * u_ent[1]
                realized -= sw
                swap_tot += sw
                u_open[1] = False
                tp1_out[k] = 1
                if tp1_be and dirn * (ent - sl_px) > 0:
                    sl_px = ent
            # 4) intrabar: stop first (pessimistic), then targets
            adverse = xl if dirn > 0 else xh
            if dirn * (adverse - sl_px) <= 0:
                xp = sl_px - dirn * slip
                rsn = 1
                break
            fav = xh if dirn > 0 else xl
            if has_tp and dirn * (fav - tp_px) >= 0:
                xp = tp_px
                rsn = 2
                break
            if u_open[1] and dirn * (fav - tp1_px) >= 0:
                realized += dirn * (tp1_px - u_ent[1]) * u_sz[1] - comm * u_sz[1]
                sw = u_sz[1] * (roll_cum[j] - roll_cum[u_i[1]]) * swap_rate * u_ent[1]
                realized -= sw
                swap_tot += sw
                u_open[1] = False
                tp1_out[k] = 1
                if tp1_be and dirn * (ent - sl_px) > 0:
                    sl_px = ent   # effective from the next bar (already checked this bar)
            if dirn * (fav - best) > 0:
                best = fav
            if be_r > 0 and not moved and dirn * (best - be_px) >= 0:
                nb = ent + dirn * sig_be_off[k]
                if dirn * (nb - sl_px) > 0:
                    sl_px = nb
                moved = True
            if trail > 0 and moved and dirn * ((best - dirn * trail) - sl_px) > 0:
                sl_px = best - dirn * trail
            # 5) pyramid decision on this bar's close
            if add_at_r > 0 and not added and j + 1 < end:
                xc = close[j] if dirn > 0 else close[j] + spj
                if dirn * (xc - ent) >= add_at_r * sl:
                    add_pending = True
                    added = True   # one attempt only
            j += 1
        if rsn == 0:
            if end < n:
                j = end
                xp = open_[end] - slip if dirn > 0 else open_[end] + spread[end] + slip
                rsn = 3
            else:
                j = n - 1
                xp = close[n - 1] if dirn > 0 else close[n - 1] + spread[n - 1]
                rsn = 6
        elif rsn == 1 and moved:
            if dirn * (sl_px - ent) > -1e-9:
                rsn = 5 if trail > 0 else 4

        p = realized
        for u in range(3):
            if u_open[u]:
                sw = u_sz[u] * (roll_cum[j] - roll_cum[u_i[u]]) * swap_rate * u_ent[u]
                pu = (xp - u_ent[u]) * dirn * u_sz[u] - comm * u_sz[u] - sw
                p += pu
                swap_tot += sw
                if u == 2:
                    add_pnl_out[k] = pu
        add_sz_out[k] = u_sz[2] if u_open[2] else 0.0
        status[k] = 0
        exit_i[k] = j
        entry_px[k] = ent
        size[k] = sz
        pnl[k] = p
        risk_amt[k] = r_amt
        reason[k] = rsn
        swap_out[k] = swap_tot
        equity += p
        if equity > peak:
            peak = equity
        eq_after[k] = equity
        day_pnl += p
        day_trades += 1
        if p < 0:
            day_consec += 1
        else:
            day_consec = 0
        busy_until = j
        if equity <= hard_stop_eq:
            stopped = True

    return status, exit_i, entry_px, size, pnl, risk_amt, reason, eq_after, add_sz_out, add_pnl_out, tp1_out, swap_out


def simulate(bars: pd.DataFrame, sig: Signals, cost, risk: RiskConfig, gp: dict | None = None) -> dict:
    """Account simulation of the signal groups. Returns {trades, final_equity, stopped_out, skipped}."""
    gp = {**GROUP_DEFAULTS, **(gp or getattr(sig, "group", {}) or {})}
    s = sig.finalize()
    idx = bars.index
    o, h, lo, c = (bars[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    spread = cost.spread_array(c, idx)
    t = ns(idx)
    day = (t // (86_400 * 10**9)).astype(np.int64)
    out = _sim(o, h, lo, c, spread, day, t,
               s.entry_idx, s.direction, s.sl_dist, s.tp_dist, s.exit_idx, s.be_trigger_r, s.be_offset, s.trail_dist,
               float(risk.initial_equity), float(risk.risk_pct), float(risk.reduced_risk_pct), float(risk.dd_reduce_pct),
               float(risk.max_risk_pct_at_min_lot), float(risk.min_size), float(risk.size_step),
               float(risk.daily_loss_pct), int(risk.max_trades_per_day), int(risk.max_consec_losses_per_day),
               float(risk.hard_stop_equity), float(risk.leverage), float(cost.slippage_stop), float(cost.commission_per_oz),
               cost.rollover_cum(idx), float(cost.swap_annual_pct) / 100.0 / 365.0,
               float(gp["add_at_r"]), float(gp["add_frac"]), float(gp["add_lock_r"]), float(gp["max_group_risk"]),
               float(gp["tp1_r"]), float(gp["tp1_frac"]), bool(gp["tp1_be"]),
               int(float(gp["cut_h"]) * 3600 * 10**9), float(gp["cut_r"]))
    status, exit_i, entry_px, size, pnl, risk_amt, reason, eq_after, add_sz, add_pnl, tp1, swap = out
    tk = status == 0
    trades = pd.DataFrame({
        "entry_time": idx[s.entry_idx[tk]], "exit_time": idx[exit_i[tk]], "direction": s.direction[tk],
        "entry": entry_px[tk], "sl_dist": s.sl_dist[tk], "size_oz": size[tk], "pnl": pnl[tk], "risk": risk_amt[tk],
        "r": pnl[tk] / risk_amt[tk], "exit_reason": pd.Series(reason[tk]).map(EXIT_NAMES).to_numpy(),
        "equity": eq_after[tk], "add_size_oz": add_sz[tk], "add_r": add_pnl[tk] / risk_amt[tk], "tp1_hit": tp1[tk],
        "swap": swap[tk], "entry_idx": s.entry_idx[tk], "exit_idx": exit_i[tk]})
    skipped = {STATUS_NAMES[q]: int((status == q).sum()) for q in range(1, len(STATUS_NAMES)) if (status == q).any()}
    final = float(trades["equity"].iloc[-1]) if len(trades) else float(risk.initial_equity)
    return {"trades": trades, "final_equity": final, "skipped": skipped,
            "stopped_out": bool(skipped.get("hard_stop", 0) > 0 or final <= risk.hard_stop_equity)}


# ----------------------------------------------------------------------------------- evaluation

def evaluate(params: dict | None = None, risk_pct: float = 2.0, bars: pd.DataFrame | None = None,
             periods: tuple[str, ...] | None = None) -> dict:
    """Same output as scripts/gold_full_eval.evaluate, but runs the group simulator."""
    from backtest.markets import cost_model, keep_entries_from, r_stats, research_risk
    from backtest.metrics import max_drawdown_pct
    from scripts.gold_full_eval import PERIODS, gold_all

    params = {**DEFAULT_PARAMS, **(params or {})}
    bars = gold_all() if bars is None else bars
    sig_all = generate_signals(bars, **params)
    gp = sig_all.group
    cost = cost_model("XAUUSD", swap_annual_pct=5.0)
    out = {}
    for name, (s, e) in PERIODS.items():
        if periods and name not in periods:
            continue
        t0, t1 = pd.Timestamp(s, tz="UTC"), pd.Timestamp(e, tz="UTC")
        m = bars[bars.index < t1]
        sig = keep_entries_from(sig_all, bars.index, t0)
        keep = sig.entry_idx < len(m)
        for f in ("entry_idx", "direction", "sl_dist", "tp_dist", "exit_idx", "be_trigger_r", "be_offset", "trail_dist", "tag"):
            setattr(sig, f, getattr(sig, f)[keep])
        sig.exit_idx = np.where(sig.exit_idx >= len(m), -1, sig.exit_idx)
        raw = simulate(m, sig, cost, research_risk(), gp)
        rc = RiskConfig(risk_pct=risk_pct, reduced_risk_pct=risk_pct / 2, max_risk_pct_at_min_lot=max(3.0, 1.5 * risk_pct))
        acc = simulate(m, sig, cost, rc, gp)
        at = acc["trades"]
        eq = np.concatenate([[rc.initial_equity], at["equity"].to_numpy()]) if len(at) else np.array([rc.initial_equity])
        rt = raw["trades"]
        extra = {"adds": int((rt["add_size_oz"] > 0).sum()), "add_avg_r": round(float(rt.loc[rt["add_size_oz"] > 0, "add_r"].mean()), 3)
                 if (rt["add_size_oz"] > 0).any() else None} if gp["add_at_r"] > 0 else {}
        if gp["tp1_r"] > 0:
            extra["tp1_hits"] = int(rt["tp1_hit"].sum())
        out[name] = {**r_stats(rt, s, e), **extra, "account_final": round(acc["final_equity"], 2),
                     "account_max_dd_pct": round(max_drawdown_pct(eq), 1), "hard_stop": acc["stopped_out"]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", default="{}")
    ap.add_argument("--risk", type=float, default=2.0)
    ap.add_argument("--periods", default="")
    a = ap.parse_args()
    per = tuple(p for p in a.periods.split(",") if p) or None
    for k, v in evaluate(json.loads(a.params), a.risk, periods=per).items():
        print(f"{k:14s} {json.dumps(v)}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
