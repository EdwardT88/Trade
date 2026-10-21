# session_breakout: research log (session-open breakouts, FX M15 + gold H1)

**Verdict: marginal, not robust. I would not deploy it.** Breakouts of the pre-session range at the London and
New York opens, and fades of those breaks, have about 0 R gross edge on 11 FX pairs over 2013-2019. They lose
0.06-0.40 R per trade after cent-account costs. One narrow cell stayed positive: the London **first-hour**
opening-range breakout, traded only in the direction of the H1 EMA(100) trend, on **GBPUSD and GBPJPY**,
held to 16:00 London. It returns +0.06 R/trade on dev and on validation at base cost, and its pooled
dev+val t of 2.05 clears the pre-registered t >= 2 gate by a hair. It does not survive realistic stress:
+0.01 R on validation at 1.5x costs (dev+val t = 0.81). It lost 0.17 R/trade through all of 2021.
Validation's profit comes from a few volatility-shock days (the top 10 trades = 151% of validation R).
The validation max drawdown is 64 R on a +32 R total.

## Protocol
- Dev 2013-01-01..2020-01-01 for all tuning and for choosing pairs. Validation 2020-01-01..2022-03-05 was run once
  for the frozen choice (base + 1.5x stress). There was no revision after validation.
- Engine and costs: `backtest/engine.py` and `backtest/markets.py` cent-account cost models (GBPUSD 1.7 pips,
  GBPJPY 3.0 pips, 0.2 pip stop slippage, rollover spread x3, swap 3%/yr), `research_risk()`, R statistics.
- **33 distinct parameter sets** were backtested on dev (all listed below). Twelve were also re-run at zero cost as
  gross diagnostics. Before that, exploratory event studies looked at gross forward drift after the first M15
  close beyond the range: 3 FX range definitions + the London first-hour opening range, 3 gold-H1 definitions,
  and about 15 conditioning cuts (break time, range width, break-bar extension, direction, trend alignment).
- EURCHF was in the dev context runs but never in a candidate set (SNB peg until 2015-01-15).
- Times: zoneinfo local time (Europe/London / America/New_York), DST-aware. Volatility yardstick: H1 ATR(24)
  (SMA of true range = MT5 iATR) of the last H1 bar completed at range end.

## 1. Event study (dev, all 11 FX pairs, gross, H1-ATR units)
First M15 close beyond the range, entry at the next open, forward move in the break direction:

| definition | n | 1-2 h | to noon | to 16:00 | spread cost |
|---|---|---|---|---|---|
| London: Asian range 00-07 London, breaks 07-11 | 15,921 | -0.011 | -0.016 | -0.025 | 0.138 |
| NY: London-morning range 03-08 NY, breaks 08-11 NY | 13,925 | -0.005 | -0.007 | -0.022 | 0.136 |
| NY: 08:00-09:30 NY range, breaks 09:30-12 NY | 15,900 | +0.007 | +0.007 | +0.022 | 0.135 |

- Every slice is within about ±0.1 ATR. The cost alone is 0.09-0.25 ATR. Pooled t-stats overstate significance
  because pairs are correlated on the same day.
- London breaks at 07:30-08:00 (just before the London open) reverse by -0.06 to -0.10 ATR. Narrow Asian ranges
  also reverse, and wide ones continue weakly. None of these effects is large enough to pay for the spread.
- Trend alignment (break direction = sign(H1 close - EMA100)) helps a little. On the London first-hour opening
  range (08-09 London, breaks 09-12), with-trend breaks drift +0.075 ATR by 16:00 and against-trend breaks
  drift -0.04.
- Gold H1 (dev): London Asian-range breaks drift +0.14 ATR by 16:00 (t 1.7, n 1,127). NY breaks drift about 0.

## 2. Dev backtests (base costs, all 11 FX pairs unless noted; GBPUSD / GBPJPY per-pair avg R shown)
Shared settings: entry at the next open after an M15 close beyond the range, one trade per day, opposite-side
stop (unless noted), skip if stop is outside 0.25-4 ATR.

| # | config | n | avg R | t | med hold h | GBPUSD | GBPJPY | gross avg R |
|---|---|---|---|---|---|---|---|---|
| L1 | Asian 00-07 London bo, win 240, TP 1R, flat 16 | 15051 | -0.071 | -10.1 | 4.8 | -0.046 | -0.034 | +0.007 |
| N1 | London-morning 03-08 NY bo, TP 1R, flat 16 NY | 11506 | -0.063 | -9.7 | 6.0 | -0.036 | -0.049 | 0.000 |
| N2 | 08-09:30 NY range bo, TP 1R, flat 16 NY | 15252 | -0.092 | -15.2 | 4.8 | -0.066 | -0.061 | -0.003 |
| F1 | fade first London break 07-08, 1 ATR stop, TP 1R, flat 12 | 8498 | -0.126 | -12.3 | 1.0 | -0.045 | -0.088 | +0.018 |
| F2 | same, stop beyond break bar +0.1 ATR | 3408 | -0.395 | -25.5 | 0.0 | -0.279 | -0.384 | -0.062 |
| F3 | London reclaim fade (break then close back in <= 4 bars), stop beyond extreme | 8609 | -0.196 | -18.9 | 0.8 | -0.099 | -0.110 | -0.007 |
| F4 | NY (03-08 range) reclaim fade | 7358 | -0.164 | -15.1 | 0.8 | -0.093 | -0.095 | +0.001 |
| F5 | NY 09:30 reclaim fade | 8469 | -0.191 | -5.7 | 0.8 | -0.088 | -0.227 | -0.008 |
| **B1** | **London ORB 08-09, win 180, trend EMA100, no TP, flat 16** | 8976 | -0.076 | -5.7 | 5.0 | **+0.070** | **+0.050** | +0.036 |
| B2 | Asian 00-07 London bo, trend EMA100, no TP, flat 16 | 8310 | -0.061 | -4.9 | 6.8 | +0.005 | -0.018 | +0.022 |
| B3 | B1, flat 20:00 | 8976 | -0.086 | -5.8 | 6.2 | +0.014 | +0.022 | |
| B4 | B1, EMA200 | 8804 | -0.072 | -5.3 | 5.0 | +0.044 | +0.047 | |
| B5 | B1, EMA50 | 9255 | -0.085 | -6.6 | 5.0 | +0.061 | +0.030 | |
| B6 | B1, TP 2R | 8976 | -0.074 | -6.4 | 4.2 | +0.010 | +0.026 | |
| B7 | B1, ORB 30 min (08:00-08:30) | 9320 | -0.117 | -7.7 | 4.2 | +0.043 | +0.012 | |
| B8 | B1, ORB 90 min (08:00-09:30) | 7581 | -0.075 | -5.7 | 4.8 | +0.047 | +0.010 | |
| B9 | B1, window 120 | 8114 | -0.081 | -5.7 | 5.2 | +0.046 | +0.028 | |
| B10 | B1, window 300 | 9904 | -0.066 | -5.3 | 4.5 | +0.073 | +0.038 | |
| B11 | B1 without trend filter | 16918 | -0.089 | -9.1 | 5.0 | +0.034 | -0.020 | |
| B12 | B1, flat 14:00 | 8976 | -0.080 | -7.3 | 3.8 | +0.006 | -0.021 | |
| B13 | B1, range width <= 1.5 ATR | 6426 | -0.109 | -6.4 | 4.5 | +0.073 | -0.014 | |
| B14 | B1, range width >= 0.75 ATR | 7978 | -0.061 | -4.5 | 5.2 | +0.057 | +0.031 | |
| B15 | B1, breakeven at 1R then 1 ATR trail | 8976 | -0.069 | -6.3 | 3.5 | +0.034 | +0.025 | |

Gold (XAUUSD H1, dev, base costs):

| # | config | n | avg R | t | med hold h |
|---|---|---|---|---|---|
| G1 | Asian 00-07 London bo, no TP, flat 16 | 1047 | -0.001 | -0.0 | 6 |
| G2 | G1 + trend EMA100 | 561 | +0.063 | 1.3 | 7 |
| G3 / G4 | G2 with EMA50 / EMA200 | 588 / 546 | +0.032 / +0.060 | 0.7 / 1.3 | 7 |
| G5 / G6 | G2 flat 20:00 / 12:00 | 561 / 561 | +0.114 / -0.048 | 2.0 / -2.2 | 10 / 3 |
| G7 / G8 / G9 | G2 TP 2R / range to 08:00 / mid stop | 561 / 508 / 605 | +0.017 / +0.053 / +0.080 | 0.4 / 1.1 / 1.2 | 6 / 6 / 5 |
| G10 | B1 rules on gold (H1) | 657 | +0.014 | 0.3 | 4 |

Gold is positive only when trades are held through the London afternoon (12:00 flat is negative). It is driven by
2013/2015/2017; 2018-2019 are negative in almost every variant. The B1 rules give about 0 on gold, so gold
was left out rather than giving it its own rule set.

## 3. Final choice (frozen on dev)
**B1 on GBPUSD + GBPJPY** (`DEFAULT_PARAMS`, `PAIRS`). Pairs were chosen on dev because they were the only 2 of 11
that were positive net in B1 and in nearly all of its neighbours. There is also a structural story: GBP is the
home currency of the London session, and UK data comes out at 07:00 and 09:30 London, inside the trade window.
They also had the highest gross R in B1 (+0.16 / +0.15 R against -0.13..+0.07 for the other pairs). This is still
a selection of 2 out of 11, and the t-stats below are not adjusted for it or for the 33 combinations tried.

Rules (all times Europe/London local, DST-aware):
- Range = high/low of the M15 bars 08:00-08:45.
- Trend = sign(close - EMA(100)) of the H1 bar 08:00-09:00.
- Signal: the first M15 bar between 09:00 and 12:00 that closes beyond either side of the range. If its direction
  equals the trend, place a market order at the next bar open. Otherwise there is no trade that day.
- Stop: at the opposite side of the range. Skip the trade if the stop is outside 0.25-4 H1 ATR(24).
- Exit: no target; close at 16:00 London.

## 4. Results
| | n | avg R | se | t | win% | PF | med hold h | trades/mo |
|---|---|---|---|---|---|---|---|---|
| dev 2013-19, base | 1564 | +0.060 | 0.034 | 1.78 | 43.0 | 1.12 | 5.2 | 18.6 |
| dev 2013-19, stress 1.5 | 1564 | +0.028 | 0.033 | 0.84 | 41.8 | 1.06 | 5.2 | 18.6 |
| **validation 2020-22.03, base** | 500 | **+0.063** | 0.062 | 1.02 | 41.4 | 1.12 | 5.2 | 19.2 |
| **validation, stress 1.5** | 500 | **+0.010** | 0.060 | 0.17 | 39.6 | 1.02 | 5.0 | 19.2 |
| dev+val base | 2064 | +0.061 | 0.030 | **2.05** | | | | |
| dev+val stress | 2064 | +0.024 | 0.029 | 0.81 | | | | |

Per pair (avg R / n): dev GBPUSD +0.070/786, GBPJPY +0.050/778. Val GBPUSD +0.051/247, GBPJPY +0.075/253.
Val stress GBPUSD +0.029, GBPJPY -0.008.

Robustness:
- **By year:** 2013 -0.02, 2014 -0.14, 2015 +0.19, 2016 +0.03, 2017 +0.03, 2018 +0.14, 2019 +0.16.
  Validation: 2020 +0.21, **2021 -0.17 (223 trades, about -39 R)**, 2022 Q1 +0.54 (39 trades).
- **Concentration:** in validation the top 10 trades = 151% of total R. Profit comes from the March 2020 and
  February-March 2022 volatility. On dev the top 10 = 67%.
- **Drawdown:** max DD 42 R (dev) and 64 R (validation). Longest losing streak 18 (dev) and 12 (validation). Only 49-52%
  of months are positive. At 2% risk on a $50 cent account this would hit the $35 hard stop.
- **Shorts vs longs:** shorts are better (+0.10 vs +0.02 R on dev). GBP fell through most of 2014-2016.
- **Neighbours:** GBPUSD is positive net in all 13 one-at-a-time neighbours of B1 (B3-B15), GBPJPY in 10 of 13
  (it is negative without the trend filter, with a 14:00 exit, and with the width <= 1.5 ATR filter). All 11 pairs
  pooled are negative in every variant.
- **Costs:** each extra 0.5x spread costs about 0.03-0.05 R/trade. The median stop is about 33-37 GBPUSD pips.

## Assessment
The result mechanically clears pre-registered gates 1-4 at base cost (dev > 0, val > 0, t = 2.05, val stress
+0.010 > 0, median hold 5 h), each by the smallest possible margin. I don't think the edge is real enough for a
$50 account. It is 2 pairs picked out of 11 from 33 configurations, it vanishes at 1.5x costs, it lost money
for all of 2021, and it relies on rare shock days. Gate 5 (2026 holdout) can only check GBPUSD, because there is
no GBPJPY in the 2026 sample. The clean finding is that session-open breakouts and their fades on FX have
no gross edge; costs decide the result.
