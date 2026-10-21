# mean_reversion: research log (intraday mean-reversion scalp, XAUUSD)

**Verdict: not viable.** Classic intraday fades on gold have no gross edge in 2022–2023: Bollinger pierces,
RSI extremes, rolling-range sweeps and large-stretch fades all average about 0 R before costs. Costs are
0.10–0.25 R per trade at M5/M15 stop sizes, so every one of these variants loses money.

The only family with a positive gross edge on dev was a fade of failed breaks of the **previous day's high/low**,
taken only on quiet days. Its result was small: +0.066 R/trade net, t ≈ 1.1, and most of it came from 2023 Q1.
It **failed the 2024 validation**: −0.116 R/trade net, −0.06 R before costs, and 3 of 4 quarters negative.
I made no revision after seeing 2024, because any change would have been fitted to 2024.

## Protocol
- Development: 2022-01-01 .. 2024-01-01. Validation: 2024, run once with the final parameters. No revision afterwards.
- Default `CostModel`: spread max($0.25, 0.8 bps), ×3 at 21–22 UTC, $0.05 stop slippage.
  Stress test on 2024: spread max($0.40, 1.2 bps), $0.10 slippage.
- **41 strategy backtests on dev:**
  - 39 parameter sets (table below);
  - 2 zero-cost hour-breakdown runs of the BB fade (all hours 0–21 UTC, M5 and M15);
  - 3 zero-cost diagnostics that repeat S1–S3 with the same parameters.
- **About 250 cells of exploratory statistics on dev**, none of them on 2024:
  - forward returns after BB z-score extremes;
  - return autocorrelation by timeframe and hour;
  - reversal after large multi-bar moves;
  - zero-cost symmetric-bracket outcomes for stretch events (180 cells);
  - HTF-trend agreement;
  - session-to-session reversals;
  - London AM/PM fix;
  - Asian-range, previous-day and current-day extreme sweeps.

  That much searching guarantees some false positives, which is why I treat a dev t-stat of about 1 as noise.
  2024 confirmed it.
- All distances are in ATR units. The final version uses H1 ATR(14), MT5 iATR style (SMA of true range).

## What the data says (dev 2022–2023)
- **Short-horizon returns are almost a random walk.** Lag-1 autocorrelation of M1–H1 returns is between −0.03
  and +0.02 in every session.
  - The only large mean-reversion number is in 21–23 UTC (rollover). That comes from bid-quote artefacts
    while spreads are wide, so it cannot be traded and the rules forbid it anyway.
- **Bollinger / RSI / rolling-range fades have zero gross edge.** Zero-cost averages: BB M5 +0.002 R,
  rolling 4h sweep −0.006 R, BB M15 −0.033 R.
  - Adding an HTF regime filter changes the gross by less than ±0.03 R: H1 EMA50 "flat", "with trend"
    (buy dips in an uptrend), or D1/H4 trend agreement. With trend was not better than against trend.
  - No hour of the day is positive in both 2022 and 2023.
- **Large stretch moves** (more than 4× the pre-move M5 ATR in 30 min) revert by about 0.3 M5-ATR close-to-close
  in London. With a stop, though, the noise stops the trade out first: zero-cost bracket ≈ +0.02 R, net −0.21 R (ST1).
- **Asian-range sweeps during London keep going.** Fading them averages −0.08 to −0.17 R even at zero cost.
  This is a useful hint for the breakout researchers.
- **Previous-day high/low (PDH/PDL) failed breaks** are the only fade with consistent positive gross:
  +0.03 to +0.19 R, positive in both years and on both sides.
  - Costs are about $0.30 per round trip, so stops need to be large (at least 1 H1 ATR, about $4) to keep
    costs below 0.1 R.
  - A "quiet day" filter improves it monotonically: day range so far ≤ 0.8 / 1.0 / 1.2 / off × D1 ATR gives
    +0.084 / +0.066 / +0.053 / +0.027 R net.
  - Days that have already travelled a full average range are trend or news days, and fading on them loses.

## Dev sweep (no-limits, default costs)
"zc" = average R at zero cost (gross edge). For S1–S6 and ST1 the unit is the signal-timeframe ATR(14);
for everything else it is H1 ATR(14). Unless stated otherwise, PDH/PDL rows use: M5 signals, 07–20 UTC,
90-min time exit, flat at 20:45 UTC.

| # | setup / change | trades | /mo | win% | avg R | zc R | avg win R | PF | maxDD% | hold | 2022 / 2023 | L / S |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | BB(20,2) pierce M5, 07–12, stop extreme+0.3, min 2 ATR, TP 1R, 60 min | 1967 | 82 | 44.3 | −0.116 | +0.002 | 0.78 | 0.70 | 98.8 | 35 | −0.131 / −0.098 | −0.125 / −0.106 |
| S2 | BB pierce M15, 07–12, min 1 ATR, 90 min | 1376 | 57 | 42.2 | −0.168 | −0.033 | 0.83 | 0.65 | 98.7 | 41 | −0.183 / −0.151 | |
| S3 | 4h-range sweep M5, 07–12 | 1412 | 59 | 43.3 | −0.129 | −0.006 | 0.77 | 0.67 | 96.9 | 36 | −0.148 / −0.109 | |
| S4 | 8h-range sweep M15, 07–12 | 938 | 39 | 41.3 | −0.174 | | 0.87 | 0.69 | 96.2 | 39 | −0.175 / −0.174 | |
| S5 | RSI(14) 30/70 cross-back M5, 07–12 | 748 | 31 | 44.3 | −0.115 | | 0.75 | 0.69 | 84.2 | 38 | −0.161 / −0.057 | |
| S6 | BB pierce M5, 01–20 | 1521 | 63 | 41.9 | −0.174 | | 0.80 | 0.67 | 99.6 | 32 | −0.153 / −0.258 | |
| ST1 | stretch > 4 ATR in 30 min, M5, 07–12, 12-bar cooldown | 413 | 17 | 40.7 | −0.206 | +0.019 | 0.93 | 0.66 | 83.0 | 15 | −0.179 / −0.235 | |
| B1 | BB M5, H1-ATR stops (min 0.5), 07–12, H1 trend flat (<1 ATR) | 656 | 27 | 43.0 | −0.157 | +0.012 | 0.84 | 0.63 | 88.2 | 30 | −0.194 / −0.114 | |
| B2 | B1 with trend = "with" (buy dips in uptrend) | 1040 | 43 | 43.0 | −0.147 | −0.011 | 0.84 | 0.67 | 95.4 | 29 | −0.132 / −0.164 | |
| B3 | B1, 01–12 UTC | 1375 | 57 | 41.8 | −0.160 | −0.005 | 0.73 | 0.61 | 98.3 | 38 | −0.172 / −0.146 | |
| B4 | B1 on M15 | 377 | 16 | 44.6 | −0.140 | −0.003 | 0.79 | 0.68 | 68.8 | 46 | −0.200 / −0.071 | |
| R1 | 24h-range sweep M5, 07–17, P7 stops | 746 | 31 | 43.2 | −0.061 | +0.015 | 0.97 | 0.83 | 70.9 | 57 | −0.101 / −0.013 | |
| R2 | 8h-range sweep M5, 07–17, P7 stops | 1513 | 63 | 42.3 | −0.096 | −0.017 | 0.89 | 0.75 | 95.3 | 60 | −0.106 / −0.084 | |
| P1 | PDH/PDL fade, buf 0.2, min 0.4, max 1.5 ATR, TP 1R | 292 | 12 | 48.3 | −0.073 | +0.034 | 0.88 | 0.84 | 50.2 | 34 | −0.093 / −0.055 | −0.079 / −0.066 |
| P2 | P1, TP 1.5R | 292 | 12 | 43.5 | −0.057 | +0.071 | 1.11 | 0.87 | 49.6 | 42 | −0.121 / +0.005 | |
| P3 | P2, buf 0.3, min 0.7 | 285 | 12 | 46.0 | −0.019 | +0.107 | 1.00 | 0.94 | 43.0 | 51 | −0.086 / +0.043 | |
| P4 | P2, 07–17 | 273 | 11 | 43.6 | −0.047 | +0.085 | 1.11 | 0.89 | 47.3 | 41 | −0.123 / +0.025 | |
| P5 | P1, TP 2R | 292 | 12 | 39.7 | −0.053 | +0.076 | 1.29 | 0.86 | 50.3 | 47 | −0.187 / +0.075 | |
| P6 | P2 on M15 | 242 | 10 | 43.4 | −0.109 | +0.003 | 0.94 | 0.78 | 51.8 | 51 | −0.134 / −0.082 | |
| P7 | **buf 0.3, min 1.0, max 2.0, TP 1.5R** | 310 | 13 | 47.7 | +0.027 | +0.115 | 0.92 | 1.04 | 29.5 | 63 | −0.019 / +0.073 | +0.029 / +0.024 |
| P8 | buf 0.3, min 0.7, TP 1R | 285 | 12 | 50.9 | −0.024 | +0.060 | 0.83 | 0.93 | 38.6 | 43 | −0.052 / +0.001 | |
| P9 | buf 0.3, min 1.0, max 2.0, TP 1R | 310 | 13 | 51.3 | −0.001 | +0.083 | 0.77 | 0.98 | 30.5 | 54 | −0.013 / +0.011 | |
| N1 | P7, TP 1.25 | 310 | 13 | 49.4 | +0.013 | +0.105 | 0.85 | 1.01 | 29.8 | 59 | −0.030 / +0.057 | |
| N2 | P7, TP 2.0 | 310 | 13 | 46.1 | −0.009 | +0.076 | 0.90 | 0.95 | 35.5 | 68 | −0.096 / +0.079 | |
| N3 | P7, min 0.8 | 310 | 13 | 45.5 | −0.024 | +0.089 | 0.96 | 0.93 | 42.6 | 56 | −0.075 / +0.028 | |
| N4 | P7, min 1.2, max 2.5 | 342 | 14 | 49.1 | −0.002 | +0.081 | 0.73 | 0.97 | 30.0 | 70 | −0.044 / +0.039 | |
| N5 | P7, 07–17 | 290 | 12 | 48.6 | +0.053 | +0.145 | 0.93 | 1.11 | 26.1 | 63 | +0.007 / +0.099 | |
| N6 | P7, 60-min exit | 310 | 13 | 46.1 | +0.014 | +0.106 | 0.82 | 1.01 | 30.0 | 47 | −0.003 / +0.030 | |
| N7 | P7, buf 0.5 | 301 | 13 | 48.5 | +0.028 | +0.107 | 0.87 | 1.05 | 29.5 | 65 | −0.051 / +0.105 | |
| F1 | P7 + H1 trend flat (<2 ATR) | 164 | 7 | 47.6 | +0.047 | +0.125 | 1.01 | 1.08 | 19.2 | 59 | −0.017 / +0.113 | +0.103 / −0.020 |
| **F2** | **P7 + day range ≤ 1.0 D1 ATR (final)** | 275 | 11.5 | 49.1 | **+0.066** | +0.162 | 0.93 | 1.14 | 23.3 | 63 | +0.012 / +0.118 | +0.064 / +0.069 |
| F3 | P7 + day range ≤ 0.8 | 245 | 10 | 50.2 | +0.084 | +0.182 | 0.93 | 1.19 | 14.9 | 64 | +0.044 / +0.121 | +0.066 / +0.106 |
| F4 | P7 + day range ≤ 1.2 | 288 | 12 | 48.6 | +0.053 | +0.146 | 0.94 | 1.11 | 27.8 | 63 | −0.005 / +0.108 | |
| F5 | F2, 07–17 | 258 | 11 | 50.0 | +0.093 | +0.192 | 0.94 | 1.21 | 20.8 | 63 | +0.038 / +0.144 | |
| G1 | F2, TP 1.25 | 275 | 11.5 | 49.8 | +0.036 | +0.136 | 0.86 | 1.06 | 24.3 | 59 | −0.017 / +0.088 | |
| G2 | F2, TP 2.0 | 275 | 11.5 | 47.3 | +0.020 | +0.112 | 0.90 | 1.02 | 29.8 | 68 | −0.080 / +0.117 | |
| G3 | F2, min 0.8 | 275 | 11.5 | 46.2 | +0.005 | +0.123 | 0.97 | 0.99 | 36.4 | 56 | −0.065 / +0.072 | |
| G4 | F2, min 1.2, max 2.5 | 303 | 12.6 | 50.2 | +0.023 | +0.110 | 0.74 | 1.05 | 25.9 | 71 | −0.030 / +0.074 | |
| G5 | F2 on M15 | 243 | 10 | 51.0 | +0.032 | +0.098 | 0.79 | 1.07 | 27.1 | 69 | −0.083 / +0.153 | |

Why F2 rather than F3 or F5: 1.0 × D1 ATR is the round, "one average day" value in the middle of a monotone
plateau. Restricting hours to 07–17 (F5) was chosen after looking at results, so I did not adopt it.

## Final parameters (DEFAULT_PARAMS = F2)
- **Bars and units.** M5 signal bars. The unit is H1 ATR(14), the last completed H1 bar.
- **Levels.** PDH and PDL are the high and low of the previous full UTC day (at least 12 hours of quotes;
  Monday uses Friday).
- **Entry window.** M5 bars closing in [07:00, 20:00) UTC.
- **Signal.** After a pierce of PDH (or PDL) inside the window, the first M5 close back inside triggers a short
  (or long). Enter at the next M1 open. At most one signal per side per day.
- **Quiet-day filter.** UTC-day range so far must be ≤ 1.0 × D1 ATR(14) of full UTC days.
- **Stop.** |entry − sweep extreme| + 0.3 ATR, at least 1.0 ATR; skip the trade if it would exceed 2.0 ATR.
- **Exits.** TP 1.5 R, 90-min time exit, flat at 20:45 UTC.

## Results
| run | trades | /mo | win% | avg R | gross R | avg win R | PF | return % | maxDD% | pos months | worst month |
|---|---|---|---|---|---|---|---|---|---|---|---|
| dev 2022–23, no limits | 275 | 11.5 | 49.1 | +0.066 | +0.162 | 0.93 | 1.14 | +36.3 | 23.3 | 54% | −8.8% |
| dev 2022–23, account (2% risk, $50 cent) | 275 | 11.5 | 49.1 | +0.066 | | 0.93 | 1.07 | +13.5 | 18.8 | 50% | −8.5% |
| **val 2024, no limits** | 132 | 11.0 | 41.7 | **−0.116** | −0.060 | 0.82 | 0.72 | −27.9 | 33.4 | 50% | −13.2% |
| **val 2024, account** | 132 | 11.0 | 41.7 | −0.116 | | 0.82 | 0.71 | −18.7 | 23.3 | 50% | −7.8% |
| stress 2024, no limits | 132 | 11.0 | 40.9 | −0.155 | | 0.77 | 0.66 | −34.0 | 38.3 | 50% | −17.1% |
| stress 2024, account | 132 | 11.0 | 40.9 | −0.155 | | 0.77 | 0.63 | −23.2 | 26.9 | 42% | −8.7% |

Monte Carlo (6 months, day bootstrap, account rules):

| | hard stop hit | profitable | median equity | 5th / 95th percentile |
|---|---|---|---|---|
| dev | 0.0% | 63% | $52.9 | $43.3 / $70.4 |
| 2024 | 0.18% | 11% | $43.7 | $38.5 / $52.9 |

The default risk rules kept the account above the hard stop in every run.

### Detail
- **Dev quarters (R/trade).** +0.12, +0.10, −0.13, −0.03, **+0.39**, +0.14, +0.01, −0.05.
  2023 Q1 alone contributes 13.6 of the 18.2 R. Net t-stat 1.14.
- **2024 quarters (R/trade).** −0.08, −0.07, −0.28, 0.00. Net t-stat −1.46.
  - The problem is the edge, not costs. The cost was only 0.056 R/trade because stops were larger (average $5.5)
    as volatility rose. 2024 was a strong one-way gold trend year.
- **Hours.** In both periods, entries after 16 UTC are negative (small samples).
- **Long vs short.** Dev +0.064 / +0.069; 2024 −0.078 / −0.142.

## Notes for the engine / harness (no changes made)
- `scripts/evaluate.py` loads only the [start, end) window. Strategies that need daily history therefore lose
  the first ~3 weeks of every test window to warm-up: this one uses D1 ATR(14) and the previous day's levels.
  An EA always has history, so backtests slightly under-count trades. This is not a bug.
- Long stop and target distances are measured from the ASK fill, while strategies compute levels from BID bars.
  A stop "beyond the bid extreme" for a long therefore sits one spread closer than intended. Shorts are
  consistent, because their stops are checked against ASK highs.
- The risk manager's "day" is the UTC calendar day. An MT5 EA usually uses the broker's server day (GMT+2/+3),
  so daily-loss and trade-count limits reset at a different time.
