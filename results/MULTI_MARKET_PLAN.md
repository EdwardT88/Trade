# Multi-market short-duration search — pre-registered rule

Written before any agent ran. The 2026 samples (Mar 26 – Sep 25 2026, M1/M15: EURUSD, GBPUSD, USDJPY,
AUDUSD, USDCAD, USDCHF, EURGBP, EURJPY, XAUUSD, XAGUSD) are moved out of data/ and hidden from all agents.

Data for development: FX M15 2012-11 – 2022-03 (11 pairs), gold H1 2012 – 2021 + gold M1 2022 – 2025.
Costs: `backtest/markets.py` cent-account spreads (EURUSD 1.3 pips … GBPJPY 3.0 pips, gold max($0.25, 0.8 bps)),
stop slippage 0.2 pip, swap 3%/yr (gold 5%). Stress = 1.5× spread and slippage.

Styles (one researcher each): Asian-session range mean reversion, session-open breakouts,
intraday H1 momentum/reversal basket, calendar/time-of-day flows (Tokyo fix/gotobi, London fix, etc.).

## A style (with the pair set chosen on dev) is deployable only if ALL hold
1. Pooled avg R > 0 after base costs on dev (2013-01-01 – 2020-01-01) **and** on validation (2020-01-01 – 2022-03-05).
2. Pooled dev+validation t-stat ≥ 2.0.
3. Validation avg R > 0 under stress costs.
4. Median holding time ≤ 24 h.
5. Final holdout 2026 (pairs available in the sample): pooled avg R > 0 after base costs.
   Holdout window: trades entered 2026-05-01 – 2026-09-25 (Mar 26 – Apr 30 only warms indicators up),
   run with `scripts/holdout_2026.py` (FX on M15, gold/silver on M1).

If no style passes, the answer is reported as "no robust short-duration edge found".
