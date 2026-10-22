"""Account/broker-side levers and cash-flow schedules for the gold swing EA ($50 cent account).

Two questions, both on the fixed EA trade list from mm_sim (strategies/swing_pullback, max_hold_days=3):

1. Account side (no tuning, "re-run the same trades with different costs", MM_RESEARCH_PLAN):
   swap-free (get_trades(swap=0)), tighter/wider spread (stress), IB rebates (extra $ per oz traded, with the
   sub-cent / minimum-payout rules of real rebate sites), a paid VPS, and graduating to a Pro account.
   Each scenario is reported as avg R per period and as $ under fixed 3%, the ladder 5/3/2 and the
   rolling half-Kelly W60 policy from scripts/mm_sizing.py (re-implemented here, same rule).

2. Cash-flow schedules (tuned on dev 2013-19 only, combos counted in DEV_GRID): withdraw x% at each k-x
   multiple, free-roll (take the $50 stake out once), barbell, monthly/quarterly/annual profit sweeps,
   monthly deposits (DCA $5/$10), refill-to-$50, and DCA timed by the equity-curve signal.
   Judged in total-wealth terms: "wealth" = $50 + cumulative trading P&L (= equity + withdrawn - deposits
   after the start). For withdrawal-only schedules this is just equity + withdrawn (mm_sim's "total").
   Finalists are picked by pick_finalists() from dev numbers alone; validation is run once.

Live-implementable: flows are things the owner does by hand on month boundaries or at equity multiples; the
EA itself only needs its peak / start-balance globals adjusted for balance operations (see results/mm_account.md).

    python scripts/mm_account.py             # everything, prints the tables used in results/mm_account.md
    python scripts/mm_account.py --dev-only  # dev grid only (what the selection was made on)
"""
from __future__ import annotations

import math
import multiprocessing as mp
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mm_sim import MAX_RISK, PERIODS, RUIN, START_EQUITY, fixed, get_trades, ladder, simulate  # noqa: E402

DEV_KEY = "dev_2013_2019"
VAL_KEYS = ("val_2020_2021", "val_2022_2025", "val_2026")
ALL_KEY = "all_2013_2026"
SPANS = {**PERIODS, ALL_KEY: ("2013-01-01", "2026-09-26")}
SEED = 20261022
HARD_STOP = 0.70  # the EA's InpHardStopPct = 30 (equity < 0.7 x start balance halts it)


def _slice(t: pd.DataFrame, s: str, e: str) -> pd.DataFrame:
    return t[(t["entry_time"] >= pd.Timestamp(s, tz="UTC")) & (t["entry_time"] < pd.Timestamp(e, tz="UTC"))]


# ---------------------------------------------------------------- base sizing policies

def rolling_kelly(W=60, frac=0.5, lo=0.01, hi=0.06, warm=0.02, min_n=15):
    """'C' from scripts/mm_sizing.py (unshrunk, n0=0): 0.5 x mean/max(var, 0.5) of the last W closed-trade R,
    clipped to 1-6%, 2% for the first 15 trades."""
    def pol(st, tr):
        h = st["r_hist"]
        if len(h) < min_n:
            return warm
        x = np.asarray(h[-W:], dtype=float)
        return float(np.clip(frac * x.mean() / max(x.var(ddof=1), 0.5), lo, hi))
    return pol


def ladder_ea(f=(0.05, 0.03, 0.02), x=(2.0, 4.0)):
    """The EA's InpRiskLadder as coded in mql5/GoldSwingCent.mq5: growth = balance / start-balance GV, and the EA
    shifts that GV (and the peak GV) by every deposit/withdrawal (OnTradeTransaction, DEAL_TYPE_BALANCE) and resets
    it to the balance when it falls to <= 0 (OnTick). Without cash flows this is exactly mm_sim.ladder()."""
    def pol(st, tr):
        g = st["equity"] / st.get("ea_start", st["start"])
        return f[0] if g < x[0] else f[1] if g < x[1] else f[2]
    return pol


BASES = {"fixed3": lambda: fixed(0.03), "ladder": lambda: ladder_ea(), "C_W60": lambda: rolling_kelly()}
if "--ladder-fixed-thresholds" in sys.argv:  # alternative: ladder steps at fixed $100 / $200 whatever the flows
    BASES["ladder"] = lambda: ladder()
BASE_LABEL = {"fixed3": "fixed 3%", "ladder": "ladder 5/3/2", "C_W60": "C rolling half-Kelly W60"}


def ma_signal(hist, L):
    """cumR_last - mean(cumR over the last L closed trades) (same as mm_sizing.ma_signal)."""
    tail = np.asarray(hist[-L:], dtype=float)
    return float(np.dot(np.arange(len(tail), dtype=float), tail)) / len(tail)


# ---------------------------------------------------------------- cash-flow schedules
# A flow is called before every trade with the account state, the month indices (year*12+month-1) whose
# first day passed since the previous call, and the entry time. It returns (deposit, withdrawal) in $.

class Flow:
    name = "none"

    def reset(self, start):
        pass

    def __call__(self, st, months, ts):
        return 0.0, 0.0


class WithdrawAtMultiple(Flow):
    """When equity >= k x base: withdraw x of equity; the base becomes the equity left (so it repeats)."""
    def __init__(self, k=2.0, x=0.5):
        self.k, self.x = k, x

    def reset(self, start):
        self.base = start

    def __call__(self, st, months, ts):
        eq = st["equity"]
        if eq >= self.k * self.base:
            w = self.x * eq
            self.base = eq - w
            return 0.0, w
        return 0.0, 0.0


class FreeRoll(Flow):
    """Once, when equity first reaches k x start: withdraw the starting stake. Nothing after that."""
    def __init__(self, k=2.0):
        self.k = k

    def reset(self, start):
        self.done = False

    def __call__(self, st, months, ts):
        if not self.done and st["equity"] >= self.k * st["start"]:
            self.done = True
            return 0.0, st["start"]
        return 0.0, 0.0


class Sweep(Flow):
    """On the first day of every `every`-th month (Jan for 12, Jan/Apr/Jul/Oct for 3): withdraw s x the
    equity above the $50 start."""
    def __init__(self, s=1.0, every=1):
        self.s, self.every = s, every

    def __call__(self, st, months, ts):
        if any(m % self.every == 0 for m in months) and st["equity"] > st["start"]:
            return 0.0, self.s * (st["equity"] - st["start"])
        return 0.0, 0.0


class DCA(Flow):
    """Deposit `amount` on the first day of every month."""
    def __init__(self, amount=10.0):
        self.amount = amount

    def __call__(self, st, months, ts):
        return self.amount * len(months), 0.0


class Refill(Flow):
    """On the first day of each month, if equity < start: top up to start, at most `cap` per month."""
    def __init__(self, cap=10.0):
        self.cap = cap

    def __call__(self, st, months, ts):
        if months and st["equity"] < st["start"]:
            return min(self.cap * len(months), st["start"] - st["equity"]), 0.0
        return 0.0, 0.0


class DCAOnSignal(Flow):
    """Set aside `amount` every month (committed cash, kept at the bank at 0%); move all of it into the account
    whenever the EA's cumulative R is above its L-trade mean (the mm_sizing equity-curve signal)."""
    def __init__(self, amount=10.0, L=20):
        self.amount, self.L = amount, L

    def reset(self, start):
        self.bank = 0.0
        self.committed = []  # (time, amount): what the owner set aside, used for IRR / contributions

    def __call__(self, st, months, ts):
        if months:
            self.bank += self.amount * len(months)
            self.committed.append((ts, self.amount * len(months)))
        h = st["r_hist"]
        if self.bank > 0 and len(h) >= self.L and ma_signal(h, self.L) > 0:
            d, self.bank = self.bank, 0.0
            return d, 0.0
        return 0.0, 0.0


def barbell(base_factory, k=3.0, after=0.05):
    """Free-roll at k x start, then trade the rest at `after` risk (policy reads state['withdrawn'] > 0)."""
    def make():
        b = base_factory()
        return lambda st, tr: after if st["withdrawn"] > 0 else b(st, tr)
    return make, lambda: FreeRoll(k)


# ---------------------------------------------------------------- simulator

def irr(flows, lo=-0.99, hi=50.0):
    """Annual money-weighted return of [(time, amount)] (contributions negative, terminal value positive)."""
    t0 = flows[0][0]
    y = np.array([(t - t0).total_seconds() / (365.25 * 86400) for t, _ in flows])
    a = np.array([v for _, v in flows])

    def npv(r):
        return float(np.sum(a * (1 + r) ** (-y)))
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return float("nan")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        f = npv(mid)
        if f_lo * f > 0:
            lo, f_lo = mid, f
        else:
            hi = mid
    return 0.5 * (lo + hi)


def run(t: pd.DataFrame, policy, flow: Flow | None = None, *, t0, t1, start=START_EQUITY,
        rebate=0.0, rebate_min=0.0, payout_min=0.0, fee_month=0.0, alt_r=None, alt_when=None) -> dict:
    """Compound a $50 account over trades t with sizing `policy` and cash-flow schedule `flow`.

    rebate: $ per oz traded (round turn), credited to the account at the close; a single trade's rebate below
    rebate_min is not paid (PipsbackFX: no sub-cent rebates); with payout_min > 0 rebates accrue and are paid
    in one amount once >= payout_min (HighFxRebates $1). fee_month: $ taken from the account on the first of
    each month (paid VPS). alt_r / alt_when(state): use alt_r for the trade once alt_when has fired (latched),
    e.g. Pro-account costs after a milestone. Sizing is continuous (risk$ = f x equity, size = risk$/per_oz)."""
    r = t["r"].to_numpy(float)
    per_oz = (t["risk"] / t["size_oz"]).to_numpy(float)
    times = list(t["entry_time"])
    t0, t1 = pd.Timestamp(t0, tz="UTC"), pd.Timestamp(t1, tz="UTC")
    eq = peak = float(start)
    withdrawn = deposited = pending = rebates = fees = 0.0
    wealth = float(start)                    # start + cumulative trading P&L (incl. rebates, minus fees)
    w_path, twr, twr_path = [wealth], 1.0, [1.0]
    flows_irr = [(t0, -float(start))]
    r_hist: list[float] = []
    since_peak, switched, latched = 0, 0, False
    ruined = hard = False
    cur_m = t0.year * 12 + t0.month - 1
    ea_start = float(start)                  # the EA's start-balance GV (hard stop, ladder), shifted by cash flows
    if flow is not None:
        flow.reset(float(start))
    for i, ts in enumerate(times):
        m = ts.year * 12 + ts.month - 1
        months = list(range(cur_m + 1, m + 1))
        cur_m = max(cur_m, m)
        if months and fee_month > 0:
            fee = min(eq, fee_month * len(months))
            eq -= fee
            fees += fee
            wealth -= fee
        st = {"equity": eq, "start": float(start), "peak": peak, "withdrawn": withdrawn, "n": len(r_hist),
              "r_hist": r_hist, "last_r": r_hist[-1] if r_hist else 0.0, "trades_since_peak": since_peak,
              "ea_start": ea_start}
        if flow is not None:
            dep, wd = flow(st, months, ts)
            if dep > 0:
                eq += dep
                deposited += dep
                ea_start += dep
                peak += dep
                flows_irr.append((ts, -dep))
            if wd > 0:
                wd = min(wd, eq)
                eq -= wd
                withdrawn += wd
                ea_start -= wd
                peak = max(0.0, peak - wd)
                flows_irr.append((ts, wd))
            if ea_start <= 0:
                ea_start = eq
            st["equity"], st["withdrawn"], st["ea_start"], st["peak"] = eq, withdrawn, ea_start, peak
        if eq < RUIN:
            ruined = True
            break
        f = float(np.clip(policy(st, None), 0.0, MAX_RISK))
        ri = r[i]
        if alt_when is not None and (latched or alt_when(st, per_oz[i])):
            latched = True
            ri = alt_r[i]
            switched += 1
        risk_usd = f * eq
        pnl = risk_usd * ri
        reb = rebate * risk_usd / per_oz[i]
        if reb < rebate_min:
            reb = 0.0
        if payout_min > 0:
            pending += reb
            reb = 0.0
            if pending >= payout_min:
                reb, pending = pending, 0.0
        before = eq
        eq += pnl + reb
        rebates += reb
        wealth += pnl + reb
        twr *= eq / before
        r_hist.append(ri)
        if eq > peak:
            peak, since_peak = eq, 0
        else:
            since_peak += 1
        w_path.append(wealth)
        twr_path.append(twr)
        if eq < HARD_STOP * ea_start:      # the EA's InpHardStopPct=30 vs its (flow-shifted) start balance
            hard = True
        if eq < RUIN:
            ruined = True
            break
    end_t = min(t1, pd.Timestamp("2026-09-26", tz="UTC"))
    contributed = float(start) + deposited
    total = eq + withdrawn
    if isinstance(flow, DCAOnSignal):        # committed cash counts as contributed; unused bank is returned
        flows_irr = [(t0, -float(start))] + [(ts, -a) for ts, a in flow.committed] + \
                    [x for x in flows_irr[1:] if x[1] > 0]
        contributed = float(start) + sum(a for _, a in flow.committed)
        total += flow.bank
    flows_irr.append((end_t, total if isinstance(flow, DCAOnSignal) else eq))
    wp, tp = np.array(w_path), np.array(twr_path)
    wpk, tpk = np.maximum.accumulate(wp), np.maximum.accumulate(tp)
    return {"final_equity": round(eq, 2), "withdrawn": round(withdrawn, 2), "deposited": round(deposited, 2),
            "contributed": round(contributed, 2), "total": round(total, 2),
            "wealth": round(total - contributed + start, 2),       # $50 + net trading gain
            "net": round(total - contributed, 2), "irr": irr(flows_irr), "irr_pct": round(100 * irr(flows_irr), 1),
            "worst_net": round(float(wp.min()) - start, 2),          # worst cumulative trading P&L in $
            "dd_wealth": round(float(((wpk - wp) / np.maximum(wpk, 1e-9)).max() * 100), 1),
            "dd_twr": round(float(((tpk - tp) / tpk).max() * 100), 1),
            "ruined": ruined, "hard_stop": hard, "rebates": round(rebates, 2), "fees": round(fees, 2),
            "trades": len(w_path) - 1, "switched": switched}


def evaluate(t, make_policy, make_flow=None, keys=None, **kw) -> dict:
    keys = keys or list(SPANS)
    out = {}
    for k in keys:
        s, e = SPANS[k]
        out[k] = run(_slice(t, s, e), make_policy(), make_flow() if make_flow else None, t0=s, t1=e, **kw)
    if all(k in out for k in VAL_KEYS):
        out["val_sum"] = round(sum(out[k]["wealth"] for k in VAL_KEYS), 2)
    return out


def avg_r(t, rebate=0.0):
    per_oz = (t["risk"] / t["size_oz"]).to_numpy(float)
    rr = t["r"].to_numpy(float) + rebate / per_oz
    out = {}
    for k, (s, e) in SPANS.items():
        m = ((t["entry_time"] >= pd.Timestamp(s, tz="UTC")) & (t["entry_time"] < pd.Timestamp(e, tz="UTC"))).to_numpy()
        out[k] = float(rr[m].mean())
    return out


# ---------------------------------------------------------------- account-side scenarios (not tuned)
# swap %/yr, spread+slippage stress, rebate $/oz, rebate_min, payout_min. Spread model at stress 1:
# max($0.25, 0.8 bp x price) (= $0.25 until gold > $3125, ~$0.34 at $4200 = HFM Cent's live $0.34-0.36).

COST_SCEN = [
    # name, swap, stress, rebate, rebate_min, payout_min, note
    ("HFM Cent today (baseline)", 5.0, 1.0, 0.0, 0.0, 0.0, "swap 5%/yr, model spread ~= HFM Cent"),
    ("swap-free only", 0.0, 1.0, 0.0, 0.0, 0.0, "Exness auto swap-free for Indonesia, same spread"),
    ("swap 2.5%/yr (sensitivity)", 2.5, 1.0, 0.0, 0.0, 0.0, "if the broker's real swap is half the model's"),
    ("swap 8%/yr (sensitivity)", 8.0, 1.0, 0.0, 0.0, 0.0, "if the real swap is higher (2023-25 USD rates)"),
    ("spread x0.75 only", 5.0, 0.75, 0.0, 0.0, 0.0, "~$0.25 vs $0.34 (Exness Std Cent estimate)"),
    ("spread x0.6 only", 5.0, 0.6, 0.0, 0.0, 0.0, "~$0.20 (optimistic)"),
    ("spread x1.3", 5.0, 1.3, 0.0, 0.0, 0.0, "worse broker / news fills"),
    ("HFM + rebate $0.12/oz (theory)", 5.0, 1.0, 0.12, 0.0, 0.0, "paid on every trade, no minimum"),
    ("HFM + rebate $0.12/oz, no sub-cent", 5.0, 1.0, 0.12, 0.01, 0.0, "PipsbackFX rule: < $0.01 not paid"),
    ("HFM + rebate $0.12/oz, $1 payout", 5.0, 1.0, 0.12, 0.0, 1.0, "HighFxRebates: accrue, pay at >= $1"),
    ("Exness swap-free x0.75", 0.0, 0.75, 0.0, 0.0, 0.0, "central Exness Standard Cent case"),
    ("Exness swap-free x0.75 + rebate $0.06/oz no sub-cent", 0.0, 0.75, 0.06, 0.01, 0.0, "FXPayback $0.05-0.07"),
    ("Exness swap-free x0.6", 0.0, 0.6, 0.0, 0.0, 0.0, "optimistic"),
    ("Exness, swap-free revoked x0.75", 5.0, 0.75, 0.0, 0.0, 0.0, "downside: status removed"),
]


def cost_scenarios(bases=("fixed3", "ladder", "C_W60")):
    rows = []
    for name, swap, stress, reb, rmin, pmin, note in COST_SCEN:
        t = get_trades(swap=swap, stress=stress)
        row = {"name": name, "note": note, "avg_r": avg_r(t, reb), "n": len(t)}
        for b in bases:
            row[b] = evaluate(t, BASES[b], rebate=reb, rebate_min=rmin, payout_min=pmin)
        rows.append(row)
    return rows


def vps_and_graduation():
    """Paid VPS ($12/month from the account) and graduating to a Pro account (spread x0.7 vs Standard Cent's
    x0.75 -> about 0.52 of HFM; latched once equity >= 100 x the 1-oz stop risk, i.e. 1 oz <= 1% risk)."""
    base = get_trades()
    out = {}
    for b in ("fixed3", "ladder", "C_W60"):
        out[("VPS $12/month from the account", b)] = evaluate(base, BASES[b], fee_month=12.0)
        out[("VPS $5/month from the account", b)] = evaluate(base, BASES[b], fee_month=5.0)
    ex = get_trades(swap=0.0, stress=0.75)
    pro = get_trades(swap=0.0, stress=0.52)
    alt = ex[["entry_time"]].merge(pro[["entry_time", "r"]], on="entry_time", how="left")["r"].fillna(
        pd.Series(ex["r"].to_numpy())).to_numpy()
    for b in ("fixed3", "ladder", "C_W60"):
        out[("Exness x0.75 -> Pro x0.52 at equity >= 100 x stop", b)] = evaluate(
            ex, BASES[b], alt_r=alt, alt_when=lambda st, po: st["equity"] >= 100 * po)
    return out


# ---------------------------------------------------------------- dev grid of cash-flow schedules

def build_dev_grid():
    G = []

    def add(name, family, rule, make_flow, base, make_policy=None):
        G.append(dict(name=name, family=family, rule=rule, make_flow=make_flow, base=base,
                      make_policy=make_policy or BASES[base]))

    for base in ("fixed3", "ladder"):
        # W: withdrawals
        for k, x in ((2.0, 0.5), (2.0, 1 / 3), (1.5, 1 / 3), (3.0, 0.5)):
            add(f"W take {x:.0%} at each {k:g}x [{base}]", "W", f"equity >= {k:g} x base: withdraw {x:.0%}, rebase",
                lambda k=k, x=x: WithdrawAtMultiple(k, x), base)
        for k in (2.0, 3.0):
            add(f"W free-roll $50 at {k:g}x [{base}]", "W", f"once at {k:g}x start: withdraw $50",
                lambda k=k: FreeRoll(k), base)
        mp, mf = barbell(BASES[base], 3.0, 0.05)
        add(f"W barbell 3x then 5% [{base}]", "W", "once at 3x: withdraw $50, then 5% risk", mf, base, mp)
        for s, every, lab in ((1.0, 1, "monthly 100%"), (0.5, 1, "monthly 50%"), (0.5, 3, "quarterly 50%"),
                              (0.5, 12, "annual 50%")):
            add(f"W sweep {lab} [{base}]", "W", f"{lab} of equity above $50",
                lambda s=s, every=every: Sweep(s, every), base)
        # D: deposits
        for a in (10.0, 5.0):
            add(f"D DCA ${a:g}/month [{base}]", "D", f"+${a:g} on the 1st of each month", lambda a=a: DCA(a), base)
        add(f"D refill to $50 (<=$10/mo) [{base}]", "D", "if equity < $50 on the 1st: top up, max $10",
            lambda: Refill(10.0), base)
        add(f"D DCA $10 timed by cumR>MA20 [{base}]", "D", "$10/month set aside, deposited when cumR > MA20",
            lambda: DCAOnSignal(10.0, 20), base)
    return G


def pick_finalists(rows, refs):
    """Coded before any validation run. Per base and family: the best-dev combo that beats its base on dev
    wealth (deposit family: also IRR >= the base's dev IRR) and is not ruined. Plus two fixed references that
    are run regardless: 'W take 50% at each 2x' (the schedule tested before) and 'D DCA $10/month'."""
    fins = []
    for base in ("fixed3", "ladder"):
        ref = refs[base]
        for fam in ("W", "D"):
            ok = [r for r in rows if r["base"] == base and r["family"] == fam and not r["dev"]["ruined"]
                  and r["dev"]["wealth"] > ref["wealth"]
                  and (fam == "W" or r["dev"]["irr"] >= ref["irr"])]
            if ok:
                fins.append(max(ok, key=lambda r: r["dev"]["wealth"])["name"])
        for fixed_ref in (f"W take 50% at each 2x [{base}]", f"D DCA $10/month [{base}]"):
            if fixed_ref not in fins:
                fins.append(fixed_ref)
    return fins


# ---------------------------------------------------------------- block bootstrap (dev trades only)

_BOOT = {}


def _boot_job(args):
    seed, n, block = args
    t, grid = _BOOT["t"], _BOOT["grid"]
    rng = np.random.default_rng(seed)
    r0, po0 = t["r"].to_numpy(float), (t["risk"] / t["size_oz"]).to_numpy(float)
    N = len(t)
    res = {g["name"]: [] for g in grid}
    for _ in range(n):
        nb = math.ceil(N / block)
        idx = ((rng.integers(0, N, nb)[:, None] + np.arange(block)[None, :]) % N).ravel()[:N]
        tb = t.copy()
        tb["r"] = r0[idx]
        tb["risk"] = po0[idx]
        tb["size_oz"] = 1.0
        s, e = SPANS[DEV_KEY]
        for g in grid:
            o = run(tb, g["make_policy"](), g["make_flow"]() if g["make_flow"] else None, t0=s, t1=e)
            res[g["name"]].append((o["wealth"], o["ruined"], o["hard_stop"], o["withdrawn"], o["deposited"]))
    return res


def bootstrap(t_dev, grid, paths=1000, block=20):
    """Dev trades resampled in blocks of 20 (entry times kept), each path from a fresh $50."""
    _BOOT["t"], _BOOT["grid"] = t_dev.reset_index(drop=True), grid
    jobs = [(SEED + i, paths // 4, block) for i in range(4)]
    with ProcessPoolExecutor(4, mp_context=mp.get_context("fork")) as ex:  # fork: the grid holds lambdas
        parts = list(ex.map(_boot_job, jobs))
    out = {}
    for g in grid:
        a = np.array([x for p in parts for x in p[g["name"]]], dtype=float)
        out[g["name"]] = {"median": float(np.median(a[:, 0])), "p10": float(np.percentile(a[:, 0], 10)),
                          "p90": float(np.percentile(a[:, 0], 90)), "mean": float(a[:, 0].mean()),
                          "p_hard": float(a[:, 2].mean()), "p_ruin": float(a[:, 1].mean()),
                          "med_banked": float(np.median(a[:, 3])), "med_deposited": float(np.median(a[:, 4])),
                          "w": a[:, 0]}  # same paths, same order for every schedule (paired)
    return out


# ---------------------------------------------------------------- printing

def f2(x):
    return f"{x:.2f}"


def dd_w(d):
    """Wealth DD is only meaningful without deposits (with deposits $50 + P&L can go below 0)."""
    return "n/a" if d["contributed"] > START_EQUITY else f"{d['dd_wealth']}%"


def per_line(res, key="wealth"):
    return " | ".join(f2(res[k][key]) for k in (DEV_KEY,) + VAL_KEYS)


def main(dev_only=False):
    base_t = get_trades()
    # self-check: run() without flows reproduces mm_sim.simulate
    for b in BASES:
        for k, (s, e) in SPANS.items():
            a = run(_slice(base_t, s, e), BASES[b](), t0=s, t1=e)["total"]
            c = simulate(_slice(base_t, s, e), BASES[b]())["total"]
            assert abs(a - c) < 0.02, (b, k, a, c)

    # ---- dev grid (cash-flow schedules), dev only
    dev_t = _slice(base_t, *SPANS[DEV_KEY])
    s, e = SPANS[DEV_KEY]
    refs = {b: run(dev_t, BASES[b](), t0=s, t1=e) for b in ("fixed3", "ladder")}
    grid = build_dev_grid()
    rows = []
    for g in grid:
        rows.append({**g, "dev": run(dev_t, g["make_policy"](), g["make_flow"](), t0=s, t1=e)})
    print(f"## Dev grid: cash-flow schedules ({len(grid)} combos, dev 2013-19 only)")
    print("| schedule | base | dev wealth ($50+net) | equity | withdrawn | deposited | IRR %/yr | wealth DD | "
          "worst net $ | acct DD (TWR) | hit -30% | ruined |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for b in ("fixed3", "ladder"):
        r = refs[b]
        print(f"| REF no flows | {BASE_LABEL[b]} | {f2(r['wealth'])} | {f2(r['final_equity'])} | 0 | 0 | "
              f"{r['irr_pct']} | {dd_w(r)} | {f2(r['worst_net'])} | {r['dd_twr']}% | "
              f"{'yes' if r['hard_stop'] else 'no'} | no |")
        for x in rows:
            if x["base"] != b:
                continue
            d = x["dev"]
            print(f"| {x['name'].split(' [')[0]} | {BASE_LABEL[b]} | {f2(d['wealth'])} | {f2(d['final_equity'])} | "
                  f"{f2(d['withdrawn'])} | {f2(d['deposited'])} | {d['irr_pct']} | {dd_w(d)} | "
                  f"{f2(d['worst_net'])} | {d['dd_twr']}% | {'yes' if d['hard_stop'] else 'no'} | "
                  f"{'YES' if d['ruined'] else 'no'} |")
    fins = pick_finalists(rows, refs)
    print("\nFinalists (pick_finalists, dev only):", fins)
    if dev_only:
        return

    # ---- dev bootstrap of the finalists vs their bases (dev trades only)
    bgrid = [dict(name=f"REF {BASE_LABEL[b]}", make_policy=BASES[b], make_flow=None) for b in ("fixed3", "ladder")]
    bgrid += [dict(name=x["name"], make_policy=x["make_policy"], make_flow=x["make_flow"]) for x in rows
              if x["name"] in fins]
    boot = bootstrap(dev_t, bgrid)
    print("\n## Dev block bootstrap (block 20 trades, 1000 paths, fresh $50, wealth = $50 + net gain)")
    print("| schedule | median | mean | P10 | P90 | P(beats its base, same path) | P(hit -30% hard stop) | P(ruin) "
          "| median withdrawn | median deposited |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for g in bgrid:
        o = boot[g["name"]]
        bname = "REF fixed 3%" if g["name"].endswith("[fixed3]") else "REF ladder 5/3/2" if \
            g["name"].endswith("[ladder]") else None
        pb = f"{(o['w'] > boot[bname]['w']).mean()*100:.0f}%" if bname else "-"
        print(f"| {g['name']} | {o['median']:.1f} | {o['mean']:.1f} | {o['p10']:.1f} | {o['p90']:.1f} | {pb} | "
              f"{o['p_hard']*100:.0f}% | {o['p_ruin']*100:.1f}% | {o['med_banked']:.1f} | {o['med_deposited']:.1f} |")

    # ---- validation, once per finalist (plus the two references)
    print("\n## Final table: cash-flow schedules (validation run once; wealth = $50 + net trading gain)")
    print("better = beats fixed 3% on dev wealth and on the validation sum, never ruined; deposit schedules must "
          "also have an IRR >= fixed 3%'s on dev and on all 2013-26 (otherwise they only add capital).")
    print("| schedule | base | dev | 2020-21 | 2022-25 | 2026 | val sum | all 2013-26 | all: equity / withdrawn / "
          "deposited | IRR %/yr dev / 20-21 / 22-25 / 26 / all | wealth DD all | worst net $ all | acct DD (TWR) all "
          "| hit -30% (periods) | ruined | better | beats ladder |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    final = {}
    for b in ("fixed3", "ladder"):
        final[f"REF {b}"] = evaluate(base_t, BASES[b])
    ref3, refl = final["REF fixed3"], final["REF ladder"]
    for name in ["REF fixed3", "REF ladder"] + fins:
        fam = "REF"
        if name.startswith("REF"):
            b = name.split()[1]
            res, lab, sched = final[name], BASE_LABEL[b], "REF no flows"
        else:
            x = next(r for r in rows if r["name"] == name)
            res = evaluate(base_t, x["make_policy"], x["make_flow"])
            final[name], lab, sched, fam = res, BASE_LABEL[x["base"]], name.split(" [")[0], x["family"]
        a = res[ALL_KEY]
        hs = ",".join(k.replace("val_", "").replace("dev_2013_2019", "dev") for k in (DEV_KEY,) + VAL_KEYS
                      if res[k]["hard_stop"]) or "never"
        ruined = any(res[k]["ruined"] for k in SPANS)
        better = beats_l = None
        if fam != "REF":
            better = (res[DEV_KEY]["wealth"] > ref3[DEV_KEY]["wealth"] and res["val_sum"] > ref3["val_sum"]
                      and not ruined)
            beats_l = res[DEV_KEY]["wealth"] > refl[DEV_KEY]["wealth"] and res["val_sum"] > refl["val_sum"]
            if fam == "D":
                better = better and res[DEV_KEY]["irr"] >= ref3[DEV_KEY]["irr"] and a["irr"] >= ref3[ALL_KEY]["irr"]
                beats_l = beats_l and res[DEV_KEY]["irr"] >= refl[DEV_KEY]["irr"] and a["irr"] >= refl[ALL_KEY]["irr"]
        res["_better"], res["_beats_ladder"], res["_label"] = better, beats_l, f"{sched} [{lab}]"
        irrs = " / ".join(f"{res[k]['irr_pct']:g}" for k in (DEV_KEY,) + VAL_KEYS + (ALL_KEY,))
        yn = lambda v: "-" if v is None else ("yes" if v else "no")  # noqa: E731
        print(f"| {sched} | {lab} | {per_line(res)} | {f2(res['val_sum'])} | {f2(a['wealth'])} | "
              f"{f2(a['final_equity'])} / {f2(a['withdrawn'])} / {f2(a['deposited'])} | {irrs} | "
              f"{dd_w(a)} | {f2(a['worst_net'])} | {a['dd_twr']}% | {hs} | {'YES' if ruined else 'no'} | "
              f"{yn(better)} | {yn(beats_l)} |")

    # ---- account-side scenarios (not tuned; all periods)
    sc = cost_scenarios()
    print("\n## Account side: average R per trade (same signals, re-run with each cost set)")
    print("| scenario | n | dev | 2020-21 | 2022-25 | 2026 | all | change vs baseline (all) | note |")
    print("|---|---|---|---|---|---|---|---|---|")
    b0 = sc[0]["avg_r"][ALL_KEY]
    for x in sc:
        ar = x["avg_r"]
        print(f"| {x['name']} | {x['n']} | " + " | ".join(f"{ar[k]:+.3f}" for k in (DEV_KEY,) + VAL_KEYS + (ALL_KEY,))
              + f" | {ar[ALL_KEY]-b0:+.4f} | {x['note']} |")
    for b in ("fixed3", "ladder", "C_W60"):
        print(f"\n## Account side in $ - {BASE_LABEL[b]} (fresh $50 per period; rebates with their payout rules)")
        print("| scenario | dev | 2020-21 | 2022-25 | 2026 | val sum | all 2013-26 | max DD all | rebates paid (all) "
              "| ruined |")
        print("|---|---|---|---|---|---|---|---|---|---|")
        for x in sc:
            res = x[b]
            print(f"| {x['name']} | {per_line(res, 'total')} | {f2(res['val_sum'])} | {f2(res[ALL_KEY]['total'])} | "
                  f"{res[ALL_KEY]['dd_twr']}% | {f2(res[ALL_KEY]['rebates'])} | "
                  f"{'YES' if any(res[k]['ruined'] for k in SPANS) else 'no'} |")
    vg = vps_and_graduation()
    print("\n## VPS fee and account graduation")
    print("| scenario | base | dev | 2020-21 | 2022-25 | 2026 | all 2013-26 | fees paid (all) | ruined in | "
          "trades after switch (all) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for (name, b), res in vg.items():
        rk = ",".join(k for k in SPANS if res[k]["ruined"]) or "-"
        print(f"| {name} | {BASE_LABEL[b]} | {per_line(res, 'total')} | {f2(res[ALL_KEY]['total'])} | "
              f"{f2(res[ALL_KEY]['fees'])} | {rk} | {res[ALL_KEY]['switched']} |")

    # ---- what a rebate is worth in $ at the account's real size
    t = get_trades()
    po = (t["risk"] / t["size_oz"]).to_numpy(float)
    for eq in (50.0, 200.0, 1000.0):
        oz = 0.03 * eq / po
        print(f"\nAt equity ${eq:g} and 3% risk: median size {np.median(oz):.3f} oz (= cent-account lots), rebate "
              f"per trade at $0.12/oz: median ${np.median(oz)*0.12:.4f}, at $0.06/oz: ${np.median(oz)*0.06:.4f}; "
              f"share of trades with a rebate >= $0.01 at $0.06/oz: {(oz*0.06 >= 0.01).mean()*100:.0f}%")


if __name__ == "__main__":
    main(dev_only="--dev-only" in sys.argv)
