"""Profit vs trade duration for swing_pullback: grid of max-hold caps and take-profits over 2022-23 / 2024 / 2025."""
import sys, itertools; from pathlib import Path; ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np, pandas as pd
from backtest.data import load_m1
from backtest.engine import CostModel, RiskConfig, run_backtest
from backtest.metrics import summarize
from strategies import swing_pullback as S
from report import keep_from, WARMUP
full = load_m1()
P = (("2022-01-01","2024-01-01"),("2024-01-01","2025-01-01"),("2025-01-01","2026-01-01"))
rows = []
for hold_h, tp in itertools.product([24, 36, 48, 72, 240], [0.0, 1.5, 2.0, 3.0]):
    p = {**S.DEFAULT_PARAMS, "max_hold_days": hold_h/24, "tp_r": tp}
    out = {"hold_cap": "Jumat" if hold_h == 240 else f"{hold_h}j", "tp": tp or "-"}
    hs, rs = [], []
    for s, e in P:
        t0, t1 = pd.Timestamp(s, tz="UTC"), pd.Timestamp(e, tz="UTC")
        m1 = full[(full.index >= t0 - WARMUP) & (full.index < t1)]
        res = run_backtest(m1, keep_from(S.generate_signals(m1, **p), m1.index, t0), CostModel(swap_annual_pct=5.0), RiskConfig())
        st = summarize(res, s, e); t = res.trades
        hs.append((t.exit_time - t.entry_time).dt.total_seconds()/3600); rs.append(t.r)
        out[s[:4]] = st["final_equity"]; out[f"dd{s[2:4]}"] = st.get("max_dd_pct")
    h = pd.concat(hs); r = pd.concat(rs)
    out.update({"avgR": round(r.mean(),3), "minPer": min(out["2022"], out["2024"], out["2025"]), "med_h": round(h.median(),1), "avg_h": round(h.mean(),1), "n": len(r)})
    rows.append(out)
df = pd.DataFrame(rows)
print(df.sort_values("avg_h").to_string(index=False))
