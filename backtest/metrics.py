"""Performance metrics for a backtest Result."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .engine import Result


def equity_series(res: Result) -> pd.Series:
    t = res.trades
    if t.empty:
        return pd.Series([res.initial_equity], dtype=float)
    return pd.concat([pd.Series([res.initial_equity], index=[t["entry_time"].iloc[0]]),
                      pd.Series(t["equity"].to_numpy(), index=t["exit_time"])])


def max_drawdown_pct(eq: np.ndarray) -> float:
    eq = np.asarray(eq, dtype=float)
    if eq.size == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    return float(((eq - peak) / peak).min() * -100.0)


def longest_streak(mask: np.ndarray) -> int:
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best


def summarize(res: Result, start: str | None = None, end: str | None = None) -> dict:
    t = res.trades
    out: dict = {"trades": int(len(t)), "final_equity": round(res.final_equity, 2),
                 "return_pct": round((res.final_equity / res.initial_equity - 1) * 100, 1),
                 "hard_stopped": res.stopped_out, "skipped": res.skipped}
    if t.empty:
        return out
    eq = np.concatenate([[res.initial_equity], t["equity"].to_numpy()])
    r = t["r"].to_numpy()
    wins = r > 0
    gross_win = t.loc[t["pnl"] > 0, "pnl"].sum()
    gross_loss = -t.loc[t["pnl"] < 0, "pnl"].sum()
    t0 = pd.Timestamp(start, tz="UTC") if start else t["entry_time"].iloc[0]
    t1 = pd.Timestamp(end, tz="UTC") if end else t["exit_time"].iloc[-1]
    years = max((t1 - t0).total_seconds() / (365.25 * 86400), 1e-9)
    monthly = t.set_index("exit_time")["pnl"].resample("ME").sum()
    m_eq_start = (t.set_index("exit_time")["equity"].resample("ME").last().ffill().shift(1)
                  .fillna(res.initial_equity))
    m_ret = (monthly / m_eq_start * 100).dropna()
    days = t["entry_time"].dt.floor("D").nunique()
    hold = (t["exit_time"] - t["entry_time"]).dt.total_seconds() / 60
    out.update({
        "win_rate": round(float(wins.mean()) * 100, 1),
        "avg_r": round(float(r.mean()), 3),
        "avg_win_r": round(float(r[wins].mean()), 2) if wins.any() else 0.0,
        "avg_loss_r": round(float(r[~wins].mean()), 2) if (~wins).any() else 0.0,
        "profit_factor": round(float(gross_win / gross_loss), 2) if gross_loss > 0 else float("inf"),
        "cagr_pct": round(((res.final_equity / res.initial_equity) ** (1 / years) - 1) * 100, 1) if res.final_equity > 0 else -100.0,
        "max_dd_pct": round(max_drawdown_pct(eq), 1),
        "months": int(len(m_ret)),
        "pos_months_pct": round(float((m_ret > 0).mean()) * 100, 1) if len(m_ret) else 0.0,
        "median_month_pct": round(float(m_ret.median()), 1) if len(m_ret) else 0.0,
        "worst_month_pct": round(float(m_ret.min()), 1) if len(m_ret) else 0.0,
        "best_month_pct": round(float(m_ret.max()), 1) if len(m_ret) else 0.0,
        "trades_per_active_day": round(len(t) / max(days, 1), 2),
        "trades_per_month": round(len(t) / max(years * 12, 1e-9), 1),
        "avg_hold_min": round(float(hold.mean()), 1),
        "max_losing_streak": longest_streak(r <= 0),
        "longs": int((t["direction"] > 0).sum()),
        "long_avg_r": round(float(r[t["direction"].to_numpy() > 0].mean()), 3) if (t["direction"] > 0).any() else 0.0,
        "short_avg_r": round(float(r[t["direction"].to_numpy() < 0].mean()), 3) if (t["direction"] < 0).any() else 0.0,
        "exit_reasons": t["exit_reason"].value_counts().to_dict(),
    })
    by_year = t.groupby(t["entry_time"].dt.year)["r"].agg(["count", "mean", "sum"]).round(3)
    out["r_by_year"] = {int(y): {"n": int(row["count"]), "avg_r": float(row["mean"]), "sum_r": float(row["sum"])}
                        for y, row in by_year.iterrows()}
    return out


def r_by_hour(res: Result) -> pd.DataFrame:
    t = res.trades
    return t.groupby(t["entry_time"].dt.hour)["r"].agg(["count", "mean", "sum"]).round(3)
