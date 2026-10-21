# session_orb: research log (opening-range breakout, XAUUSD)

**Verdict: not viable as a stand-alone scalper.** Plain opening-range breakouts at the London, COMEX and
New York opens lose money after costs. One variant stayed slightly positive on dev and on 2024: the first
*retest* of the New York 09:30 opening range. Its edge is about +0.06 to +0.08 R/trade, which is not
statistically significant (t ≈ 1.0 on dev, ≈ 0.6 on 2024). It is driven by the long side and fires only
7–10 times per month, below the 15/month target.

## Protocol
- Development: 2022-01-01 .. 2024-01-01. Validation: 2024 (one run of the final choice, no revision afterwards).
- Default `CostModel` (spread max($0.25, 0.8 bps), ×3 at 21–22 UTC, $0.05 stop slippage). Stress test on 2024: spread max($0.40, 1.2 bps), $0.10 slippage.
- 31 dev backtests in total (30 parameter sets plus 1 zero-cost diagnostic), logged below. Only 1 parameter set was run on 2024.
- Volatility yardstick: H1 ATR(24) (the simple average of true range, as in MT5 iATR) of the last completed H1 bar at the end of the range. All distances are in ATR units or OR units.
- Session opens are computed with zoneinfo: London 08:00 Europe/London, COMEX 08:20 America/New_York, NY 09:30 America/New_York.

## Opening-range facts (2022–2023, 15-min OR, in H1-ATR units)
| session | median OR width | median width/ATR (10–90%) |
|---|---|---|
| London 08:00 | $2.25 | 0.52 (0.34–0.87) |
| COMEX 08:20 NY | $2.72 | 0.59 (0.31–1.44) |
| NY 09:30 | $4.53 | 0.99 (0.56–2.21) |

## Dev sweep (no-limits, default costs)
Unless a row says otherwise: OR 15 min, breakout confirmed by an M1 close, entry window 60 min, 0.25 ≤ OR/ATR ≤ 1.5, stop at the opposite side, max stop 1.5 ATR, TP 1.5 R, 90-min time exit. L/C/NY = per-session avg R.

| # | sessions | entry | changes | trades | /month | win% | avg R | avg win R | PF | maxDD% | hold min | 2022 / 2023 | by session |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | london+ny | break | or_min=15, sl_mode=opposite | 795 | 33.1 | 40.1 | -0.070 | 1.11 | 0.83 | 77.1 | 51.8 | -0.084 / -0.055 | L:-0.099 NY:-0.024 |
| 2 | comex | break | or_min=15, sl_mode=opposite | 377 | 15.7 | 34.7 | -0.207 | 1.36 | 0.68 | 82.6 | 46.1 | -0.201 / -0.216 | C:-0.207 |
| 3 | london+ny | break | or_min=15, sl_mode=mid | 821 | 34.2 | 34.8 | -0.152 | 1.4 | 0.74 | 93.2 | 22.7 | -0.161 / -0.142 | L:-0.145 NY:-0.163 |
| 4 | comex | break | or_min=15, sl_mode=mid | 385 | 16.1 | 31.4 | -0.244 | 1.52 | 0.64 | 87.5 | 20.2 | -0.239 / -0.250 | C:-0.244 |
| 5 | london+ny | break | or_min=30, sl_mode=opposite | 657 | 27.4 | 43.8 | -0.062 | 0.83 | 0.84 | 64.4 | 65.1 | -0.057 / -0.068 | L:-0.099 NY:+0.015 |
| 6 | comex | break | or_min=30, sl_mode=opposite | 339 | 14.1 | 40.7 | -0.048 | 1.32 | 0.89 | 50.1 | 48.5 | -0.043 / -0.054 | C:-0.048 |
| 7 | london+ny | break | or_min=30, sl_mode=mid | 687 | 28.6 | 38.0 | -0.091 | 1.32 | 0.85 | 80.0 | 32.7 | -0.075 / -0.113 | L:-0.120 NY:-0.038 |
| 8 | comex | break | or_min=30, sl_mode=mid | 357 | 14.9 | 33.6 | -0.165 | 1.71 | 0.72 | 77.9 | 22.9 | -0.224 / -0.076 | C:-0.165 |
| 9 | all three | break | **ZERO COST** diagnostic (same as #1/#2) | 1100 | 45.9 | 42.9 | -0.017 | 1.2 | 0.94 | 67.6 | 52.3 | -0.027 / -0.006 | L:+0.025 C:-0.128 NY:+0.072 |
| 10 | london+ny | break | confirm_tf=5min | 727 | 30.3 | 42.1 | -0.043 | 1.04 | 0.9 | 60.9 | 56.1 | -0.022 / -0.070 | L:-0.053 NY:-0.026 |
| 11 | london+ny | retest | – | 476 | 19.8 | 43.3 | -0.024 | 1.07 | 0.92 | 39.6 | 54.7 | -0.048 / +0.005 | L:-0.088 **NY:+0.083** |
| 12 | london+ny | retest | sl_mode=mid | 491 | 20.5 | 34.0 | -0.163 | 1.42 | 0.71 | 85.0 | 25.0 | -0.211 / -0.104 | L:-0.209 NY:-0.091 |
| 13 | london+ny | break | max_or_atr=0.6 (compression) | 382 | 15.9 | 36.6 | -0.127 | 1.25 | 0.75 | 68.6 | 41.8 | -0.186 / -0.056 | L:-0.148 NY:-0.003 |
| 14 | london+ny | break | tp_r=1.0 | 795 | 33.1 | 45.3 | -0.082 | 0.88 | 0.81 | 78.0 | 43.6 | -0.086 / -0.076 | L:-0.090 NY:-0.069 |
| 15 | london+ny | break | tp_r=2.5 | 795 | 33.1 | 37.6 | -0.074 | 1.23 | 0.84 | 79.3 | 59.3 | -0.073 / -0.076 | L:-0.091 NY:-0.048 |
| 16 | london+ny | touch (stop-entry approx.) | – | 827 | 34.5 | 41.1 | -0.066 | 1.14 | 0.86 | 78.2 | 48.7 | -0.054 / -0.080 | L:-0.080 NY:-0.045 |
| 17 | ny | retest | or_min=30 | 128 | 5.3 | 48.4 | +0.071 | 0.88 | 1.18 | 12.7 | 65.3 | +0.043 / +0.134 | |
| 18 | ny | retest | tp_r=2.0 | 177 | 7.4 | 43.5 | +0.096 | 1.29 | 1.19 | 16.4 | 58.9 | +0.038 / +0.206 | |
| 19 | ny | retest | tp_r=1.0 | 177 | 7.4 | 49.2 | +0.056 | 0.97 | 1.12 | 23.6 | 43.7 | -0.022 / +0.202 | |
| 20 | ny | retest | retest_tol_atr=0.15 | 197 | 8.2 | 44.2 | +0.053 | 1.11 | 1.1 | 18.9 | 55.9 | +0.013 / +0.124 | |
| 21 | ny | retest | entry_window_min=90 | 185 | 7.7 | 45.4 | +0.082 | 1.17 | 1.17 | 21.5 | 53.5 | -0.003 / +0.239 | |
| 22 | comex+ny | retest | or_min=30 | 297 | 12.4 | 45.5 | +0.011 | 1.12 | 0.98 | 29.9 | 54.6 | -0.018 / +0.062 | C:-0.018 NY:+0.066 |
| 23 | all three | retest | or_min=30 | 569 | 23.7 | 46.2 | -0.030 | 0.93 | 0.91 | 53.2 | 61.1 | -0.026 / -0.034 | L:-0.074 C:-0.018 NY:+0.066 |
| 24 | ny | retest | reentry=True | 345 | 14.4 | 44.3 | +0.020 | 1.12 | 1.02 | 20.2 | 51.0 | +0.028 / +0.005 | |
| 25 | ny | retest | reentry=True, window 120 | 489 | 20.4 | 45.2 | +0.021 | 1.06 | 1.02 | 29.8 | 54.0 | +0.021 / +0.020 | |
| 26 | london+ny | retest | reentry=True | 904 | 37.7 | 42.9 | -0.034 | 1.07 | 0.91 | 63.6 | 51.6 | -0.020 / -0.053 | L:-0.068 NY:+0.020 |
| 27 | comex+ny | retest | – | 395 | 16.5 | 39.5 | -0.082 | 1.29 | 0.84 | 62.7 | 48.1 | -0.116 / -0.030 | C:-0.192 NY:+0.084 |
| 28 | ny | retest | max_or_atr=2.0, max_sl_atr=2.0 | 209 | 8.7 | 45.0 | +0.048 | 1.12 | 1.09 | 23.0 | 55.9 | -0.000 / +0.131 | |
| 29 | ny | retest | sl_mode=atr 0.5 | 192 | 8.0 | 38.5 | -0.027 | 1.53 | 0.92 | 33.4 | 24.0 | -0.085 / +0.071 | |
| 30 | ny | retest | or_min=5 | 219 | 9.1 | 37.4 | -0.077 | 1.42 | 0.85 | 38.2 | 34.8 | -0.120 / -0.014 | |
| 31 | ny | retest | confirm_tf=5min | 154 | 6.4 | 49.4 | +0.077 | 1.05 | 1.15 | 16.3 | 54.0 | +0.010 / +0.201 | |

The final choice (NY, retest, OR 15, TP 1.5 R) is the NY slice of row 11: 177 trades, +0.083 R.

### What the sweep says
- **The plain breakout has no gross edge.** At zero cost, all three sessions together average -0.017 R/trade (#9). Costs are about 0.06–0.10 R per trade, so every breakout variant loses money (#1–16).
- **Gold's opening ranges at these sessions tend to mean-revert.** A stop at the OR midpoint is always worse than a stop at the opposite side (#3, #4, #7, #8, #12). Narrow, compressed ranges are worse, not better (#13). Re-entries after a failed breakout dilute the result to about 0 (#24–26).
- **London and COMEX are negative in every variant.** COMEX (its range contains the 08:30 ET data releases) is the worst.
- **NY 09:30 with a retest is the only positive cluster.** It holds for OR 15 or 30, TP 1.0/1.5/2.0 R, touch tolerance 0.05/0.15 ATR, window 60/90, M1 or M5 confirmation and max width 1.5/2.0: all land at +0.05 to +0.10 R. Changing the stop type kills it (mid -0.09, ATR -0.03), and so does a 5-min OR (-0.08).
- **Even that cluster is weak.**
  - 2022 contributes about 0; 2023 contributes +0.2 R/trade.
  - Five trades in 2023 Q2 produced half of all dev R (+7.3 of +14.7 R).
  - Longs +0.17 vs shorts -0.01, in a rising gold market.
  - In dev, the gain was concentrated in US summer time (DST +0.18, winter -0.07). In 2024 this flipped (winter +0.19, summer -0.02), so the time-of-year pattern is noise.

## Final parameters (DEFAULT_PARAMS)
NY 09:30 America/New_York; OR 15 min; breakout = first M1 close beyond the OR within 60 min; then wait for the first M1 bar that touches the broken level (tolerance 0.05 ATR) and closes beyond it, cancelling if a bar closes back inside; enter at the next M1 open. Stop at the opposite side of the OR (skip if over 1.5 ATR); TP 1.5 R; 90-min time exit; flat by 20:50 UTC; one trade per day. Filter 0.25 ≤ OR/ATR ≤ 1.5, with ATR = H1 ATR(24).

## Results
| | trades | /month | win% | avg R | avg win R | PF | maxDD% | hold | long / short R |
|---|---|---|---|---|---|---|---|---|---|
| dev 2022–23, no limits | 177 | 7.4 | 45.2 | +0.083 | 1.17 | 1.17 | 18.7 | 53 | +0.173 / -0.014 |
| val 2024, no limits | 115 | 9.6 | 52.2 | +0.060 | 0.95 | 1.11 | 22.4 | 51 | +0.180 / -0.057 |
| val 2024, stress costs | 115 | 9.6 | 51.3 | +0.035 | 0.92 | 1.06 | 22.2 | 52 | +0.165 / -0.093 |

Account simulation ($50 cent, 2% risk, default rules):
- **dev:** +15.4%, max DD 16.5%, 45.8% positive months, worst month -7.6%. Monte Carlo over 6 months: P(hard stop) 0%, median $52.35.
- **2024:** +5.1%, max DD 16.7%, 66.7% positive months, worst month -9.5%, not hard-stopped. Monte Carlo over 6 months: P(hard stop) 0.0%, median $51.74, p5 $42.87.
- **Longest losing streak in 2024:** 10 trades.

There was no revision after validation. A long-only rule or a change of session would have been data-snooping on 2024.

## Engine notes / limitations
- The engine fills only at M1 opens, so a true stop-entry ORB (filling at the range level) cannot be simulated. Close confirmation followed by a next-bar market order is used instead, and it ports 1:1 to an EA. Row 16 ("touch": trigger on the high/low trading through the range, then fill at the next open) approximates a stop entry and was also negative.
- Stop distance is measured from the bid open of the entry bar. For longs, this puts the effective stop one spread inside the OR low (the engine fills longs at ask). The EA should reproduce this: d = |bid − level|, SL = fill ∓ d.
- The Monte Carlo resamples R-multiples with compounding but does not apply the daily-loss or consecutive-loss rules. It is slightly pessimistic or optimistic depending on clustering.
