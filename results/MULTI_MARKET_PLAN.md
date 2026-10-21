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

---

## Results (2026 holdout run after the rule above was committed)

| Style | Pairs | Dev 2013–19 | Val 2020–22 | Val stress | Median hold | 2026 holdout | Verdict |
|---|---|---|---|---|---|---|---|
| asia_range_mr (fade 15→19 NY move, exit 07:00 London) | 7 FX | +0.136R (n 2677, t 5.9) | **−0.025R** | −0.069R | 7 h | not run | fails gate 1 |
| session_breakout (London first-hour ORB with trend) | GBPUSD, GBPJPY | +0.060R (t 1.8) | +0.063R | +0.010R | 5 h | **−0.26R** (n 55, GBPUSD) | fails gate 5 |
| intraday_h1_basket (news-shock continuation, peer-confirmed) | 10 FX + gold | +0.289R (t 6.1) | +0.071R (n 81, 24 days) | +0.055R | 6 h | **−0.009R** (n 48) | fails gate 5 |
| calendar_flows (month-end MTD into London 4pm fix, JPY pairs) | 4 JPY pairs | +0.171R (t 4.9) | +0.043R (t 0.6) | +0.024R | 4 h | +0.05R (n 8; stress −0.19R) | passes formally, evidence negligible |

**Conclusion: no robust short-duration edge was found.** The only formal survivor trades about one
month-end afternoon a month (4 trades), its post-2019 edge is ≈ +0.04R/trade (t 0.6) and the 2026 holdout
has 8 trades. At 2% risk that is roughly +0.3%/month expected, well inside noise. It is not deployed as a
growth strategy.
