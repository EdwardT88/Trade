"""Full report for one strategy: dev / validation / holdout splits, cost stress, Monte Carlo, charts.

    python scripts/report.py trend_pullback --data data/xauusd_m1.parquet --out results/trend_pullback
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.data import DEFAULT_PARQUET, load_m1  # noqa: E402
from backtest.engine import CostModel, RiskConfig, Signals, run_backtest  # noqa: E402
from backtest.metrics import r_by_hour, summarize  # noqa: E402
from backtest.montecarlo import monte_carlo  # noqa: E402
from strategies import load  # noqa: E402

SPLITS = {
    "dev_2022_2023": ("2022-01-01", "2024-01-01"),
    "val_2024": ("2024-01-01", "2025-01-01"),
    "holdout_2025": ("2025-01-01", "2026-01-01"),
}
STRESS = CostModel(spread_fixed=0.40, spread_bps=1.2, slippage_stop=0.10, swap_annual_pct=8.0)


WARMUP = pd.Timedelta(days=60)


def keep_from(sig: Signals, index: pd.DatetimeIndex, start: pd.Timestamp) -> Signals:
    sig = sig.finalize()
    keep = index[sig.entry_idx] >= start
    for f in ("entry_idx", "direction", "sl_dist", "tp_dist", "exit_idx", "be_trigger_r", "be_offset", "trail_dist", "tag"):
        setattr(sig, f, getattr(sig, f)[keep])
    return sig


def no_limits(risk: RiskConfig) -> RiskConfig:
    risk.daily_loss_pct, risk.max_trades_per_day, risk.max_consec_losses_per_day = 1e9, 10**6, 10**6
    risk.hard_stop_equity, risk.dd_reduce_pct = -1e18, 1e9
    return risk


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy")
    ap.add_argument("--data", default=str(DEFAULT_PARQUET))
    ap.add_argument("--params", default="{}")
    ap.add_argument("--out", default=None)
    ap.add_argument("--swap", type=float, default=5.0, help="base-case swap %%/yr (0 = swap-free account)")
    a = ap.parse_args()
    out = Path(a.out or f"results/{a.strategy}")
    out.mkdir(parents=True, exist_ok=True)

    mod = load(a.strategy)
    params = {**mod.DEFAULT_PARAMS, **json.loads(a.params)}
    full = load_m1(Path(a.data))
    report = {"strategy": a.strategy, "params": params, "splits": {}}
    curves = {}
    for name, (s, e) in SPLITS.items():
        t0, t1 = pd.Timestamp(s, tz="UTC"), pd.Timestamp(e, tz="UTC")
        if not ((full.index >= t0) & (full.index < t1)).any():
            continue
        # indicators warm up on the preceding WARMUP of data (as a live EA would have history);
        # only trades entered inside [s, e) are counted
        m1 = full[(full.index >= t0 - WARMUP) & (full.index < t1)]
        sig = keep_from(mod.generate_signals(m1, **params), m1.index, t0)
        base_cost = CostModel(swap_annual_pct=a.swap)
        base = run_backtest(m1, sig, base_cost, RiskConfig())
        raw = run_backtest(m1, sig, base_cost, no_limits(RiskConfig()))
        stress = run_backtest(m1, sig, STRESS, no_limits(RiskConfig()))
        report["splits"][name] = {
            "account": summarize(base, s, e),
            "raw": summarize(raw, s, e),
            "stress_raw": summarize(stress, s, e),
            "monte_carlo_6m": monte_carlo(base, months=6),
        }
        curves[name] = base
        base.trades.to_csv(out / f"trades_{name}.csv", index=False)
        print(name, "account:", {k: report["splits"][name]["account"].get(k) for k in
                                  ("trades", "return_pct", "max_dd_pct", "win_rate", "avg_r", "profit_factor", "pos_months_pct")})
        print(name, "raw avg_r:", report["splits"][name]["raw"].get("avg_r"),
              "stress avg_r:", report["splits"][name]["stress_raw"].get("avg_r"))

    (out / "summary.json").write_text(json.dumps(report, indent=1, default=str))

    fig, axes = plt.subplots(len(curves), 1, figsize=(10, 3.2 * len(curves)), squeeze=False)
    for ax, (name, res) in zip(axes[:, 0], curves.items()):
        t = res.trades
        if t.empty:
            continue
        ax.plot(t["exit_time"], t["equity"], lw=1.2, color="#2f6db5")
        ax.axhline(res.initial_equity, color="#888", lw=0.8, ls="--")
        ax.axhline(res.risk.hard_stop_equity, color="#c0392b", lw=0.8, ls=":")
        ax.set_title(f"{a.strategy} — {name}: ${res.initial_equity:.0f} -> ${res.final_equity:.2f}", fontsize=10)
        ax.set_ylabel("equity ($)")
        ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "equity.png", dpi=110)

    for name, res in curves.items():
        r_by_hour(res).to_csv(out / f"r_by_hour_{name}.csv")
    print(f"wrote {out}/summary.json, equity.png, trades_*.csv")


if __name__ == "__main__":
    main()
