"""Conviction / signal-quality sizing and volatility targeting for the gold swing EA (cluster study).

Question: can the EA put more risk on "better" setups and less on "worse" ones, using only what is known
when the trade opens (entry-time features of the gold bars + the EA's own closed-trade history), and so
beat fixed 3% risk on dev 2013-19 AND on the validation periods?

Protocol (results/MM_RESEARCH_PLAN.md): features, gates and policy grid are tuned on dev 2013-2019 only;
the frozen candidates are run once on every period. Log: results/mm_conviction.md.

    python scripts/mm_conviction.py              # full run: dev screen, dev grid, final table, validation check
    python scripts/mm_conviction.py --stage dev  # dev-only output (what was used to choose the candidates)

Every feature is MQL5-implementable: it uses completed H1/H4/D1 bars at the signal bar's close (iMA, iRSI,
iATR, iHigh/iLow, CopyBuffer) or the EA's own closed deals. Thresholds are constants fixed from dev.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.data import resample  # noqa: E402
from backtest.indicators import atr, ema, rsi  # noqa: E402
from mm_sim import PERIODS, _bars, evaluate_policy, fixed, get_trades, ladder, simulate  # noqa: E402

DEV_END = pd.Timestamp("2020-01-01", tz="UTC")
DEV_MID = pd.Timestamp("2016-07-01", tz="UTC")   # dev halves: 2013-2016H1 and 2016H2-2019
BASE = 0.03                                       # fixed-3% reference; conviction multiplies it
COMBOS: list[str] = []                            # every policy evaluated on dev (combo count)


# ------------------------------------------------------------------------------------------ features

def entry_features(t: pd.DataFrame, m1: pd.DataFrame) -> pd.DataFrame:
    """Features of each trade known at its signal bar's close (no outcome information).

    Signs are oriented by the trade direction d (+1 long, -1 short), so 'higher' means 'more in the trade
    direction' for the trend features.
    """
    d = t["direction"].to_numpy()
    close_t = t["entry_time"].dt.floor("h")                       # signal H1 bar close = fill hour
    ct = pd.DatetimeIndex(close_t).as_unit("ns").asi8

    # H1 (entry timeframe)
    eb = resample(m1, "1h")
    e_close_ns = (eb.index + pd.Timedelta("1h")).asi8
    i1 = np.searchsorted(e_close_ns, ct, side="right") - 1        # last completed H1 bar = signal bar
    c1, h1, l1 = (eb[k].to_numpy() for k in ("close", "high", "low"))
    r1 = rsi(c1, 14)
    lo10 = pd.Series(r1).rolling(10).min().to_numpy()             # RSI extreme over the last 10 H1 bars
    hi10 = pd.Series(r1).rolling(10).max().to_numpy()
    hh20 = pd.Series(h1).rolling(20).max().to_numpy()
    ll20 = pd.Series(l1).rolling(20).min().to_numpy()

    # H4 (trend + ATR yardstick, exactly as the EA)
    ht = resample(m1, "4h")
    h_close_ns = (ht.index + pd.Timedelta("4h")).asi8
    i4 = np.searchsorted(h_close_ns, ct, side="right") - 1
    hc = ht["close"].to_numpy()
    he = ema(hc, 40)
    a4 = atr(ht["high"], ht["low"], ht["close"], 14)
    up = (hc > he) & (he > np.roll(he, 6))
    dn = (hc < he) & (he < np.roll(he, 6))
    state = up.astype(int) - dn.astype(int)
    # consecutive H4 bars in the current trend state (trend age)
    age = np.zeros(len(state), dtype=int)
    for k in range(1, len(state)):
        age[k] = age[k - 1] + 1 if (state[k] == state[k - 1] and state[k] != 0) else (1 if state[k] != 0 else 0)
    a4s = pd.Series(a4)
    atr_pct500 = a4s.rolling(500, min_periods=100).rank(pct=True).to_numpy()          # ATR percentile over ~3 months of H4
    vr120 = (a4s / a4s.rolling(120).median()).to_numpy()             # ATR vs its 120-bar median

    # D1
    dt_ = resample(m1, "1D")
    d_close_ns = (dt_.index + pd.Timedelta("1D")).asi8
    i_d = np.searchsorted(d_close_ns, ct, side="right") - 1
    dc = dt_["close"].to_numpy()
    de = ema(dc, 20)
    ad = atr(dt_["high"], dt_["low"], dt_["close"], 14)

    et = t["entry_time"]
    days_to_fri = (4 - et.dt.dayofweek) % 7
    fri = et.dt.normalize() + pd.to_timedelta(days_to_fri, unit="D") + pd.Timedelta(hours=20)
    hours_avail = np.minimum(72.0, (fri - et).dt.total_seconds().to_numpy() / 3600)

    prev_r = np.r_[np.nan, t["r"].to_numpy()[:-1]]                 # EA's last closed trade (all closed first)

    f = pd.DataFrame({
        "trend_dist": d * (hc[i4] - he[i4]) / a4[i4],               # H4 close beyond EMA40, in ATR
        "trend_slope": d * (he[i4] - he[i4 - 6]) / a4[i4],          # EMA40 6-bar slope, in ATR
        "trend_age": age[i4],                                       # H4 bars since the trend state began
        "rsi_depth": np.where(d > 0, 40 - lo10[i1], hi10[i1] - 60), # how far RSI(H1) pulled back below 40
        "pb_depth": np.where(d > 0, hh20[i1] - c1[i1], c1[i1] - ll20[i1]) / a4[i4],  # pullback from 20-bar extreme, ATR
        "atr_pct": atr_pct500[i4],                                  # ATR(H4) percentile, 500 H4 bars
        "vol_ratio": vr120[i4],                                     # ATR(H4) / 120-bar median
        "d1_dist": d * (dc[i_d] - de[i_d]) / ad[i_d],               # D1 close beyond D1 EMA20, in D1 ATR
        "hours_avail": hours_avail,                                 # hours until the 72h cap / Friday close
        "entry_hour": et.dt.hour.to_numpy().astype(float),
        "prev_r": prev_r,
        "is_long": (d > 0).astype(float),
    }, index=t.index)
    return f


FEATURES = ["trend_dist", "trend_slope", "trend_age", "rsi_depth", "pb_depth", "atr_pct", "vol_ratio",
            "d1_dist", "hours_avail", "entry_hour", "prev_r", "is_long"]


# --------------------------------------------------------------------------------- stage 1: dev screen

def dev_cuts(f: pd.DataFrame, dev: pd.Series) -> dict[str, tuple[float, float]]:
    """Tercile cut points of each feature on dev trades (frozen constants for the EA)."""
    out = {}
    for k in FEATURES:
        x = f.loc[dev, k].dropna()
        if k == "is_long":
            out[k] = (0.5, 0.5)
        elif k == "hours_avail":     # >1/3 of trades have the full 72h: buckets <=48h / 48-72h / full 72h
            out[k] = (48.0, 71.99)
        else:
            out[k] = (float(x.quantile(1 / 3)), float(x.quantile(2 / 3)))
    return out


def bucket(x: np.ndarray, cuts: tuple[float, float]) -> np.ndarray:
    """0 = bottom tercile, 1 = mid, 2 = top (NaN -> mid)."""
    b = np.where(x <= cuts[0], 0, np.where(x <= cuts[1], 1, 2))
    if cuts[0] == cuts[1]:          # binary feature
        b = np.where(x > cuts[0], 2, 0)
    return np.where(np.isnan(x), 1, b)


def tercile_table(f, r, mask, cuts) -> pd.DataFrame:
    rows = []
    for k in FEATURES:
        b = bucket(f.loc[mask, k].to_numpy(), cuts[k])
        rr = r[mask].to_numpy()
        m = [rr[b == j].mean() if (b == j).any() else np.nan for j in (0, 1, 2)]
        n = [(b == j).sum() for j in (0, 1, 2)]
        rows.append({"feature": k, "bot": m[0], "mid": m[1], "top": m[2], "top-bot": m[2] - m[0],
                     "n": "/".join(map(str, n))})
    return pd.DataFrame(rows).set_index("feature")


def monotone(row) -> int:
    """+1 if bot < mid < top, -1 if bot > mid > top, else 0 (binary features: sign of top-bot)."""
    if np.isnan(row["mid"]):
        return int(np.sign(row["top-bot"]))
    if row["bot"] < row["mid"] < row["top"]:
        return 1
    if row["bot"] > row["mid"] > row["top"]:
        return -1
    return 0


def screen(f, t, cuts) -> pd.DataFrame:
    """Pre-registered gate: tercile ordering monotone, same direction, in BOTH dev halves.
    Near-pass: top-bot same sign in both halves and |top-bot| >= 0.15R on full dev."""
    et, r = t["entry_time"], t["r"]
    full = tercile_table(f, r, et < DEV_END, cuts)
    h1 = tercile_table(f, r, et < DEV_MID, cuts)
    h2 = tercile_table(f, r, (et >= DEV_MID) & (et < DEV_END), cuts)
    out = full[["bot", "mid", "top", "top-bot", "n"]].copy()
    out["h1 top-bot"] = h1["top-bot"]
    out["h2 top-bot"] = h2["top-bot"]
    out["mono_h1"] = h1.apply(monotone, axis=1)
    out["mono_h2"] = h2.apply(monotone, axis=1)
    same = np.sign(out["h1 top-bot"]) == np.sign(out["h2 top-bot"])
    out["gate"] = np.where((out["mono_h1"] == out["mono_h2"]) & (out["mono_h1"] != 0), "PASS",
                           np.where(same & (out["top-bot"].abs() >= 0.15), "near", "-"))
    out["sign"] = np.sign(out["top-bot"].fillna(0)).astype(int)
    return out


def add_vol_rank(t: pd.DataFrame, f: pd.DataFrame, lookback: int = 100) -> pd.Series:
    """Percentile of this trade's stop distance in % of price (= 2 ATR(H4) / price) among the EA's previous
    `lookback` trades (from the EA's own deal history; 0.5 when fewer than 20 exist)."""
    volp = (t["sl_dist"] / t["entry"]).to_numpy()
    out = np.full(len(volp), 0.5)
    for i in range(len(volp)):
        h = volp[max(0, i - lookback):i]
        if len(h) >= 20:
            out[i] = (h < volp[i]).mean()
    return pd.Series(out, index=t.index)


# --------------------------------------------------------------------------------- stage 2: policies

def tier_mult(x: float, cuts, sign: int, hi: float, lo: float) -> float:
    """Favoured tercile -> hi, disfavoured -> lo, middle (or NaN) -> 1. sign>0 favours the top tercile."""
    if x != x:
        return 1.0
    b = 0 if x <= cuts[0] else (1 if x <= cuts[1] else 2)
    fav, dis = (2, 0) if sign > 0 else (0, 2)
    return hi if b == fav else lo if b == dis else 1.0


def p_tier(feat, cuts, sign, hi=1.5, lo=0.5, base=None):
    """Conviction tiers on one feature; base = fixed 3% or a callable(state) (e.g. the ladder)."""
    def pol(st, tr):
        b = BASE if base is None else base(st)
        return b * tier_mult(getattr(tr, feat), cuts[feat], sign, hi, lo)
    return pol


def p_score(feats, cuts, signs, step=0.25, base=None):
    """Additive score: each feature +1 (favoured tercile) / 0 / -1 (disfavoured); mult = 1 + step*score."""
    def pol(st, tr):
        s = 0
        for k, sg in zip(feats, signs):
            m = tier_mult(getattr(tr, k), cuts[k], sg, 2.0, 0.0)   # 2 / 1 / 0  ->  +1 / 0 / -1
            s += m - 1.0
        b = BASE if base is None else base(st)
        return b * (1 + step * s)
    return pol


def p_vol(col, favour="low", power=0.25, lo=0.75, hi=1.25, base=None):
    """Vol-targeting tilt from a percentile rank in [0,1]: favour='low' scales risk up in quiet regimes."""
    def pol(st, tr):
        rk = getattr(tr, col)
        rk = 0.5 if rk != rk else rk
        q = rk if favour == "low" else 1 - rk
        b = BASE if base is None else base(st)
        return b * float(np.clip((0.5 / max(q, 0.05)) ** power, lo, hi))
    return pol


def ladder_base(st):
    e, s = st["equity"], st["start"]
    return 0.05 if e < 2 * s else 0.03 if e < 4 * s else 0.02


def sim_dev(policy, tf: pd.DataFrame) -> dict:
    """Dev only: full dev from $50, both dev halves from a fresh $50 each, and the risk-weighted mean R."""
    et = tf["entry_time"]
    dev = tf[et < DEV_END]
    out = {"dev": simulate(dev, policy), "dev_h1": simulate(tf[et < DEV_MID], policy),
           "dev_h2": simulate(tf[(et >= DEV_MID) & (et < DEV_END)], policy)}
    # risk-weighted edge: mean(mult*R)/mean(mult) with the multiplier seen at a constant $50 state
    st = {"equity": 50.0, "start": 50.0, "peak": 50.0, "withdrawn": 0.0, "n": 0, "r_hist": [], "last_r": 0.0,
          "trades_since_peak": 0}
    m = np.array([policy(st, row) for row in dev.itertuples(index=False)])
    out["wR"] = float((m * dev["r"].to_numpy()).sum() / m.sum())
    out["avg_risk"] = float(m.mean() * 100)
    return out


def dev_grid(tf: pd.DataFrame, cuts: dict, scr: pd.DataFrame) -> dict:
    """The whole dev grid. Conviction features = those passing (or near-passing) the dev screen."""
    cand = [k for k in FEATURES if scr.loc[k, "gate"] in ("PASS", "near") and k != "is_long"]
    sg = {k: int(scr.loc[k, "sign"]) for k in cand}
    pols = {"fixed 3%": fixed(0.03), "ladder 5/3/2": ladder()}
    for k in cand:
        pols[f"tier {k} 1.5/1/0.5"] = p_tier(k, cuts, sg[k])
        pols[f"tier {k} 1.25/1/0.75"] = p_tier(k, cuts, sg[k], 1.25, 0.75)
    if len(cand) >= 2:
        pols[f"score {'+'.join(cand)} step .25"] = p_score(cand, cuts, [sg[k] for k in cand], 0.25)
        pols[f"score {'+'.join(cand)} step .125"] = p_score(cand, cuts, [sg[k] for k in cand], 0.125)
    # volatility targeting (pre-registered from the research list, both signs)
    pols["vol trade-rank favour low ^.25"] = p_vol("vol_rank", "low")
    pols["vol trade-rank favour high ^.25"] = p_vol("vol_rank", "high")
    pols["vol ATR-pct favour low ^.25"] = p_vol("atr_pct", "low")
    pols["vol ATR-pct favour high ^.25"] = p_vol("atr_pct", "high")
    pols["vol ATR-pct favour low ^.5 (0.5-1.5)"] = p_vol("atr_pct", "low", 0.5, 0.5, 1.5)
    pols["vol ATR-pct favour high ^.5 (0.5-1.5)"] = p_vol("atr_pct", "high", 0.5, 0.5, 1.5)
    return pols


def p_rank(feat, dev_values: np.ndarray, sign: int, amp=0.5, base=None):
    """Smooth version of the tiers: mult = 1 + 2*amp*(rank-0.5)*sign, rank = dev empirical CDF of the feature
    (in MQL5: a constant table of dev deciles + linear interpolation)."""
    srt = np.sort(dev_values[~np.isnan(dev_values)])

    def pol(st, tr):
        x = getattr(tr, feat)
        rk = 0.5 if x != x else np.searchsorted(srt, x) / len(srt)
        b = BASE if base is None else base(st)
        return b * (1 + 2 * amp * (rk - 0.5) * sign)
    return pol


def null_check(f: pd.DataFrame, t: pd.DataFrame, cuts: dict, n_perm: int = 2000, seed: int = 7) -> dict:
    """Dev-only selection-bias check: shuffle R across dev trades (features fixed), redo the screen and take
    the best 1.5/1/0.5 tier edge among near-passing features. How often does pure noise look this good?"""
    rng = np.random.default_rng(seed)
    dev = (t["entry_time"] < DEV_END).to_numpy()
    half = (t["entry_time"] < DEV_MID).to_numpy()[dev]
    r = t["r"].to_numpy()[dev]
    feats = [k for k in FEATURES if k != "is_long"]
    B = np.stack([bucket(f[k].to_numpy()[dev], cuts[k]) for k in feats])   # (k, n) tercile ids

    def stats(rr):
        out = []
        for b in B:
            m = lambda msk: np.array([rr[msk & (b == j)].mean() for j in (0, 1, 2)])
            full, h1, h2 = m(np.ones_like(half)), m(half), m(~half)
            mono = lambda v: 1 if v[0] < v[1] < v[2] else (-1 if v[0] > v[1] > v[2] else 0)
            sp, s1, s2 = full[2] - full[0], h1[2] - h1[0], h2[2] - h2[0]
            strict = mono(h1) == mono(h2) != 0
            near = (np.sign(s1) == np.sign(s2)) and abs(sp) >= 0.15
            sg = 1 if sp > 0 else -1
            mult = np.where(b == (2 if sg > 0 else 0), 1.5, np.where(b == (0 if sg > 0 else 2), 0.5, 1.0))
            out.append((strict, near or strict, (mult * rr).sum() / mult.sum()))
        return out

    obs = stats(r)
    obs_best = max([w for s, n, w in obs if n], default=np.nan)
    n_strict, n_near, best = [], [], []
    for _ in range(n_perm):
        st = stats(rng.permutation(r))
        n_strict.append(sum(s for s, _, _ in st))
        n_near.append(sum(n for _, n, _ in st))
        best.append(max([w for s, n, w in st if n], default=-np.inf))
    best = np.array(best)
    return {"obs_strict": sum(s for s, _, _ in obs), "obs_near": sum(n for _, n, _ in obs),
            "null_mean_strict": float(np.mean(n_strict)), "null_mean_near": float(np.mean(n_near)),
            "obs_best_wR": obs_best, "plain_mean_R": float(r.mean()),
            "p_best_wR": float((best >= obs_best).mean())}


# --------------------------------------------------------------------- stage 3: frozen candidates (once)

def final_candidates(tf: pd.DataFrame, cuts: dict) -> dict:
    """Frozen after the dev stage (before any validation number was looked at)."""
    return {
        "fixed 3% (reference)": fixed(0.03),
        "ladder 5/3/2 (reference)": ladder(),
        "C1 tier rsi_depth 1.5/1/0.5": p_tier("rsi_depth", cuts, -1),
        "C2 score trend_age+rsi_depth .25": p_score(["trend_age", "rsi_depth"], cuts, [-1, -1], 0.25),
        "C3 tier trend_age 1.5/1/0.5": p_tier("trend_age", cuts, -1),
        "C4 ladder x tier rsi_depth": p_tier("rsi_depth", cuts, -1, base=ladder_base),
        "C5 vol trade-rank favour high": p_vol("vol_rank", "high"),
    }


def weighted_r(policy, m: pd.DataFrame) -> float:
    st = {"equity": 50.0, "start": 50.0, "peak": 50.0, "withdrawn": 0.0, "n": 0, "r_hist": [], "last_r": 0.0,
          "trades_since_peak": 0}
    w = np.array([policy(st, row) for row in m.itertuples(index=False)])
    return float((w * m["r"].to_numpy()).sum() / w.sum())


def min_equity_pct(policy, m: pd.DataFrame) -> float:
    """Lowest equity seen (before each trade and at the end) as % of the $50 start: below 70% a -30%-from-start
    hard stop (RiskGuard style) would have fired."""
    seen = []

    def spy(st, tr):
        seen.append(st["equity"])
        return policy(st, tr)
    res = simulate(m, spy)
    return float(min(seen + [res["final_equity"]]) / 50.0 * 100)


def val_permutation(f, t, cuts, feat="rsi_depth", sign=-1, n=10000, seed=1) -> dict:
    """Frozen 1.5/1/0.5 tiers on validation trades (2020-2026): risk-weighted mean R vs shuffled R."""
    val = (t["entry_time"] >= pd.Timestamp("2020-01-01", tz="UTC")).to_numpy()
    b = bucket(f[feat].to_numpy(), cuts[feat])
    fav, dis = (2, 0) if sign > 0 else (0, 2)
    mult = np.where(b == fav, 1.5, np.where(b == dis, 0.5, 1.0))[val]
    r = t["r"].to_numpy()[val]
    obs = (mult * r).sum() / mult.sum()
    rng = np.random.default_rng(seed)
    null = np.array([(mult * rng.permutation(r)).sum() / mult.sum() for _ in range(n)])
    x0, x2 = r[b[val] == fav], r[b[val] == dis]
    tstat = (x0.mean() - x2.mean()) / np.sqrt(x0.var(ddof=1) / len(x0) + x2.var(ddof=1) / len(x2))
    return {"wR": obs, "plain": r.mean(), "p": float((null >= obs).mean()), "fav-dis": x0.mean() - x2.mean(),
            "t": tstat, "n_fav": len(x0), "n_dis": len(x2)}


def validation_features(f, t, cuts) -> pd.DataFrame:
    """Does each dev tercile relationship (dev cut points) hold out of sample? top-bot per period."""
    et, r = t["entry_time"], t["r"]
    rows = {}
    for name, (s, e) in {"dev": PERIODS["dev_2013_2019"], "v20_21": PERIODS["val_2020_2021"],
                         "v22_25": PERIODS["val_2022_2025"], "v26": PERIODS["val_2026"],
                         "val_all": ("2020-01-01", "2026-12-31")}.items():
        msk = (et >= pd.Timestamp(s, tz="UTC")) & (et < pd.Timestamp(e, tz="UTC"))
        tt = tercile_table(f, r, msk, cuts)
        rows[name] = tt["top-bot"]
        if name in ("dev", "val_all"):
            for c in ("bot", "mid", "top"):
                rows[f"{name} {c}"] = tt[c]
    out = pd.DataFrame(rows)
    out["holds?"] = np.where(np.sign(out["dev"]) == np.sign(out["val_all"]), "same sign", "FLIPS")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["dev", "all"], default="all")
    ap.add_argument("--perm", type=int, default=2000)
    a = ap.parse_args()
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)

    t = get_trades()
    f = entry_features(t, _bars())
    f["vol_rank"] = add_vol_rank(t, f)
    dev = t["entry_time"] < DEV_END
    cuts = dev_cuts(f, dev)
    tf = pd.concat([t, f], axis=1)

    print(f"trades: {len(t)} (dev {int(dev.sum())}); dev mean R {t.loc[dev, 'r'].mean():+.3f}")
    print("\n== Stage 1 (dev only): tercile screen, dev cut points", {k: tuple(round(x, 3) for x in v) for k, v in cuts.items()})
    scr = screen(f, t, cuts)
    print(scr.round(3).to_string())
    nc = null_check(f, t, cuts, a.perm)
    print(f"\nnull (R shuffled across dev trades, {a.perm}x): strict passes observed {nc['obs_strict']} vs "
          f"{nc['null_mean_strict']:.2f} expected by chance; near/strict {nc['obs_near']} vs {nc['null_mean_near']:.2f}. "
          f"Best near-pass tier edge {nc['obs_best_wR']:+.3f}R (plain {nc['plain_mean_R']:+.3f}R): "
          f"noise does at least as well in {nc['p_best_wR'] * 100:.0f}% of shuffles")

    print("\n== Stage 2 (dev only): policy grid  [$50 start; halves each from a fresh $50; wR = risk-weighted mean R]")
    pols = dev_grid(tf, cuts, scr)
    eb = resample(_bars(), "1h")
    r1 = rsi(eb["close"].to_numpy(), 14)
    ct = pd.DatetimeIndex(t["entry_time"].dt.floor("h")).as_unit("ns").asi8
    i1 = np.searchsorted((eb.index + pd.Timedelta("1h")).asi8, ct, side="right") - 1
    d = t["direction"].to_numpy()
    tf["rsi_depth5"] = np.where(d > 0, 40 - pd.Series(r1).rolling(5).min().to_numpy()[i1],
                                pd.Series(r1).rolling(5).max().to_numpy()[i1] - 60)
    x5 = tf.loc[dev, "rsi_depth5"]
    cuts5 = {**cuts, "rsi_depth5": (float(x5.quantile(1 / 3)), float(x5.quantile(2 / 3)))}
    pols.update({
        "tier rsi_depth5 (5-bar window) 1.5/1/0.5": p_tier("rsi_depth5", cuts5, -1),
        "rank rsi_depth amp .5": p_rank("rsi_depth", f.loc[dev, "rsi_depth"].to_numpy(), -1),
        "rank trend_age amp .5": p_rank("trend_age", f.loc[dev, "trend_age"].to_numpy().astype(float), -1),
        "ladder x tier rsi_depth 1.5/1/0.5": p_tier("rsi_depth", cuts, -1, base=ladder_base),
        "ladder x score step .25": p_score(["trend_age", "rsi_depth"], cuts, [-1, -1], 0.25, base=ladder_base),
    })
    for name, p in pols.items():
        if "fixed" not in name and "ladder 5/3/2" != name:
            COMBOS.append(name)
        o = sim_dev(p, tf)
        print(f"  {name:42s} dev ${o['dev']['total']:7.2f} DD {o['dev']['max_dd_pct']:5.1f}%  "
              f"h1 ${o['dev_h1']['total']:6.2f}  h2 ${o['dev_h2']['total']:6.2f}  wR {o['wR']:+.3f}  avg risk {o['avg_risk']:.2f}%")
    n_feat = len(FEATURES)
    print(f"  dev looks: {n_feat} feature screens + {len(COMBOS)} policy variants = {n_feat + len(COMBOS)}")
    if a.stage == "dev":
        return

    print("\n== Stage 3: frozen candidates, run ONCE on every period (each from a fresh $50; all = 2013-2026 from $50)")
    rows = []
    ref = None
    lad = None
    for name, p in final_candidates(tf, cuts).items():
        ev = evaluate_policy(p, tf)
        wr = {k: weighted_r(p, tf[(tf["entry_time"] >= pd.Timestamp(s, tz="UTC")) & (tf["entry_time"] < pd.Timestamp(e, tz="UTC"))])
              for k, (s, e) in PERIODS.items()}
        row = {"policy": name, "dev": ev["dev_2013_2019"]["total"], "dev DD": ev["dev_2013_2019"]["max_dd_pct"],
               "20-21": ev["val_2020_2021"]["total"], "22-25": ev["val_2022_2025"]["total"], "2026": ev["val_2026"]["total"],
               "val_sum": ev["validation_sum"], "all": ev["all_2013_2026"]["total"],
               "all DD": ev["all_2013_2026"]["max_dd_pct"],
               "maxDD any": max(v["max_dd_pct"] for k, v in ev.items() if isinstance(v, dict)),
               "ruined": any(v["ruined"] for v in ev.values() if isinstance(v, dict)),
               "wR dev": round(wr["dev_2013_2019"], 3), "wR 20-21": round(wr["val_2020_2021"], 3),
               "wR 22-25": round(wr["val_2022_2025"], 3), "wR 26": round(wr["val_2026"], 3),
               "min eq %": round(min([min_equity_pct(p, tf[(tf["entry_time"] >= pd.Timestamp(s, tz="UTC")) &
                                                          (tf["entry_time"] < pd.Timestamp(e, tz="UTC"))])
                                      for s, e in PERIODS.values()] + [min_equity_pct(p, tf)]), 1)}
        if name.startswith("fixed"):
            ref = row
        if name.startswith("ladder"):
            lad = row
        rows.append(row)
    tab = pd.DataFrame(rows).set_index("policy")
    tab["better"] = (tab["dev"] > ref["dev"]) & (tab["val_sum"] > ref["val_sum"]) & ~tab["ruined"]
    tab["beats ladder dev+val"] = (tab["dev"] > lad["dev"]) & (tab["val_sum"] > lad["val_sum"]) & ~tab["ruined"]
    print(tab.to_string())

    print("  (min eq % = lowest equity in any period as % of the $50 start; < 70 means a -30%-from-start hard stop would fire)")
    for feat in ("rsi_depth", "trend_age"):
        vp = val_permutation(f, t, cuts, feat)
        print(f"  {feat} frozen tiers on 2020-2026 trades: risk-weighted R {vp['wR']:+.3f} vs plain {vp['plain']:+.3f}; "
              f"favoured-disfavoured tercile {vp['fav-dis']:+.3f}R (t {vp['t']:.2f}, n {vp['n_fav']}/{vp['n_dis']}); "
              f"one-sided permutation p = {vp['p']:.3f}")

    print("\n== Stage 4: do the dev feature relationships hold out of sample? (top-bot tercile mean R, dev cut points)")
    print(validation_features(f, t, cuts).round(3).to_string())

    print("\n== Stage 5: sensitivity of C1 to its exact form (run AFTER the freeze, not used to choose anything)")
    sens = {"soft tiers rsi_depth 1.25/1/0.75": p_tier("rsi_depth", cuts, -1, 1.25, 0.75),
            "smooth rank rsi_depth amp .5": p_rank("rsi_depth", f.loc[dev, "rsi_depth"].to_numpy(), -1),
            "rsi_depth 5-bar window 1.5/1/0.5": p_tier("rsi_depth5", cuts5, -1),
            "2-level: deep tercile 0.5x, else 1.25x": p_tier("rsi_depth", {"rsi_depth": (cuts["rsi_depth"][1],) * 2},
                                                            -1, 1.25, 0.5)}
    for name, p in sens.items():
        ev = evaluate_policy(p, tf)
        print(f"  {name:40s} dev ${ev['dev_2013_2019']['total']:7.2f}  20-21 ${ev['val_2020_2021']['total']:6.2f}  "
              f"22-25 ${ev['val_2022_2025']['total']:7.2f}  2026 ${ev['val_2026']['total']:6.2f}  val_sum ${ev['validation_sum']:7.2f}  "
              f"all ${ev['all_2013_2026']['total']:7.2f} (DD {ev['all_2013_2026']['max_dd_pct']}%)")


if __name__ == "__main__":
    main()
