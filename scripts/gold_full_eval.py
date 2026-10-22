"""Evaluate a gold strategy module over all gold data with the $50 cent-account simulation.

Periods: dev 2013-2019 (H1 bars), val_a 2020-2021 (H1), val_b 2022-2025 (M1), val_c 2026-03..09 (M1 sample).
The research protocol for tweaks: tune on dev only, then report val_* once.

    python scripts/gold_full_eval.py swing_pullback --params '{"max_hold_days": 3}' --risk 2
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.engine import RiskConfig, run_backtest  # noqa: E402
from backtest.markets import MARKETS, cost_model, keep_entries_from, load, r_stats, research_risk  # noqa: E402
from backtest.metrics import max_drawdown_pct  # noqa: E402
from strategies import load as load_strategy  # noqa: E402

PERIODS = {"dev_2013_2019": ("2013-01-01", "2020-01-01"), "val_2020_2021": ("2020-01-01", "2022-01-01"),
           "val_2022_2025": ("2022-01-01", "2026-01-01"), "val_2026": ("2026-03-26", "2026-09-26")}


def gold_all() -> pd.DataFrame:
    df = load("XAUUSD", "2012-11-01", "2026-01-01", warmup_days=0)
    f26 = MARKETS / "XAUUSD_m1_2026.parquet"
    if f26.exists():
        extra = pd.read_parquet(f26)
        extra.index = pd.DatetimeIndex(extra.index).as_unit("ns")
        df = pd.concat([df, extra]).sort_index()
    return df[~df.index.duplicated()]


def evaluate(mod, params: dict, risk_pct: float = 2.0, bars: pd.DataFrame | None = None) -> dict:
    bars = gold_all() if bars is None else bars
    sig_all = mod.generate_signals(bars, sym="XAUUSD", **params) if "sym" in mod.generate_signals.__code__.co_varnames \
        else mod.generate_signals(bars, **params)
    cost = cost_model("XAUUSD", swap_annual_pct=5.0)
    out = {}
    for name, (s, e) in PERIODS.items():
        t0, t1 = pd.Timestamp(s, tz="UTC"), pd.Timestamp(e, tz="UTC")
        m = bars[bars.index < t1]
        sig = keep_entries_from(sig_all, bars.index, t0)
        keep = sig.entry_idx < len(m)
        for f in ("entry_idx", "direction", "sl_dist", "tp_dist", "exit_idx", "be_trigger_r", "be_offset", "trail_dist", "tag"):
            setattr(sig, f, getattr(sig, f)[keep])
        sig.exit_idx = np.where(sig.exit_idx >= len(m), -1, sig.exit_idx)
        raw = run_backtest(m, sig, cost, research_risk())
        rc = RiskConfig(risk_pct=risk_pct, reduced_risk_pct=risk_pct / 2, max_risk_pct_at_min_lot=max(3.0, 1.5 * risk_pct))
        acc = run_backtest(m, sig, cost, rc)
        eq = np.concatenate([[rc.initial_equity], acc.trades["equity"].to_numpy()]) if len(acc.trades) else np.array([rc.initial_equity])
        out[name] = {**r_stats(raw.trades, s, e), "account_final": round(acc.final_equity, 2),
                     "account_max_dd_pct": round(max_drawdown_pct(eq), 1), "hard_stop": acc.stopped_out}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy")
    ap.add_argument("--params", default="{}")
    ap.add_argument("--risk", type=float, default=2.0)
    a = ap.parse_args()
    mod = load_strategy(a.strategy)
    params = {**mod.DEFAULT_PARAMS, **json.loads(a.params)}
    for k, v in evaluate(mod, params, a.risk).items():
        print(f"{k:14s} {json.dumps(v)}")


if __name__ == "__main__":
    main()
