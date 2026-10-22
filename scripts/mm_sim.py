"""Shared money-management simulator for the gold swing EA.

Trades come from the EA's signals (strategies/swing_pullback, max_hold_days=3) on all gold data 2013-2026,
run with continuous sizing so each trade's R multiple (costs, swap included) is exact. A sizing policy then
compounds a $50 account trade by trade.

    from mm_sim import get_trades, simulate, evaluate_policy, fixed
    t = get_trades()
    print(evaluate_policy(fixed(0.02)))

A policy is a callable(state: dict, trade: pandas row) -> risk fraction (e.g. 0.02), or a tuple
(risk_fraction, withdraw_amount) to also take money out of the account before the trade.
state keys: equity, start, peak, withdrawn, n, r_hist (list of past R), last_r, trades_since_peak.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.engine import run_backtest  # noqa: E402
from backtest.markets import cost_model, keep_entries_from, research_risk  # noqa: E402
from gold_full_eval import gold_all  # noqa: E402
from strategies import swing_pullback as S  # noqa: E402

PERIODS = {"dev_2013_2019": ("2013-01-01", "2020-01-01"), "val_2020_2021": ("2020-01-01", "2022-01-01"),
           "val_2022_2025": ("2022-01-01", "2026-01-01"), "val_2026": ("2026-03-26", "2026-09-26")}
START_EQUITY = 50.0
RUIN = 5.0          # below $5 the account is considered gone
MAX_RISK = 0.12     # hard cap on any single trade's risk fraction


@lru_cache(maxsize=8)
def _bars():
    return gold_all()


@lru_cache(maxsize=32)
def _trades_cached(params_key: tuple, swap: float, stress: float) -> pd.DataFrame:
    bars = _bars()
    params = {**S.DEFAULT_PARAMS, "max_hold_days": 3, **dict(params_key)}
    sig = keep_entries_from(S.generate_signals(bars, **params), bars.index, "2013-01-01")
    t = run_backtest(bars, sig, cost_model("XAUUSD", stress=stress, swap_annual_pct=swap), research_risk()).trades
    return t.reset_index(drop=True)


def get_trades(params: dict | None = None, swap: float = 5.0, stress: float = 1.0) -> pd.DataFrame:
    """EA trades 2013-2026 with columns entry_time, exit_time, direction, entry, sl_dist, r, swap, mae, mfe, ..."""
    key = tuple(sorted((params or {}).items()))
    return _trades_cached(key, float(swap), float(stress)).copy()


def simulate(trades: pd.DataFrame, policy, start_equity: float = START_EQUITY) -> dict:
    eq, peak, withdrawn = start_equity, start_equity, 0.0
    r_hist: list[float] = []
    path = []
    since_peak = 0
    ruined = False
    for row in trades.itertuples(index=False):
        state = {"equity": eq, "start": start_equity, "peak": peak, "withdrawn": withdrawn, "n": len(r_hist),
                 "r_hist": r_hist, "last_r": r_hist[-1] if r_hist else 0.0, "trades_since_peak": since_peak}
        out = policy(state, row)
        risk, take = (out if isinstance(out, tuple) else (out, 0.0))
        if take > 0:
            take = min(take, eq)
            eq -= take
            withdrawn += take
        risk = float(np.clip(risk, 0.0, MAX_RISK))
        eq += eq * risk * row.r
        r_hist.append(row.r)
        if eq > peak:
            peak, since_peak = eq, 0
        else:
            since_peak += 1
        path.append(eq)
        if eq < RUIN:
            ruined = True
            break
    eqs = np.array([start_equity] + path)
    pk = np.maximum.accumulate(eqs)
    mdd = float(((pk - eqs) / pk).max() * 100)
    return {"final_equity": round(eq, 2), "withdrawn": round(withdrawn, 2), "total": round(eq + withdrawn, 2),
            "max_dd_pct": round(mdd, 1), "ruined": ruined, "trades": len(path)}


def evaluate_policy(policy, trades: pd.DataFrame | None = None) -> dict:
    """Policy results per period (each from a fresh $50) and over the whole history."""
    t = get_trades() if trades is None else trades
    out = {}
    for name, (s, e) in PERIODS.items():
        m = t[(t["entry_time"] >= pd.Timestamp(s, tz="UTC")) & (t["entry_time"] < pd.Timestamp(e, tz="UTC"))]
        out[name] = simulate(m, policy)
    out["all_2013_2026"] = simulate(t, policy)
    val = [out[k]["total"] for k in ("val_2020_2021", "val_2022_2025", "val_2026")]
    out["validation_sum"] = round(sum(val), 2)
    return out


# ---------------------------------------------------------------- reference policies

def fixed(f: float):
    return lambda st, tr: f


def ladder(f0=0.05, f2=0.03, f4=0.02):
    return lambda st, tr: f0 if st["equity"] < 2 * st["start"] else f2 if st["equity"] < 4 * st["start"] else f4


if __name__ == "__main__":
    import json
    for name, pol in {"fixed 2%": fixed(0.02), "fixed 3%": fixed(0.03), "ladder 5/3/2": ladder()}.items():
        print(name, json.dumps({k: (v["total"], v["max_dd_pct"]) if isinstance(v, dict) else v
                                for k, v in evaluate_policy(pol).items()}))
