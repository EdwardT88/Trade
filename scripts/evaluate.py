"""Backtest one strategy and print metrics as JSON.

    python scripts/evaluate.py example_ema_pullback --start 2022-01-01 --end 2025-01-01
    python scripts/evaluate.py example_ema_pullback --params '{"tp_r": 2.0}' --mc --by-hour
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.data import DEFAULT_PARQUET, load_m1  # noqa: E402
from backtest.engine import CostModel, RiskConfig, run_backtest  # noqa: E402
from backtest.metrics import r_by_hour, summarize  # noqa: E402
from backtest.montecarlo import monte_carlo  # noqa: E402
from strategies import load  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy")
    ap.add_argument("--params", default="{}", help="JSON dict overriding DEFAULT_PARAMS")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--data", default=str(DEFAULT_PARQUET))
    ap.add_argument("--spread-fixed", type=float, default=CostModel.spread_fixed)
    ap.add_argument("--spread-bps", type=float, default=CostModel.spread_bps)
    ap.add_argument("--slippage", type=float, default=CostModel.slippage_stop)
    ap.add_argument("--risk", type=float, default=RiskConfig.risk_pct)
    ap.add_argument("--equity", type=float, default=RiskConfig.initial_equity)
    ap.add_argument("--min-size", type=float, default=RiskConfig.min_size, help="oz; cent=0.01, standard=1.0")
    ap.add_argument("--no-limits", action="store_true", help="disable daily loss / streak / hard-stop rules")
    ap.add_argument("--mc", action="store_true", help="add Monte Carlo (6 months, day bootstrap)")
    ap.add_argument("--by-hour", action="store_true")
    ap.add_argument("--json", default=None, help="write summary JSON here")
    ap.add_argument("--trades-csv", default=None)
    a = ap.parse_args()

    mod = load(a.strategy)
    params = {**mod.DEFAULT_PARAMS, **json.loads(a.params)}
    m1 = load_m1(Path(a.data), a.start, a.end)
    t0 = time.time()
    sig = mod.generate_signals(m1, **params)
    cost = CostModel(spread_fixed=a.spread_fixed, spread_bps=a.spread_bps, slippage_stop=a.slippage)
    risk = RiskConfig(risk_pct=a.risk, initial_equity=a.equity, min_size=a.min_size)
    if a.no_limits:
        risk.daily_loss_pct, risk.max_trades_per_day, risk.max_consec_losses_per_day = 1e9, 10**6, 10**6
        risk.hard_stop_equity, risk.dd_reduce_pct = -1e18, 1e9
    res = run_backtest(m1, sig, cost, risk)
    s = summarize(res, a.start or str(m1.index[0].date()), a.end or str(m1.index[-1].date()))
    s["signals"] = int(len(sig.entry_idx))
    s["params"] = params
    s["runtime_s"] = round(time.time() - t0, 2)
    if a.mc:
        s["monte_carlo_6m"] = monte_carlo(res, months=6)
    print(json.dumps(s, indent=1, default=str))
    if a.by_hour:
        print(r_by_hour(res).to_string())
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(s, indent=1, default=str))
    if a.trades_csv:
        res.trades.to_csv(a.trades_csv, index=False)


if __name__ == "__main__":
    main()
