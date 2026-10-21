"""Final holdout on the 2026 samples (pre-registered in results/MULTI_MARKET_PLAN.md).

Signals use the sample from 2026-03-26 for indicator warm-up; only trades entered from 2026-05-01 count.
FX pairs use M15 bars, gold/silver use M1 bars (as in the development data from 2022 onwards).

    python scripts/holdout_2026.py asia_range_mr --pairs EURGBP,USDCHF --dir data/markets
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.engine import run_backtest  # noqa: E402
from backtest.markets import MARKETS, cost_model, keep_entries_from, r_stats, research_risk  # noqa: E402
from strategies import load as load_strategy  # noqa: E402

START, END = "2026-05-01", "2026-09-26"
AVAILABLE = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "EURGBP", "EURJPY", "XAUUSD", "XAGUSD"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("strategy")
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--params", default="{}")
    ap.add_argument("--dir", default=str(MARKETS))
    ap.add_argument("--stress", type=float, default=1.0)
    a = ap.parse_args()
    mod = load_strategy(a.strategy)
    params = {**mod.DEFAULT_PARAMS, **json.loads(a.params)}
    per, frames = {}, []
    for sym in a.pairs.split(","):
        if sym not in AVAILABLE:
            per[sym] = "no 2026 sample"
            continue
        tf = "m1" if sym in ("XAUUSD", "XAGUSD") else "m15"
        bars = pd.read_parquet(Path(a.dir) / f"{sym}_{tf}_2026.parquet")
        bars.index = pd.DatetimeIndex(bars.index).as_unit("ns")
        bars = bars[bars.index < pd.Timestamp(END, tz="UTC")]
        sig = keep_entries_from(mod.generate_signals(bars, sym=sym, **params), bars.index, START)
        res = run_backtest(bars, sig, cost_model(sym, a.stress), research_risk())
        per[sym] = r_stats(res.trades, START, END)
        if not res.trades.empty:
            frames.append(res.trades.assign(sym=sym))
    for sym, s in per.items():
        print(f"{sym:7s} {json.dumps(s)}")
    pooled = r_stats(pd.concat(frames), START, END) if frames else {"n": 0}
    print(f"POOLED  {json.dumps(pooled)}")


if __name__ == "__main__":
    main()
