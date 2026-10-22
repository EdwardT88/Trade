"""Synthesis of the four money-management cluster studies: re-check, combine, rank. Prints everything to stdout.

Levers. Every lever was frozen by its own cluster on dev 2013-2019; nothing is re-tuned here.
  account     HFM = HFM Cent as today: swap 5%/yr, model spread (stress 1)       [mm_account baseline]
              EXN = Exness Standard Cent: swap-free + spread x0.75, NOT tuned    [mm_account central case]
  management  EA, W1, X1, T2, C1 = W1+X1, C5 = W1+X1+R2, C7 = W1+X1+R2+T2.
              These are the mm_management finals that passed validation. R2 alone failed, so it is not offered alone.
  sizing      F3 = fixed 3%.
              K  = rolling half-Kelly over the last 60 closed-trade R, clip 1-6%, 2% for the first 15 trades
                   (mm_sizing 'C'; the best dev finalist among those without look-ahead).
              T  = rsi_depth tiers 1.5/1/0.5 x 3% (mm_conviction 'C1'; the best look-ahead-free dev candidate).
              KT = K x the T multiplier (risk 0.5%..9%).
              The 5/3/2 ladder is excluded as a lever because its 2x/4x thresholds were chosen after seeing all the
              data. B and C4 are built on it, so they are excluded too. The ladder stays as a reference.

Selection rule for the combination. It was fixed before any combination was run on a validation period.
  On dev 2013-2019 at HFM costs, a (management, sizing) pair is ELIGIBLE if it:
    - beats EA + fixed 3% on the dev total and on both dev halves (each half from a fresh $50);
    - is never ruined;
    - never closes below the EA's -30% hard stop (InpHardStopPct=30) from a fresh $50 on dev.
  PRIMARY = the eligible pair with the highest dev total.
  The account lever is not selected: it is a broker fact, not a parameter. The primary is reported at both cost sets.
  Disclosure: the author had read every cluster's validation numbers, so the components were known to have passed.
  Only the combination itself is new on validation, and it is run here once.

Conventions are the same as scripts/mm_sim.py: each period starts from a fresh $50, and all = one account 2013-2026.
validation_sum = 2020-21 + 2022-25 + 2026. Sizing is continuous unless a table says "cent lots".

    python scripts/mm_combined.py
    python scripts/mm_combined.py --dev-only     # selection stage only
"""
from __future__ import annotations

import math
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mm_management as MG  # noqa: E402
from backtest.data import resample  # noqa: E402
from backtest.indicators import rsi  # noqa: E402
from mm_sim import MAX_RISK, PERIODS, RUIN, START_EQUITY, _bars, fixed, get_trades, ladder  # noqa: E402
from mm_sizing import rolling_kelly  # noqa: E402

DEV = ("2013-01-01", "2020-01-01")
HALVES = {"dev_h1": ("2013-01-01", "2016-07-01"), "dev_h2": ("2016-07-01", "2020-01-01")}
VAL_KEYS = ("val_2020_2021", "val_2022_2025", "val_2026")
PER_KEYS = ("dev_2013_2019",) + VAL_KEYS
HARD = 0.70           # EA InpHardStopPct = 30: halts when equity <= 0.7 x start balance
SEED = 20261022

ACCOUNTS = {          # name: (swap %/yr, spread+slippage stress)
    "HFM": (5.0, 1.0), "EXN": (0.0, 0.75),
    # used only for the lever ranking / stress tests
    "SWAPFREE": (0.0, 1.0), "SPREAD75": (5.0, 0.75), "STRESS15": (5.0, 1.5), "EXN_STRESS": (0.0, 1.125),
    "SWAPFREE_STRESS": (0.0, 1.5), "SPREAD75_STRESS": (5.0, 1.125),
}
_W1, _X1 = MG.GRID["W1 wkd long >=1R lock .5 ->Tue"], MG.GRID["X1 cap ext >=0R trend ->Fri"]
_T2 = MG.GRID["T2 add 0.5x @+1ATR max1"]
MGMT = {"EA": {}, "W1": _W1, "X1": _X1, "T2": _T2, "C1": MG.GRID2["C1 W1+X1"], "C5": MG.GRID2["C5 W1+X1+R2"],
        "C7": MG.GRID2["C7 W1+X1+R2+T2"]}
SIZING = ("F3", "K", "T", "KT")


def _slice(t: pd.DataFrame, s: str, e: str) -> pd.DataFrame:
    return t[(t["entry_time"] >= pd.Timestamp(s, tz="UTC")) & (t["entry_time"] < pd.Timestamp(e, tz="UTC"))]


# ------------------------------------------------------------------------------------------- trade lists

@lru_cache(maxsize=1)
def _h1_rsi():
    eb = resample(_bars(), "1h")
    r1 = rsi(eb["close"].to_numpy(), 14)
    return ((eb.index + pd.Timedelta("1h")).asi8, pd.Series(r1).rolling(10).min().to_numpy(),
            pd.Series(r1).rolling(10).max().to_numpy())


def rsi_depth(t: pd.DataFrame) -> np.ndarray:
    """Same as mm_conviction.entry_features()['rsi_depth']. Long: 40 - lowest RSI(14,H1) over the last 10 completed
    H1 bars at the signal bar's close; short: highest - 60. Known at entry."""
    close_ns, lo10, hi10 = _h1_rsi()
    ct = pd.DatetimeIndex(t["entry_time"].dt.floor("h")).as_unit("ns").asi8
    i1 = np.searchsorted(close_ns, ct, side="right") - 1
    d = t["direction"].to_numpy()
    return np.where(d > 0, 40 - lo10[i1], hi10[i1] - 60)


@lru_cache(maxsize=64)
def trades(mgmt: str, acct: str) -> pd.DataFrame:
    """Group trades for a management option at an account's costs.

    For the Turtle add, it also splits the group R into r1 (the first unit, whose stop moves at the add) and radd
    (the add unit, per unit of size). Every stop is common, so the path does not depend on the add size and
    R(add_frac) = r1 + add_frac * radd exactly. This is checked against a second run.
    """
    opts = MGMT[mgmt]
    swap, stress = ACCOUNTS[acct]
    t = MG.run(opts, swap=swap, stress=stress)
    t["r1"], t["radd"], t["has_add"] = t["r"].to_numpy(), 0.0, False
    if opts.get("add_atr", 0) > 0:
        frac = opts.get("add_frac", 1.0)
        t2 = MG.run({**opts, "add_frac": frac / 2}, swap=swap, stress=stress)
        same = (len(t) == len(t2) and (t["entry_time"].to_numpy() == t2["entry_time"].to_numpy()).all()
                and (t["exit_time"].to_numpy() == t2["exit_time"].to_numpy()).all()
                and (t["n_add"].to_numpy() == t2["n_add"].to_numpy()).all())
        if not same:
            raise RuntimeError("add decomposition: paths differ with the add size")
        radd = (t["r"].to_numpy() - t2["r"].to_numpy()) / (frac - frac / 2)
        t["radd"] = radd
        t["r1"] = t["r"].to_numpy() - frac * radd
        t["has_add"] = t["n_add"].to_numpy() > 0
        t["add_frac"] = frac
    t["rsi_depth"] = rsi_depth(t)
    t["slip"] = 0.05 * stress
    return t


@lru_cache(maxsize=1)
def cuts() -> tuple[float, float]:
    """Frozen rsi_depth tercile cut points from the EA's dev trades at HFM costs (= mm_conviction dev_cuts)."""
    t = trades("EA", "HFM")
    x = t.loc[t["entry_time"] < pd.Timestamp(DEV[1], tz="UTC"), "rsi_depth"].dropna()
    return float(x.quantile(1 / 3)), float(x.quantile(2 / 3))


# ------------------------------------------------------------------------------------------- sizing policies

def tier(x: float) -> float:
    """mm_conviction C1: shallow pullback (bottom dev tercile) 1.5x, deep (top tercile) 0.5x, middle / NaN 1x."""
    if x != x:
        return 1.0
    c0, c1 = cuts()
    return 1.5 if x <= c0 else (0.5 if x > c1 else 1.0)


def policy(name: str):
    if name == "F3":
        return fixed(0.03)
    if name == "F2":
        return fixed(0.02)
    if name == "LAD":
        return ladder()
    if name == "T":
        return lambda st, tr: 0.03 * tier(tr.rsi_depth)
    k = rolling_kelly(W=60, n0=0)
    if name == "K":
        return k
    if name == "KT":
        return lambda st, tr: k(st, tr) * tier(tr.rsi_depth)
    if name.endswith("+brake"):          # the EA's default drawdown brake on top: min(1%, base) while DD >= 10%
        base = policy(name[:-6])
        return lambda st, tr: min(0.01, base(st, tr)) if st["equity"] < 0.9 * st["peak"] else base(st, tr)
    raise ValueError(name)


def withdraw_half_at_2x(base: str):
    """mm_account 'take 50% at each 2x': when equity >= 2 x base, withdraw 50%; base = the equity left."""
    b = policy(base)
    box = {"base": START_EQUITY, "n": -1}

    def pol(st, tr):
        if st["n"] == 0 or st["n"] < box["n"]:
            box["base"] = st["start"]
        box["n"] = st["n"]
        take = 0.0
        if st["equity"] >= 2 * box["base"]:
            take = 0.5 * st["equity"]
            box["base"] = st["equity"] - take
        return b(st, tr), take
    return pol


# ------------------------------------------------------------------------------------------- simulator

def sim(t: pd.DataFrame, pol, *, lots=False, halt=False, seed_hist=None, start=START_EQUITY,
        max_min_lot=0.03, buffer=0.10) -> dict:
    """mm_sim.simulate plus three options.
    - lots: cent-account lots. One step (0.01 lot) risks (sl_dist + buffer)/100 $. Lots are floored. If that gives
      zero, the minimum lot is taken when it risks <= max(3%, policy risk); this is the EA's InpMaxRiskAtMinLotPct.
      The Turtle add is max(1 step, floor(0.5 x first lots)), so at 1 step the add is 1.0x and not 0.5x.
    - halt: trading stops for good once equity closes <= 0.7 x start (the EA's hard stop with no manual reset).
    - seed_hist: earlier closed-trade R that the policy sees (warm start).
    The system R is appended to the history whatever the account did with the trade."""
    eq = peak = float(start)
    hist = list(seed_hist or [])
    path, risks = [], []
    withdrawn, skipped, ruined, hit, halted = 0.0, 0, False, False, False
    for row in t.itertuples(index=False):
        st = {"equity": eq, "start": float(start), "peak": peak, "withdrawn": withdrawn, "n": len(hist),
              "r_hist": hist, "last_r": hist[-1] if hist else 0.0, "trades_since_peak": 0}
        out = pol(st, row)
        f, take = out if isinstance(out, tuple) else (out, 0.0)
        if take > 0:
            take = min(take, eq)
            eq -= take
            withdrawn += take
        f = float(np.clip(f, 0.0, MAX_RISK))
        e0 = eq
        if lots:
            step_risk = (row.sl_dist + buffer) / 100.0
            steps = math.floor(eq * f / step_risk + 1e-9)
            if steps == 0:
                steps = 1 if step_risk / eq <= max(max_min_lot, f) else 0
            if steps:
                unit = (row.sl_dist + row.slip) / 100.0
                add = max(1, math.floor(0.5 * steps + 1e-9)) if row.has_add else 0
                eq += steps * unit * row.r1 + add * unit * row.radd
                risks.append(steps * step_risk / e0)
            else:
                skipped += 1
        else:
            eq += eq * f * row.r
            risks.append(f)
        hist.append(row.r)
        peak = max(peak, eq)
        path.append(eq)
        if eq <= HARD * start:
            hit = True
            if halt:
                halted = True
                break
        if eq < RUIN:
            ruined = True
            break
    eqs = np.array([float(start)] + path)
    pk = np.maximum.accumulate(eqs)
    return {"total": round(eq + withdrawn, 2), "final": round(eq, 2), "withdrawn": round(withdrawn, 2),
            "max_dd": round(float(((pk - eqs) / pk).max() * 100), 1), "ruined": ruined, "hard_hit": hit,
            "halted": halted, "skipped": skipped, "avg_risk": float(np.mean(risks)) if risks else 0.0,
            "n": len(path)}


def evalp(t: pd.DataFrame, make, **kw) -> dict:
    """Every period from a fresh $50, plus the dev halves, the whole history and validation_sum."""
    out = {k: sim(_slice(t, *PERIODS[k]), make(), **kw) for k in PER_KEYS}
    for k, (s, e) in HALVES.items():
        out[k] = sim(_slice(t, s, e), make(), **kw)
    out["all"] = sim(t, make(), **kw)
    out["val_sum"] = round(sum(out[k]["total"] for k in VAL_KEYS), 2)
    out["max_dd_any"] = max(out[k]["max_dd"] for k in PER_KEYS + ("all",))
    out["hard_in"] = [k.replace("val_", "").replace("dev_2013_2019", "dev") for k in PER_KEYS if out[k]["hard_hit"]]
    out["ruined"] = any(out[k]["ruined"] for k in PER_KEYS + ("all",))
    return out


def row_str(name: str, ev: dict) -> str:
    return (f"| {name} | {ev['dev_2013_2019']['total']:.2f} | {ev['val_2020_2021']['total']:.2f} | "
            f"{ev['val_2022_2025']['total']:.2f} | {ev['val_2026']['total']:.2f} | {ev['val_sum']:.2f} | "
            f"{ev['all']['total']:.2f} | {ev['all']['max_dd']:.1f}% | {ev['max_dd_any']:.1f}% | "
            f"{','.join(ev['hard_in']) or '-'} | {'RUIN' if ev['ruined'] else 'no'} |")


HDR = ("| config | dev | 2020-21 | 2022-25 | 2026 | val sum | all 2013-26 | max DD all | max DD any | "
       "-30% hard stop hit (fresh $50) | ruined |\n|---|---|---|---|---|---|---|---|---|---|---|")


# ------------------------------------------------------------------------------------------- block bootstrap

def bootstrap(t: pd.DataFrame, pol: str, block: int, horizon=150, paths=2000, seed=SEED) -> dict:
    """Circular block bootstrap of the config's trade sequence (R and the trade's rsi_depth tier move together),
    `horizon` trades from a fresh $50, cold start. Vectorised versions of F3 / LAD / K / T / KT."""
    r = t["r"].to_numpy(float)
    m = np.array([tier(x) for x in t["rsi_depth"].to_numpy(float)])
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(horizon / block))
    st = rng.integers(0, len(r), size=(paths, nb))
    idx = ((st[:, :, None] + np.arange(block)[None, None, :]) % len(r)).reshape(paths, -1)[:, :horizon]
    R, M = r[idx], m[idx]
    eq = np.full(paths, START_EQUITY)
    lo = eq.copy()
    alive = np.ones(paths, bool)
    for k in range(horizon):
        if pol in ("K", "KT"):
            if k < 15:
                f = np.full(paths, 0.02)
            else:
                w = R[:, max(0, k - 60):k]
                f = np.clip(0.5 * w.mean(1) / np.maximum(w.var(1, ddof=1), 0.5), 0.01, 0.06)
        elif pol == "LAD":
            f = np.where(eq < 2 * START_EQUITY, 0.05, np.where(eq < 4 * START_EQUITY, 0.03, 0.02))
        else:
            f = np.full(paths, 0.03)
        if pol in ("T", "KT"):
            f = f * M[:, k]
        f = np.minimum(f, MAX_RISK)
        eq = np.where(alive, eq * (1 + f * R[:, k]), eq)
        lo = np.minimum(lo, eq)
        alive &= eq >= RUIN
    return {"median": float(np.median(eq)), "p10": float(np.percentile(eq, 10)), "p90": float(np.percentile(eq, 90)),
            "mean": float(eq.mean()), "p_hard": float((lo <= HARD * START_EQUITY).mean()),
            "p_loss": float((eq < START_EQUITY).mean()), "p_ruin": float((~alive).mean())}


# ------------------------------------------------------------------------------------------- main

def main(dev_only=False):
    pd.set_option("display.width", 250)
    # 0) the inputs are what the clusters used
    ref = get_trades()
    ea = trades("EA", "HFM")
    same = len(ref) == len(ea) and np.allclose(ref["r"].to_numpy(), ea["r"].to_numpy(), atol=1e-9)
    print(f"check: mm_management.run({{}}) == mm_sim.get_trades(): {same} (n {len(ea)})")
    c = cuts()
    print(f"frozen rsi_depth dev cut points: {c[0]:.3f} / {c[1]:.3f} (mm_conviction: 1.826 / 4.905)")
    c7 = trades("C7", "HFM")
    print(f"C7 add decomposition: {int(c7['has_add'].sum())} groups with an add; max |r1 + 0.5 radd - r| = "
          f"{np.abs(c7['r1'] + 0.5 * c7['radd'] - c7['r']).max():.1e}")

    # 1) selection on dev only (HFM)
    print("\n## 1. Selection stage: dev 2013-2019 only, HFM costs ($50 fresh; halves each from a fresh $50)")
    print("| management | sizing | dev $ | DD | h1 $ | h2 $ | avg risk | -30% hit on dev | eligible |\n|---|---|---|---|---|---|---|---|---|")
    base = {k: sim(_slice(ea, *v), policy("F3")) for k, v in {"dev": DEV, **HALVES}.items()}
    print(f"| EA | F3 (reference) | {base['dev']['total']:.2f} | {base['dev']['max_dd']:.1f}% | {base['dev_h1']['total']:.2f} | "
          f"{base['dev_h2']['total']:.2f} | 3.00% | {'yes' if base['dev']['hard_hit'] else 'no'} | - |")
    sel = []
    for m in MGMT:
        t = trades(m, "HFM")
        for s in SIZING:
            if m == "EA" and s == "F3":
                continue
            d = {k: sim(_slice(t, *v), policy(s)) for k, v in {"dev": DEV, **HALVES}.items()}
            ok = (d["dev"]["total"] > base["dev"]["total"] and d["dev_h1"]["total"] > base["dev_h1"]["total"]
                  and d["dev_h2"]["total"] > base["dev_h2"]["total"] and not d["dev"]["ruined"]
                  and not d["dev"]["hard_hit"])
            sel.append((m, s, d, ok))
            print(f"| {m} | {s} | {d['dev']['total']:.2f} | {d['dev']['max_dd']:.1f}% | {d['dev_h1']['total']:.2f} | "
                  f"{d['dev_h2']['total']:.2f} | {d['dev']['avg_risk'] * 100:.2f}% | {'yes' if d['dev']['hard_hit'] else 'no'} | "
                  f"{'YES' if ok else 'no'} |")
    elig = [x for x in sel if x[3]]
    pm, ps, pd_, _ = max(elig, key=lambda x: x[2]["dev"]["total"])
    print(f"\ncombos evaluated on dev: {len(sel)}; eligible: {len(elig)}; PRIMARY (highest eligible dev $) = {pm} + {ps} "
          f"(dev ${pd_['dev']['total']:.2f})")
    best_any = max(sel, key=lambda x: x[2]["dev"]["total"])
    print(f"highest dev $ overall (eligible or not): {best_any[0]} + {best_any[1]} ${best_any[2]['dev']['total']:.2f} "
          f"(hard stop hit on dev: {best_any[2]['dev']['hard_hit']})")
    if dev_only:
        return

    # 2) validation: the primary, once, at both cost sets, next to the references (and the whole grid for context)
    print("\n## 2. The primary and the references on every period (validation of the combination is run here once)")
    print(HDR)
    refs = {"fixed 2% (EA, HFM)": ("EA", "HFM", "F2"), "fixed 3% (EA, HFM)": ("EA", "HFM", "F3"),
            "ladder 5/3/2 (EA, HFM)": ("EA", "HFM", "LAD"),
            "fixed 2% (EA, EXN)": ("EA", "EXN", "F2"), "fixed 3% (EA, EXN)": ("EA", "EXN", "F3"),
            "ladder 5/3/2 (EA, EXN)": ("EA", "EXN", "LAD"),
            f"PRIMARY {pm}+{ps} (HFM)": (pm, "HFM", ps), f"PRIMARY {pm}+{ps} (EXN)": (pm, "EXN", ps)}
    R = {}
    for name, (m, a, s) in refs.items():
        R[name] = evalp(trades(m, a), lambda s=s: policy(s))
        print(row_str(name, R[name]))
    prim_h, prim_x = R[f"PRIMARY {pm}+{ps} (HFM)"], R[f"PRIMARY {pm}+{ps} (EXN)"]
    f3 = R["fixed 3% (EA, HFM)"]
    print(f"\nprimary (HFM) better than fixed 3% by the plan's rule (dev AND val_sum, never ruined): "
          f"{prim_h['dev_2013_2019']['total'] > f3['dev_2013_2019']['total'] and prim_h['val_sum'] > f3['val_sum'] and not prim_h['ruined']}")
    print(f"avg risk used (all, HFM): {prim_h['all']['avg_risk'] * 100:.2f}%; trades all {prim_h['all']['n']}")

    print("\n### Context: the whole management x sizing grid on validation (HFM, then EXN). Not used to choose anything.")
    print(HDR)
    grid_val = {}
    for a in ("HFM", "EXN"):
        for m in MGMT:
            for s in SIZING:
                ev = evalp(trades(m, a), lambda s=s: policy(s))
                grid_val[(m, s, a)] = ev
                mark = " <- PRIMARY" if (m, s) == (pm, ps) else ""
                print(row_str(f"{m}+{s} ({a}){mark}", ev))
    for a in ("HFM", "EXN"):
        keys = [(m, s) for (m, s, aa) in grid_val if aa == a]
        dev_v = pd.Series([grid_val[(m, s, a)]["dev_2013_2019"]["total"] for m, s in keys])
        val_v = pd.Series([grid_val[(m, s, a)]["val_sum"] for m, s in keys])
        pos = int((val_v > grid_val[(pm, ps, a)]["val_sum"]).sum()) + 1
        print(f"{a}: the primary ranks {pos}/{len(keys)} on val_sum; Spearman(dev $, val_sum) over the grid = "
              f"{dev_v.rank().corr(val_v.rank()):.2f}")

    # 3) robustness of the primary (none of this chooses anything)
    print("\n## 3. Robustness of the primary")
    print("\n### 3a. Cent lots (0.01-lot steps, min-lot rule, Turtle add >= 1 step) and the EA's -30% halt with no reset")
    print("| config | sim | dev | 2020-21 | 2022-25 | 2026 | val sum | all | max DD all | halted in | skipped (all) |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for name, (m, a, s) in [("fixed 3% (EA, HFM)", ("EA", "HFM", "F3")), ("ladder 5/3/2 (EA, HFM)", ("EA", "HFM", "LAD")),
                            (f"PRIMARY (HFM)", (pm, "HFM", ps)), (f"PRIMARY (EXN)", (pm, "EXN", ps))]:
        for lab, kw in (("cent lots", dict(lots=True)), ("halt at -30%", dict(halt=True)),
                        ("cent lots + halt", dict(lots=True, halt=True))):
            ev = evalp(trades(m, a), lambda s=s: policy(s), **kw)
            hl = [k for k in PER_KEYS + ("all",) if ev[k]["halted"]]
            print(f"| {name} | {lab} | {ev['dev_2013_2019']['total']:.2f} | {ev['val_2020_2021']['total']:.2f} | "
                  f"{ev['val_2022_2025']['total']:.2f} | {ev['val_2026']['total']:.2f} | {ev['val_sum']:.2f} | "
                  f"{ev['all']['total']:.2f} | {ev['all']['max_dd']:.1f}% | {','.join(hl) or '-'} | {ev['all']['skipped']} |")

    print("\n### 3b. Warm start: each validation period sees the config's own earlier R history (as a seeded EA would)")
    for name, (m, a, s) in [("fixed 3% (EA, HFM)", ("EA", "HFM", "F3")), ("K (EA, HFM)", ("EA", "HFM", "K")),
                            ("PRIMARY (HFM)", (pm, "HFM", ps)), ("PRIMARY (EXN)", (pm, "EXN", ps))]:
        t = trades(m, a)
        vals = []
        for k in VAL_KEYS:
            s0, e0 = PERIODS[k]
            seed = _slice(t, "2000-01-01", s0)["r"].tolist()
            vals.append(sim(_slice(t, s0, e0), policy(s), seed_hist=seed)["total"])
        print(f"  {name:22s} 20-21 {vals[0]:7.2f}  22-25 {vals[1]:8.2f}  2026 {vals[2]:6.2f}  sum {sum(vals):8.2f}")

    print("\n### 3c. Costs: x1.5 spread+slippage with swap 5% (STRESS15); Exness with swap-free revoked (SPREAD75); "
          "Exness at x1.125 spread")
    print(HDR)
    for a in ("STRESS15", "SPREAD75", "EXN_STRESS"):
        for name, (m, s) in [("fixed 3% EA", ("EA", "F3")), ("ladder EA", ("EA", "LAD")), ("PRIMARY", (pm, ps))]:
            print(row_str(f"{name} ({a})", evalp(trades(m, a), lambda s=s: policy(s))))

    print("\n### 3d. Start-year sensitivity: fresh $50 on 1 January, cold start, run to 2026-09 (final $, max DD)")
    rows = {}
    for name, (m, a, s) in [("F3 EA HFM", ("EA", "HFM", "F3")), ("ladder EA HFM", ("EA", "HFM", "LAD")),
                            ("PRIMARY HFM", (pm, "HFM", ps)), ("PRIMARY EXN", (pm, "EXN", ps))]:
        t = trades(m, a)
        rows[name] = [sim(_slice(t, f"{y}-01-01", "2030-01-01"), policy(s)) for y in range(2013, 2026)]
    yt = pd.DataFrame({k: [f"{x['total']:.0f} ({x['max_dd']:.0f}%){' H' if x['hard_hit'] else ''}" for x in v]
                       for k, v in rows.items()}, index=range(2013, 2026))
    print(yt.to_string())
    for k in ("PRIMARY HFM", "PRIMARY EXN"):
        w3 = sum(a["total"] > b["total"] for a, b in zip(rows[k], rows["F3 EA HFM"]))
        wl = sum(a["total"] > b["total"] for a, b in zip(rows[k], rows["ladder EA HFM"]))
        print(f"  {k}: beats fixed 3% in {w3}/13 start years, the ladder in {wl}/13; "
              f"-30% hit in {sum(x['hard_hit'] for x in rows[k])}/13 (F3: {sum(x['hard_hit'] for x in rows['F3 EA HFM'])}/13, "
              f"ladder: {sum(x['hard_hit'] for x in rows['ladder EA HFM'])}/13)")

    print("\n### 3e. Block bootstrap, 150 trades (~3 years) from $50, 2000 paths, cold start. "
          "Pool = the config's own trades; 'dev pool' = 2013-19 trades only (a 2013-19-like future)")
    print("| config | pool | block | median | P10 | P90 | mean | P(-30% hit) | P(< $50) | P(ruin) |\n|---|---|---|---|---|---|---|---|---|---|")
    for name, (m, a, s) in [("fixed 3% EA HFM", ("EA", "HFM", "F3")), ("ladder EA HFM", ("EA", "HFM", "LAD")),
                            ("K EA HFM", ("EA", "HFM", "K")), ("PRIMARY HFM", (pm, "HFM", ps)),
                            ("fixed 3% EA EXN", ("EA", "EXN", "F3")), ("PRIMARY EXN", (pm, "EXN", ps))]:
        t = trades(m, a)
        for pool, tp in (("all", t), ("dev", _slice(t, *DEV))):
            for blk in (10, 40, 120):
                b = bootstrap(tp, s, blk)
                print(f"| {name} | {pool} | {blk} | {b['median']:.1f} | {b['p10']:.1f} | {b['p90']:.1f} | {b['mean']:.1f} | "
                      f"{b['p_hard']:.0%} | {b['p_loss']:.0%} | {b['p_ruin']:.1%} |")

    print("\n### 3f. Single account 2013-2026 (HFM): equity multiple per year @ average risk, and the system's mean R")
    t = trades(pm, "HFM")
    pol = policy(ps)
    eq, hist, rec = START_EQUITY, [], []
    for row in t.itertuples(index=False):
        st = {"equity": eq, "start": START_EQUITY, "peak": eq, "withdrawn": 0.0, "n": len(hist), "r_hist": hist,
              "last_r": hist[-1] if hist else 0.0, "trades_since_peak": 0}
        f = float(np.clip(pol(st, row), 0, MAX_RISK))
        rec.append((row.entry_time.year, f, eq, eq * (1 + f * row.r), row.r))
        eq *= 1 + f * row.r
        hist.append(row.r)
    d = pd.DataFrame(rec, columns=["y", "f", "e0", "e1", "r"]).groupby("y").agg(
        n=("r", "size"), meanR=("r", "mean"), avg_risk=("f", "mean"), e0=("e0", "first"), e1=("e1", "last"))
    d["mult"] = d["e1"] / d["e0"]
    d["avg_risk"] *= 100
    ea_y = ea.groupby(ea["entry_time"].dt.year)["r"].mean()
    d["EA meanR"] = ea_y
    print(d[["n", "meanR", "EA meanR", "avg_risk", "mult", "e1"]].round(3).to_string())

    print("\n### 3g. What the primary would risk on the NEXT trade if seeded with its full history (live warm start)")
    sl26 = float(_slice(ea, "2026-01-01", "2027-01-01")["sl_dist"].median())
    for a in ("HFM", "EXN"):
        h = trades(pm, a)["r"].to_numpy()[-60:]
        k = float(np.clip(0.5 * h.mean() / max(h.var(ddof=1), 0.5), 0.01, 0.06))
        print(f"  {a}: last 60 R mean {h.mean():+.3f}, var {h.var(ddof=1):.2f} -> K base {k * 100:.2f}% "
              f"(x 0.5 / 1 / 1.5 by rsi_depth tier if T is in the primary); at $50 the min lot (0.01) with the 2026 "
              f"median stop ${sl26:.1f} risks {(sl26 + 0.10) / 100 / 50 * 100:.2f}%")

    print("\n### 3h. EA defaults that change the result: the drawdown brake (InpDDReducePct=10 -> 1%)")
    print(HDR)
    for name, (m, a, s) in [("fixed 3% EA HFM + brake", ("EA", "HFM", "F3+brake")),
                            ("PRIMARY HFM + brake", (pm, "HFM", ps + "+brake")),
                            ("PRIMARY EXN + brake", (pm, "EXN", ps + "+brake"))]:
        print(row_str(name, evalp(trades(m, a), lambda s=s: policy(s))))
    t7 = trades(pm, "HFM")
    if (t7["tag"] == 1).any():
        prev_exit = t7["exit_time"].shift(1)
        same_day = ((t7["tag"] == 1) & (t7["entry_time"].dt.floor("D") == prev_exit.dt.floor("D"))).sum()
        print(f"re-entries (R2) in the primary: {int((t7['tag'] == 1).sum())}; on the same UTC day as the stop-out "
              f"they follow: {int(same_day)}. With risk >= 5% the EA's InpDailyLossPct=5 would block those.")

    # 4) lever ranking
    print("\n## 4. Lever ranking")
    print("Robust = beats its reference on dev, val_sum and all-history; no period (dev, 20-21, 22-25, 2026) more "
          "than 5% below the reference; still beats it on all-history at x1.5 costs.")
    print("gm ratio = geometric mean over the 4 periods of (lever $ / reference $), each from a fresh $50: "
          "every period counts the same, so 2022-25 compounding does not dominate it.")
    print("| lever | reference | dev | val sum | all | max DD all | periods better (of 4) | worst period ratio | "
          "gm ratio | all @x1.5 costs | robust |\n|---|---|---|---|---|---|---|---|---|---|---|")

    def lever(name, refspec, spec, stress_ref=None, stress_spec=None):
        (rm, ra, rs), (m, a, s) = refspec, spec
        e0, e1 = evalp(trades(rm, ra), lambda: policy(rs)), evalp(trades(m, a), lambda: policy(s))
        ratios = [e1[k]["total"] / e0[k]["total"] for k in PER_KEYS]
        sr = stress_ref or (rm, "STRESS15" if ra == "HFM" else ra, rs)
        ss = stress_spec or (m, "STRESS15" if a == "HFM" else "EXN_STRESS", s)
        x0 = evalp(trades(sr[0], sr[1]), lambda: policy(sr[2]))["all"]["total"]
        x1 = evalp(trades(ss[0], ss[1]), lambda: policy(ss[2]))["all"]["total"]
        rob = (e1["dev_2013_2019"]["total"] > e0["dev_2013_2019"]["total"] and e1["val_sum"] > e0["val_sum"]
               and e1["all"]["total"] > e0["all"]["total"] and min(ratios) >= 0.95 and x1 > x0)
        print(f"| {name} | {rm}+{rs} {ra} | {e0['dev_2013_2019']['total']:.2f} -> {e1['dev_2013_2019']['total']:.2f} | "
              f"{e0['val_sum']:.2f} -> {e1['val_sum']:.2f} | {e0['all']['total']:.2f} -> {e1['all']['total']:.2f} | "
              f"{e0['all']['max_dd']:.0f}% -> {e1['all']['max_dd']:.0f}% | {sum(x > 1 for x in ratios)} | "
              f"{min(ratios):.2f} | {math.exp(np.mean(np.log(ratios))):.2f} | {x0:.0f} -> {x1:.0f} | "
              f"{'YES' if rob else 'no'} |")
        return rob

    print("| **single levers from EA + fixed 3% at HFM** | | | | | | | | | | |")
    B = ("EA", "HFM", "F3")
    lever("account: Exness swap-free + spread x0.75", B, ("EA", "EXN", "F3"), ("EA", "STRESS15", "F3"),
          ("EA", "EXN_STRESS", "F3"))
    lever("account: swap-free only", B, ("EA", "SWAPFREE", "F3"), ("EA", "STRESS15", "F3"),
          ("EA", "SWAPFREE_STRESS", "F3"))
    lever("account: spread x0.75 only", B, ("EA", "SPREAD75", "F3"), ("EA", "STRESS15", "F3"),
          ("EA", "SPREAD75_STRESS", "F3"))
    for m in ("W1", "X1", "T2", "C1", "C5", "C7"):
        lever(f"management: {m}", B, (m, "HFM", "F3"))
    for s, lab in (("K", "sizing: K rolling half-Kelly W60"), ("T", "sizing: T rsi_depth tiers"),
                   ("KT", "sizing: K x T"), ("LAD", "sizing: ladder 5/3/2 (look-ahead, reference)"),
                   ("F3+brake", "EA default DD brake ON (10% -> 1%)")):
        lever(lab, B, ("EA", "HFM", s))
    e0 = evalp(ea, lambda: policy("F3"))
    e1 = evalp(ea, lambda: withdraw_half_at_2x("F3"))
    print(f"| cash flow: withdraw 50% at each 2x (total = equity + withdrawn) | EA+F3 HFM | "
          f"{e0['dev_2013_2019']['total']:.2f} -> {e1['dev_2013_2019']['total']:.2f} | {e0['val_sum']:.2f} -> {e1['val_sum']:.2f} | "
          f"{e0['all']['total']:.2f} -> {e1['all']['total']:.2f} | | | | | | no |")
    print(f"| **leave one out from the PRIMARY {pm}+{ps} at EXN (each row removes one lever)** | | | | | | | | | | |")
    P = (pm, "EXN", ps)
    lever("remove account lever (EXN -> HFM)", (pm, "HFM", ps), P, (pm, "STRESS15", ps), (pm, "EXN_STRESS", ps))
    if pm != "EA":
        lever(f"remove management ({pm} -> EA)", ("EA", "EXN", ps), P, ("EA", "EXN_STRESS", ps), (pm, "EXN_STRESS", ps))
        if pm == "C7":
            for sub in ("C1", "C5"):
                lever(f"management {sub} -> C7", (sub, "EXN", ps), P, (sub, "EXN_STRESS", ps), (pm, "EXN_STRESS", ps))
            lever("management W1 -> C7", ("W1", "EXN", ps), P, ("W1", "EXN_STRESS", ps), (pm, "EXN_STRESS", ps))
    if "K" in ps:
        rest = ps.replace("K", "") or "F3"
        lever(f"remove K ({rest} -> {ps})", (pm, "EXN", rest), P, (pm, "EXN_STRESS", rest), (pm, "EXN_STRESS", ps))
    if "T" in ps:
        rest = ps.replace("T", "") or "F3"
        lever(f"remove T ({rest} -> {ps})", (pm, "EXN", rest), P, (pm, "EXN_STRESS", rest), (pm, "EXN_STRESS", ps))
    posthoc(pm, ps)


def underwater(t: pd.DataFrame, pol) -> dict:
    """Single account: longest stretch below a previous equity peak (calendar days, peak date -> recovery date)."""
    eq, peak, peak_t, hist, longest, worst = START_EQUITY, START_EQUITY, t["entry_time"].iloc[0], [], 0.0, None
    for row in t.itertuples(index=False):
        st = {"equity": eq, "start": START_EQUITY, "peak": peak, "withdrawn": 0.0, "n": len(hist), "r_hist": hist,
              "last_r": hist[-1] if hist else 0.0, "trades_since_peak": 0}
        eq *= 1 + float(np.clip(pol(st, row), 0, MAX_RISK)) * row.r
        hist.append(row.r)
        if eq >= peak:
            d = (row.exit_time - peak_t).days
            if d > longest:
                longest, worst = d, (peak_t.date(), row.exit_time.date())
            peak, peak_t = eq, row.exit_time
    end = (t["exit_time"].iloc[-1] - peak_t).days
    return {"longest_days": longest, "span": worst, "open_days_at_end": end}


def posthoc(pm: str, ps: str):
    """Diagnostics run AFTER the primary's validation. Nothing here chooses the primary."""
    print("\n## 5. Post-hoc diagnostics (after validation; information only)")
    print("\n### 5a. Time under water in the single 2013-2026 account (longest peak-to-recovery, calendar days)")
    for name, (m, a, s) in [("fixed 3% EA HFM", ("EA", "HFM", "F3")), ("ladder EA HFM", ("EA", "HFM", "LAD")),
                            ("PRIMARY HFM", (pm, "HFM", ps)), ("PRIMARY EXN", (pm, "EXN", ps)),
                            ("W1+KT EXN", ("W1", "EXN", "KT"))]:
        u = underwater(trades(m, a), policy(s))
        print(f"  {name:18s} longest {u['longest_days']:5d} days {u['span']}; still under water at the end: "
              f"{u['open_days_at_end']} days")

    print("\n### 5b. Start-year test WITH the EA's -30% halt and no manual reset (final $; H = halted)")
    rows = {}
    for name, (m, a, s) in [("F3 EA HFM", ("EA", "HFM", "F3")), ("ladder EA HFM", ("EA", "HFM", "LAD")),
                            ("PRIMARY HFM", (pm, "HFM", ps)), ("PRIMARY EXN", (pm, "EXN", ps))]:
        t = trades(m, a)
        rows[name] = [sim(_slice(t, f"{y}-01-01", "2030-01-01"), policy(s), halt=True) for y in range(2013, 2026)]
    print(pd.DataFrame({k: [f"{x['total']:.0f}{' H' if x['halted'] else ''}" for x in v] for k, v in rows.items()},
                       index=range(2013, 2026)).to_string())

    print("\n### 5c. Risk actually used by the primary (single account, all history)")
    for a in ("HFM", "EXN"):
        t = trades(pm, a)
        pol, eq, hist, fs = policy(ps), START_EQUITY, [], []
        for row in t.itertuples(index=False):
            st = {"equity": eq, "start": START_EQUITY, "peak": eq, "withdrawn": 0.0, "n": len(hist), "r_hist": hist,
                  "last_r": hist[-1] if hist else 0.0, "trades_since_peak": 0}
            f = float(np.clip(pol(st, row), 0, MAX_RISK))
            fs.append(f)
            eq *= 1 + f * row.r
            hist.append(row.r)
        fs = np.array(fs) * 100
        worst = (np.array(fs) / 100 * t["r"].to_numpy()).min() * 100
        print(f"  {a}: mean {fs.mean():.2f}%, median {np.median(fs):.2f}%; share of trades at <= 1.5%: "
              f"{(fs <= 1.5).mean():.0%}, > 6%: {(fs > 6).mean():.0%}, = 9%: {(fs >= 8.99).mean():.0%}; "
              f"worst single-trade loss {worst:.1f}% of equity")

    print("\n### 5d. Ablations of the stack (post hoc: these use validation knowledge, they are NOT validated choices)")
    print(HDR)
    MGMT["C6"] = MG.GRID2["C6 W1+X1+T2"]
    for name, (m, a, s) in [("C6=W1+X1+T2 (no R2) + KT (HFM)", ("C6", "HFM", "KT")),
                            ("C6=W1+X1+T2 (no R2) + KT (EXN)", ("C6", "EXN", "KT")),
                            ("PRIMARY C7+KT (HFM)", (pm, "HFM", ps)), ("PRIMARY C7+KT (EXN)", (pm, "EXN", ps)),
                            ("robust-only core W1+KT (HFM)", ("W1", "HFM", "KT")),
                            ("robust-only core W1+KT (EXN)", ("W1", "EXN", "KT"))]:
        print(row_str(name, evalp(trades(m, a), lambda s=s: policy(s))))
    for m in ("C6", "C7", "W1"):
        t = trades(m, "HFM")
        per = {k: _slice(t, *PERIODS[k])["r"].mean() for k in PER_KEYS}
        print(f"  {m} avg R (HFM): " + ", ".join(f"{k} {v:+.3f}" for k, v in per.items()) + f", all {t['r'].mean():+.3f}")

    print("\n### 5f. Parameter sensitivity of the primary's sizing (post hoc; the frozen choice is W60, cap 6%, tiers 1.5/0.5)")
    print("| K window | K cap | tiers hi/lo | dev | val sum | all | max DD all | -30% hit (fresh $50) |\n|---|---|---|---|---|---|---|---|")
    c0, c1 = cuts()
    for W in (40, 60, 80):
        for hi in (0.04, 0.06):
            for th, tl in ((1.5, 0.5), (1.25, 0.75)):
                def mk(W=W, hi=hi, th=th, tl=tl):
                    k = rolling_kelly(W=W, n0=0, hi=hi)
                    return lambda st, tr: k(st, tr) * (1.0 if tr.rsi_depth != tr.rsi_depth else
                                                      th if tr.rsi_depth <= c0 else tl if tr.rsi_depth > c1 else 1.0)
                ev = evalp(trades(pm, "HFM"), mk)
                print(f"| {W} | {hi:.0%} | {th}/{tl} | {ev['dev_2013_2019']['total']:.2f} | {ev['val_sum']:.2f} | "
                      f"{ev['all']['total']:.2f} | {ev['all']['max_dd']:.1f}% | {','.join(ev['hard_in']) or '-'} |")

    print("\n### 5e. Where the primary's whole-history growth came from (HFM single account, log-growth share)")
    t = trades(pm, "HFM")
    pol, eq, hist, rec = policy(ps), START_EQUITY, [], []
    for row in t.itertuples(index=False):
        st = {"equity": eq, "start": START_EQUITY, "peak": eq, "withdrawn": 0.0, "n": len(hist), "r_hist": hist,
              "last_r": hist[-1] if hist else 0.0, "trades_since_peak": 0}
        g = math.log1p(float(np.clip(pol(st, row), 0, MAX_RISK)) * row.r)
        rec.append((row.entry_time, g))
        eq *= math.exp(g)
        hist.append(row.r)
    d = pd.DataFrame(rec, columns=["t", "g"])
    tot = d["g"].sum()
    for k in PER_KEYS:
        s0, e0 = PERIODS[k]
        g = d[(d["t"] >= pd.Timestamp(s0, tz="UTC")) & (d["t"] < pd.Timestamp(e0, tz="UTC"))]["g"].sum()
        print(f"  {k}: x{math.exp(g):.2f} ({g / tot:.0%} of the total log growth x{math.exp(tot):.0f})")


if __name__ == "__main__":
    main(dev_only="--dev-only" in sys.argv)
