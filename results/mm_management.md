# mm_management: trade management for more return (cluster study)

Code: `scripts/mm_management.py` (`python scripts/mm_management.py` prints everything below; `--stage dev` prints only
what was used to choose). Protocol: results/MM_RESEARCH_PLAN.md.

## Verdict
- **Passes the rule, and is the most robust: W1, the weekend hold for winning longs.** At Friday 20:00 UTC, a long that
  is ≥ +1 R stays open. Its SL moves to entry + 0.5 R, the chandelier trail keeps running, and it closes on Tuesday at
  20:00 UTC. Compared with the EA at 3%:
  - Dev: $73.44 vs $59.93.
  - Validation sum: $317.24 vs $280.39.
  - No validation period is worse: 2026 is unchanged because no trade qualified.
  - Whole history: $205.36 vs $137.50, with the same max DD of 65%.
  - Better than the EA in 9 of 14 years.
- **Passes the rule, with the highest return: C7 (pre-declared primary) = W1 + X1 + R2 + T2.** At 3%:
  - Dev $137.21 vs $59.93; validation sum $637.51 vs $280.39; whole history $563.24 vs $137.50.
  - The cost is a larger max DD: 80% vs 65%.
  - The gain is a trend-regime bet. 2020–21 is worse ($21.84 vs $32.72, DD 58% vs 39%), 2026 is slightly worse
    ($40.88 vs $42.77), and 2022–25 carries the whole validation sum ($574.79 vs $204.90).
- **Also pass:**
  - T2, the Turtle add on its own: validation sum $402.49, but it is worse in 2020–21 and 2026.
  - C1 = W1+X1: $381.73.
  - C5 = W1+X1+R2: $368.43.
  - X1, the cap extension on its own: $286.92. This is a pass by only $6.5, with t ≈ 0.4 across years, so treat it as noise.
- **Fails validation: R2, re-entry after a stop-out.** Validation sum $270.01 vs $280.39. It still sits inside C7,
  because C7 was frozen before validation. C7 without R2 was not validated, so it is not a result.
- **Rejected on dev:**
  - Stale-trade exit (S): only S3 passed, and it was an isolated peak.
  - Partial TP + runner (P): none passed.
  - 12 h and 24 h cooldowns after a stop-out (R5, R6).
  - Turtle add triggered at +1.5 ATR (T3).
- **Same max DD, if the owner wants C7: run it at 2%.** On the whole history, C7 at 2% has the EA-at-3% drawdown (65%)
  and ends at $298.68 vs $137.50. Its validation sum is $347.54 vs $280.39. It is still worse in 2020–21: $29.22 vs
  $32.72. This was read off the table after validation and is not a separately validated choice.
- **Do not combine C7 with the 5/3/2 ladder.** In 2020–21, $50 falls to $11.69 (DD 78%), and the owner's −30% hard
  stop would fire.

## Protocol and method
- **Simulator.** A numba group simulator replays the EA's own signals on the same bars and costs as `backtest/engine.py`:
  spread max($0.25, 0.8 bps), ×3 at rollover, $0.05 slippage on stop and time exits, and swap of 5%/yr per unit, ×3 on
  Wednesdays.
  - With every option off, it reproduces `mm_sim.get_trades()` exactly: 603 trades, identical R and exit reasons,
    including swap-free.
  - R = group P&L / first unit's initial risk.
  - The $50 account comes from `mm_sim.simulate`, at fixed 2%, fixed 3% and the 5/3/2 ladder, each period from a fresh
    $50.
  - Extended trades block new entries, as in the EA, which holds one position at a time.
- **Combos.** 48 combos were evaluated on dev 2013–2019 only:
  - 40 single ideas in round 1, with the grid written before any result.
  - 8 combinations of family winners in round 2.
  - A family winner had to beat the EA on dev avg R, on dev $ at 2% and at 3%, and on avg R in both dev halves
    (2013–16H1 and 2016H2–19), and could not be an isolated peak.
- **Finals.** 7 finals were frozen before any validation number was seen and run once. C7 was declared primary in advance.
- **Disclosure.** The research-phase quick checks that suggested W (weekend) and X (extension) used the full
  2013–2026 sample. Validation is therefore not fully blind for those two ideas. R2, T2 and the combinations had no
  such look.

## Dev sweep (2013–2019; $50 fresh; max DD in brackets)
| combo | n | avg R | halves (13–16H1 / 16H2–19) | $ @2% | $ @3% | $ ladder |
|---|---|---|---|---|---|---|
| EA | 313 | +0.038 | +0.091 / −0.013 | 58.68 (29%) | 59.93 (41%) | 84.61 (54%) |
| W1 wkd long ≥1R, lock .5, →Tue | 313 | +0.062 | +0.119 / +0.006 | 67.42 (31%) | 73.44 (44%) | 97.64 (44%) |
| W2 / W7 (≥0.5R; lock .25) | 313 | +0.063 / +0.062 | both up | 67.82 / 67.38 | 74.03 / 73.38 | 92.72 / 97.55 |
| W3 / W6 (≥1.5R →Tue / →Mon) | 313 | +0.046 / +0.033 | | 61.27 / 56.72 | 63.85 / 56.94 | |
| W4 / W5 (→Mon 20:00) | 313 | +0.053 / +0.057 | H2 worse | 63.78 / 65.56 | 67.68 / 70.45 | |
| W8 both sides | 311 | +0.049 | H2 worse | 62.22 | 65.20 | 84.67 |
| X1 cap ext ≥0R →Fri, SL to BE | 309 | +0.053 | +0.114 / −0.007 | 63.70 (26%) | 67.63 (37%) | 82.98 (47%) |
| X2 / X3 (≥0.5R / ≥1R) | 310 / 311 | +0.041 / +0.038 | H2 worse | 59.21 / 58.51 | 60.66 / 59.62 | |
| X4–X6 (no H4-trend condition) | | = X1–X3 | | | | |
| X7 / X8 (+2d / +4d through weekend) | 309 / 307 | +0.044 / +0.046 | | 60.45 / 60.85 | 62.58 / 63.15 | |
| S1–S6 stale exit (12–48 h, MFE <0.3/0.5R) | 316–348 | +0.011…+0.046 | mixed | 51.00…62.56 | 49.30…66.46 | |
| P1–P6 ½ TP 1–2R + runner | 305–319 | +0.017…+0.038 | none pass | 52.56…59.09 | 51.67…61.18 | |
| R1 / R3 / R4 re-entry RSI 35 / 30 / 35-24h | 317 | +0.039 / +0.053 / +0.039 | | 58.89 / 64.41 / 58.89 | 60.18 / 68.78 / 60.18 | |
| R2 re-entry RSI 45/55, 48 h | 327 | +0.071 | +0.120 / +0.025 | 72.90 (30%) | 82.56 (43%) | 104.91 (49%) |
| R5 / R6 cooldown 24 h / 12 h | 300 / 307 | +0.028 / +0.035 | | 54.88 / 57.18 | 54.39 / 57.70 | |
| T1 add 1.0x @+1 ATR | 319 | +0.091 | +0.141 / +0.043 | 71.76 (41%) | 73.70 (55%) | 93.64 (76%) |
| T2 add 0.5x @+1 ATR | 319 | +0.074 | +0.119 / +0.031 | 69.90 (32%) | 74.92 (45%) | 95.92 (65%) |
| T3 add 1.0x @+1.5 ATR | 323 | +0.003 | −0.085 in H2 | 42.38 | 34.31 (65%) | 19.30 |
| T4 / T5 / T6 (0.5x 2 adds / 1.0x 2 adds / 0.5x @+0.5 ATR 2 adds) | 322–323 | +0.065 / +0.084 / +0.104 | | 64.00 / 62.32 / 78.28 | 64.16 / 55.75 / 83.96 (56%) | |
| C1 W1+X1 | 309 | +0.088 | +0.151 / +0.027 | 78.45 (29%) | 91.77 (40%) | 121.45 (44%) |
| C2 W1+R2 / C3 W1+T2 / C4 X1+T2 | | +0.082 / +0.086 / +0.084 | | 78.03 / 74.56 / 73.75 | 91.12 / 82.09 / 80.88 | |
| C5 W1+X1+R2 | 321 | +0.107 | +0.177 / +0.039 | 90.05 (30%) | 112.48 (42%) | 160.42 (47%) |
| C6 W1+X1+T2 | 315 | +0.114 | +0.196 / +0.037 | 87.76 (35%) | 103.94 (48%) | 142.24 (50%) |
| **C7 W1+X1+R2+T2** | 329 | +0.140 | +0.240 / +0.045 | 106.06 (38%) | 137.21 (52%) | 206.33 (53%) |
| C8 W1+X1+R2+T6 | 335 | +0.174 | +0.343 / +0.017 | 122.05 (47%) | 157.85 (63%) | 211.35 (57%) |

Dev notes:
- The H4-trend condition in X never binds: every cap exit in profit still had the trend.
- The Turtle add gains come from the 2015–17 trend years and lose in 2013, 2014 and 2019, the same pattern as the
  rejected E5 pyramid.
- Under 1.5× spread and slippage, T2's dev edge almost vanishes: $55.28 vs $53.55 at 3%.
- R2 rests on only 14 re-entries in 7 years.

## Final run (once). Avg R and $50 at 3% (DD); validation_sum = 2020–21 + 2022–25 + 2026
| candidate | dev 13–19 | 2020–21 | 2022–25 | 2026 | all 2013–26 | val_sum @3% | val_sum @2% | val_sum ladder |
|---|---|---|---|---|---|---|---|---|
| EA avg R | +0.038 | −0.145 | +0.289 | −0.206 | +0.076 | | | |
| EA $ | 59.93 (41%) | 32.72 (39%) | 204.90 (20%) | 42.77 (24%) | 137.50 (65%) | 280.39 | 214.87 | 314.27 |
| W1 avg R | +0.062 | −0.130 | +0.327 | −0.206 | +0.101 | | | |
| W1 $ | 73.44 (44%) | 33.98 (36%) | 240.49 (20%) | 42.77 (24%) | 205.36 (65%) | **317.24** | 231.64 | 353.63 |
| X1 avg R | +0.053 | −0.191 | +0.303 | −0.151 | +0.083 | | | |
| X1 $ | 67.63 (37%) | 29.17 (46%) | 213.22 (18%) | 44.53 (20%) | 149.85 (66%) | 286.92 | 217.16 | 317.72 |
| R2 avg R | +0.071 | −0.171 | +0.274 | −0.238 | +0.083 | | | |
| R2 $ | 82.56 (43%) | 29.91 (44%) | 198.62 (23%) | 41.48 (26%) | 162.73 (69%) | 270.01 ✗ | 209.10 | 303.91 |
| T2 avg R | +0.074 | −0.187 | +0.392 | −0.249 | +0.116 | | | |
| T2 $ | 74.92 (45%) | 28.16 (46%) | 332.99 (23%) | 41.34 (28%) | 232.40 (72%) | 402.49 | 264.60 | 405.12 |
| C1 avg R | +0.088 | −0.194 | +0.386 | −0.167 | +0.125 | | | |
| C1 $ | 91.77 (40%) | 29.09 (47%) | 308.59 (16%) | 44.05 (20%) | 290.29 (68%) | 381.73 | 256.51 | 394.88 |
| C5 avg R | +0.107 | −0.218 | +0.368 | −0.202 | +0.124 | | | |
| C5 $ | 112.48 (42%) | 26.58 (51%) | 299.13 (19%) | 42.72 (22%) | 305.67 (72%) | 368.43 | 249.99 | 381.74 |
| C7 avg R | +0.140 | −0.269 | +0.511 | −0.243 | +0.171 | | | |
| **C7 $** | 137.21 (52%) | 21.84 (58%) | 574.79 (21%) | 40.88 (27%) | 563.24 (80%) | **637.51** | 347.54 | 558.53 |
| C7 @2% $ | 106.06 (38%) | 29.22 (43%) | 274.42 (14%) | 43.90 (19%) | 298.68 (65%) | | | |
| C7 ladder $ | 206.33 (53%) | 11.69 (78%) | 511.79 (22%) | 35.05 (42%) | 610.05 (76%) | | | |

- Ladder reference (EA trades): dev $84.61, validation sum $314.27, whole history $213.76 (DD 74%).
  - Run under the same ladder, W1, T2, C1, C5 and C7 beat it on all three measures. X1 loses on dev ($82.98) and on
    the whole history ($197.97). R2 loses on validation ($303.91).
  - At plain fixed 3%, only C1, C5 and C7 beat the ladder reference on all three. W1 at 3% beats it only on validation
    ($317.24); it loses on dev ($73.44) and on the whole history ($205.36).
- Nothing was ruined (equity never fell below $5) at 2%, 3% or the ladder.
- The worst single trade in all candidates is still −1.24 R. With the add, C7 has 6 trades below −1.1 R; the EA has 2.

**Per-year sum of R vs the EA** (information only, after the once-only run):
- W1 is better in 9 of 14 years; its worst year is 2018 (−1.7 R).
- C7 is better in 10 of 14 years, but loses 12 R in 2021 and 3.4 R in 2018, and gains 22.5 R in 2024.
- t of the yearly differences: W1 2.07, C7 2.13, T2 1.88, C1 1.85, X1 0.44, R2 0.76.

**Costs** (same frozen rules, @3%; dev / val_sum / all):
| candidate | swap-free | stress 1.5× spread and slippage |
|---|---|---|
| EA | $83.63 / $321.20 / $248.73 | $53.55 / $273.49 / $117.16 |
| W1 | $104.12 / $368.33 / $382.49 | $65.61 / $309.42 / $175.10 |
| C7 | $224.20 / $800.60 / $1317.82 | $103.02 / $614.79 / $398.24 |

The ordering holds in both cost scenarios.

## MQL5 (all of it uses the position's own state, the clock and completed H4 bars)
- **W1.** At Fri 20:00 UTC: if the position is long and Bid − entry ≥ 1 R, do not close. Set SL = max(SL, entry +
  0.5 R), keep trailing, and close at Tue 20:00 UTC. The PC must be on, or use OnInit/OnTimer catch-up.
- **X1.** At entry + 72 h: if open P&L ≥ 0, set SL = max(SL, entry) and keep the position until the Friday close, where
  the W1 rule applies.
- **T2.** When the trade opens, place a buy-stop (sell-stop for shorts) at entry ± 1 × ATR(H4) at entry, with 0.5× the
  lots.
  - On fill, set the SL of both positions to max(SL, fill − 2 ATR), never loosened.
  - Check that both positions' combined risk to that SL is ≤ 1.5 × the first position's risk.
  - Trail and close both together; delete the pending order when the first position closes.
  - At $50 and 3%, the first unit is about 0.05 oz at a $30 stop, so the add rounds down to 0.02 oz. At 2026's ~$73
    stops it is 0.02 oz, so the add is 0.01 oz, which is coarse but possible.
- **R2.** After an SL loss, for 48 h, also accept an RSI(14) H1 cross of 45 (shorts: 55) in the same direction if the
  H4 trend still agrees, with one re-entry per stop-out. It failed validation alone, so it should be dropped if C7 is
  ever rebuilt. That rebuilt version would be a new, unvalidated variant.
