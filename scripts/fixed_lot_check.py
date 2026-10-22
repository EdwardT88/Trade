"""Standard account, fixed 0.01 lot (= 1 oz of gold) on $50 vs the cent account at 2% risk, same EA signals.

Runs the gold swing EA (swing_pullback, 3-day cap) from several start dates and reports the final balance,
or the date the $50 is wiped out (equity <= $2, i.e. the broker's stop-out).
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backtest.engine import RiskConfig, run_backtest  # noqa: E402
from backtest.markets import cost_model, keep_entries_from  # noqa: E402
from gold_full_eval import gold_all  # noqa: E402
from strategies import swing_pullback as S  # noqa: E402

STARTS = ["2013-01-01", "2016-01-01", "2020-01-01", "2022-01-01", "2024-01-01", "2025-01-01", "2026-03-26"]


def fixed_lot() -> RiskConfig:
    r = RiskConfig(initial_equity=50.0, risk_pct=1e-6, min_size=1.0, size_step=1.0, max_risk_pct_at_min_lot=1e9,
                   leverage=2000.0)
    r.daily_loss_pct, r.max_trades_per_day, r.max_consec_losses_per_day, r.dd_reduce_pct = 1e9, 10**6, 10**6, 1e9
    r.hard_stop_equity = 2.0      # broker stop-out: the account is gone
    return r


def main():
    bars = gold_all()
    sig_all = S.generate_signals(bars, **{**S.DEFAULT_PARAMS, "max_hold_days": 3})
    cost = cost_model("XAUUSD", swap_annual_pct=5.0)
    rows = []
    for s in STARTS:
        sig = keep_entries_from(sig_all, bars.index, s)
        std = run_backtest(bars, sig, cost, fixed_lot())
        cent = run_backtest(bars, sig, cost, RiskConfig(risk_pct=2.0))
        t = std.trades
        first = t.iloc[0] if len(t) else None
        rows.append({
            "start": s,
            "std_0.01lot_result": f"WIPED OUT {t['exit_time'].iloc[-1].date()} after {len(t)} trades" if std.stopped_out
                                  else f"${std.final_equity:.2f}",
            "first_trade_risk_%_of_$50": round(first["risk"] / 50 * 100) if first is not None else None,
            "max_equity_reached": round(t["equity"].max(), 2) if len(t) else None,
            "cent_2%_result": f"${cent.final_equity:.2f}",
        })
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
