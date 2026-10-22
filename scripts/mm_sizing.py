"""Sizing-policy search for the gold swing EA ($50 cent account), on the fixed EA trade list from mm_sim.

Protocol (results/MM_RESEARCH_PLAN.md): every policy below is tuned on dev 2013-2019 only. The dev grid is
fixed in DEV_GRID (one line = one combo, counted). Finalists are chosen by the rule in pick_finalists() from
dev numbers alone; only finalists (plus the two references) are then run once on the validation periods.
Policies only use state before the trade (equity, peak, start, closed-trade R history) and never the
trade's own R / exit. Everything is MQL5-implementable (R per closed deal = profit / risk money at entry,
kept in a file or global variables).

    python scripts/mm_sizing.py            # dev grid + finalists + validation + diagnostics, prints tables
    python scripts/mm_sizing.py --dev-only # dev grid only (what the selection was made on)
"""
from __future__ import annotations

import math
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mm_sim import MAX_RISK, PERIODS, RUIN, START_EQUITY, evaluate_policy, fixed, get_trades, ladder, simulate  # noqa: E402

DEV = ("2013-01-01", "2020-01-01")
DEV_HALVES = {"dev_h1": ("2013-01-01", "2016-07-01"), "dev_h2": ("2016-07-01", "2020-01-01")}
VAL_KEYS = ("val_2020_2021", "val_2022_2025", "val_2026")
SEED = 20261022


def _slice(t: pd.DataFrame, s: str, e: str) -> pd.DataFrame:
    return t[(t["entry_time"] >= pd.Timestamp(s, tz="UTC")) & (t["entry_time"] < pd.Timestamp(e, tz="UTC"))]


# ---------------------------------------------------------------- helpers on the closed-trade R history

def ma_signal(hist: list, L: int) -> float:
    """c_last - mean(c over the last L closed trades), c = cumulative R. Equals sum_i (i-1)/L * r_i over the
    last L trades (i = 1 oldest .. L newest), i.e. a linearly weighted sum of recent R."""
    tail = np.asarray(hist[-L:], dtype=float)
    return float(np.dot(np.arange(L, dtype=float), tail)) / L


# ---------------------------------------------------------------- policy families
# Every factory returns policy(state, trade) -> risk fraction. Only state and entry-time fields are used.

def eq_throttle(L=20, hi=0.04, lo=0.015, warm=None):
    """A: equity-curve throttle. hi when the system's cumulative R is above its L-trade mean, else lo."""
    warm = lo if warm is None else warm

    def pol(st, tr):
        h = st["r_hist"]
        if len(h) < L:
            return warm
        return hi if ma_signal(h, L) > 0 else lo
    return pol


def sum_throttle(N=25, hi=0.04, lo=0.015):
    """A2: R-momentum throttle. hi when the sum of the last N closed-trade R is > 0, else lo (lo in warm-up)."""
    def pol(st, tr):
        h = st["r_hist"]
        if len(h) < N:
            return lo
        return hi if sum(h[-N:]) > 0 else lo
    return pol


def _ladder_base(eq, start, f=(0.05, 0.03, 0.02), x=(2.0, 4.0)):
    return f[0] if eq < x[0] * start else f[1] if eq < x[1] * start else f[2]


def ladder_x_throttle(L=20, up=1.33, dn=0.5, f=(0.05, 0.03, 0.02), x=(2.0, 4.0)):
    """B: milestone ladder 5/3/2 (2x/4x) multiplied by the equity-curve throttle (dn during warm-up)."""
    def pol(st, tr):
        base = _ladder_base(st["equity"], st["start"], f, x)
        h = st["r_hist"]
        if len(h) >= L and ma_signal(h, L) > 0:
            return base * up
        return base * dn
    return pol


def rolling_kelly(W=60, n0=0, k_prior=0.029, frac=0.5, lo=0.01, hi=0.06, warm=0.02, min_n=15):
    """C: rolling fractional Kelly on the last W closed-trade R, shrunk toward k_prior with weight n0.
    k_prior = dev mu/var (0.029, dev trades only)."""
    def pol(st, tr):
        h = st["r_hist"]
        if len(h) < min_n:
            return warm
        x = np.asarray(h[-W:], dtype=float)
        kw = x.mean() / max(x.var(ddof=1), 0.5)
        k = (len(x) * kw + n0 * k_prior) / (len(x) + n0)
        return float(np.clip(frac * k, lo, hi))
    return pol


def gz_floor(fk=0.08, alpha=0.5, lo=0.005, hi=0.08):
    """F: Grossman-Zhou drawdown-floor sizing: risk = fk * (1 - alpha * peak / equity)."""
    return lambda st, tr: float(np.clip(fk * (1 - alpha * st["peak"] / st["equity"]), lo, hi))


def cppi(mult=0.12, lo=0.005, hi=0.08):
    """F: CPPI, floor = max(0.7 x start, 0.5 x peak); risk = mult * cushion / equity."""
    def pol(st, tr):
        floor = max(0.7 * st["start"], 0.5 * st["peak"])
        return float(np.clip(mult * (st["equity"] - floor) / st["equity"], lo, hi))
    return pol


def fixed_ratio(delta=24.0, unit_frac=0.03):
    """G: Ryan Jones fixed ratio. unit = 3% of start; N units with N(N-1)/2 * delta <= profit."""
    def pol(st, tr):
        unit = unit_frac * st["start"]
        p = max(st["equity"] - st["start"], 0.0)
        n = math.floor(0.5 * (1 + math.sqrt(1 + 8 * p / delta)))
        return n * unit / st["equity"]
    return pol


def house_money(h=0.04, core_frac=0.02):
    """H: 2% of core (= start) + h of profits above start."""
    def pol(st, tr):
        eq, core = st["equity"], st["start"]
        return (core_frac * min(eq, core) + h * max(eq - core, 0.0)) / eq
    return pol


def cont_ladder(f0=0.05, beta=0.37, lo=0.015):
    """I: continuous ladder risk = f0 * (equity/start)^-beta, clipped to [lo, f0]."""
    return lambda st, tr: float(np.clip(f0 * (st["equity"] / st["start"]) ** (-beta), lo, f0))


def step_ladder(f=(0.05, 0.03, 0.02), x=(2.0, 4.0), on_peak=False):
    """I: step ladder (thresholds on current equity, or on peak so risk never steps back up)."""
    def pol(st, tr):
        return _ladder_base(st["peak"] if on_peak else st["equity"], st["start"], f, x)
    return pol


def streak(base=0.03, step=0.01, cap=0.05):
    """J: anti-martingale: + step per consecutive win (R > 0), reset after a loss."""
    def pol(st, tr):
        w = 0
        for r in reversed(st["r_hist"]):
            if r > 0:
                w += 1
            else:
                break
        return min(base + step * w, cap)
    return pol


def dd_derisk_stateful(base=0.03, dd=0.25, reduced=0.02, restore_dd=0.0):
    """K (exact hysteresis): keeps a 'deep drawdown' flag across trades; reset at each new simulation."""
    box = {"deep": False, "n": -1}

    def pol(st, tr):
        if st["n"] == 0 or st["n"] < box["n"]:
            box["deep"] = False
        box["n"] = st["n"]
        cur_dd = 1 - st["equity"] / st["peak"]
        if cur_dd >= dd:
            box["deep"] = True
        elif cur_dd <= restore_dd:
            box["deep"] = False
        return reduced if box["deep"] else base
    return pol


def cushion_gate(base=0.03, gate=1.10, mult=0.5):
    """L: prop-style: trade at mult x base until equity >= gate x start (re-gated whenever below)."""
    return lambda st, tr: base if st["equity"] >= gate * st["start"] else base * mult


# ---------------------------------------------------------------- bootstrap drawdown-constrained f (E)

def bootstrap_table(r: np.ndarray, fs: np.ndarray, block=20, horizon=100, paths=4000, seed=SEED) -> np.ndarray:
    """min over the horizon of equity / equity at the start, for each f and each block-bootstrap path."""
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(horizon / block))
    starts = rng.integers(0, len(r), size=(paths, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % len(r)
    rr = r[idx.reshape(paths, -1)[:, :horizon]]
    out = np.empty((len(fs), paths))
    for i, f in enumerate(fs):
        eq = np.cumprod(1 + f * rr, axis=1)
        out[i] = np.minimum(eq.min(axis=1), 1.0)
    return out


def f_star(table, fs, ratio, tol=0.15):
    ok = [f for f, row in zip(fs, table) if (row < ratio).mean() <= tol]
    return max(ok) if ok else fs[0]


BOOT_FS = np.round(np.arange(0.01, 0.0801, 0.005), 4)


def dd_bootstrap(tab: np.ndarray, absolute=False, floor=0.7, tol=0.15):
    """E: largest f in 1..8% with P(equity < floor x equity-at-start-of-horizon within 100 trades) <= tol,
    block bootstrap of dev R (tab = bootstrap_table(dev_r, BOOT_FS)). absolute=True: floor fixed at
    0.7 x START, recomputed at each doubling (allowed loss grows as equity grows)."""
    fs = BOOT_FS
    cache = {}

    def f_for_ratio(ratio):
        if ratio not in cache:
            cache[ratio] = float(f_star(tab, fs, ratio, tol))
        return cache[ratio]

    def pol(st, tr):
        if not absolute:
            return f_for_ratio(floor)
        k = max(int(math.floor(math.log2(st["equity"] / st["start"]))), 0) if st["equity"] >= st["start"] else 0
        return f_for_ratio(round(floor / 2 ** k, 6))
    pol.describe = lambda: {k: f_for_ratio(round(floor / 2 ** k, 6)) for k in range(4)}
    return pol


# ---------------------------------------------------------------- the dev grid (each line = one combo)

def build_dev_grid(dev_r: np.ndarray):
    G = []

    def add(name, family, rule, make, params):
        """make: zero-argument constructor of a fresh policy (stateful policies need a fresh closure)."""
        G.append(dict(name=name, family=family, rule=rule, make=make, params=params))

    # A: equity-curve throttle (switch hi/lo), warm-up at lo unless stated
    for L in (10, 15, 20, 30, 40):
        add(f"A eqMA{L} 4/1.5", "A_eq_throttle", f"cumR>MA{L}(cumR): 4% else 1.5% (warm-up 1.5%)",
            lambda L=L: eq_throttle(L, 0.04, 0.015), dict(L=L, hi=4, lo=1.5))
    for hi, lo in ((0.03, 0.015), (0.04, 0.02), (0.05, 0.02)):
        add(f"A eqMA20 {hi*100:g}/{lo*100:g}", "A_eq_throttle", f"cumR>MA20: {hi*100:g}% else {lo*100:g}%",
            lambda hi=hi, lo=lo: eq_throttle(20, hi, lo), dict(L=20, hi=hi * 100, lo=lo * 100))
    add("A eqMA20 4/1.5 warm3", "A_eq_throttle", "cumR>MA20: 4% else 1.5%, warm-up 3%",
        lambda: eq_throttle(20, 0.04, 0.015, warm=0.03), dict(L=20, hi=4, lo=1.5, warm=3))
    # A2: R-momentum (sum of last N R > 0)
    for N in (25, 50):
        add(f"A2 sumR{N} 4/1.5", "A2_sum_throttle", f"sum(last {N} R)>0: 4% else 1.5%",
            lambda N=N: sum_throttle(N, 0.04, 0.015), dict(N=N, hi=4, lo=1.5))
    # B: ladder x throttle
    for L in (15, 20):
        for up, dn in ((1.33, 0.5), (1.2, 0.6)):
            add(f"B lad x eqMA{L} {up}/{dn}", "B_ladder_x_throttle",
                f"ladder 5/3/2 @2x/4x times {up} if cumR>MA{L} else {dn}",
                lambda L=L, up=up, dn=dn: ladder_x_throttle(L, up, dn), dict(L=L, up=up, dn=dn))
    # C: rolling Kelly (k_prior = dev mu/var)
    k_prior = float(dev_r.mean() / dev_r.var(ddof=1))
    for W in (40, 60, 80):
        for n0 in (0, 60):
            add(f"C rollKelly W{W} n0={n0}", "C_rolling_kelly",
                f"0.5 x shrunk Kelly(last {W} R), prior {k_prior:.3f} w{n0}, clip 1-6%",
                lambda W=W, n0=n0: rolling_kelly(W, n0, k_prior), dict(W=W, n0=n0, frac=0.5))
    # D: static Kelly anchor: 0.5 x dev Kelly
    fs = np.arange(0.005, 0.1, 0.0025)
    kelly_dev = float(fs[int(np.argmax([np.mean(np.log1p(f * dev_r)) for f in fs]))])
    add(f"D fixed 0.5xKellyDev", "D_kelly_static",
        f"fixed {0.5*kelly_dev*100:.2f}% (dev growth-optimal f = {kelly_dev*100:.2f}%)",
        lambda: fixed(0.5 * kelly_dev), dict(f=0.5 * kelly_dev * 100, kelly_dev=kelly_dev * 100))
    # E: bootstrap DD-constrained f (table from dev R only)
    tab = bootstrap_table(dev_r, BOOT_FS)
    d1 = dd_bootstrap(tab, absolute=False).describe()
    d2 = dd_bootstrap(tab, absolute=True).describe()
    add("E boot f* relative", "E_dd_bootstrap", f"fixed f*={d1[0]*100:g}% (P(-30% in 100 tr)<=15%)",
        lambda: dd_bootstrap(tab, absolute=False), dict(f=d1[0] * 100))
    add("E boot f* absolute", "E_dd_bootstrap",
        "f* vs floor 0.7 x start, recomputed per doubling: " + "/".join(f"{v*100:g}" for v in d2.values()) + "%",
        lambda: dd_bootstrap(tab, absolute=True), {f"k{k}": v * 100 for k, v in d2.items()})
    # F: floors
    add("F GZ 8%/0.5", "F_floor", "8% x (1 - 0.5 peak/equity), clip 0.5-8%", lambda: gz_floor(0.08),
        dict(fk=8, alpha=0.5))
    add("F GZ 10%/0.5", "F_floor", "10% x (1 - 0.5 peak/equity), clip 0.5-8%", lambda: gz_floor(0.10),
        dict(fk=10, alpha=0.5))
    add("F CPPI 0.12", "F_floor", "0.12 x (eq - max(0.7 start, 0.5 peak))/eq", lambda: cppi(0.12), dict(mult=0.12))
    # G: fixed ratio
    for d in (15, 24, 40):
        add(f"G fixedRatio d{d}", "G_fixed_ratio", f"Jones fixed ratio, unit $1.5, delta ${d}",
            lambda d=d: fixed_ratio(d), dict(delta=d))
    # H: house money
    for h in (0.04, 0.06):
        add(f"H house {h*100:g}%", "H_house_money", f"2% of start + {h*100:g}% of profits",
            lambda h=h: house_money(h), dict(h=h * 100))
    # I: ladders
    for beta in (0.25, 0.37, 0.5):
        add(f"I contLadder b{beta}", "I_ladder", f"5% x (eq/start)^-{beta}, clip 1.5-5%",
            lambda beta=beta: cont_ladder(0.05, beta), dict(beta=beta))
    add("I ladder 5/3/2 on peak", "I_ladder", "5/3/2 @2x/4x of PEAK", lambda: step_ladder(on_peak=True),
        dict(on_peak=1))
    add("I ladder 5/3/2 @1.5x/3x", "I_ladder", "5/3/2 @1.5x/3x", lambda: step_ladder(x=(1.5, 3.0)), dict(x="1.5/3"))
    add("I ladder 5/3/2 @3x/6x", "I_ladder", "5/3/2 @3x/6x", lambda: step_ladder(x=(3.0, 6.0)), dict(x="3/6"))
    add("I ladder 4/3/2 @2x/4x", "I_ladder", "4/3/2 @2x/4x", lambda: step_ladder(f=(0.04, 0.03, 0.02)),
        dict(f="4/3/2"))
    add("I ladder 6/4/2 @2x/4x", "I_ladder", "6/4/2 @2x/4x", lambda: step_ladder(f=(0.06, 0.04, 0.02)),
        dict(f="6/4/2"))
    add("I ladder step-up 2/3/4", "I_ladder", "2/3/4 @2x/4x (risk UP as it grows)",
        lambda: step_ladder(f=(0.02, 0.03, 0.04)), dict(f="2/3/4"))
    # J: streaks
    add("J streak 3+1 cap5", "J_streak", "3% + 1% per consecutive win, cap 5%", lambda: streak(0.03, 0.01, 0.05),
        dict(base=3, step=1, cap=5))
    add("J streak 2+1 cap4", "J_streak", "2% + 1% per consecutive win, cap 4%", lambda: streak(0.02, 0.01, 0.04),
        dict(base=2, step=1, cap=4))
    # K: drawdown de-risking (exact hysteresis)
    add("K dd25->2% until new high", "K_dd_derisk", "3%; 2% once DD>=25% until a new high",
        lambda: dd_derisk_stateful(0.03, 0.25, 0.02, 0.0), dict(dd=25, reduced=2, restore=0))
    add("K dd25->2% until dd<10", "K_dd_derisk", "3%; 2% once DD>=25% until DD<=10%",
        lambda: dd_derisk_stateful(0.03, 0.25, 0.02, 0.10), dict(dd=25, reduced=2, restore=10))
    add("K EA-default dd10->1%", "K_dd_derisk", "3%; 1% while DD>=10% (EA InpDDReducePct=10 / Reduced 1%)",
        lambda: (lambda st, tr: 0.01 if st["equity"] < 0.9 * st["peak"] else 0.03), dict(dd=10, reduced=1))
    # L: cushion gate
    add("L cushion gate 1.1x", "L_cushion", "1.5% until equity >= 1.1 x start, then 3%",
        lambda: cushion_gate(0.03, 1.10, 0.5), dict(gate=1.1))
    return G, dict(k_prior=k_prior, kelly_dev=kelly_dev, boot_rel=d1, boot_abs=d2)


# ---------------------------------------------------------------- evaluation helpers

def dev_eval(pol, t):
    out = {"dev": simulate(_slice(t, *DEV), pol)}
    for k, (s, e) in DEV_HALVES.items():
        out[k] = simulate(_slice(t, s, e), pol)
    return out


def avg_risk(pol, trades):
    """Average risk fraction actually used (needs the simulated path)."""
    used = []

    def spy(st, tr):
        f = pol(st, tr)
        used.append(float(np.clip(f if not isinstance(f, tuple) else f[0], 0, MAX_RISK)))
        return f
    simulate(trades, spy)
    return float(np.mean(used)) if used else 0.0


def pick_finalists(rows, ref, max_n=5):
    """Pre-registered rule: eligible = beats fixed 3% on dev total AND in both dev halves AND never ruined on
    dev. One finalist per family (its best dev total), families ranked by that, at most max_n."""
    best = {}
    for r in rows:
        ok = (r["dev"]["total"] > ref["dev"]["total"] and r["dev_h1"]["total"] > ref["dev_h1"]["total"]
              and r["dev_h2"]["total"] > ref["dev_h2"]["total"] and not r["dev"]["ruined"])
        r["eligible"] = ok
        if ok and (r["family"] not in best or r["dev"]["total"] > best[r["family"]]["dev"]["total"]):
            best[r["family"]] = r
    return sorted(best.values(), key=lambda r: -r["dev"]["total"])[:max_n]


def with_seed(pol, seed_hist):
    """Warm start: the policy sees the system's R history before the period (data available live)."""
    def p(st, tr):
        st2 = dict(st)
        st2["r_hist"] = list(seed_hist) + list(st["r_hist"])
        st2["n"] = len(st2["r_hist"])
        return pol(st2, tr)
    return p


def warm_validation(pol_factory, t):
    out = {}
    for k in VAL_KEYS:
        s, e = PERIODS[k]
        seed = _slice(t, "2000-01-01", s)["r"].tolist()
        out[k] = simulate(_slice(t, s, e), with_seed(pol_factory(), seed))
    out["sum"] = round(sum(out[k]["total"] for k in VAL_KEYS), 2)
    return out


def simulate_lots(trades, policy, start_equity=START_EQUITY, max_risk_min_lot=0.03, buffer=0.10):
    """Like mm_sim.simulate but with cent-account lots: 0.01 lot of XAUUSDc risks (sl_dist+buffer)/100 $,
    lots floored to 0.01; if 0.01 lot would risk > max(3%, policy risk) of equity the trade is skipped
    (the EA's InpMaxRiskAtMinLotPct, set to at least the policy's risk)."""
    eq, peak, r_hist, path, since_peak, skipped = start_equity, start_equity, [], [], 0, 0
    for row in trades.itertuples(index=False):
        st = {"equity": eq, "start": start_equity, "peak": peak, "withdrawn": 0.0, "n": len(r_hist),
              "r_hist": r_hist, "last_r": r_hist[-1] if r_hist else 0.0, "trades_since_peak": since_peak}
        f = float(np.clip(policy(st, row), 0.0, MAX_RISK))
        step_risk = (row.sl_dist + buffer) / 100.0
        steps = math.floor(eq * f / step_risk + 1e-9)
        if steps == 0:
            steps = 1 if step_risk / eq <= max(max_risk_min_lot, f) else 0
        if steps:
            eq += steps * row.sl_dist / 100.0 * row.r
        else:
            skipped += 1
        r_hist.append(row.r)  # the system's R is known even when the trade is skipped (signal tracked)
        if eq > peak:
            peak, since_peak = eq, 0
        else:
            since_peak += 1
        path.append(eq)
        if eq < RUIN:
            break
    eqs = np.array([start_equity] + path)
    pk = np.maximum.accumulate(eqs)
    return {"total": round(eq, 2), "max_dd_pct": round(float(((pk - eqs) / pk).max() * 100), 1),
            "ruined": eq < RUIN, "skipped": skipped}


# ---------------------------------------------------------------- permutation diagnostic (dev only)

_PERM = {}


def _perm_job(args):
    name, seed, n = args
    pol_factory, r = _PERM[name]
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        rr = rng.permutation(r)
        df = pd.DataFrame({"r": rr, "sl_dist": 10.0})
        a = simulate(df, pol_factory())["total"]
        b = simulate(df, fixed(0.03))["total"]
        out.append(math.log(max(a, 1e-9) / b))
    return out


def perm_test(name, pol_factory, dev_r, actual_log_ratio, n=1000):
    _PERM[name] = (pol_factory, dev_r)
    jobs = [(name, SEED + i, n // 4) for i in range(4)]
    with ProcessPoolExecutor(4) as ex:
        res = np.concatenate([np.array(x) for x in ex.map(_perm_job, jobs)])
    return float((res >= actual_log_ratio).mean()), float(np.exp(np.median(res)))


# ---------------------------------------------------------------- main

def fmt_money(x):
    return f"{x:8.2f}"


def hard_stop_hit(trades, pol, start_equity=START_EQUITY, level=0.7):
    """True if equity (continuous sizing, same as mm_sim.simulate) ever closes below level x start:
    the EA's InpHardStopPct=30 would have halted it there."""
    eq, peak, r_hist, since_peak = start_equity, start_equity, [], 0
    for row in trades.itertuples(index=False):
        st = {"equity": eq, "start": start_equity, "peak": peak, "withdrawn": 0.0, "n": len(r_hist),
              "r_hist": r_hist, "last_r": r_hist[-1] if r_hist else 0.0, "trades_since_peak": since_peak}
        eq += eq * float(np.clip(pol(st, row), 0.0, MAX_RISK)) * row.r
        r_hist.append(row.r)
        peak, since_peak = (eq, 0) if eq > peak else (peak, since_peak + 1)
        if eq < level * start_equity:
            return True
    return False


def ea_dd_reduce(base_pol, dd=0.10, reduced=0.01):
    """The EA's built-in drawdown brake (defaults InpDDReducePct=10, InpReducedRiskPct=1): min(reduced, base)
    while equity < (1-dd) x peak. mm_sim's references (and every policy here) assume it is switched off."""
    def pol(st, tr):
        b = base_pol(st, tr)
        return min(reduced, b) if st["equity"] < (1 - dd) * st["peak"] else b
    return pol


def main(dev_only=False):
    t = get_trades()
    dev_t = _slice(t, *DEV)
    dev_r = dev_t["r"].to_numpy()
    grid, info = build_dev_grid(dev_r)
    print(f"trades: all {len(t)}, dev {len(dev_t)}; dev mean R {dev_r.mean():+.3f}, sd {dev_r.std(ddof=1):.3f}")
    print(f"dev growth-optimal fixed f (Kelly) = {info['kelly_dev']*100:.2f}%, dev mu/var = {info['k_prior']:.3f}; "
          f"bootstrap f* relative {info['boot_rel'][0]*100:g}%, absolute by doubling "
          + ", ".join(f"{2**k}x:{v*100:g}%" for k, v in info["boot_abs"].items()))

    refs = {"REF fixed 3%": fixed(0.03), "REF ladder 5/3/2": ladder(), "REF fixed 2%": fixed(0.02)}
    ref_dev = {k: dev_eval(p, t) for k, p in refs.items()}
    rows = []
    for g in grid:
        rows.append({**g, **dev_eval(g["make"](), t)})
    print(f"\nDEV GRID ({len(grid)} combos; $50 fresh start each window; dev halves 2013-16H1 / 2016H2-19)")
    print(f"{'policy':34s} {'dev $':>8s} {'DD%':>5s} {'h1 $':>8s} {'h2 $':>8s}  rule")
    for k, v in ref_dev.items():
        print(f"{k:34s} {fmt_money(v['dev']['total'])} {v['dev']['max_dd_pct']:5.1f} "
              f"{fmt_money(v['dev_h1']['total'])} {fmt_money(v['dev_h2']['total'])}")
    f3 = ref_dev["REF fixed 3%"]
    finals = pick_finalists(rows, f3)
    for r in rows:
        print(f"{r['name']:33s}{'*' if r['eligible'] else ' '} {fmt_money(r['dev']['total'])} "
              f"{r['dev']['max_dd_pct']:5.1f} {fmt_money(r['dev_h1']['total'])} {fmt_money(r['dev_h2']['total'])}  "
              f"{r['rule']}" + ("  RUINED" if r["dev"]["ruined"] else ""))
    print("(* = eligible: beats fixed 3% on dev and in both dev halves)")
    fams = pd.DataFrame([{"family": r["family"], "dev": r["dev"]["total"], "elig": r["eligible"]} for r in rows])
    agg = fams.groupby("family").agg(n=("dev", "size"), median=("dev", "median"), max=("dev", "max"),
                                     eligible=("elig", "sum"))
    print(f"\nfamily summary on dev (fixed 3% = {f3['dev']['total']:.2f}):")
    print(agg.sort_values("median", ascending=False).round(2).to_string())

    print("\nFINALISTS (pre-registered rule: best eligible combo per family, top 5 families by dev $):")
    for r in finals:
        print(f"  {r['name']:30s} dev ${r['dev']['total']:.2f}  {r['rule']}")

    # ---------------- dev-only diagnostics of the finalists (before any validation run)
    print("\nDEV DIAGNOSTICS (dev only): fixed f at the policy's own average dev risk; "
          "trade-order permutation test (1000 shuffles of the dev R sequence)")
    f3dev = f3["dev"]["total"]
    for r in finals:
        r["avg_risk_dev"] = avg_risk(r["make"](), dev_t)
        fm = simulate(dev_t, fixed(r["avg_risk_dev"]))["total"]
        act = math.log(r["dev"]["total"] / f3dev)
        p, med = perm_test(r["name"], r["make"], dev_r, act, n=1000)
        r["perm_p"], r["perm_med_ratio"], r["risk_matched_dev"] = p, med, fm
        print(f"  {r['name']:30s} avg risk {r['avg_risk_dev']*100:.2f}% -> fixed at that risk ${fm:.2f} "
              f"(policy ${r['dev']['total']:.2f}); shuffled: median policy/fixed3 {med:.2f}x, "
              f"P(shuffle >= actual {math.exp(act):.2f}x) = {p:.3f}")
    if dev_only:
        return rows, finals, None

    # ---------------- validation, run once per finalist (+ references)
    factories = {"REF fixed 3%": lambda: fixed(0.03), "REF ladder 5/3/2": lambda: ladder()}
    for r in finals:
        factories[r["name"]] = r["make"]
    factories["REF EA-default brake, 3%"] = lambda: ea_dd_reduce(fixed(0.03))
    factories["REF EA-default brake, ladder"] = lambda: ea_dd_reduce(ladder())
    name2grid = {g["name"]: g for g in grid}
    table = []
    for name, fac in factories.items():
        ev = evaluate_policy(fac(), t)
        wv = warm_validation(fac, t)
        lots = {k: simulate_lots(_slice(t, *PERIODS[k]), fac()) for k in PERIODS}
        lots_all = simulate_lots(t, fac())
        hs = [k for k in PERIODS if hard_stop_hit(_slice(t, *PERIODS[k]), fac())]
        g = name2grid.get(name)
        table.append(dict(
            name=name, rule=g["rule"] if g else name, params=g["params"] if g else {},
            dev=ev["dev_2013_2019"]["total"], dev_dd=ev["dev_2013_2019"]["max_dd_pct"],
            v20=ev["val_2020_2021"]["total"], v22=ev["val_2022_2025"]["total"], v26=ev["val_2026"]["total"],
            val_sum=ev["validation_sum"], all=ev["all_2013_2026"]["total"], dd_all=ev["all_2013_2026"]["max_dd_pct"],
            dd_val=max(ev[k]["max_dd_pct"] for k in VAL_KEYS),
            ruined=any(ev[k]["ruined"] for k in list(PERIODS) + ["all_2013_2026"]),
            hard_stop=hs, warm_sum=wv["sum"],
            warm=(wv["val_2020_2021"]["total"], wv["val_2022_2025"]["total"], wv["val_2026"]["total"]),
            lots_dev=lots["dev_2013_2019"]["total"], lots_val=round(sum(lots[k]["total"] for k in VAL_KEYS), 2),
            lots_all=lots_all["total"], lots_skip=lots_all["skipped"],
            avg_risk_dev=avg_risk(fac(), dev_t), avg_risk_all=avg_risk(fac(), t)))
    ref3, lad = table[0], table[1]
    for row in table:
        row["better"] = (not row["name"].startswith("REF") and row["dev"] > ref3["dev"]
                         and row["val_sum"] > ref3["val_sum"] and not row["ruined"])
        row["beats_ladder"] = row["dev"] > lad["dev"] and row["val_sum"] > lad["val_sum"]

    print("\nFINAL TABLE ($ from a fresh $50 per period; validation run once; all = one account 2013-2026)")
    print(f"{'policy':30s} {'dev':>7s} {'ddDev':>5s} {'20-21':>7s} {'22-25':>7s} {'2026':>6s} {'valSum':>7s} "
          f"{'all':>8s} {'ddAll':>5s} {'ddVal':>5s} {'better':>6s} {'>lad':>4s}  -30% hard stop hit in")
    for r in table:
        print(f"{r['name']:30s} {r['dev']:7.2f} {r['dev_dd']:5.1f} {r['v20']:7.2f} {r['v22']:7.2f} {r['v26']:6.2f} "
              f"{r['val_sum']:7.2f} {r['all']:8.2f} {r['dd_all']:5.1f} {r['dd_val']:5.1f} {str(r['better']):>6s} "
              f"{'yes' if r['beats_ladder'] else 'no':>4s}  {','.join(r['hard_stop']) or '-'}"
              + ("  RUINED" if r["ruined"] else ""))
    print("\nROBUSTNESS (not used for selection)")
    print(f"{'policy':30s} {'avg risk dev/all':>16s}  {'warm-start val 20-21/22-25/2026 = sum':>38s}  "
          f"cent lots (0.01 steps): dev / valSum / all (skipped trades)")
    for r in table:
        w = r["warm"]
        print(f"{r['name']:30s} {r['avg_risk_dev']*100:7.2f}/{r['avg_risk_all']*100:5.2f}%   "
              f"{w[0]:7.2f}/{w[1]:7.2f}/{w[2]:6.2f} = {r['warm_sum']:7.2f}   "
              f"{r['lots_dev']:7.2f} / {r['lots_val']:7.2f} / {r['lots_all']:8.2f} ({r['lots_skip']})")

    # ---------------- where the money came from: one account 2013-2026, growth multiple @ average risk per year
    print("\nYEAR BY YEAR in the single 2013-2026 account: equity multiple @ average risk % (system mean R in last col)")
    yr_cols = {}
    for name in [k for k in factories if not k.startswith("REF EA")]:
        p, eq, hist, peak, rec = factories[name](), START_EQUITY, [], START_EQUITY, []
        for row in t.itertuples(index=False):
            st = {"equity": eq, "start": START_EQUITY, "peak": peak, "withdrawn": 0.0, "n": len(hist),
                  "r_hist": hist, "last_r": hist[-1] if hist else 0.0, "trades_since_peak": 0}
            f = float(np.clip(p(st, row), 0.0, MAX_RISK))
            e0 = eq
            eq += eq * f * row.r
            hist.append(row.r)
            peak = max(peak, eq)
            rec.append((row.entry_time.year, f, e0, eq))
        d = pd.DataFrame(rec, columns=["y", "f", "e0", "e1"]).groupby("y").agg(f=("f", "mean"), e0=("e0", "first"),
                                                                                e1=("e1", "last"))
        yr_cols[name.replace("REF ", "")[:16]] = [f"{a:.2f}@{b*100:.1f}" for a, b in zip(d.e1 / d.e0, d.f)]
        idx = d.index
    yt = pd.DataFrame(yr_cols, index=idx)
    yt["meanR"] = t.groupby(t["entry_time"].dt.year)["r"].mean().round(3).to_numpy()
    print(yt.to_string())

    # ---------------- cost sensitivity (same signals; R re-computed): costs x1.5, and swap-free (Exness ID)
    print("\nCOST SENSITIVITY (not used for selection): valSum / all-history $ / max DD all")
    t_stress = get_trades(stress=1.5)
    t_sf = t.copy()
    t_sf["r"] = t_sf["r"] + t_sf["swap"] / t_sf["risk"]
    for nm, fac in factories.items():
        if nm.startswith("REF EA"):
            continue
        a = evaluate_policy(fac(), t_stress)
        b = evaluate_policy(fac(), t_sf)
        print(f"  {nm:30s} costs x1.5: {a['validation_sum']:8.2f} / {a['all_2013_2026']['total']:8.2f} / "
              f"{a['all_2013_2026']['max_dd_pct']:4.1f}%   swap-free: {b['validation_sum']:8.2f} / "
              f"{b['all_2013_2026']['total']:8.2f} / {b['all_2013_2026']['max_dd_pct']:4.1f}%")

    # ---------------- start-date sensitivity: fresh $50 (cold start) on each 1 January, run to the end of data
    print("\nSTART-YEAR SENSITIVITY (fresh $50 on 1 Jan of each year, cold start, to 2026-09): final $ (max DD %)")
    sy = {}
    for nm, fac in factories.items():
        if nm.startswith("REF EA"):
            continue
        col = []
        for y in range(2013, 2026):
            res = simulate(_slice(t, f"{y}-01-01", "2030-01-01"), fac())
            col.append(f"{res['total']:.0f} ({res['max_dd_pct']:.0f})" + ("R" if res["ruined"] else ""))
        sy[nm.replace("REF ", "")[:16]] = col
    syt = pd.DataFrame(sy, index=range(2013, 2026))
    print(syt.to_string())
    base = [simulate(_slice(t, f"{y}-01-01", "2030-01-01"), fixed(0.03))["total"] for y in range(2013, 2026)]
    for nm, fac in factories.items():
        if nm.startswith("REF"):
            continue
        wins = sum(simulate(_slice(t, f"{y}-01-01", "2030-01-01"), fac())["total"] > b
                   for y, b in zip(range(2013, 2026), base))
        print(f"  {nm:30s} beats fixed 3% in {wins}/13 start years")

    # ---------------- post-hoc: the finalists' grid neighbours on validation (looked at AFTER the finalists
    # were fixed and validated; not used to choose anything; shows whether a pass is a family effect or luck)
    print("\nPOST-HOC FAMILY SENSITIVITY on validation (finalist families only; NOT used for selection)")
    print(f"{'combo':34s} {'dev':>7s} {'valSum':>8s} {'all':>8s} {'ddAll':>5s}  vs fixed 3% valSum {ref3['val_sum']:.2f}")
    fin_fams = {r["family"] for r in finals}
    for g in grid:
        if g["family"] not in fin_fams:
            continue
        ev = evaluate_policy(g["make"](), t)
        mark = "F" if g["name"] in {r["name"] for r in finals} else " "
        print(f"{mark} {g['name']:32s} {ev['dev_2013_2019']['total']:7.2f} {ev['validation_sum']:8.2f} "
              f"{ev['all_2013_2026']['total']:8.2f} {ev['all_2013_2026']['max_dd_pct']:5.1f}  "
              f"{'pass' if ev['validation_sum'] > ref3['val_sum'] else 'FAIL'}")
    return rows, finals, table


if __name__ == "__main__":
    main(dev_only="--dev-only" in sys.argv)
