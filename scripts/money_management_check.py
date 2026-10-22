"""Two questions from the owner, on all gold data (2013-2026) with the EA's signals:

1) Equity milestones: what if something changes every time the account doubles (withdraw half, lock a floor,
   step risk down or up)?  Simulated by compounding the EA's per-trade R multiples (costs included) from a
   $50 start; 'total' = account + money withdrawn.
2) Trade management: breakeven-plus ("SL plus"), tighter/looser trailing, fixed TP, per period (avg R).
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.engine import run_backtest  # noqa: E402
from backtest.markets import cost_model, keep_entries_from, research_risk  # noqa: E402
from gold_full_eval import PERIODS, gold_all  # noqa: E402
from strategies import swing_pullback as S  # noqa: E402

STARTS = ["2013-01-01", "2016-01-01", "2020-01-01", "2022-01-01", "2024-01-01", "2025-01-01", "2026-03-26"]


def simulate(r: np.ndarray, scheme: str) -> tuple[float, float, bool]:
    """Returns (total wealth = equity + withdrawn, max drawdown % of trading equity, ruined)."""
    eq, base, withdrawn, peak, mdd, floor = 50.0, 50.0, 0.0, 50.0, 0.0, 0.0
    for x in r:
        if scheme == "fixed2":
            risk = 0.02
        elif scheme == "fixed5":
            risk = 0.05
        elif scheme == "step_down":          # 5% -> 3% after 2x -> 2% after 4x (of $50)
            risk = 0.05 if eq < 100 else 0.03 if eq < 200 else 0.02
        elif scheme == "step_up":            # 2% -> 3% after 2x -> 5% after 4x
            risk = 0.02 if eq < 100 else 0.03 if eq < 200 else 0.05
        else:                                # withdraw-half / floor schemes trade at 5%
            risk = 0.05
        eq += eq * risk * x
        if scheme == "withdraw_half" and eq >= 2 * base:
            withdrawn += eq / 2              # take half out every time the account doubles
            eq /= 2
            base = eq
        if scheme == "lock_floor" and eq >= 2 * max(base, 50.0):
            base = eq
            floor = eq / 2                   # never give back more than half of the last doubling level
        peak = max(peak, eq)
        mdd = max(mdd, 1 - eq / peak)
        if scheme == "lock_floor" and floor > 0 and eq <= floor:
            return floor + withdrawn, mdd * 100, False   # stop trading at the floor (profit locked)
        if eq < 5:
            return eq + withdrawn, mdd * 100, True
    return eq + withdrawn, mdd * 100, False


def main():
    bars = gold_all()
    cost = cost_model("XAUUSD", swap_annual_pct=5.0)
    base_params = {**S.DEFAULT_PARAMS, "max_hold_days": 3}
    sig_all = S.generate_signals(bars, **base_params)

    print("1) EVERY DOUBLING (total = account + withdrawn, from $50; maxDD of trading account)")
    rows = []
    for scheme in ("fixed2", "fixed5", "withdraw_half", "lock_floor", "step_down", "step_up"):
        row = {"scheme": scheme}
        for s in STARTS:
            t = run_backtest(bars, keep_entries_from(sig_all, bars.index, s), cost, research_risk()).trades
            total, mdd, ruined = simulate(t["r"].to_numpy(), scheme)
            row[s[:7]] = ("RUIN " if ruined else "") + f"${total:.0f} ({mdd:.0f}%)"
        rows.append(row)
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n2) TRADE MANAGEMENT (avg R per trade by period; EA default = trail 3 ATR from entry, no BE, no TP)")
    variants = {
        "EA default (trail 3 ATR)": {},
        "SL plus: BE+0.1R at +1R, then trail 3": {"be_r": 1.0, "be_off_r": 0.1},
        "SL plus: BE+0.1R at +0.5R, then trail 3": {"be_r": 0.5, "be_off_r": 0.1},
        "SL plus at +1R, no trailing": {"be_r": 1.0, "be_off_r": 0.1, "trail_atr": 0.0},
        "trail 2 ATR": {"trail_atr": 2.0},
        "trail 2.5 ATR": {"trail_atr": 2.5},
        "trail 4 ATR": {"trail_atr": 4.0},
        "no trailing, no BE": {"trail_atr": 0.0},
        "TP 2R (+trail 3)": {"tp_r": 2.0},
        "TP 3R (+trail 3)": {"tp_r": 3.0},
    }
    rows = []
    for name, p in variants.items():
        sig_v = S.generate_signals(bars, **{**base_params, **p})
        row = {"management": name}
        allr = []
        for per, (s, e) in PERIODS.items():
            t = run_backtest(bars[bars.index < pd.Timestamp(e, tz="UTC")], keep_entries_from(sig_v, bars.index, s), cost,
                             research_risk()).trades
            t = t[t["entry_time"] < pd.Timestamp(e, tz="UTC")]
            row[per] = f"{t['r'].mean():+.3f}"
            allr.append(t["r"].to_numpy())
        a = np.concatenate(allr)
        row["ALL"] = f"{a.mean():+.3f} (n {len(a)})"
        rows.append(row)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
