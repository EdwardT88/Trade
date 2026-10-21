"""Monte Carlo on a strategy's R-multiples: how likely is the account to hit the hard stop?

Two resampling schemes:
- "trade": i.i.d. bootstrap of individual trade R-multiples
- "day":   bootstrap of whole trading days (keeps intraday clustering of wins/losses)

Each path compounds with the same sizing rules as the EA: risk_pct of current equity,
reduced_risk_pct while equity is more than dd_reduce_pct below its peak, hard stop at
hard_stop_equity (path is frozen there = "ruin").
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import Result, RiskConfig


def _paths(day_rs: list[np.ndarray], n_days: int, n_paths: int, risk: RiskConfig, rng: np.random.Generator):
    finals = np.empty(n_paths)
    max_dds = np.empty(n_paths)
    ruined = np.zeros(n_paths, dtype=bool)
    picks = rng.integers(0, len(day_rs), size=(n_paths, n_days))
    for p in range(n_paths):
        eq = peak = risk.initial_equity
        mdd = 0.0
        for d in picks[p]:
            for r in day_rs[d]:
                rp = risk.reduced_risk_pct if eq < peak * (1 - risk.dd_reduce_pct / 100) else risk.risk_pct
                eq += eq * rp / 100 * r
                peak = max(peak, eq)
                mdd = max(mdd, 1 - eq / peak)
                if eq <= risk.hard_stop_equity:
                    ruined[p] = True
                    break
            if ruined[p]:
                break
        finals[p] = eq
        max_dds[p] = mdd * 100
    return finals, max_dds, ruined


def monte_carlo(res: Result, months: int = 6, n_paths: int = 5000, scheme: str = "day", seed: int = 7) -> dict:
    t = res.trades
    if t.empty:
        return {}
    rng = np.random.default_rng(seed)
    risk = res.risk
    span_days = max((t["exit_time"].iloc[-1] - t["entry_time"].iloc[0]).days, 1)
    if scheme == "day":
        groups = t.groupby(t["entry_time"].dt.floor("D"))["r"].apply(lambda s: s.to_numpy())
        # include flat trading days so the trade frequency is preserved
        bdays = len(pd.bdate_range(t["entry_time"].iloc[0].floor("D"), t["exit_time"].iloc[-1].floor("D")))
        day_rs = list(groups.to_numpy()) + [np.zeros(0)] * max(bdays - len(groups), 0)
        n_days = int(round(months * 21.7))
    else:
        day_rs = [np.array([r]) for r in t["r"].to_numpy()]
        n_days = int(round(len(t) / span_days * 30.44 * months))
    finals, mdds, ruined = _paths(day_rs, n_days, n_paths, risk, rng)
    init = risk.initial_equity
    return {
        "scheme": scheme,
        "months": months,
        "paths": n_paths,
        "p_hit_hard_stop_pct": round(float(ruined.mean()) * 100, 2),
        "p_profit_pct": round(float((finals > init).mean()) * 100, 1),
        "p_double_pct": round(float((finals >= 2 * init).mean()) * 100, 1),
        "final_equity_p5": round(float(np.percentile(finals, 5)), 2),
        "final_equity_p25": round(float(np.percentile(finals, 25)), 2),
        "final_equity_median": round(float(np.median(finals)), 2),
        "final_equity_p75": round(float(np.percentile(finals, 75)), 2),
        "final_equity_p95": round(float(np.percentile(finals, 95)), 2),
        "max_dd_median_pct": round(float(np.median(mdds)), 1),
        "max_dd_p95_pct": round(float(np.percentile(mdds, 95)), 1),
    }
