"""Account growth vs risk per trade for the gold swing EA (strategies/swing_pullback, 3-day cap) on all gold data.

Gold 2013-2021 H1 bars, 2022-2025 M1, 2026 (Mar-Sep) M1 sample. Prints, per risk level, the $50 account path
with the EA's rules (reduced risk = half in a 10% drawdown, daily -5% stop, hard stop at -30%), CAGR, max drawdown,
worst calendar year, and a 12-month Monte Carlo (day bootstrap) probability of hitting the hard stop.

    python scripts/risk_sizing_study.py --h2026 path/to/XAUUSD_m1_2026.parquet
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.engine import RiskConfig, run_backtest  # noqa: E402
from backtest.markets import cost_model, keep_entries_from, load  # noqa: E402
from backtest.metrics import max_drawdown_pct  # noqa: E402
from backtest.montecarlo import monte_carlo  # noqa: E402
from strategies import swing_pullback as S  # noqa: E402

START = "2013-01-01"


def gold_bars(h2026: str | None) -> pd.DataFrame:
    df = load("XAUUSD", START, "2026-01-01")
    if h2026:
        extra = pd.read_parquet(h2026)
        extra.index = pd.DatetimeIndex(extra.index).as_unit("ns")
        df = pd.concat([df, extra]).sort_index()
        df = df[~df.index.duplicated()]
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--h2026", default=None)
    ap.add_argument("--params", default='{"max_hold_days": 3}')
    a = ap.parse_args()
    import json
    bars = gold_bars(a.h2026)
    params = {**S.DEFAULT_PARAMS, **json.loads(a.params)}
    sig = keep_entries_from(S.generate_signals(bars, **params), bars.index, START)
    cost = cost_model("XAUUSD", swap_annual_pct=5.0)
    years = (bars.index[-1] - pd.Timestamp(START, tz="UTC")).days / 365.25
    # all trades without account limits: the R distribution the Monte Carlo resamples
    full = run_backtest(bars, sig, cost, RiskConfig(initial_equity=1e9, min_size=1e-9, size_step=1e-9))
    rows = []
    for risk in (0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0):
        rc = RiskConfig(risk_pct=risk, reduced_risk_pct=risk / 2, max_risk_pct_at_min_lot=max(3.0, risk * 1.5))
        res = run_backtest(bars, sig, cost, rc)
        t = res.trades
        eq = np.concatenate([[rc.initial_equity], t["equity"].to_numpy()])
        yearly = t.groupby(t["exit_time"].dt.year)["equity"].last()
        prev = yearly.shift(1).fillna(rc.initial_equity)
        yr_ret = (yearly / prev - 1) * 100
        full.risk = rc
        mc = monte_carlo(full, months=12, n_paths=3000)
        stopped_at = t["exit_time"].iloc[-1].date() if res.stopped_out else "-"
        rows.append({
            "risk%": risk, "final$": round(res.final_equity, 2),
            "CAGR%": round(((res.final_equity / 50) ** (1 / years) - 1) * 100, 1) if res.final_equity > 0 else -100,
            "maxDD%": round(max_drawdown_pct(eq), 1), "worst_year%": round(yr_ret.min(), 1), "best_year%": round(yr_ret.max(), 1),
            "hard_stop_hit": stopped_at, "MC12m_P(-30%)": mc["p_hit_hard_stop_pct"], "MC12m_median$": mc["final_equity_median"],
            "trades": len(t)})
    print(pd.DataFrame(rows).to_string(index=False))
    r = full.trades["r"]
    m, v = r.mean(), (r ** 2).mean()
    print(f"\nR per trade: n={len(r)} mean={m:+.3f} sd={r.std():.2f}  ->  Kelly risk ~ {100 * m / v:.1f}% (half-Kelly {50 * m / v:.1f}%)")


if __name__ == "__main__":
    main()
