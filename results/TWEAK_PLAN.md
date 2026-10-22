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
