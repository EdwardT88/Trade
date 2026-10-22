# gold_combo: several gold swing systems in one account + sizing rules (research log)

**Verdict: REJECTED. Keep the deployed EA.** The final candidate beat the EA on dev 2013–2019 at both 2% and 3% risk,
but lost on the sum of the validation periods at both risk levels (results/TWEAK_PLAN.md rule 2):

- **2% risk:** $169.42 vs $211.10.
- **3% risk:** $162.20 vs $240.80.

It won 2020–2021 and 2026, but it lost most of the 2022–2025 profit.

Module: `strategies/gold_combo.py`. It has its own small portfolio simulator, because `backtest/engine.py` holds only one
position at a time. Run it with `python -m strategies.gold_combo --risk 2`. The output has the same format as
`scripts/gold_full_eval.py`, plus `by_sys` and `risk_w_r` (the sum of R × actual risk / nominal risk).
With `--params '{"systems": "pullback", "w_pullback": 1, "vol_hi": 1}'` the simulator reproduces the engine to the cent
in every period:

| Period | 2% risk | 3% risk |
|---|---|---|
| dev 2013–2019 | $56.41 | $62.08 |
| 2020–2021 | $41.95 | $40.35 |
| 2022–2025 | $122.45 | $154.70 |
| 2026 | $46.70 | $45.75 |

## Protocol
- **Selection.** Every choice used dev 2013-01-01 .. 2020-01-01 only (gold H1 bars). The sweep harness truncated the
  data at 2020-01-01 and never computed a validation number.
- **Validation.** The final candidate ran on all periods once, at 2% and 3%. Nothing was revised afterwards.
- **Parameter combos.** 36 were run on dev, plus the baseline (A1). One combo, H4, was run twice: a bug made
  "risk × 0" fall through to the min-lot exception, so it was fixed and rerun. That makes 38 dev runs in total.
- **Costs.** As in `gold_full_eval`: spread max($0.25, 0.8 bps), ×3 at rollover, $0.05 stop slippage, 5%/yr swap.
- **Account rules.** These are the EA's rules, applied to the whole account:
  - $50 start;
  - risk % of the balance;
  - half risk in a 10% drawdown;
  - min lot 0.01 oz, with the min-lot exception up to 3%;
  - day stop at −5%, at most 3 losses and 8 entries a day;
  - hard stop at $35;
  - no single trade risks more than 3%.

  Each system keeps its own one-position rule. The portfolio adds an **open-risk cap**: the sum of the initial risks of
  all open positions may not exceed `cap × risk%` of the balance.
- **Dev robustness score.** The account result of one run is very path-dependent. At $50, the 0.01 oz lot step and the
  drawdown halving amplify that. So each combo was also run at risk 1.5/2/2.5/3 on full dev and on each half of dev
  (2013-01..2016-06 and 2016-07..2019-12, each from a fresh $50). The score is the mean log(final / baseline final)
  over those 12 runs. "wins" counts how many of the 12 beat the baseline.

## Component systems on dev (each alone, no account limits)

| System | n | avg R | t | med hold |
|---|---|---|---|---|
| pullback, the EA (A1) | 313 | +0.038 | 0.59 | 34 h |
| breakout, H4 Donchian 20 + EMA50, flat Friday (A2) | 399 | +0.017 | 0.26 | 45 h |
| breakout, weekends held, max 5 days (A3) | 398 | +0.040 | 0.55 | 108 h |
| regime, EMA50/200 flip + EMA20 reclaim, flat Friday (A4) | 408 | −0.062 | −1.06 | 32 h |

Weekly R correlation between pullback and breakout (Friday-flat version) is 0.36. The regime system loses on dev, so
it was dropped after B3 and E8.

## Dev diagnostics (dev only, used for the choices)
- **Volatility.** Volatility is the percentile of ATR(14,H4)/close over the last 1500 H4 bars. In the top tercile, all
  four systems were negative on dev:
  - pullback −0.054;
  - breakout −0.176 (Friday-flat) and −0.144 (weekend);
  - regime −0.261.

  The bottom and middle terciles were better. This consistency is why the high-volatility risk cut was tested. The
  linear vol_k sizing was tested too, but the low-volatility tercile was not uniformly good (pullback −0.015 there).
- **Equity-curve state.** Measured as the system's R curve against its mean over the last 20 trades. The two systems
  disagreed:
  - pullback was −0.016 R below the mean vs +0.079 above it (the filter would help);
  - breakout was +0.042 below vs −0.006 above (the filter would hurt).

  The equity-curve filter (C5, C6) did not survive.

## All dev combos (risk 2% and 3%: final $ / max DD; then score | wins | worst DD of the 12 runs | any hard stop)
Defaults while sweeping: `w=1` per system, `cap=2`, 3 slots, all sizing rules off. "pb" is pullback and "bo" is
breakout. "5d" means breakout holds over weekends for at most 5 days; "fri" means breakout is flat on Friday.

| id | change | 2%: $ / DD | 3%: $ / DD | score | wins | worst DD | HS |
|---|---|---|---|---|---|---|---|
| A1 | baseline: the EA alone | $56.41 / 20% | $62.08 / 27% | +0.000 | – | 27 | 0 |
| A2 | breakout (fri) alone | $55.38 / 29% | $54.16 / 40% | −0.025 | 4/12 | 40 | 0 |
| A3 | breakout (5d) alone | $51.64 / 25% | $46.95 / 33% | −0.085 | 4/12 | 34 | 0 |
| A4 | regime alone | $37.60 / 38% | $34.99 / 34% | −0.319 | 0/12 | 38 | 1 |
| B1 | pb + bo(fri), w 1/1, cap 2 | $43.03 / 37% | $43.22 / 51% | −0.190 | 0/12 | 51 | 0 |
| B2 | pb + bo(5d), w 1/1, cap 2 | $47.83 / 35% | $42.58 / 48% | −0.208 | 1/12 | 48 | 1 |
| B3 | all three, w 1, cap 2 | $34.49 / 32% | $34.58 / 51% | −0.347 | 0/12 | 51 | 1 |
| B4 | B1 with cap 1.5 | $47.61 / 37% | $38.34 / 51% | −0.203 | 1/12 | 51 | 0 |
| B5 | B1 with one shared slot | $45.01 / 34% | $34.70 / 41% | −0.221 | 2/12 | 46 | 1 |
| B6 | B1 with w_bo 0.5 | $52.60 / 27% | $41.16 / 41% | −0.114 | 4/12 | 41 | 0 |
| C1 | pb, vol_k +0.5 (more risk when quiet) | $47.05 / 21% | $49.63 / 26% | −0.140 | 0/12 | 26 | 0 |
| C2 | pb, vol_k −0.5 | $64.66 / 20% | $59.14 / 25% | +0.024 | 6/12 | 26 | 0 |
| C3 | B1 with vol_k +0.5 | $54.02 / 37% | $46.58 / 46% | −0.081 | 2/12 | 47 | 0 |
| C4 | B2 with vol_k +0.5 | $48.73 / 35% | $43.01 / 44% | −0.115 | 2/12 | 44 | 0 |
| C5 | pb, equity-curve filter 20 trades (×0.5) | $60.37 / 16% | $47.26 / 22% | −0.025 | 6/12 | 22 | 0 |
| C6 | B1 with equity-curve filter 20 | $41.18 / 28% | $37.45 / 39% | −0.200 | 2/12 | 40 | 0 |
| D1 | B1, top vol tercile ×0.5 | $56.83 / 30% | $47.24 / 42% | −0.067 | 7/12 | 42 | 0 |
| D2 | pb, top vol tercile ×0.5 | $58.41 / 19% | $49.58 / 24% | −0.017 | 6/12 | 24 | 0 |
| D3 | B1 with w_bo 0.5, vol ×0.5 | $58.48 / 24% | $55.54 / 33% | −0.035 | 5/12 | 34 | 0 |
| D4 | B2, vol ×0.5 | $65.94 / 29% | $48.19 / 43% | −0.012 | 5/12 | 43 | 0 |
| E1 | pb + bo(fri), w 0.5/0.5, cap 1 | $54.01 / 21% | $49.31 / 32% | −0.050 | 5/12 | 32 | 0 |
| E2 | pb + bo(5d), w 0.5/0.5, cap 1 | $68.06 / 21% | $54.71 / 28% | +0.022 | 8/12 | 28 | 0 |
| E3 | E2 with w 0.75/0.75, cap 1.5 | $54.71 / 28% | $42.45 / 38% | −0.100 | 4/12 | 38 | 0 |
| E4 | E2 with bo max hold 4 d | $63.65 / 19% | $45.69 / 25% | −0.074 | 6/12 | 27 | 0 |
| E5 | E2 with bo max hold 3 d | $66.15 / 20% | $48.05 / 27% | −0.026 | 5/12 | 28 | 0 |
| **E6** | **E2 + top vol tercile ×0.5 (FINAL)** | **$71.47 / 19%** | **$69.41 / 24%** | **+0.104** | **10/12** | 24 | 0 |
| E7 | E2 with vol_k +0.5 | $75.47 / 23% | $60.44 / 28% | +0.086 | 9/12 | 29 | 0 |
| E8 | all three, w 1/3 each, cap 1 | $56.44 / 23% | $34.93 / 30% | −0.130 | 4/12 | 31 | 1 |
| H1 | E6, vol threshold 0.60 | $64.56 / 17% | $63.38 / 23% | +0.039 | 9/12 | 24 | 0 |
| H2 | E6, vol threshold 0.75 | $72.08 / 21% | $69.41 / 27% | +0.109 | 12/12 | 27 | 0 |
| H3 | E6, vol mult 0.25 | $72.20 / 18% | $66.12 / 23% | +0.107 | 11/12 | 23 | 0 |
| H4 | E6, vol mult 0 (skip; rerun after fix) | $73.11 / 19% | $75.38 / 26% | +0.116 | 12/12 | 27 | 0 |
| H5 | E6, vol mult 0.75 | $71.72 / 20% | $61.92 / 26% | +0.071 | 9/12 | 26 | 0 |
| H6 | E6, vol lookback 750 H4 bars | $57.68 / 19% | $67.41 / 25% | +0.037 | 9/12 | 25 | 0 |
| H7 | E6, vol lookback 3000 H4 bars | $67.38 / 21% | $48.77 / 29% | +0.013 | 9/12 | 29 | 0 |
| H8 | E6 with breakout Friday-flat | $68.22 / 18% | $63.48 / 25% | +0.050 | 9/12 | 25 | 0 |
| H9 | E6 with w 0.75/0.75, cap 1.5 | $69.41 / 24% | $60.02 / 34% | +0.092 | 10/12 | 34 | 0 |

What dev says:
1. **More simultaneous risk hurts.** Adding a second or third system at the full per-trade risk (B-series, E3) loses on
   dev. Drawdowns reach 35–51%, and two runs hit the hard stop. Each extra system has only a +0.02 to +0.04 R edge, so
   it adds variance faster than return. The half-risk-in-drawdown rule then makes the recoveries slow.
2. **Splitting the same risk helps a little.** Splitting the EA's risk over two partly independent systems (E2) helps
   a little, but only with the breakout version that holds over weekends. The Friday-flat version (E1) does not help.
3. **Halving risk in the top third of volatility helps.** It is the only rule that improved every neighbour
   (H1–H9 all have a positive score, 9–12 wins of 12). E6 was chosen as the middle of that plateau: threshold 0.67
   between 0.60 and 0.75, ×0.5 between ×0.25 and ×0.75, and a 1-year lookback between 6 months and 2 years. Halving
   is a sizing rule. H4 (skip) scored slightly higher, but it is a filter, and it was within noise of E6.

## Final candidate (E6, DEFAULT_PARAMS)
- **Systems.** Two systems, each with its own position slot:
  - the EA (swing_pullback, max_hold_days=3);
  - swing_breakout: an H4 close beyond the previous 20-bar Donchian high/low, in the direction of the close vs
    EMA(50), stop 2 ATR(14,H4), chandelier 5 ATR, no TP, positions **held over weekends, closed after 5 calendar
    days**.
- **Sizing.** Each trade risks 0.5 × risk% of the balance. If ATR(14,H4)/close of the last completed H4 bar ranks
  above 67% of the last 1500 H4 bars, it risks half of that.
- **Cap.** The total initial open risk may not exceed 1 × risk%. That equals the EA's single trade, so the maximum
  exposure is the baseline's. The rest are the EA's account rules.
- **Activity.** 8.5 trades per month, with a median hold of 52 h (average 64 h).

## Validation (run once, not revised)

| Period | risk 2%: final / DD | avg R (n) | baseline 2% | risk 3%: final / DD | baseline 3% |
|---|---|---|---|---|---|
| dev 2013–2019 | **$71.47** / 19.4% | +0.039 (710) | $56.41 | **$69.41** / 23.8% | $62.08 |
| 2020–2021 | **$49.50** / 15.2% | −0.046 (202) | $41.95 | **$49.93** / 19.9% | $40.35 |
| 2022–2025 | $70.91 / 10.5% | +0.125 (414) | **$122.45** | $66.75 / 16.7% | **$154.70** |
| 2026 Mar–Sep | **$49.01** / 8.4% | +0.018 (47) | $46.70 | $45.52 / 13.8% | **$45.75** |
| validation sum | $169.42 | | **$211.10** | $162.20 | **$240.80** |

No run hit the hard stop. The max DD was ≤ 24% everywhere. **The candidate fails the acceptance rule at both risk
levels.**

## Why it lost (post-hoc, on the final candidate's own trades; nothing was changed)
- **2022–2025 is the only period with a real edge, and it belongs to the EA's own signal.** Alone, pullback made
  +0.289 R on 178 trades and breakout made +0.003 R on 242. The combo gives half of the risk budget to a system that
  earned nothing there. It also halves the EA's trades, so it gives up most of the +51 R.
- **The combo traded at about half of the EA's exposure per trade.** Its mean realised risk per trade was
  0.66–0.73% of the balance. The EA's was 1.34% on dev and 1.81% in 2022–2025 at nominal 2%. (Both are below nominal
  because of the 0.01 oz rounding and the drawdown halving.) Lower exposure won on the flat dev period and lost in
  the strong trend period.
- **The volatility rule kept its sign out of sample.** Top-tercile trades were worse than the rest in every
  validation period:

  | Period | top tercile | rest |
  |---|---|---|
  | 2020–2021 | −0.11 R | −0.03 R |
  | 2022–2025 | +0.08 R | +0.15 R |
  | 2026 | −0.21 R | +0.28 R |

  But in 2022–2025 the top tercile was still profitable, so halving it also cost money there.
- **In 2026 the min-lot rule bites.** Gold is around $4000 and the stop is about $60–100. One min lot then already
  uses most of the 1 × risk cap, so the second system was blocked 14–19 times (`min_lot_or_cap`).

## Bottom line for the owner
- **No mix of the available gold swing systems gives more return than the EA alone.** It does not help at the same
  risk, and it does not help at more simultaneous risk. The extra systems (breakout, MA regime) have no edge on
  2013–2021 gold.
- **The money in 2022–2025 came from the EA's own signal in a strong gold trend.** Diluting that signal costs more
  than diversification saves.
- **More open risk makes it worse, not better.** Running the systems side by side at full risk each is what pushed
  dev drawdowns to 35–51% and hit the hard stop.
- **The account guards limit the damage. They do not create edge.** These are the daily −5% stop, the halving in a
  10% drawdown, and the $35 hard stop.

## Note on `scripts/gold_full_eval.py gold_combo`
`generate_signals()` returns the merged signals of both systems. The single-position engine therefore evaluates a
"one shared slot at full fixed risk" variant, not the portfolio. After validation it was run once as a smoke test,
and it is not a candidate:

| Period | final at 2% |
|---|---|
| dev | $50.72 |
| 2020–2021 | $55.82 |
| 2022–2025 | $52.65 |
| 2026 | $49.01 |

It is below the baseline on dev, so it would not have been selected, and its validation sum ($157.48) is also below.

## Reproduce
```
python -m strategies.gold_combo --risk 2          # final candidate, all periods (also --risk 3, --detail)
python -m strategies.gold_combo --risk 2 --params '{"systems": "pullback", "w_pullback": 1, "vol_hi": 1}'   # = the EA
python -m strategies.gold_combo --risk 2 --periods dev_2013_2019 --params '{"breakout": {}}'               # H8
```
