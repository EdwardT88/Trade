"""Multi-market helpers: data loading, cent-account cost models and R-based statistics.

Data (built by scripts/prepare_markets.py / prepare_data.py, all true UTC):
- FX pairs: M15 bars 2012-11 .. 2022-03          -> data/markets/<SYM>_m15_2012_2022.parquet
- XAUUSD:   H1 bars 2012-05 .. 2022-03           -> data/markets/XAUUSD_h1_2012_2022.parquet
            M1 bars 2022-01 .. 2025-12           -> data/xauusd_m1.parquet
- 2026 samples (M1 and M15) are the final holdout and are not loaded by default.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .engine import CostModel, RiskConfig, Result

ROOT = Path(__file__).resolve().parents[1]
MARKETS = ROOT / "data" / "markets"

FX = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURCHF"]

# typical cent-account spreads in pips (Exness Standard Cent / HFM Cent ballpark, slightly conservative)
SPREAD_PIPS = {"EURUSD": 1.3, "GBPUSD": 1.7, "USDJPY": 1.5, "AUDUSD": 1.5, "USDCAD": 2.0, "USDCHF": 1.8,
               "EURGBP": 1.8, "EURJPY": 2.0, "GBPJPY": 3.0, "AUDJPY": 2.0, "EURCHF": 2.2}


def pip(sym: str) -> float:
    if sym == "XAUUSD":
        return 0.01
    if sym == "XAGUSD":
        return 0.001
    return 0.01 if sym.endswith("JPY") else 0.0001


def cost_model(sym: str, stress: float = 1.0, swap_annual_pct: float = 3.0) -> CostModel:
    """Cent-account costs in price units. stress multiplies spread and slippage (e.g. 1.5)."""
    if sym == "XAUUSD":
        return CostModel(spread_fixed=0.25 * stress, spread_bps=0.8 * stress, slippage_stop=0.05 * stress,
                         swap_annual_pct=max(swap_annual_pct, 5.0))
    if sym == "XAGUSD":
        return CostModel(spread_fixed=0.03 * stress, spread_bps=0.0, slippage_stop=0.005 * stress,
                         swap_annual_pct=max(swap_annual_pct, 5.0))
    p = pip(sym)
    return CostModel(spread_fixed=SPREAD_PIPS[sym] * p * stress, spread_bps=0.0, slippage_stop=0.2 * p * stress,
                     swap_annual_pct=swap_annual_pct)


def _ns_index(df: pd.DataFrame) -> pd.DataFrame:
    df.index = pd.DatetimeIndex(df.index).as_unit("ns")
    return df


def load(sym: str, start: str | None = None, end: str | None = None, warmup_days: int = 60,
         gold_tf: str = "auto") -> pd.DataFrame:
    """Bars for `sym` covering [start - warmup, end). FX: M15. XAUUSD: H1 before 2022, M1 from 2022
    (gold_tf='h1' forces H1 everywhere by resampling the M1 data)."""
    t0 = pd.Timestamp(start, tz="UTC") - pd.Timedelta(days=warmup_days) if start else None
    t1 = pd.Timestamp(end, tz="UTC") if end else None
    if sym == "XAUUSD":
        parts = [_ns_index(pd.read_parquet(MARKETS / "XAUUSD_h1_2012_2022.parquet"))]
        m1 = _ns_index(pd.read_parquet(ROOT / "data" / "xauusd_m1.parquet"))
        m1 = m1[m1.index < pd.Timestamp("2026-01-01", tz="UTC")]
        if gold_tf == "h1":
            from .data import resample
            m1 = resample(m1, "1h")
        parts[0] = parts[0][parts[0].index < m1.index[0]]
        df = pd.concat([parts[0], m1])
    else:
        df = _ns_index(pd.read_parquet(MARKETS / f"{sym}_m15_2012_2022.parquet"))
    if t0 is not None:
        df = df[df.index >= t0]
    if t1 is not None:
        df = df[df.index < t1]
    return df


def research_risk() -> RiskConfig:
    """Huge equity, continuous sizing, no account limits: isolates the raw R edge."""
    r = RiskConfig(initial_equity=1e9, min_size=1e-9, size_step=1e-9)
    r.daily_loss_pct, r.max_trades_per_day, r.max_consec_losses_per_day = 1e9, 10**6, 10**6
    r.hard_stop_equity, r.dd_reduce_pct = -1e30, 1e9
    return r


def r_stats(trades: pd.DataFrame, start: str | None = None, end: str | None = None) -> dict:
    if trades is None or trades.empty:
        return {"n": 0}
    r = trades["r"].to_numpy()
    hold = (trades["exit_time"] - trades["entry_time"]).dt.total_seconds() / 3600
    t0 = pd.Timestamp(start, tz="UTC") if start else trades["entry_time"].iloc[0]
    t1 = pd.Timestamp(end, tz="UTC") if end else trades["exit_time"].iloc[-1]
    months = max((t1 - t0).days / 30.44, 1e-9)
    se = float(r.std(ddof=1) / np.sqrt(len(r))) if len(r) > 1 else float("nan")
    gw, gl = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": int(len(r)), "avg_r": round(float(r.mean()), 3), "se": round(se, 3),
            "t": round(float(r.mean() / se), 2) if se and se == se and se > 0 else None,
            "win": round(float((r > 0).mean()) * 100, 1), "pf": round(float(gw / gl), 2) if gl > 0 else None,
            "med_hold_h": round(float(hold.median()), 1), "avg_hold_h": round(float(hold.mean()), 1),
            "trades_per_month": round(len(r) / months, 1), "sum_r": round(float(r.sum()), 1)}


def keep_entries_from(sig, index: pd.DatetimeIndex, start: str | pd.Timestamp):
    """Drop signals entered before `start` (they only existed to warm indicators up)."""
    sig = sig.finalize()
    keep = index[sig.entry_idx] >= pd.Timestamp(start, tz="UTC") if isinstance(start, str) else index[sig.entry_idx] >= start
    for f in ("entry_idx", "direction", "sl_dist", "tp_dist", "exit_idx", "be_trigger_r", "be_offset", "trail_dist", "tag"):
        setattr(sig, f, getattr(sig, f)[keep])
    return sig
