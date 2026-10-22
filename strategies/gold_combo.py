"""Multi-system gold portfolio + sizing rules for the $50 cent account (research module).

RESEARCH RESULT: REJECTED (results/gold_combo_dev.md). The final candidate (DEFAULT_PARAMS = dev combo E6: the EA +
the H4 Donchian breakout system held max 5 days, each trade at 0.5 x risk, total open risk <= 1 x risk, and half of
that again when ATR(14,H4)/close is in the top third of the last 1500 H4 bars) beat the EA on dev 2013-2019
($71.47 vs $56.41 at 2 %, $69.41 vs $62.08 at 3 %) but lost on the validation sum ($169.42 vs $211.10 at 2 %,
$162.20 vs $240.80 at 3 %): it dilutes the EA's 2022-2025 profit (+0.29 R) with a system that made 0 R there.
Selected after 36 dev combos (+ baseline); validation was run once. Keep the deployed EA.

Idea: the deployed EA (strategies/swing_pullback, max_hold_days=3) takes only ~3.7 trades a month with one
position at a time. Running several gold swing entry systems side by side, each with its OWN position slot
and its own share of the risk, gives the account more (partly independent) bets. Total open risk is capped,
and optional sizing rules scale the per-trade risk:

  systems     '+'-joined subset of
                pullback  strategies/swing_pullback  (the EA: H4 EMA40 trend + slope, H1 RSI 40/60 cross,
                                                     stop 2 ATR(H4), chandelier 3 ATR, Friday 20:00 flat, 3 days)
                breakout  strategies/swing_breakout  (H4 close beyond the 20-bar Donchian channel, EMA50 filter,
                                                     stop 2 ATR, chandelier 5 ATR)
                regime    strategies/swing_ma_regime (H4 EMA50/200 regime, flip + EMA20 reclaim entries,
                                                     stop 2 ATR, chandelier 3 ATR, Friday flat)
              per-system overrides: params 'pullback' / 'breakout' / 'regime' (dicts on top of SYSTEMS below)
  w_<system>  risk of one trade of that system = w x risk_pct % of the balance
  cap         sum of the INITIAL risk of all open positions (entry -> stop, incl. stop slippage) may not exceed
              cap x risk_pct % of the balance; a new trade is shrunk to the room left (or skipped if even the
              minimum lot does not fit). The first position on a flat account follows the EA rules exactly.
  slots       max positions open at once over all systems (1 = one shared slot, like the EA)
  vol_k       volatility sizing: p = percentile rank of ATR(14,H4)/close among the last vol_len H4 bars
              (completed bars, known at the signal); risk x (1 + vol_k * (1 - 2p)), clipped to [0.25, 2].
              vol_k > 0: more risk in quiet markets, less in wild ones; vol_k < 0: the opposite; 0 = off.
  vol_hi      high-volatility cut: when p > vol_hi the trade risks vol_hi_mult x (1.0 = off)
  max_trade_risk  no single trade risks more than max(this, risk_pct) % (TWEAK_PLAN rule 3: 3 %); applied to
              the weighted / vol-scaled risk before the drawdown halving
  eq_len      equity-curve filter per system: after each closed trade the system's cumulative R curve is
              compared with its mean over the last eq_len closed trades; below it -> next trade at eq_mult x
              risk. 0 = off. (Only trades the account actually took count, as an EA would know them.)

Account rules (identical to backtest/engine.py / scripts/gold_full_eval.py): $50 start, risk % of the
BALANCE (closed trades), half risk while the balance is > 10 % below its peak, min lot 0.01 oz with the
min-lot exception up to max(3 %, 1.5 x risk), day stop after -5 % realised on the day, max 3 losses and 8
entries a day, hard stop at $35 (no new entries; open positions run to their own exits), margin <= 50 % of
balance at 1:500. Each system keeps its single-position rule (a signal while that system is in a trade is
ignored). Positions are independent orders, each with its own stop at entry (no averaging, no grid).

How it is simulated (the engine holds one position, so this file has a small portfolio simulator):
  1. every signal of every system is run ALONE through backtest.engine._simulate (no account limits), which
     gives its fill bar, exit bar and R multiple (bid data, spread, stop slippage, swap, trailing exactly as
     in the engine). P&L of a position is R x lots x (stop distance + slippage), exactly linear in the lots.
  2. the portfolio walks through the signals in time order, realises every position whose exit bar is
     before the new entry bar, applies the account rules above and sizes the new position.
  With systems='pullback', w=1, cap/slots/vol/eq off it reproduces backtest/engine.py to the cent
  (checked on every period at 2 % and 3 %: dev $56.41 / $62.08, 2020-21 $41.95 / $40.35,
  2022-25 $122.45 / $154.70, 2026 $46.70 / $45.75).

MQL5 port: three independent signal blocks (the existing EAs' entry code) in one EA, each with its own magic
number; before an order: lots = floor(balance * w * risk% * volmult * eqmult / (SL$ + 0.05) / 0.01) * 0.01,
shrunk so that sum over open positions of lots x |open price - initial SL| <= cap x risk% x balance.

    python -m strategies.gold_combo --risk 2                       # final (rejected) candidate, all periods
    python -m strategies.gold_combo --risk 2 --params '{"systems": "pullback", "w_pullback": 1, "vol_hi": 1}'  # = the EA
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.data import resample  # noqa: E402
from backtest.engine import RiskConfig, Signals, _simulate, align_htf_to_m1, ns  # noqa: E402
from backtest.indicators import atr  # noqa: E402

# base configuration of each component system (module, overrides on top of that module's DEFAULT_PARAMS)
SYSTEMS = {
    "pullback": ("swing_pullback", {"max_hold_days": 3}),      # = the deployed EA
    "breakout": ("swing_breakout", {"fri_close": True}),       # weekly flat like the EA (max hold <= 5 days)
    "regime": ("swing_ma_regime", {}),                          # Friday flat by default
}
SYS_ORDER = ("pullback", "breakout", "regime")  # tie-break when two systems fill on the same bar

# final choice (dev combo E6 in results/gold_combo_dev.md): the EA + the H4 breakout system (held over weekends,
# max 5 days), each trade at HALF the nominal risk, total open risk <= 1 x nominal risk (= the EA's one trade),
# and half of that again when H4 volatility is in the top third of its last ~year.
DEFAULT_PARAMS = dict(
    systems="pullback+breakout",
    pullback={}, breakout={"fri_close": False, "max_hold_days": 5}, regime={},
    w_pullback=0.5, w_breakout=0.5, w_regime=0.5,
    cap=1.0, slots=2,
    vol_k=0.0, vol_len=1500, vol_hi=0.67, vol_hi_mult=0.5,
    eq_len=0, eq_mult=0.5,
    max_trade_risk=3.0,
)

_SIG_FIELDS = ("entry_idx", "direction", "sl_dist", "tp_dist", "exit_idx", "be_trigger_r", "be_offset", "trail_dist", "tag")


def _sys_list(params: dict) -> list[str]:
    names = [s for s in str(params["systems"]).split("+") if s]
    bad = set(names) - set(SYSTEMS)
    if bad:
        raise ValueError(f"unknown systems {sorted(bad)}")
    return [s for s in SYS_ORDER if s in names]


def system_signals(bars: pd.DataFrame, name: str, overrides: dict | None = None) -> Signals:
    from strategies import load as load_strategy
    mod_name, base = SYSTEMS[name]
    mod = load_strategy(mod_name)
    p = {**mod.DEFAULT_PARAMS, **base, **(overrides or {})}
    return mod.generate_signals(bars, **p).finalize()


def generate_signals(bars: pd.DataFrame, sym: str = "XAUUSD", **params) -> Signals:
    """All systems' signals merged into one list (tag = 100 x system number + the system's own tag).

    NOTE: backtest/engine.py (and scripts/gold_full_eval.py) hold ONE position at a time, so running these
    signals through the engine gives the 'one shared slot' variant with plain fixed-% sizing. The portfolio
    (separate slots, risk shares, cap, sizing rules) is evaluated with `python -m strategies.gold_combo`."""
    params = {**DEFAULT_PARAMS, **params}
    parts = []
    for k, name in enumerate(_sys_list(params)):
        s = system_signals(bars, name, params.get(name))
        s.tag = (SYS_ORDER.index(name) + 1) * 100 + s.tag
        parts.append(s)
    if not parts:
        return Signals.empty()
    out = Signals(**{f: np.concatenate([getattr(s, f) for s in parts]) for f in _SIG_FIELDS})
    return out.finalize()


# ------------------------------------------------------------------ per-signal outcomes (no account limits)

@njit(cache=True)
def _each(open_, high, low, close, spread, day, idx, dirn, sl, tp, ex, ber, beo, tr, slip, comm, roll, swap_rate):
    n = idx.shape[0]
    r = np.full(n, np.nan)
    xi = np.full(n, -1, np.int64)
    epx = np.full(n, np.nan)
    for k in range(n):
        a_i = np.empty(1, np.int64)
        a_d = np.empty(1, np.int64)
        a_x = np.empty(1, np.int64)
        a_sl = np.empty(1)
        a_tp = np.empty(1)
        a_br = np.empty(1)
        a_bo = np.empty(1)
        a_tr = np.empty(1)
        a_i[0] = idx[k]
        a_d[0] = dirn[k]
        a_x[0] = ex[k]
        a_sl[0] = sl[k]
        a_tp[0] = tp[k]
        a_br[0] = ber[k]
        a_bo[0] = beo[k]
        a_tr[0] = tr[k]
        # research_risk(): huge equity, continuous sizing, no limits -> R of the trade alone
        out = _simulate(open_, high, low, close, spread, day, a_i, a_d, a_sl, a_tp, a_x, a_br, a_bo, a_tr,
                        1e9, 2.0, 1.0, 1e9, 3.0, 1e-9, 1e-9, 1e9, 1000000, 1000000, -1e30, 500.0,
                        slip, comm, roll, swap_rate)
        status, exit_i, entry_px, exit_px, size, pnl, risk_amt = out[0], out[1], out[2], out[3], out[4], out[5], out[6]
        if status[0] == 0:
            r[k] = pnl[0] / risk_amt[0]
            xi[k] = exit_i[0]
            epx[k] = entry_px[0]
    return r, xi, epx


def _vol_pct(bars: pd.DataFrame, entry_idx: np.ndarray, vol_len: int) -> np.ndarray:
    """Percentile rank (0..1) of ATR(14,H4)/close of the last completed H4 bar among the last vol_len H4 bars."""
    h4 = resample(bars, "4h")
    a = atr(h4["high"], h4["low"], h4["close"], 14) / h4["close"].to_numpy()
    pct = pd.Series(a).rolling(vol_len, min_periods=max(50, vol_len // 3)).rank(pct=True).to_numpy()
    return align_htf_to_m1(bars.index[entry_idx], h4.index, "4h", pct)


def candidates(m: pd.DataFrame, sig: Signals, cost, name: str, vol_len: int = 1500) -> pd.DataFrame:
    """Every signal of one system with its stand-alone outcome on bars `m` (already truncated)."""
    s = sig.finalize()
    if len(s.entry_idx) == 0:
        return pd.DataFrame(columns=["sys", "entry_idx", "exit_idx", "direction", "r", "per_oz", "entry_px", "vol_p"])
    idx = m.index
    o, h, lo, c = (m[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    spread = cost.spread_array(c, idx)
    day = (ns(idx) // (86_400 * 10**9)).astype(np.int64)
    r, xi, epx = _each(o, h, lo, c, spread, day, s.entry_idx, s.direction, s.sl_dist, s.tp_dist, s.exit_idx,
                       s.be_trigger_r, s.be_offset, s.trail_dist, float(cost.slippage_stop),
                       float(cost.commission_per_oz), cost.rollover_cum(idx), float(cost.swap_annual_pct) / 100.0 / 365.0)
    ok = np.isfinite(r)
    df = pd.DataFrame({"sys": name, "entry_idx": s.entry_idx[ok], "exit_idx": xi[ok], "direction": s.direction[ok],
                       "r": r[ok], "per_oz": s.sl_dist[ok] + cost.slippage_stop + cost.commission_per_oz,
                       "entry_px": epx[ok]})
    df["vol_p"] = _vol_pct(m, df["entry_idx"].to_numpy(), vol_len) if len(df) else np.zeros(0)
    return df


# ------------------------------------------------------------------ portfolio account simulator

def simulate(m: pd.DataFrame, cand: pd.DataFrame, risk_pct: float, params: dict, rc: RiskConfig | None = None) -> dict:
    """Compound a $50 account over the merged candidate list. Returns trades taken, final balance, etc."""
    params = {**DEFAULT_PARAMS, **params}
    rc = rc or RiskConfig(risk_pct=risk_pct, reduced_risk_pct=risk_pct / 2, max_risk_pct_at_min_lot=max(3.0, 1.5 * risk_pct))
    names = _sys_list(params)
    order = {n: k for k, n in enumerate(SYS_ORDER)}
    c = cand[cand["sys"].isin(names)].copy()
    c["_o"] = c["sys"].map(order)
    c = c.sort_values(["entry_idx", "_o"], kind="stable")
    t_ns = ns(m.index)
    day_of = t_ns // (86_400 * 10**9)
    cap = float(params["cap"])
    slots = int(params["slots"])
    vol_k = float(params["vol_k"])
    vol_hi, vol_hi_mult = float(params["vol_hi"]), float(params["vol_hi_mult"])
    eq_len = int(params["eq_len"])
    eq_mult = float(params["eq_mult"])
    max_trade = max(float(params["max_trade_risk"]), rc.risk_pct)
    w = {n: float(params.get(f"w_{n}", 1.0)) for n in names}

    bal = peak = float(rc.initial_equity)
    hard = float(rc.hard_stop_equity)
    stopped = False
    cur_day, day_start, day_pnl, day_trades, day_consec = -1, bal, 0.0, 0, 0
    open_pos: list[dict] = []
    busy = {n: -1 for n in names}
    rhist = {n: [] for n in names}   # R of the system's closed trades (for the equity-curve filter)
    rcum = {n: [] for n in names}
    eq_path = [bal]
    taken: list[dict] = []
    skipped: dict[str, int] = {}

    def newday(d):
        nonlocal cur_day, day_start, day_pnl, day_trades, day_consec
        if d != cur_day:
            cur_day, day_start, day_pnl, day_trades, day_consec = d, bal, 0.0, 0, 0

    def realize(upto: int):
        nonlocal bal, peak, day_pnl, day_consec, stopped
        while open_pos:
            j = min(range(len(open_pos)), key=lambda q: open_pos[q]["exit_idx"])
            if open_pos[j]["exit_idx"] >= upto:
                return
            p = open_pos.pop(j)
            newday(day_of[p["exit_idx"]])
            bal += p["pnl"]
            peak = max(peak, bal)
            day_pnl += p["pnl"]
            day_consec = day_consec + 1 if p["pnl"] < 0 else 0
            p["equity"] = bal
            eq_path.append(bal)
            rhist[p["sys"]].append(p["r"])
            rcum[p["sys"]].append((rcum[p["sys"]][-1] if rcum[p["sys"]] else 0.0) + p["r"])
            if bal <= hard:
                stopped = True

    def skip(why):
        skipped[why] = skipped.get(why, 0) + 1

    for row in c.itertuples(index=False):
        i, name = int(row.entry_idx), row.sys
        realize(i)
        if i <= busy[name]:
            skip("busy")
            continue
        newday(day_of[i])
        if stopped or bal <= hard:
            stopped = True
            skip("hard_stop")
            continue
        if day_pnl <= -rc.daily_loss_pct / 100.0 * day_start:
            skip("daily_loss")
            continue
        if day_consec >= rc.max_consec_losses_per_day:
            skip("consec_losses")
            continue
        if day_trades >= rc.max_trades_per_day:
            skip("max_trades")
            continue
        if len(open_pos) >= slots:
            skip("slots")
            continue
        rp = rc.risk_pct * w[name]
        if vol_k != 0.0 and np.isfinite(row.vol_p):
            rp *= float(np.clip(1.0 + vol_k * (1.0 - 2.0 * row.vol_p), 0.25, 2.0))
        if vol_hi < 1.0 and np.isfinite(row.vol_p) and row.vol_p > vol_hi:
            rp *= vol_hi_mult
        if eq_len > 0 and len(rcum[name]) >= eq_len:
            cr = rcum[name]
            if cr[-1] < np.mean(cr[-eq_len:]):
                rp *= eq_mult
        rp = min(rp, max_trade)
        if rp <= 0.0:
            skip("zero_risk")
            continue
        if bal < peak * (1.0 - rc.dd_reduce_pct / 100.0):
            rp *= rc.reduced_risk_pct / rc.risk_pct
        per_oz = float(row.per_oz)
        want = bal * rp / 100.0
        room = np.inf
        if open_pos:
            room = cap * rc.risk_pct / 100.0 * bal - sum(p["risk"] for p in open_pos)
            want = min(want, room)
        sz = np.floor(max(want, 0.0) / per_oz / rc.size_step + 1e-9) * rc.size_step
        if sz < rc.min_size - 1e-12:
            if rc.min_size * per_oz / bal * 100.0 <= rc.max_risk_pct_at_min_lot and rc.min_size * per_oz <= room + 1e-12:
                sz = rc.min_size
            else:
                skip("min_lot_or_cap")
                continue
        if (sum(p["margin"] for p in open_pos) + sz * row.entry_px / rc.leverage) > bal * 0.5:
            skip("margin")
            continue
        pos = {"sys": name, "entry_idx": i, "exit_idx": int(row.exit_idx), "direction": int(row.direction),
               "r": float(row.r), "size_oz": sz, "risk": sz * per_oz, "risk_pct": sz * per_oz / bal * 100.0,
               "pnl": float(row.r) * sz * per_oz, "margin": sz * row.entry_px / rc.leverage}
        open_pos.append(pos)
        taken.append(pos)
        busy[name] = pos["exit_idx"]
        day_trades += 1
    realize(np.iinfo(np.int64).max)

    tr = pd.DataFrame(taken)
    if len(tr):
        tr["entry_time"] = m.index[tr["entry_idx"].to_numpy()]
        tr["exit_time"] = m.index[tr["exit_idx"].to_numpy()]
    eq = np.asarray(eq_path)
    pk = np.maximum.accumulate(eq)
    return {"trades": tr, "final_equity": bal, "max_dd_pct": float(((pk - eq) / pk).max() * 100.0),
            "stopped_out": bool(stopped or skipped.get("hard_stop", 0) > 0), "skipped": skipped}


# ------------------------------------------------------------------ evaluation (same periods as gold_full_eval)

def period_candidates(bars: pd.DataFrame, params: dict, periods: tuple[str, ...] | None = None, cost=None) -> dict:
    """{period: (truncated bars, candidate DataFrame of all requested systems)}, exactly like gold_full_eval."""
    from backtest.markets import cost_model, keep_entries_from
    from scripts.gold_full_eval import PERIODS
    params = {**DEFAULT_PARAMS, **params}
    cost = cost or cost_model("XAUUSD", swap_annual_pct=5.0)
    sigs = {n: system_signals(bars, n, params.get(n)) for n in _sys_list(params)}
    out = {}
    for pname, (s, e) in PERIODS.items():
        if periods and pname not in periods:
            continue
        t0, t1 = pd.Timestamp(s, tz="UTC"), pd.Timestamp(e, tz="UTC")
        m = bars[bars.index < t1]
        frames = []
        for n, sa in sigs.items():
            sig = keep_entries_from(sa, bars.index, t0)
            keep = sig.entry_idx < len(m)
            for f in _SIG_FIELDS:
                setattr(sig, f, getattr(sig, f)[keep])
            sig.exit_idx = np.where(sig.exit_idx >= len(m), -1, sig.exit_idx)
            frames.append(candidates(m, sig, cost, n, int(params["vol_len"])))
        out[pname] = (m, pd.concat(frames, ignore_index=True))
    return out


def solo_trades(cand: pd.DataFrame, m: pd.DataFrame) -> pd.DataFrame:
    """Trades each system takes alone (its own single-slot rule, no account limits): the raw R edge."""
    rows = []
    for n, g in cand.groupby("sys"):
        busy = -1
        for row in g.sort_values("entry_idx", kind="stable").itertuples(index=False):
            if row.entry_idx <= busy:
                continue
            rows.append((n, row.entry_idx, row.exit_idx, row.r))
            busy = row.exit_idx
    t = pd.DataFrame(rows, columns=["sys", "entry_idx", "exit_idx", "r"])
    t["entry_time"] = m.index[t["entry_idx"].to_numpy()]
    t["exit_time"] = m.index[t["exit_idx"].to_numpy()]
    return t.sort_values("entry_idx", kind="stable").reset_index(drop=True)


def evaluate(params: dict | None = None, risk_pct: float = 2.0, bars: pd.DataFrame | None = None,
             periods: tuple[str, ...] | None = None, detail: bool = False) -> dict:
    from backtest.markets import r_stats
    from scripts.gold_full_eval import PERIODS, gold_all
    params = {**DEFAULT_PARAMS, **(params or {})}
    bars = gold_all() if bars is None else bars
    out = {}
    for pname, (m, cand) in period_candidates(bars, params, periods).items():
        s, e = PERIODS[pname]
        acc = simulate(m, cand, risk_pct, params)
        tr = acc["trades"]
        st = r_stats(tr, s, e) if len(tr) else {"n": 0}
        if len(tr):
            st["risk_w_r"] = round(float((tr["r"] * tr["risk_pct"]).sum() / risk_pct), 1)  # sum R x (risk / risk_pct)
            st["by_sys"] = {n: [int(len(g)), round(float(g["r"].mean()), 3)] for n, g in tr.groupby("sys")}
        out[pname] = {**st, "account_final": round(acc["final_equity"], 2), "account_max_dd_pct": round(acc["max_dd_pct"], 1),
                      "hard_stop": acc["stopped_out"]}
        if detail:
            out[pname]["skipped"] = acc["skipped"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", default="{}")
    ap.add_argument("--risk", type=float, default=2.0)
    ap.add_argument("--periods", default="")
    ap.add_argument("--detail", action="store_true")
    a = ap.parse_args()
    per = tuple(p for p in a.periods.split(",") if p) or None
    for k, v in evaluate(json.loads(a.params), a.risk, periods=per, detail=a.detail).items():
        print(f"{k:14s} {json.dumps(v)}")


if __name__ == "__main__":
    main()
