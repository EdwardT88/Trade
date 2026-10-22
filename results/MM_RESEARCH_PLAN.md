# Money/trade-management research — protocol (written before the search)

Question (owner): beyond "risk A or B", what else can be tuned — sizing rules, milestones, trade handling,
account/broker side — to get the most return out of the gold swing EA? Research first, then test.

Shared tools: `scripts/mm_sim.py` (EA trades 2013–2026 with exact R incl. costs; $50 compounding with any
sizing policy; periods dev 2013–19, val 2020–21 / 2022–25 / 2026) and `scripts/gold_full_eval.py`
(entry/exit changes through the engine).

References (from mm_sim, fresh $50 per period; validation_sum = 2020–21 + 2022–25 + 2026 totals):
| Policy | dev 2013–19 | val sum | all 2013–2026 | max DD all |
|---|---|---|---|---|
| fixed 2% | $58.68 | $214.87 | $106.13 | 49% |
| fixed 3% | $59.93 | $280.39 | $137.50 | 65% |
| ladder 5/3/2 (chosen after seeing all data) | $84.61 | $314.27 | $213.76 | 74% |

Rules: ideas are tuned on dev 2013–2019 only; validation is run once per final candidate. A candidate is
"better" if it beats fixed 3% on dev AND on validation_sum, is never ruined (< $5), and reports its max DD
(the owner accepts large drawdowns but every result states them). Cost/account-side changes (swap-free,
spread, rebates) are evaluated by re-running the same trades with different costs.
