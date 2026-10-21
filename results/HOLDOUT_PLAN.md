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
