# Conviction (signal-quality) sizing and volatility targeting: gold swing EA

Code: `scripts/mm_conviction.py` (`python scripts/mm_conviction.py` prints everything; `--stage dev` prints only
the dev output that was used to choose candidates). Trades come from `mm_sim.get_trades()` (603 EA trades
2013-2026, exact R including costs and 5% swap). Sizing only scales risk from 0.5x to 1.5x, so the trade list never
changes. Skipping a trade (0x) would change which later signals get taken, so it is an entry change and is
out of scope here.

## Protocol followed
1. **Features (12, chosen before looking at any R).** All are known at the signal H1 bar's close and use
   completed bars only:
   - H4 trend distance (close minus EMA40, in ATR), EMA40 slope, and trend age (H4 bars in the current trend state)
   - RSI pullback depth: 40 minus the lowest RSI(14,H1) of the last 10 H1 bars (mirrored for shorts)
   - pullback from the 20-bar H1 extreme, in ATR
   - ATR(H4) percentile over 500 bars, and ATR / its 120-bar median
   - D1 close minus EMA20, in D1 ATR
   - hours left before the 72h cap or Friday close
   - entry hour, previous trade R, and long/short
2. **Dev screen, 2013-19 (313 trades).** Tercile cut points come from dev. The pre-registered strict gate was:
   tercile ordering monotone, in the same direction, in both dev halves (2013-16H1 and 2016H2-19). The "near"
   gate was: top-minus-bottom has the same sign in both halves and is at least 0.15R in size on full dev.
   - **No feature passed the strict gate.** Two were near-passes: trend_age (younger trends better) and
     rsi_depth (shallow pullbacks better).
   - Selection-bias null (R shuffled across dev trades 2000 times): chance alone gives 0.60 strict passes
     and 3.2 near-passes. The best near-pass tier edge (+0.078R vs plain +0.038R) is matched by noise
     in 73% of shuffles. **So the dev evidence on its own was no better than chance.**
3. **Dev policy grid: 17 variants**, plus the 12 feature screens, for **29 dev looks** in total.
   - tiers at 1.5/1/0.5 and 1.25/1/0.75
   - a 2-feature additive score
   - 6 vol-targeting tilts (trade-history rank or ATR percentile; favour low or favour high; power 0.25 or 0.5)
   - robustness forms: smooth rank, and a 5-bar RSI window
   - ladder composites

   Every vol-targeting variant stayed within ±0.004R of plain on dev: no edge.
4. **Frozen candidates (C1-C5), each run once on every period.**

## Final table ($50 fresh per period; all = 2013-2026 from $50; wR = risk-weighted mean R)
| policy | dev | dev DD | 20-21 | 22-25 | 2026 | val_sum | all | max DD (any) | min eq % | ruined | better |
|---|---|---|---|---|---|---|---|---|---|---|---|
| fixed 3% (ref) | 59.93 | 40.9 | 32.72 | 204.90 | 42.77 | 280.39 | 137.50 | 64.7 | 64.4 | no | - |
| ladder 5/3/2 (ref) | 84.61 | 53.6 | 23.61 | 252.47 | 38.19 | 314.27 | 213.76 | 74.4 | 46.4 | no | (yes) |
| **C1 rsi_depth tiers 1.5/1/0.5** | **83.96** | 43.2 | 38.78 | 262.42 | 42.39 | **343.59** | **289.76** | **59.2** | 66.4 | no | **YES** |
| C2 score trend_age+rsi_depth (step .25) | 80.35 | 45.9 | 35.48 | 241.79 | 43.76 | 321.03 | 241.28 | 64.7 | 66.4 | no | yes |
| C3 trend_age tiers 1.5/1/0.5 | 75.34 | 48.7 | 32.26 | 218.10 | 45.10 | 295.46 | 191.23 | 69.9 | 64.5 | no | yes (marginal) |
| C4 ladder x rsi_depth tiers | 109.28 | 51.1 | 30.98 | 328.88 | 37.62 | 397.48 | 328.46 | 64.0 | 48.9 | no | YES, also beats the ladder |
| C5 vol targeting, favour high vol | 61.07 | 39.7 | 30.41 | 202.17 | 41.20 | 273.78 | 123.74 | 66.2 | 60.8 | no | no |

- **wR by period** (dev / 20-21 / 22-25 / 2026):
  - plain: +0.038 / -0.145 / +0.289 / -0.206
  - C1: +0.078 / -0.077 / +0.364 / -0.243
  - C1 helps in 3 of 4 periods and is slightly worse in 2026, where there are only 24 trades.
- **min eq %** is the lowest equity in any period as a % of $50. A -30%-from-start hard stop would have fired in
  2013 for every policy here, fixed 3% included. C1 has the same exposure as fixed 3%, and C4 has the same
  exposure as the ladder.
- **rsi_depth out of sample** (frozen dev cut points, 2020-2026 trades):
  - shallow tercile +0.321R, mid +0.116R, deep -0.040R, so the ordering is monotone in validation
  - shallow minus deep +0.361R (t 1.94, n 83/109)
  - one-sided permutation p = 0.018 for the risk-weighted gain
  - it holds in 2020-21 (-0.401) and 2022-25 (-0.450), and flips in 2026 (+0.106, n=24)
- **trend_age out of sample:** p = 0.26, and it flips in 2020-21. Its gain is weak.
- **Sensitivity** (run after the freeze, not used for selection). Every form of the rsi_depth rule beats fixed 3%
  on both dev and val_sum:

  | form | dev | val_sum | all |
  |---|---|---|---|
  | soft 1.25/1/0.75 | $71.41 | $311.42 | $202.37 |
  | smooth rank | $77.16 | $328.50 | $244.56 |
  | 5-bar RSI window | $81.89 | $338.28 | $279.22 |
  | 2-level (deep 0.5x, else 1.25x) | $86.95 | $322.47 | $273.23 |

  The result does not depend on the exact tercile cut.

## Do the dev relationships hold in validation? (top-minus-bottom tercile R, dev cut points)
- **Hold, and strong enough to matter:** rsi_depth (dev -0.24, validation -0.36).
- **Same sign but weak or inconsistent across periods:** trend_age, d1_dist, atr_pct, pb_depth, entry_hour, hours_avail.
- **Flip:** long/short (dev: shorts better; validation: longs +0.38 better because of the gold bull market),
  and trend_slope.
- **Vol targeting:** the vol terciles are inconsistent from period to period (atr_pct: 20-21 -0.15, 22-25 -0.23,
  2026 +0.40). The EA already sizes from a 2xATR stop, so a further vol tilt adds noise and no edge. This
  matches Man AHL's finding that vol targeting does not raise the Sharpe ratio for commodities.
- **Previous-trade R** looked flat on dev (+0.05) but was +0.37 in validation. It was not selected on dev and is not used here.
  It belongs to the equity-curve cluster.

## MQL5 rule for C1 (constants fixed from dev)
At the signal, take m = the lowest RSI(14,H1) over the last 10 completed H1 bars, the cross bar included
(`CopyBuffer(rsi,0,1,10,..)`). For a short, use the highest RSI instead and mirror the thresholds around 50.

| long: m | short: highest RSI | risk |
|---|---|---|
| m >= 38.17 | <= 61.83 | 1.5 x base |
| 35.09 <= m < 38.17 | 61.83 to 64.91 | 1.0 x base |
| m < 35.09 | > 64.91 | 0.5 x base |

With base 3%, average risk stays at 3.00%. C4 uses the 5/3/2 ladder as the base, so risk can reach 7.5% below $100.

## Verdict
- **C1 (rsi_depth tiers on 3%)** is the one conviction rule with out-of-sample support:
  - it beats fixed 3% on dev (+40%) and on val_sum (+23%)
  - all 2013-2026: $290 vs $138
  - lower max DD (59% vs 65%), never ruined
  - it plausibly reflects a real mechanism: a deep RSI pullback means the trend is losing momentum
- **Caveats:**
  - it failed the strict dev gate, and its dev selection was indistinguishable from noise
  - the evidence rests on validation alone: p ≈ 0.02 one-sided, about 0.05 after allowing for the 3 independent
    ideas validated (rsi_depth, trend_age, vol)
  - it was worse in 2026 (24 trades)
- **Recommendation:** treat it as a moderate tilt. The soft 1.25/0.75 form keeps most of the gain with less
  dependence on the effect.
- **C4 (ladder x C1)** has the highest numbers (val_sum $397, all $328, max DD 64%). It inherits the ladder's
  look-ahead and the ladder's 2013 dip to 49% of start, so it is incompatible with a -30% hard stop.
- **Rejected:** vol targeting (C5) and pure trend-age sizing (C3, marginal and unstable).
