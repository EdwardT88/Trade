"""Lower-timeframe variants of the EA strategy on gold M1 2022-2025 (swap-free, cost stress 1.0 / 1.5).

    python scripts/timeframe_check.py
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest.engine import run_backtest
from backtest.markets import cost_model, keep_entries_from, load, r_stats, research_risk
from strategies import swing_pullback as S
CFG = {
 "EA: H4 tren / H1 entry":      dict(trend_tf="4h", entry_tf="1h", atr_tf="4h"),
 "H4 tren / M30 entry":         dict(trend_tf="4h", entry_tf="30min", atr_tf="4h"),
 "H4 tren / M15 entry":         dict(trend_tf="4h", entry_tf="15min", atr_tf="4h"),
 "H2 tren / M30 entry (x0.5)":  dict(trend_tf="2h", entry_tf="30min", atr_tf="2h"),
 "H1 tren / M15 entry (x0.25)": dict(trend_tf="1h", entry_tf="15min", atr_tf="1h"),
 "M30 tren / M5 entry":         dict(trend_tf="30min", entry_tf="5min", atr_tf="30min"),
 "M15 tren / M5 entry":         dict(trend_tf="15min", entry_tf="5min", atr_tf="15min"),
}
PER = [("2022-01-01","2024-01-01"),("2024-01-01","2026-01-01")]
for name, p in CFG.items():
    out=[]
    for s,e in PER:
        bars = load("XAUUSD", s, e)
        params = {**S.DEFAULT_PARAMS, "max_hold_days": 3, **p}
        sig = keep_entries_from(S.generate_signals(bars, **params), bars.index, s)
        for stress in (1.0, 1.5):
            t = run_backtest(bars, sig, cost_model("XAUUSD", stress=stress, swap_annual_pct=0), research_risk()).trades
            st = r_stats(t, s, e)
            out.append((s[:4]+"-"+str(int(e[:4])-1), stress, st.get("n"), st.get("avg_r"), st.get("t"), st.get("trades_per_month"), st.get("med_hold_h")))
    print(name)
    for o in out: print("   ", o)
