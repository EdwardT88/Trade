"""Hand-computed scenarios for the execution engine and risk manager."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.engine import CostModel, RiskConfig, Signals, align_htf_to_m1, htf_close_to_m1_entry, run_backtest  # noqa: E402

NOCOST = CostModel(spread_fixed=0.0, spread_bps=0.0, rollover_mult=1.0, slippage_stop=0.0)
SPREAD = CostModel(spread_fixed=0.5, spread_bps=0.0, rollover_mult=1.0, slippage_stop=0.0)
LOOSE = RiskConfig(initial_equity=100.0, risk_pct=1.0, daily_loss_pct=1e9, max_trades_per_day=10**6,
                   max_consec_losses_per_day=10**6, hard_stop_equity=-1e9, dd_reduce_pct=1e9)


def bars(rows, start="2024-01-02 08:00"):
    idx = pd.date_range(start, periods=len(rows), freq="1min", tz="UTC").as_unit("ns")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)


def one(entry, d, sl, tp, **kw):
    n = 1
    return Signals(np.array([entry]), np.array([d]), np.array([sl]), np.array([tp]),
                   **{k: np.array([v]) for k, v in kw.items()})


def test_long_tp_and_sizing():
    m1 = bars([(100, 100.5, 99.8, 100.2), (100.2, 100.4, 99.9, 100.3), (100.3, 102.5, 100.2, 102.0)])
    r = run_backtest(m1, one(0, 1, 1.0, 2.0), NOCOST, LOOSE)
    t = r.trades.iloc[0]
    assert t["entry"] == 100 and t["exit"] == 102 and t["exit_reason"] == "tp"
    assert t["size_oz"] == pytest.approx(1.0)  # 1% of 100 / $1 stop
    assert t["r"] == pytest.approx(2.0)


def test_same_bar_sl_and_tp_assumes_stop_first():
    m1 = bars([(100, 103, 98, 100)])
    r = run_backtest(m1, one(0, 1, 1.0, 2.0), NOCOST, LOOSE)
    assert r.trades.iloc[0]["exit_reason"] == "sl" and r.trades.iloc[0]["r"] == pytest.approx(-1.0)


def test_long_pays_spread_on_entry_short_on_exit():
    m1 = bars([(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 100)])
    rl = run_backtest(m1, one(0, 1, 1.0, 0.0, exit_idx=2), SPREAD, LOOSE).trades.iloc[0]
    assert rl["entry"] == pytest.approx(100.5) and rl["exit"] == pytest.approx(100.0)
    rs = run_backtest(m1, one(0, -1, 1.0, 0.0, exit_idx=2), SPREAD, LOOSE).trades.iloc[0]
    assert rs["entry"] == pytest.approx(100.0) and rs["exit"] == pytest.approx(100.5)
    assert rl["pnl"] == pytest.approx(rs["pnl"])


def test_short_stop_uses_ask():
    # bid high 100.6 + spread 0.5 = ask 101.1 >= stop 101.0
    m1 = bars([(100, 100.2, 99.9, 100), (100, 100.6, 99.9, 100.1)])
    t = run_backtest(m1, one(0, -1, 1.0, 5.0), SPREAD, LOOSE).trades.iloc[0]
    assert t["exit_reason"] == "sl" and t["exit"] == pytest.approx(101.0)


def test_gap_through_stop_fills_at_open():
    m1 = bars([(100, 100.2, 99.9, 100), (97, 97.5, 96.5, 97)])
    t = run_backtest(m1, one(0, 1, 1.0, 5.0), NOCOST, LOOSE).trades.iloc[0]
    assert t["exit"] == pytest.approx(97.0) and t["r"] == pytest.approx(-3.0)


def test_breakeven_applies_from_next_bar():
    # bar0 reaches +1R (101) -> stop moves to 100.1 for bar1; bar1 dips to 100 -> breakeven exit
    m1 = bars([(100, 101.2, 99.5, 101), (101, 101.1, 100.0, 100.5)])
    t = run_backtest(m1, one(0, 1, 1.0, 3.0, be_trigger_r=1.0, be_offset=0.1), NOCOST, LOOSE).trades.iloc[0]
    assert t["exit_reason"] == "breakeven" and t["exit"] == pytest.approx(100.1)


def test_time_exit_at_open_of_exit_bar():
    m1 = bars([(100, 100.2, 99.9, 100), (100, 100.3, 99.9, 100.2), (100.25, 100.3, 100.1, 100.2)])
    t = run_backtest(m1, one(0, 1, 1.0, 5.0, exit_idx=2), NOCOST, LOOSE).trades.iloc[0]
    assert t["exit_reason"] == "time" and t["exit"] == pytest.approx(100.25) and t["exit_idx"] == 2


def test_min_lot_skip_when_too_risky():
    # $50 standard account (min 1 oz): $5 stop at min size = 10% risk -> skipped
    m1 = bars([(100, 100, 100, 100)] * 3)
    risk = RiskConfig(initial_equity=50, min_size=1.0, size_step=1.0)
    r = run_backtest(m1, one(0, 1, 5.0, 10.0), NOCOST, risk)
    assert r.trades.empty and r.skipped == {"min_lot_risk": 1}
    # cent account (min 0.01 oz): sized to 2% -> 0.2 oz
    r = run_backtest(m1, one(0, 1, 5.0, 10.0), NOCOST, RiskConfig(initial_equity=50))
    assert r.trades.iloc[0]["size_oz"] == pytest.approx(0.2)


def test_daily_loss_and_streak_limits():
    rows = [(100, 100, 98, 98)] * 20  # every long is stopped out on its entry bar
    m1 = bars(rows)
    sig = Signals(np.arange(0, 20, 2), np.ones(10, int), np.full(10, 1.0), np.full(10, 2.0))
    risk = RiskConfig(initial_equity=100, risk_pct=2.0, daily_loss_pct=5.0, max_consec_losses_per_day=10,
                      hard_stop_equity=0)
    r = run_backtest(m1, sig, NOCOST, risk)
    assert len(r.trades) == 3  # -2, -1.96, -1.92 => -5.88% >= 5% limit
    risk.max_consec_losses_per_day, risk.daily_loss_pct = 2, 1e9
    r = run_backtest(m1, sig, NOCOST, risk)
    assert len(r.trades) == 2 and r.skipped["consec_losses"] == 8


def test_hard_stop_freezes_account():
    m1 = bars([(100, 100, 90, 90)] * 6, start="2024-01-02 08:00")
    sig = Signals(np.arange(6), np.ones(6, int), np.full(6, 5.0), np.full(6, 5.0))
    risk = RiskConfig(initial_equity=50, risk_pct=20.0, hard_stop_equity=35, daily_loss_pct=1e9,
                      max_consec_losses_per_day=99, dd_reduce_pct=1e9)
    r = run_backtest(m1, sig, NOCOST, risk)
    assert r.stopped_out and r.final_equity <= 35 and len(r.trades) == 2


def test_htf_alignment_has_no_lookahead():
    m1 = bars([(i, i, i, i) for i in range(20)])
    from backtest.data import resample
    m5 = resample(m1, "5min")
    entry = htf_close_to_m1_entry(m1.index, m5.index, "5min")
    assert list(entry) == [5, 10, 15, 20]
    al = align_htf_to_m1(m1.index, m5.index, "5min", m5["close"].to_numpy())
    assert np.isnan(al[:5]).all() and al[5] == 4 and al[9] == 4 and al[10] == 9


def test_swap_charged_per_rollover_wednesday_triple():
    # Tue 20:00 -> Thu 20:00 UTC crosses Tue 21:00 (x1) and Wed 21:00 (x3) = 4 nights
    idx = pd.date_range("2024-01-02 20:00", "2024-01-04 20:00", freq="1h", tz="UTC").as_unit("ns")
    m1 = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0}, index=idx)
    cost = CostModel(spread_fixed=0.0, spread_bps=0.0, rollover_mult=1.0, slippage_stop=0.0, swap_annual_pct=36.5)
    t = run_backtest(m1, one(0, 1, 1.0, 0.0, exit_idx=len(idx) - 1), cost, LOOSE).trades.iloc[0]
    # 36.5%/yr = 0.1%/night of $100 = $0.10 per oz per night, 1 oz, 4 nights
    assert t["swap"] == pytest.approx(0.4) and t["pnl"] == pytest.approx(-0.4)
