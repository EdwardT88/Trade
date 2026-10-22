# gold_exits: trade management for more return (exits, partial TP, early cut, pyramiding)

**Verdict: REJECTED. Keep the deployed EA's exits.** The final candidate beat the EA on dev 2013–2019 but lost on
the sum of the validation periods at both 2% and 3% risk (results/TWEAK_PLAN.md rule 2).

Module: `strategies/gold_exits.py`. Entries and the initial stop are unchanged from `swing_pullback` (the EA).
Only what happens after the fill changes. Run it with `python -m strategies.gold_exits --risk 2`. It prints the
same output as `scripts/gold_full_eval.py`, but runs a group simulator, because the engine cannot hold a pyramid add.

## Protocol
- Selection used dev 2013-01-01 .. 2020-01-01 only (gold H1 bars). There were **42 parameter combos** in 3 rounds,
  all listed below.
- Validation (2020–21, 2022–25, 2026 Mar–Sep) ran **once** on the final candidate, at 2% and 3%. Nothing was
  revised afterwards.
- Costs: spread max($0.25, 0.8 bps), ×3 around the rollover, $0.05 stop/time slippage, swap 5%/yr (×3 Wednesday)
  charged per unit from its own fill.
- Account: the $50 cent account with the evaluator's rules (half risk below a 10% drawdown, daily −5%, 3 losses a
  day, hard stop at $35, 0.01 oz minimum lot).
- **Simulator check.** With every group option off, `gold_exits.simulate` matches `backtest/engine.py` exactly: all
  4 periods at 2% and 3% (R stats, account, drawdown), plus be_r, tp_r, trail-start and long-only variants.

## Group options (custom simulator, pessimistic)
- **Pyramid.**
  - Trigger: a bar (H1 on dev, M1 from 2022) closes ≥ `add_at_r` R in profit.
  - Fill: a market order at the next bar's open, at most one add.
  - Stop: the common stop of both units moves to entry₁ + `add_lock_r`·R and is never loosened. Both units then
    share the chandelier trail.
  - Size: the add is shrunk so that the open risk to the common stop never exceeds 1.5 × the first unit's risk
    (each unit is counted ≥ 0, plus slippage). It is rounded down to the 0.01 lot step and skipped below the
    minimum lot or if the price is already through the new stop.
  - In the final run the worst group loss in any period was −1.24 R.
- **Partial TP.** `tp1_frac` of the first unit closes at +`tp1_r` R with a limit order; the rest then moves to
  breakeven.
- **Early cut.** One check at the first bar that opens `cut_h` hours after the fill: close if below +`cut_r` R.

## What dev says before tuning (baseline trades, 313)
- After +1 R the rest of a trade is worth only +0.09 R on average: 118 trades reached +1 R and finished at
  +1.09 R. After +2 R it is +0.04 R. So there is little continuation to pyramid into on dev.
- From 24 h onwards the remaining expectancy is slightly negative in every unrealised-P&L bucket (−0.05 to −0.11 R,
  which includes swap). Before 12 h, trades that are under water are about flat (≈0.00 R), not negative, so an
  early cut has little to remove.

## Dev sweep (2013–2019; R stats without account limits, $50 account at 2% and 3%)
| # | change vs EA | n | avg R | SE | win% | med hold h | adds (avg R/add) | $50 @2% | DD% | $50 @3% | DD% |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BASE | EA (trail 3.0, hold 3 d) | 313 | +0.038 | 0.065 | 43.8 | 34 | | 56.41 | 19.7 | 62.08 | 26.6 |
| A1 | trail 2.0 | 358 | +0.058 | 0.052 | 42.5 | 25 | | 67.82 | 18.6 | 75.09 | 24.2 |
| A2 | trail 2.5 | 323 | +0.064 | 0.061 | 45.8 | 31 | | 67.54 | 19.6 | 77.19 | 25.5 |
| A3 | trail 4.0 | 304 | +0.015 | 0.067 | 43.1 | 38 | | 49.95 | 21.7 | 43.63 | 29.0 |
| A4 | no trail | 302 | +0.012 | 0.068 | 45.0 | 39 | | 50.69 | 21.6 | 37.60 | 29.3 |
| A5 | trail 2.0 from +1 R | 325 | +0.035 | 0.062 | 50.5 | 31 | | 55.95 | 22.0 | 57.03 | 28.4 |
| A6 | trail 1.5 from +1 R | 326 | +0.012 | 0.057 | 51.2 | 28 | | 49.30 | 21.2 | 45.76 | 29.9 |
| A7 | breakeven at +1 R | 321 | +0.024 | 0.063 | 50.8 | 34 | | 55.16 | 22.4 | 51.07 | 31.8 |
| A8 | TP 2 R | 317 | +0.019 | 0.059 | 43.5 | 30 | | 50.30 | 20.6 | 51.21 | 26.1 |
| A9 | TP 3 R | 313 | +0.043 | 0.065 | 43.8 | 33 | | 56.35 | 19.6 | 64.88 | 26.4 |
| A10 | hold 2 d | 330 | +0.033 | 0.057 | 46.4 | 34 | | 55.96 | 19.4 | 56.69 | 25.0 |
| A11 | hold 4 d | 307 | +0.060 | 0.069 | 43.0 | 35 | | 63.45 | 18.5 | 66.40 | 23.7 |
| A12 | hold 5 d | 307 | +0.050 | 0.068 | 42.7 | 35 | | 56.53 | 19.9 | 57.94 | 25.5 |
| A13 | weekend hold, 5 d | 316 | +0.087 | 0.074 | 43.4 | 69.5 | | 69.59 | 21.7 | 65.93 | 28.0 |
| B1 | early cut 8 h | 375 | +0.028 | 0.047 | 29.6 | 9 | | 60.16 | 19.6 | 57.30 | 26.0 |
| B2 | early cut 24 h | 329 | +0.048 | 0.060 | 39.2 | 24 | | 56.30 | 19.1 | 61.24 | 27.0 |
| B3 | early cut 4 h | 415 | −0.044 | 0.040 | 22.4 | 4 | | 38.47 | 23.3 | 35.78 | 32.0 |
| C1 | ½ TP at 1 R, rest BE | 316 | +0.020 | 0.054 | 50.6 | 34 | 119 TP hits | 54.82 | 19.6 | 48.84 | 26.5 |
| C2 | ½ TP at 1.5 R, rest BE | 313 | +0.028 | 0.059 | 44.7 | 34 | 74 TP hits | 56.81 | 20.7 | 59.57 | 27.2 |
| C3 | ½ TP at 1 R, no BE | 313 | +0.018 | 0.054 | 50.8 | 34 | 118 TP hits | 49.43 | 19.4 | 46.09 | 25.1 |
| D1 | add 1.0× at +1 R, lock BE | 313 | +0.069 | 0.088 | 38.0 | 34 | 99 (+0.079) | 50.07 | 22.7 | 56.73 | 30.0 |
| D2 | add 0.5× at +1 R, lock BE | 313 | +0.057 | 0.075 | 39.9 | 34 | 99 (+0.040) | 61.24 | 22.0 | 48.67 | 27.6 |
| D3 | add 0.5× at +0.5 R, lock BE | 336 | +0.020 | 0.070 | 33.3 | 29 | 184 (−0.006) | 54.33 | 29.0 | 58.54 | 38.2 |
| D4 | add 1.0× at +1.5 R, lock +0.5 R | 314 | +0.041 | 0.079 | 38.5 | 34 | 65 (+0.051) | 53.07 | 25.8 | 43.51 | 33.6 |
| D5 | add 1.0× at +1 R, lock −0.5 R (add shrunk to the 1.5 R cap) | 313 | +0.063 | 0.087 | 38.7 | 34 | 99 (+0.077) | 56.81 | 22.4 | 54.56 | 29.6 |
| D6 | add 0.5× at +1 R, lock +0.25 R | 316 | +0.061 | 0.074 | 38.6 | 33 | 100 (+0.041) | 64.41 | 19.9 | 67.87 | 26.9 |
| E1 | trail 2.25 | 338 | +0.064 | 0.057 | 44.7 | 28 | | 70.68 | 21.5 | 76.67 | 27.9 |
| E2 | trail 2.5, hold 4 d | 320 | +0.064 | 0.062 | 43.8 | 31 | | 65.69 | 18.6 | 66.47 | 25.8 |
| E3 | trail 2.0, hold 4 d | 358 | +0.067 | 0.053 | 41.9 | 25 | | 72.87 | 17.8 | 92.69 | 23.9 |
| E4 | trail 2.5 + add 0.5× at +1 R, lock +0.25 R | 325 | +0.082 | 0.070 | 39.4 | 30 | 99 (+0.042) | 69.58 | 18.7 | 85.06 | 25.8 |
| **E5** | **trail 2.5 + add 1.0× at +1 R, lock BE (final)** | 323 | **+0.094** | 0.082 | 38.4 | 31 | 98 (+0.089) | **71.23** | 20.3 | **88.18** | 29.1 |
| E6 | trail 2.0 + add 1.0× at +1 R, lock BE | 358 | +0.078 | 0.070 | 34.9 | 25 | 96 (+0.076) | 76.00 | 23.2 | 73.56 | 30.3 |
| E7 | trail 2.0 + add 0.5× at +1 R, lock BE | 358 | +0.068 | 0.060 | 38.5 | 25 | 96 (+0.038) | 75.66 | 20.5 | 78.78 | 27.8 |
| E8 | trail 2.5, weekend hold 5 d | 332 | +0.089 | 0.067 | 41.9 | 60.5 | | 78.20 | 19.9 | 66.85 | 27.7 |
| E9 | trail 2.5, TP 3 R | 323 | +0.062 | 0.060 | 45.8 | 30 | | 67.97 | 19.7 | 73.84 | 26.2 |
| E10 | trail 2.0 + add 1.0× at +1.5 R, lock +0.5 R | 358 | +0.069 | 0.064 | 39.7 | 25 | 59 (+0.066) | 64.61 | 20.2 | 60.66 | 28.5 |
| E11 | add 0.5× at +1 R, lock +0.5 R | 317 | +0.064 | 0.072 | 46.4 | 31 | 101 (+0.040) | 71.19 | 20.4 | 65.18 | 26.8 |
| E12 | add 0.5× at +1 R, lock +0.25 R, hold 4 d | 311 | +0.082 | 0.079 | 37.3 | 34 | 106 (+0.048) | 70.74 | 19.4 | 61.69 | 28.3 |
| F1 | trail 2.5 + add 1.0× at +0.75 R | 331 | +0.057 | 0.085 | 36.3 | 30 | 132 (+0.038) | 57.03 | 27.3 | 66.06 | 35.8 |
| F2 | trail 2.5 + add 1.0× at +1.25 R | 323 | +0.104 | 0.079 | 41.5 | 31 | 73 (+0.177) | 70.37 | 18.6 | 97.99 | 24.7 |
| F3 | trail 2.25 + add 1.0× at +1 R | 338 | +0.087 | 0.077 | 37.0 | 28 | 99 (+0.076) | 80.44 | 23.9 | 92.33 | 33.2 |
| F4 | trail 2.75 + add 1.0× at +1 R | 317 | +0.077 | 0.086 | 37.9 | 33 | 101 (+0.067) | 55.54 | 21.1 | 65.92 | 29.0 |
| F5 | trail 2.5 + add 0.75× at +1 R | 323 | +0.088 | 0.076 | 39.3 | 31 | 98 (+0.067) | 66.47 | 19.9 | 89.11 | 26.8 |

Trail = chandelier distance in ATR(H4,14) at entry. "lock" = where both stops go when the add fills (R of unit 1).

**Why E5 was chosen.**
- It sits on a dev plateau of trail 2.0–2.5 plus a full add at +1.0–1.25 R, at about $150–173 for the
  @2% + @3% account sum. The EA scores $118 and the tighter trail alone $143–147. Every neighbour except trail 2.75
  and the +0.75 R trigger stays clearly above the EA.
- It uses round values. F3 (trail 2.25) and F2 (add at +1.25 R) scored higher, but they are less round and are
  the edges of the plateau.
- Other variants were not chosen:
  - Weekend hold (A13, E8) conflicts with the owner's preference for short holds and adds gap risk.
  - Partial TP, breakeven, fixed TP and early cuts were all ≤ the EA.

**Dev robustness of E5, before validation:**
- The whole gain comes from the trending years: 2015 +0.48 R vs +0.38 for the EA, 2016 +0.49 vs +0.28, 2017
  +0.20 vs +0.12. In the losing years there was no gain: 2013 −0.12 vs −0.15, 2014 −0.16 vs −0.12, 2018 −0.07
  vs −0.14, 2019 −0.20 vs −0.14.
- Under stress costs (spread and slippage ×1.5, swap 8%) the advantage disappears: $49.40 vs $49.70 at 2%. The add
  pays a second spread and a second slippage.
- All of these differences are within about one SE (SE of avg R ≈ 0.06–0.08).

## Final run (once): E5 vs the EA, $50 start each period
| period | E5 avg R (n) | adds (avg R/add) | E5 $ @2% (DD) | EA $ @2% (DD) | E5 $ @3% (DD) | EA $ @3% (DD) |
|---|---|---|---|---|---|---|
| dev 2013–2019 | +0.094 (323) | 98 (+0.089) | 71.23 (20.3%) | 56.41 (19.7%) | 88.18 (29.1%) | 62.08 (26.6%) |
| val 2020–2021 | −0.120 (92) | 21 (−0.039) | 42.97 (19.6%) | 41.95 (19.2%) | 41.22 (27.0%) | 40.35 (24.1%) |
| val 2022–2025 | +0.274 (186) | 78 (+0.166) | 98.86 (13.6%) | 122.45 (11.3%) | 115.52 (17.3%) | 154.70 (14.9%) |
| val 2026 Mar–Sep | −0.430 (24) | 9 (−0.539) | 42.73 (19.0%) | 46.70 (12.8%) | 41.02 (22.6%) | 45.75 (15.4%) |
| **validation sum** | | | **184.56** | **211.10** | **197.76** | **240.80** |

There was no hard stop and the maximum drawdown was 29.1%, but the validation sum is lower at both risk levels, so
**the candidate is rejected.**

**Post-hoc decomposition (information only, at 2%; neither is a valid candidate).**
- **Trail 2.5 alone.** 2022–25 drops to +0.201 R / $93.73, against +0.289 R / $122.45 for the EA. The tighter
  trail cuts the 2022–25 trend winners. This is the main damage.
- **Add alone, with the EA trail (D1).** 2022–25 rises to +0.416 R / $165.01, but 2020–21 is $40.81 and 2026 is
  $42.68. D1 also lost on dev ($50.07 vs $56.41), so the rule would have rejected it anyway.

The general lesson: exits that suit the range-bound dev years (tighter trail) hurt the trending years, and the
reverse holds for pyramiding. No exit or management change was robust across both kinds of regime.

## Other observations
- **The half-risk drawdown rule shapes the account path.** On dev, 55% of the EA's trades ran at half risk because
  the account was more than 10% below its peak. Variants that add variance, like the pyramid, spend more time
  there: 66% for D1. That is why D1's higher avg R (+0.069 vs +0.038) still gave a lower dev account ($50.07 vs
  $56.41).
- **Resolution caveat.** Dev is H1 data, so the add decision and the trail update happen hourly. From 2022 they
  happen every minute (M1), so the add fills closer to exactly +1 R.

## MQL5 notes, if pyramiding is ever revisited
- **Add rule.** On each new M1 bar: if the position is still open, no add has been made yet, and the previous M1
  close is at least 1 R in profit (Bid − entry for longs, entry − Ask for shorts), open a second position with the
  same lots at market.
- **Stops after the add.** Set the SL of both positions to max(current SL, entry₁). Trail both with the same
  chandelier rule, and close both at the Friday 20:00 UTC or 3-day exit.
- **Risk cap.** Before sending the add, check that (lots₁·max(0, entry₁−SL) + lots₂·(price−SL)) ≤ 1.5 × the
  initial risk; otherwise reduce lots₂.
