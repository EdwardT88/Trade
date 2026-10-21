"""Run strategies/swing_pullback (gold rules, unchanged) on gold H1 2013-2022, 11 FX pairs (M15) and 2026 1-minute samples.
Requires data/markets/ built by scripts/prepare_markets.py. Prints avg R per trade (trade count) per period."""
import sys; from pathlib import Path; sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np, pandas as pd
from backtest.engine import CostModel, RiskConfig, run_backtest
from strategies import swing_pullback as S
M = str(Path(__file__).resolve().parents[1] / "data" / "markets") + "/"
PIP = {"JPY": 0.01}
SPREAD_PIPS = {"EURUSD":1.2,"GBPUSD":1.6,"USDJPY":1.4,"AUDUSD":1.4,"USDCAD":2.0,"USDCHF":1.8,"EURGBP":1.8,"EURJPY":2.0,"GBPJPY":2.8,"AUDJPY":2.0,"EURCHF":2.2}
def cost(sym):
    if sym in ("XAUUSD",): return CostModel(swap_annual_pct=5.0)
    if sym == "XAGUSD": return CostModel(spread_fixed=0.03, spread_bps=0, slippage_stop=0.005, swap_annual_pct=5.0)
    pip = 0.01 if sym.endswith("JPY") else 0.0001
    return CostModel(spread_fixed=SPREAD_PIPS[sym]*pip, spread_bps=0, slippage_stop=0.2*pip, swap_annual_pct=3.0)
def nolim():
    r = RiskConfig(initial_equity=1e9, min_size=1e-9, size_step=1e-9); r.daily_loss_pct=1e9; r.max_trades_per_day=10**6
    r.max_consec_losses_per_day=10**6; r.hard_stop_equity=-1e30; r.dd_reduce_pct=1e9; return r
def run(df, sym, start, end, p):
    t0, t1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    m = df[(df.index >= t0 - pd.Timedelta(days=60)) & (df.index < t1)]
    sig = S.generate_signals(m, **{**S.DEFAULT_PARAMS, **p}).finalize()
    keep = m.index[sig.entry_idx] >= t0
    for f in ("entry_idx","direction","sl_dist","tp_dist","exit_idx","be_trigger_r","be_offset","trail_dist","tag"):
        setattr(sig, f, getattr(sig, f)[keep])
    t = run_backtest(m, sig, cost(sym), nolim()).trades
    return t
syms = ["XAUUSD","EURUSD","GBPUSD","USDJPY","AUDUSD","USDCAD","USDCHF","EURGBP","EURJPY","GBPJPY","AUDJPY","EURCHF"]
for cap in [3]:
    print(f"=== swing_pullback (gold rules unchanged), max hold {cap}d; avg R per trade (n)")
    rows = []
    for sym in syms:
        hist = pd.read_parquet(M + (f"{sym}_h1_2012_2022.parquet" if sym=="XAUUSD" else f"{sym}_m15_2012_2022.parquet"))
        hist.index = hist.index.as_unit("ns")
        out = {"sym": sym}
        for name, (s, e) in {"2013-15": ("2013-01-01","2016-01-01"), "2016-19": ("2016-01-01","2020-01-01"), "2020-22": ("2020-01-01","2022-03-05")}.items():
            t = run(hist, sym, s, e, {"max_hold_days": cap})
            out[name] = f"{t.r.mean():+.2f} ({len(t)})"
        f26 = M + f"{sym}_m1_2026.parquet"
        try:
            d26 = pd.read_parquet(f26); d26.index = d26.index.as_unit("ns")
            t = run(d26, sym, "2026-05-10", "2026-09-26", {"max_hold_days": cap})
            out["2026"] = f"{t.r.mean():+.2f} ({len(t)})"
        except FileNotFoundError:
            out["2026"] = "-"
        rows.append(out); print(out, flush=True)
