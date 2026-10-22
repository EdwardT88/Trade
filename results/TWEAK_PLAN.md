# Return-maximising tweaks for the gold swing EA — protocol (written before the search)

Goal (owner): maximum account growth "by any means", without getting margin-called.

Baseline = strategies/swing_pullback with max_hold_days=3 (the EA default), $50 cent account, risk 2%:
dev 2013–2019 $50→$56.41 (+0.038R, 313 trades) | 2020–2021 $50→$41.95 (−0.145R) |
2022–2025 $50→$122.45 (+0.289R) | 2026 Mar–Sep $50→$46.70 (−0.206R).

Rules:
1. Every tweak is chosen using **dev 2013-01 – 2019-12 only** (gold H1 data). Validation periods
   (2020–2021, 2022–2025, 2026) are run once per final candidate and reported as they come out.
   Caveat: the base system itself was designed on 2022–2023, so 2022–2025 is not fully independent.
2. A tweak is accepted only if it beats the baseline on dev AND on the sum of the validation periods
   (account growth at the same risk), with no hard stop and max drawdown ≤ 40%.
3. Risk per trade is capped at 3% (sizing study: 5%+ hit the −30% hard stop in 2013).
Evaluation: `python scripts/gold_full_eval.py <module> --risk 2` (and 3).

---

## Results (validation run once per candidate)

$50 account, final equity per period. Validation sum = 2020–21 + 2022–25 + 2026.

| Candidate | Dev 2013–19 (2%) | 2020–21 | 2022–25 | 2026 | Val sum 2% | Val sum 3% | Verdict |
|---|---|---|---|---|---|---|---|
| **Baseline (EA)** | $56.41 | $41.95 | **$122.45** | $46.70 | **$211.10** | **$240.80** | kept |
| gold_regime (skip low D1 vol) | $79.24 | $43.71 | $78.50 | $46.70 | $168.91 | $186.12 | rejected |
| gold_exits (trail 2.5 ATR + 1 pyramid add at +1R) | $71.23 | $42.97 | $98.86 | $42.73 | $184.56 | $197.76 | rejected |
| gold_combo (pullback + breakout, vol sizing, shared risk cap) | $71.47 | $49.50 | $70.91 | $49.01 | $169.42 | $162.20 | rejected |

Every tweak improved the period it was tuned on and lost out of sample, mostly in 2022–2025 where the
baseline's trades were best. Directional regime filters (SMA/EMA 100–250, momentum, W1 trend, long-only in
up-regimes) did not help even on dev. Adding systems at full risk raised dev drawdowns to 35–51%.
**Decision: no tweak is deployed; the EA stays as is.** Research logs: results/gold_*_dev.md.
