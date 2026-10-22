# gold_regime: regime / direction / volatility filters on the gold swing EA (research log)

**Verdict: NOT ACCEPTED.** The final rule (skip signals when D1 volatility is in the bottom 30% of the last year)
roughly doubled the dev R edge, but it lost to the baseline on the validation sum at both 2% and 3% risk. Most of the
loss is in 2022–2025. No directional regime filter beat the baseline robustly, even on dev. Keep the deployed EA
as it is.

## Protocol (results/TWEAK_PLAN.md)
- **Base.** `swing_pullback` with `max_hold_days=3` (= mql5/GoldSwingCent.mq5). The filters only *remove* base signals before the single-position engine runs, so a removed signal frees the slot for a later one, as it would in an EA.
- **Selection.** Everything was chosen on dev 2013-01 .. 2019-12 only, with the harness truncating data at 2020-01-01.
- **Parameter combos.** 39 were run (C01–C39).
- **Dev-only diagnostics.**
  - 2 bucket tables (R by regime alignment; R by ER / ATR-percentile quintiles).
  - A circular-shift null test of the vol filter (200 draws).
  - Zero-cost and stress-cost runs.
  - Every leading candidate re-run on H4 grid offsets 0/1/2/3 h.
- **Validation.** The final candidate was run once on all periods, at 2% and 3% risk. There was no revision afterwards.
- **Regime clock.**
  - D1 = New-York-close broker day (17:00 NY), using the last *completed* D1 bar at the fill time.
  - W1 = Mon–Fri of those days.
  - Filters that are still warming up let the signal through. Because the data starts 2012-11, the 250-day vol filter is inactive for all of 2013.

## Final candidate (C23) and validation
Rule: x = ATR(D1,14)/close of the last completed D1 bar. If x ranks below the 30th percentile of the last 250 D1 values, skip the signal. Everything else is identical to the baseline.

| period | gold_regime 2% | baseline 2% | gold_regime 3% | baseline 3% | avg R (n) regime / base |
|---|---|---|---|---|---|
| dev 2013–2019 | **$79.24**, DD 15.4% | $56.41, DD 19.7% | **$104.50**, DD 19.8% | $62.08, DD 26.6% | +0.143 (194) / +0.038 (313) |
| val 2020–2021 | $43.71, DD 15.8% | $41.95 | $41.53, DD 21.2% | $40.35 | −0.167 (63) / −0.145 (88) |
| val 2022–2025 | $78.50, DD 15.4% | $122.45 | $98.84, DD 23.0% | $154.70 | +0.188 (136) / +0.289 (178) |
| val 2026 Mar–Sep | $46.70 | $46.70 | $45.75 | $45.75 | identical: the filter never fired |
| **validation sum** | **$168.91** | **$211.10** | **$186.12** | **$240.80** | |

There was no hard stop, and the maximum DD was 23%. It fails the acceptance rule anyway, because the validation sum is lower at both risks.

**Why it failed (information only, run after the decision).** These are the baseline's own trades, split by the filter:

| period | low-vol trades (would be skipped) | other trades |
|---|---|---|
| dev | −0.139 R (n=120) | +0.149 R (n=193) |
| 2020–21 | −0.109 R (n=26) | −0.160 R (n=62) |
| 2022–25 | **+0.577 R (n=43)** | +0.197 R (n=135) |

The dev pattern reversed out of sample.

## Dev sweep (2013–2019; $50 account final equity at 2% / 3%; baseline $56.41 / $62.08)
| # | filter | n | avg R | acc 2% | acc 3% |
|---|---|---|---|---|---|
| C01 | D1 close vs SMA200, trade only with it | 198 | +0.070 | 61.51 | 60.53 |
| C02 | SMA150 with | 203 | +0.066 | 60.33 | 51.79 |
| C03 | SMA250 with | 202 | +0.031 | 53.07 | 55.53 |
| C04 | SMA100 with | 206 | +0.033 | 53.69 | 54.45 |
| C05 | EMA100 with | 220 | +0.008 | 50.46 | 43.40 |
| C06 | EMA200 with | 204 | +0.038 | 53.02 | 48.87 |
| C07 | SMA200: no shorts while above (longs always) | 261 | +0.072 | 68.36 | 67.36 |
| C08 | SMA200: no longs while below | 250 | +0.028 | 49.55 | 48.29 |
| C09 | 60-day momentum sign with | 189 | +0.042 | 53.90 | 55.31 |
| C10 | 120-day momentum with | 192 | +0.037 | 54.54 | 44.45 |
| C11 | 250-day momentum with | 191 | +0.055 | 56.35 | 56.95 |
| C12 | W1 close vs EMA20 with | 201 | +0.012 | 50.50 | 49.95 |
| C13 | W1 EMA40 with | 192 | +0.042 | 53.57 | 50.21 |
| C14 | SMA200 with + SMA slope(20 d) agrees | 148 | +0.083 | 58.53 | 59.35 |
| C15 | SMA200 with, neutral band ±1 ATR(D1) | 185 | +0.054 | 54.82 | 58.48 |
| C16 | SMA150 no-short-up | 261 | +0.058 | 64.43 | 53.67 |
| C17 | SMA250 no-short-up | 265 | +0.061 | 65.36 | 53.36 |
| C18 | SMA100 no-short-up | 266 | +0.029 | 58.30 | 47.25 |
| C19 | EMA200 no-short-up | 265 | +0.051 | 62.92 | 49.29 |
| C20 | 250-day momentum no-short-up | 267 | +0.040 | 59.65 | 57.30 |
| C21 | W1 EMA40 no-short-up | 261 | +0.062 | 64.94 | 51.02 |
| C22 | vol pct(250) ≥ 20 | 227 | +0.111 | 74.45 | 77.85 |
| **C23** | **vol pct(250) ≥ 30 (final)** | 194 | **+0.143** | **79.24** | **104.50** |
| C24 | vol pct(250) ≥ 40 | 173 | +0.137 | 72.19 | 87.14 |
| C25 | vol pct(500) ≥ 30 | 209 | +0.050 | 56.95 | 48.93 |
| C26 | vol pct(250) ≤ 90 (skip extreme high) | 284 | +0.021 | 51.67 | 43.39 |
| C27 | vol pct(250) ≥ 25 | 209 | +0.130 | 75.47 | 91.71 |
| C28 | vol pct(250) ≥ 35 | 178 | +0.129 | 70.96 | 85.68 |
| C29 | vol pct(120) ≥ 30 | 197 | +0.079 | 60.89 | 63.81 |
| C30 | vol pct(375) ≥ 30 | 200 | +0.126 | 73.17 | 86.90 |
| C31 | C23 + C07 | 162 | +0.166 | 79.42 | 104.33 |
| C32 | C23 + SMA200 with | 125 | +0.159 | 68.54 | 84.36 |
| C33 | ATR(D1,14)/ATR(D1,250) ≥ 0.8 | 242 | +0.052 | 66.20 | 62.79 |
| C34 | ATR ratio ≥ 0.9 | 187 | +0.052 | 59.16 | 62.32 |
| C35 | ATR ratio ≥ 1.0 | 131 | +0.085 | 56.16 | 59.76 |
| C36 | H4 ATR% percentile(1500 bars) ≥ 30 | 210 | +0.048 | 62.62 | 63.71 |
| C37 | raw-$ ATR(D1) percentile(250) ≥ 30 | 190 | +0.127 | 73.91 | 88.15 |
| C38 | C22 + C07 | 189 | +0.131 | 74.40 | 91.06 |
| C39 | C24 + C07 | 144 | +0.147 | 69.74 | 73.19 |

## Robustness checks done on dev before validation
- **H4 grid offsets 0/1/2/3 h**, mean account at 2% / 3%:
  - C23: $64.1 / $77.1, against $55.8 / $53.0 for the baseline. Avg R was above the baseline on all 4 offsets: +0.143 / +0.106 / +0.049 / +0.068, against +0.038 / +0.043 / +0.033 / +0.016.
  - On the +2 h grid it was *below* the baseline at 2% ($51.25 vs $55.88). That was the first warning.
  - C07 was better than the baseline in avg R on every offset, but only by about 0.02 R.
- **Adding C07 to the vol filter.** It did not help consistently across thresholds 20/30/40 and grid offsets: it was slightly worse at 2% in all three. It was therefore dropped for parsimony.
- **Circular-shift null.** Shifting the D1 vol mask in time (200 draws) gave a mean of +0.013 R and $49.4. The 95th percentile was $61.3. The actual result was +0.143 R and $79.2, so p < 0.005 for a single test. That figure was inflated by ~15 tried vol variants and turned out not to predict validation.
- **Costs.** At zero cost: +0.199 vs +0.097 R. Under stress costs: +0.108 vs +0.001 R.
- **Form-dependence.** The effect depended on the exact form of the measure:
  - the ATR-ratio form (C33–C35), the H4 form (C36) and the 500- and 120-day lookbacks were much weaker;
  - only a percentile rank over 250–375 days worked.

## Takeaways for the owner
- **Direction regimes do not add to this EA.** It already trades with the H4 trend. Daily and weekly trend agreement, or long-only in an up-regime, changed dev by no more than noise. Short-horizon agreement (SMA50, 20-day momentum) was actually *worse*.
- **The volatility filter does not generalise.** It looked like the strongest lever on 2013–2019, but the pattern flipped in 2022–2025, the period the baseline earns most in. Filtering trades away mostly reduces compounding when the base edge is positive.
- **Leave this module off.** None of these filters should be added to GoldSwingCent. The module keeps `regime="none"` and the rejected vol rule as DEFAULT_PARAMS, for reproducibility only.
