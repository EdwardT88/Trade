# Sizing policies for the gold swing EA (mm_sizing)

Code: `scripts/mm_sizing.py`. It runs in about 15 s and prints every table below. Run `--dev-only` to see only what the selection was made on.
Data: the fixed EA trade list from `scripts/mm_sim.py` (603 trades from 2013 to 2026, with exact R including costs and 5%/yr swap).
Each period starts from a fresh $50. "all" means one account run from 2013 to 2026.

## Protocol and how many combos were tried
- **Dev grid:** 47 combos, tuned on dev 2013-19 only, across 13 families (listed in `build_dev_grid`). I also looked at the dev halves 2013-16H1 and 2016H2-19.
- **Finalist rule:** this rule was coded before any validation run.
  - A combo is eligible if it beats fixed 3% on dev and in both dev halves.
  - Each family contributes its best eligible combo.
  - The top 5 families by dev $ give the 5 finalists.
- **Validation:** each finalist was run once on 2020-21, 2022-25 and 2026, and on the whole history.
- **Disclosure:** the research phase had already seen first-pass dev numbers for most of these ideas. It also did a sign check of the "above or below MA20" split on the validation years. So validation is not fully blind for the equity-curve feature.
- **Live model:** the policies use only the account state and the system's closed-trade R. R per closed deal = profit / risk money at entry.

## Dev results by family (fixed 3% = $59.93, ladder 5/3/2 = $84.61)
| family | combos | median dev $ | best dev $ | eligible |
|---|---|---|---|---|
| B ladder x equity-curve throttle | 4 | 121.4 | 135.4 | 4 |
| C rolling half-Kelly (window W) | 6 | 86.6 | 106.4 | 2 |
| A equity-curve throttle (cumR vs its MA) | 9 | 82.5 | 100.8 | 7 |
| A2 R-momentum (sum of last N R > 0) | 2 | 76.0 | 88.4 | 1 |
| I ladder variants (continuous, on peak, thresholds, levels, step-up) | 9 | 64.1 | 75.8 | 0 |
| G Jones fixed ratio | 3 | 63.8 | 66.3 | 2 |
| E bootstrap DD-constrained f (f\* = 2% relative; 2/6/8% absolute) | 2 | 58.7 | 58.7 | 0 |
| D 0.5 x dev Kelly (dev Kelly = 3.0%, so 1.5%) | 1 | 57.2 | 57.2 | 0 |
| F Grossman-Zhou / CPPI floors | 3 | 56.1 | 58.6 | 0 |
| K drawdown de-risking (incl. the EA's own 10%->1% brake: **$39.08**) | 3 | 56.0 | 59.6 | 0 |
| J streak anti-martingale | 2 | 54.8 | 54.9 | 0 |
| H house money | 2 | 54.2 | 55.8 | 0 |
| L prop cushion gate | 1 | 49.7 | 49.7 | 0 |

All the policies that won on dev share one feature: they size up when the system's own recent R has been good. The rules that respond to account level, drawdown, streaks or a profit cushion did not win.
Notes:
- **Dev Kelly:** it is only 3.0% (the all-data figure of 6% comes mostly from 2022-25). So fixed 3% is already full Kelly on dev, and 5% is about 1.7x dev Kelly.
- **Permutation test:** shuffling the dev trade order 1000 times erases the gain. The throttles end at a median of 0.79-0.93x fixed 3% on shuffled order, against 1.47-2.26x on the real order (p = 0.006-0.02). These p-values are the best of a grid, so they are optimistic.
- **Same average risk:** fixed sizing at the same average risk as each policy gives about $60 on dev. The gain comes from when the risk is taken, not from taking more of it.

## Final table (validation run once)
| policy | dev | 2020-21 | 2022-25 | 2026 | val sum | all 2013-26 | max DD all | -30% hard stop hit (fresh $50) | better | beats ladder |
|---|---|---|---|---|---|---|---|---|---|---|
| REF fixed 3% | 59.93 | 32.72 | 204.90 | 42.77 | 280.39 | 137.50 | 64.7% | dev, 2020-21 | – | – |
| REF ladder 5/3/2 | 84.61 | 23.61 | 252.47 | 38.19 | 314.27 | 213.76 | 74.4% | dev, 2020-21 | – | – |
| **C rolling half-Kelly W60** | 106.43 | 40.79 | 499.59 | 47.27 | **587.65** | **601.83** | **42.9%** | never | yes | yes |
| B ladder x MA15 (1.33/0.5) | 135.41 | 30.60 | 247.68 | 43.95 | 322.23 | 336.48 | 52.9% | dev, 2020-21 | yes | yes |
| A eqMA15 4%/1.5% | 100.75 | 37.90 | 203.70 | 46.34 | 287.94 | 295.69 | 53.8% | never | yes (barely) | no |
| A2 sum of last 50 R > 0: 4%/1.5% | 88.35 | 40.86 | 201.58 | 46.34 | 288.78 | 326.09 | 52.9% | never | yes (barely) | no |
| G fixed ratio delta $40 | 66.28 | 30.83 | 150.84 | 42.60 | 224.27 | 134.86 | 54.1% | dev, 2020-21 | no | no |
| REF EA default brake (DD>=10% -> 1%), 3% | 39.08 | 40.97 | 131.61 | 47.08 | 219.66 | 54.48 | 35.4% | never | – | – |
| REF EA default brake, ladder | 37.95 | 42.84 | 84.41 | 49.80 | 177.05 | 45.68 | 35.7% | never | – | – |

No policy was ruined in any period.

## Robustness checks (none of these were used to choose)
- **Cent lots:**
  - Setup: 0.01-lot steps, floored, taking the minimum lot when it risks no more than 3%.
  - All-history results stay close to the continuous-size results: C $575, B $321, A $289, fixed 3% $141. No trades were skipped.
- **Warm start:**
  - Setup: each validation period is seeded with the system's earlier R history.
  - Validation sums: C 453, A2 360, B 332, A 297, all still above fixed 3% (280).
  - C is lower here because it starts 2022 still at 1% after the bad 2020-21.
- **Costs x1.5:**
  - Validation sum / all-history: C 554 / 463, B 317 / 302, A 281 / 242. Fixed 3% gets 273 / 117 and the ladder 306 / 170.
  - Swap-free: C 808 / 1295 and fixed 3% 321 / 249.
- **Start year:** starting a fresh $50 on 1 January of each year from 2013 to 2025, C beats fixed 3% in 12 of 13 start years. B wins 13/13, A 12/13, A2 9/13 and G 2/13.
- **Family check, done after validation:**
  - All 6 C variants pass validation, including the shrunk ones (val sum 377-609).
  - B passes 4 of 4. A passes 8 of 9; it fails only 3%/1.5%, which takes less risk overall.
  - So the result holds across each family, not just for one lucky parameter.
- **Where C's money came from:**
  - C is close to a two-state switch. About 45% of trades are at the 1% floor and 34% at the 6% cap.
  - The system's mean R by year: 2013-14 −0.15/−0.12; 2015-17 +0.38/+0.28/+0.12; 2018-21 −0.14/−0.14/−0.02/−0.29; 2022-25 +0.29/+0.54/+0.17/+0.24; 2026 −0.21.
  - C ran at about 1% in the bad years and 5-6% in the good years.
  - It reacts with a lag: 2022 was still at 1.3% (1.14x vs 1.41x for fixed 3%), and 2026 was at 4% while the system lost (0.88x).

## Verdict
- **Best: C, rolling half-Kelly over the last 60 trades, clipped to 1-6%, at 2% for the first 15 trades.**
  - It beats fixed 3% and the ladder on dev, on validation and on the whole history.
  - It has the lowest whole-history max DD (43%, against 65% for fixed 3% and 74% for the ladder).
  - It never hit the -30% hard stop from a fresh $50 in any period.
- **Caveat:**
  - C is a bet that the system's edge comes in multi-year regimes. 13 years of gold give only about 4 regime changes, so there are few independent observations, and C gives back a little at each turn.
  - If gold's regimes become shorter than about a year, C turns into a lagging switch that buys high and sells low (expect results near fixed 3% or worse).
- **Current state:** the last 60 R average −0.02, so C would trade at its 1% floor right now. At $50 with 2026 stops (about $73), the minimum lot actually risks about 1.5%.
- **B** has higher dev returns but hits the -30% hard stop in 2013 and 2020-21. Its ladder part was also chosen after seeing all the data.
- **A / A2** pass validation only marginally (+3%), but they are simpler and give a much better one-account history than fixed 3%.
- **Rejected:** Kelly anchor, bootstrap f\*, Grossman-Zhou/CPPI, fixed ratio, house money, all ladder variants, streak sizing, drawdown de-risking and the cushion gate. All of them lose to fixed 3% on dev, or on validation (fixed ratio).
- **Important side finding:** the EA's default drawdown brake (`InpDDReducePct=10`, `InpReducedRiskPct=1`) costs more than half of the long-run return.
  - Whole-history results: $54 vs $138 at 3%, and $46 vs $214 with the ladder.
  - Every number in mm_sim assumes the brake is off. Set `InpDDReducePct=100` with any of these policies.

## MQL5 sketch for C
- **On every close:** compute R = net profit (including swap and commission) / risk money at entry. Store the risk money per ticket in a GlobalVariable. Append R to `MQL5/Files/GoldSwingCent_R.csv`.
- **Before an entry:**
  - If fewer than 15 R are stored, use 2%.
  - Otherwise take x = the last min(n, 60) R. Compute k = mean(x) / max(sample variance(x), 0.5). Risk = clamp(0.5·k, 1%, 6%).
- **Optional seed:** load the file with the backtest's latest 60 R values (warm start).
- **Settings:** keep the hard stop, and set `InpDDReducePct=100`. The 5% daily-loss stop only blocks the rest of the day after a full loss at 6%, which is harmless with one position at a time.
