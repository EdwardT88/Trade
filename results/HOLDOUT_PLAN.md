# Holdout 2025 — pre-registered decision rule

Written **before** any strategy was run on 2025 data. The 2025 file was kept outside the repo
data folder during all development; no researcher had access to it.

## Context
- Five intraday scalping archetypes (trend pullback, opening-range breakout, Asian range,
  mean reversion, momentum breakout) were developed on 2022–2023 and validated on 2024.
  All five were judged **not viable** (≈0R gross edge, negative after spread). They are not
  candidates for deployment and will only be run on 2025 for information.
- Swing/trend candidates were developed on 2022–2023 and validated once on 2024.

## Data fix applied before the holdout
HistData XAUUSD timestamps follow New York wall-clock time (EST/EDT), not fixed EST
(verified: NFP spikes at 13:30 UTC in winter and 12:30 UTC in summer after the fix).
All candidates are re-run on the corrected data for dev, 2024 and 2025.

## Primary candidate
`swing_pullback` (H4 EMA40 trend, H1 RSI(14) cross back through 40/60, 2×ATR(H4) stop,
3×ATR chandelier trail, flat Friday 20:00 UTC), parameters frozen as in its DEFAULT_PARAMS.

## Decision rule for the primary candidate (base costs: default spread + 5%/yr swap)
Deploy to the EA if **all** hold on 2025:
1. avg R per trade > 0 after costs (no-limits run), and
2. $50 account simulation with default risk rules does not hit the hard stop, and
3. max drawdown of the account simulation < 25%.

Otherwise: do not deploy as a validated strategy; report the result honestly.

Secondary candidates (`swing_breakout`, `swing_ma_regime` if viable) are evaluated with the
same rule and reported, but cannot replace the primary on the basis of 2025 alone
(choosing the best of several on the holdout would turn it into another in-sample test).

---

## Result (run after the rule above was committed)

Corrected (true-UTC) data, 60-day indicator warm-up, default spread, swap 5%/yr, $50 cent account,
default risk rules. Full numbers: `results/<strategy>/summary.json`, trades in `trades_*.csv`.

| Strategy | 2022–23 avg R | 2024 avg R | **2025 avg R** | 2025 trades | 2025 account | 2025 max DD | Hard stop |
|---|---|---|---|---|---|---|---|
| **swing_pullback (primary)** | +0.42 | +0.21 | **+0.26** | 53 | **+27.9%** | 9.9% | no |
| swing_breakout | +0.16 | +0.19 | +0.33 | 44 | +21.3% | 15.4% | no |
| swing_ma_regime | +0.20 | +0.08 | +0.11 | 58 | +9.0% | 13.0% | no |

**Decision: swing_pullback passes all three criteria → deployed in `mql5/GoldSwingCent.mq5`.**

Caveats: shorts lost in 2024 (−0.52R, 15 trades) and 2025 (−0.13R, 16 trades), both strong gold bull
years; longs carried the result. Default stays long+short as pre-registered; `InpSides` allows long-only.
Pooled 2022–2025: 174 trades, +0.31R/trade, SE 0.10 (includes the in-sample dev period).

Scalping archetypes on 2025 (information only, swap 0): trend_pullback −15.0%, session_orb −22.3%,
asia_range −16.5%, mean_reversion −12.7%, momentum_breakout −13.9% (account returns).
