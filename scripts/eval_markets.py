"""Evaluate one strategy module on several markets with cent-account costs; prints per-market and pooled R stats.

    python scripts/eval_markets.py asia_range_mr --pairs EURGBP,EURCHF,AUDJPY --start 2013-01-01 --end 2020-01-01
    python scripts/eval_markets.py asia_range_mr --pairs all --start 2020-01-01 --end 2022-03-05 --stress 1.5

The strategy module must expose DEFAULT_PARAMS and generate_signals(bars, sym=..., **params) -> Signals,
where `bars` are the market's native bars (FX: M15; XAUUSD: H1 before 2022, M1 from 2022).
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.engine import run_backtest  # noqa: E402
from backtest.markets import FX, cost_model, keep_entries_from, load, r_stats, research_risk  # noqa: E402
from strategies import load as load_strategy  # noqa: E402


def evaluate(mod, pairs, start, end, params, stress=1.0, swap=None):
    per, all_trades = {}, []
    for sym in pairs:
        bars = load(sym, start, end)
        sig = keep_entries_from(mod.generate_signals(bars, sym=sym, **params), bars.index, start)
        res = run_backtest(bars, sig, cost_model(sym, stress, swap), research_risk())
        per[sym] = r_stats(res.trades, start, end)
        if not res.trades.empty:
            all_trades.append(res.trades.assign(sym=sym))
    pooled = pd.concat(all_trades) if all_trades else pd.DataFrame()
    return per, r_stats(pooled, start, end) if len(pooled) else {"n": 0}, pooled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy")
    ap.add_argument("--pairs", default="all", help="comma list or 'all' (11 FX pairs) or 'all+gold'")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--stress", type=float, default=1.0)
    ap.add_argument("--swap", type=float, default=None, help="swap %%/yr (default: FX 3, metals 5; 0 = swap-free)")
    ap.add_argument("--trades-csv", default=None)
    a = ap.parse_args()
    pairs = FX if a.pairs == "all" else FX + ["XAUUSD"] if a.pairs == "all+gold" else a.pairs.split(",")
    mod = load_strategy(a.strategy)
    params = {**mod.DEFAULT_PARAMS, **json.loads(a.params)}
    per, pooled, trades = evaluate(mod, pairs, a.start, a.end, params, a.stress, a.swap)
    for sym, s in per.items():
        print(f"{sym:7s} {json.dumps(s)}")
    print(f"POOLED  {json.dumps(pooled)}")
    if a.trades_csv and len(trades):
        trades.to_csv(a.trades_csv, index=False)


if __name__ == "__main__":
    main()
