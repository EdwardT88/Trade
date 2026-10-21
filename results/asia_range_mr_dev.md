# asia_range_mr: Asian-session mean reversion ("night scalping"), FX M15 — research log

**Verdict: NOT VIABLE.** The classic night-scalper setup (fade M15 band/z-score overextensions in the
Asian session) has a small gross edge that costs eat completely. A structural variant (fade the
thin-liquidity 15:00 → 19:00 New York move at the Asian open and hold to 07:00 London) looked strong on
dev: +0.136 R, t = 5.9. It **failed validation**: −0.025 R (t −0.7) at base costs and −0.069 R
(t −2.1) under stress. No revision was made after validation.

Protocol: dev 2013-01-01..2020-01-01 for every choice, including the pair set. Validation
2020-01-01..2022-03-05 was run once on the frozen choice. Costs: `backtest/markets.cost_model` (cent
spreads, 0.2 pip stop slippage, swap 3 %/yr), and stress = 1.5×. Backtests: 33 runs, which is 31 distinct
parameter combinations (listed below). Exploratory event studies on dev, all at zero cost on bid
closes: 9 studies, about 40 conditioning cuts.

## 1. Cost vs Asian-session volatility (dev, decided the pair universe)

Asian session = 19:00 New York → 07:00 London. ATR = M15 ATR(14) during the session.

| pair | spread (pips) | Asian M15 ATR | spread / ATR | median session range | spread / range |
|---|---|---|---|---|---|
| USDJPY | 1.5 | 6.5 | 0.23 | 36.5 | 0.041 |
| AUDUSD | 1.5 | 5.9 | 0.25 | 34.4 | 0.044 |
| AUDJPY | 2.0 | 8.1 | 0.25 | 45.0 | 0.044 |
| EURJPY | 2.0 | 8.0 | 0.25 | 43.1 | 0.046 |
| EURUSD | 1.3 | 4.4 | 0.29 | 24.8 | 0.052 |
| GBPJPY | 3.0 | 10.4 | 0.29 | 54.3 | 0.055 |
| GBPUSD | 1.7 | 5.4 | 0.31 | 29.4 | 0.058 |
| USDCAD | 2.0 | 4.6 | 0.43 | 24.1 | 0.083 |
| USDCHF | 1.8 | 3.7 | 0.48 | 20.0 | 0.090 |
| EURGBP | 1.8 | 3.2 | 0.57 | 15.6 | 0.115 |
| EURCHF | 2.2 | 3.3 | 0.66 | 14.8 | 0.149 |

The traditional night-scalper pairs (EURGBP, EURCHF, USDCHF, USDCAD) pay half to two-thirds of an
Asian M15 ATR per round trip at cent-account spreads, so they are structurally hopeless here. The pair
set was fixed by the rule spread / ATR < ~0.32, giving 7 pairs: EURUSD GBPUSD USDJPY AUDUSD EURJPY
GBPJPY AUDJPY. The per-pair dev backtests agreed (the 4 excluded pairs were ≤ 0 R).

## 2. Event studies (dev)

* **Rollover artefact:** M15 bars at 17:00-18:00 NY have about twice the normal range on EURCHF,
  EURGBP and USDCHF. This is bid-quote distortion from spread widening, and anything traded around it
  showed large "reversion" that cannot be traded. All entries were therefore placed at or after
  19:00 NY, 30 min after the engine's ×3 window ends.
* **M15 overextension fades** (z = (close − EMA20)/ATR14 > 1.5 / 2 / 2.5 / 3, BB(20,2) close outside,
  RSI(2) 95/5, RSI(14) 70/30, distance from a session VWAP proxy): the gross reversion is
  statistically real (t 3-4.5 on EURUSD, AUDUSD, USDCHF, EURGBP, EURCHF) but only **0.5-1.5 pips over
  1-4 h**, i.e. 0.5-1.4 spreads. Net of spread every bucket was negative, whether split by distance in
  spreads, by z, or by ATR/spread. Reversion was best in the post-NY lull and before Frankfurt, and
  weak at 01-03 UTC (Tokyo open/fix, AU data, CNY fix).
* **Overnight fade of the late-NY move:** move = close(19:00 NY) − close(15:00 NY). Fading the top and
  bottom quintiles gave a positive forward return to 07:00 London on all 11 pairs (3-8 pips, t 3-4.6
  on 6 pairs). Most of it came from the 15:00-16:30 NY part, which is before the rollover, so it is
  not a rollover artefact. Lookback windows 12-16, 13-19, 14-19 and 16:30-19 were clearly weaker
  (6 windows tested). Reversion built up through the night: about 1.2 spreads after 2 h, 1.9 after
  4 h, 3.0 after 8 h.

## 3. Backtests on dev (no account limits, base costs)

| # | variant | pairs | n | avg R | t | med hold h |
|---|---|---|---|---|---|---|
| 1 | M15 z(EMA20)>2.5, SL 2 ATR14, TP at mean, ≤3 h, 19:00 NY-06:00 London | 11 | 11462 | −0.119 | −13.8 | 1.8 |
| 2-19 | late-NY fade grid: thr {1,1.5,2} × SL {2,3,4} ATR96 × exit {4 h, 07:00 London} | 11 | 2273-6570 | 4 h exit: 0.001-0.062; London exit: 0.042-0.111 | 0.1-5.2 | 4 / 7 |
| 20 | **thr 1.5, SL 3, exit 07:00 London (final)** | 7 | 2677 | **+0.136** | **5.91** | 7.0 |
| 21 | thr 2.0 | 7 | 1622 | +0.144 | 4.86 | 7.0 |
| 22-23 | TP 0.5 / 1.0 × move | 7 | 2677 | +0.002 / +0.036 | 0.2 / 2.4 | 1.5 / 3.2 |
| 24-25 | exit 06:00 / 08:00 London | 7 | 2677 | +0.119 / +0.150 | 5.3 / 6.0 | 6 / 8 |
| 26-27 | lookback from 14:00 / 16:00 NY | 7 | 3444 / 1951 | +0.020 / +0.066 | 1.1 / 2.6 | 7 |
| 28-29 | signal 18:30 / 19:30 NY (window shifted) | 7 | 2652 / 2704 | +0.093 / +0.027 | 4.0 / 1.3 | 7.5 / 6.5 |
| 30-31 | thr 1.25 / 1.75 | 7 | 3471 / 2125 | +0.122 / +0.149 | 6.3 / 5.8 | 7 |
| 32-33 | SL 2.5 / 3.5 | 7 | 2677 | +0.132 / +0.117 | 5.1 / 5.8 | 7 |

Dev checks on the final choice: 6 of 7 years > 0 (2017 −0.02 R); long +0.127 / short +0.144; every
weekday > 0; dev stress +0.089 R (t 3.9); no swap paid. Warning signs that were visible before
validation: TPs destroyed the edge, the result was sensitive to the clock (lookback from 14:00 → 0.02 R,
signal 30 min later → 0.03 R), and holding shorter than the full night cut the edge in half.

## 4. Final rules (frozen before validation)

M15 bars. Mon-Thu, at the close of the bar ending 19:00 America/New_York:
move = close − close(bar ending 15:00 NY), A = ATR(96) on M15 (MT5 iATR). If |move| ≥ 1.5·A, open a
market order against the move at the 19:00 bar open. Stop at 3·A, no TP. Close at the first bar at or
after 07:00 Europe/London (about 7 h later). One position per pair.
Pairs: EURUSD GBPUSD USDJPY AUDUSD EURJPY GBPJPY AUDJPY.

## 5. Results

| set | n | avg R | se | t | win % | PF | med hold h | trades / month |
|---|---|---|---|---|---|---|---|---|
| dev 2013-2019, base | 2677 | +0.136 | 0.023 | 5.91 | 49.5 | 1.37 | 7.0 | 31.9 |
| dev, stress 1.5 | 2677 | +0.089 | 0.023 | 3.94 | 47.9 | 1.23 | 7.0 | 31.9 |
| **validation 2020-03/2022, base** | 792 | **−0.025** | 0.033 | −0.74 | 44.3 | 0.94 | 7.0 | 30.4 |
| **validation, stress 1.5** | 792 | **−0.069** | 0.033 | −2.11 | 42.3 | 0.83 | 7.0 | 30.4 |
| dev + validation, base | 3469 | +0.099 | 0.019 | 5.14 | 48.3 | 1.27 | 7.0 | 31.5 |

Per pair, avg R (n): dev → validation
EURUSD +0.118 (297) → +0.124 (94); GBPUSD +0.057 (245) → +0.003 (101); USDJPY +0.083 (475) → +0.023 (115);
AUDUSD +0.146 (452) → −0.104 (128); EURJPY +0.190 (390) → −0.012 (106); GBPJPY +0.157 (375) → −0.022 (113);
AUDJPY +0.171 (443) → −0.126 (135).

Validation diagnostics (no rule changes):
* The gross edge, at zero cost, fell from +0.12…+0.28 R per pair on dev to about +0.08 R pooled
  (1.5-2.5 pips, roughly one spread).
* By year: 2020 −0.02, 2021 +0.04, Jan-Mar 2022 −0.27 R.
* By side: longs −0.11 R (t −2.5), shorts +0.05 R.
* All 11 pairs on validation: −0.032 R. Pair selection did not cause the failure.

The pooled dev+validation t of 5.1 is almost entirely the in-sample dev result. It does **not** meet the
pre-registered rule, which needs validation avg R > 0 at base costs and under stress.

## 6. Conclusion

At cent-account spreads, Asian-session mean reversion on M15 is not a deployable edge. The bar-level
fades lose to the spread outright. The overnight late-NY fade worked in 2013-2019 and did not survive
2020-2022, which is consistent with an overfit clock anchor or a decayed effect. If it is ever revisited,
it should be treated as a new hypothesis that needs fresh out-of-sample data (e.g. 2026), and never
traded on the current evidence.
