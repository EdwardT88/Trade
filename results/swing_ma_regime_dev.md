# swing_ma_regime: research log (H4 EMA 50/200 regime, flip + EMA20-reclaim entries, XAUUSD)

**Verdict: weak and not statistically established. It is not a proven edge.** After spread and a 5%/yr swap the final rule is positive on dev 2022–2023 (+0.19 R, t ≈ 1.7) and on 2024 (+0.13 R, t ≈ 0.7). It stays positive at swap 0 and under the stress cost model. Five things weaken it:

- **2024 is long-only profit.** Longs made +0.35 R (41 trades) and shorts lost −0.49 R (15 trades). Every 2024 neighbour lost on shorts too.
- **The entry trigger did not help in 2024.** Random entries in the regime direction with the same exits made +0.087 R on average (p = 0.33 that random does at least as well). On dev the same test gave p = 0.025, but that is in-sample. The 2024 profit is mostly "be long gold, flat on Friday" in a strong bull year.
- **The official 2024 number is flattered by indicator warm-up.** evaluate.py loads no history before `--start`, so EMA(200) on H4 blocks trading until 22 Feb 2024. A warm-started run (indicators from Sep 2023, only 2024 entries counted, which is what a live EA would do) gives **+0.063 R** on 65 trades (SE 0.153). The extra Jan–Feb trades lost.
- **It trades rarely.** About 4.5 trades a month and about 2-day holds give wide error bars. Removing the best 3 trades leaves 2024 at −0.04 R.
- **The edge is small next to swap.** Swap at 5%/yr costs about 0.03–0.04 R per trade, roughly a fifth to a quarter of the dev edge.

## Protocol
- **Development and validation.** Dev ran on 2022-01-01 .. 2024-01-01. Validation was one run of the final choice on 2024-01-01 .. 2025-01-01. There was **no revision after validation.**
- **Number of runs on dev.** 46 parameter runs were made: 45 distinct combos (#31 and #39 are identical) plus one zero-cost diagnostic. Everything was run on dev only. Trade-tag breakdowns (flip vs reclaim, long vs short) came from the same runs.
- **Runs on 2024 after validation, information only.** These were 9 neighbours, swap 0, stress, the weekend-hold variant, warm-start and the random / always-in-regime benchmarks. None of them was used for any choice.
- **Costs.**
  - Base: default `CostModel` + `--swap 5`.
  - Swap-free: `--swap 0`.
  - Stress: `--spread-fixed 0.40 --spread-bps 1.2 --slippage 0.10 --swap 8`.
- **Sweep sizing.** Sweeps used `RiskConfig(initial_equity=1e6, min_size=1e-6, size_step=1e-6)` with no limits. R = pnl / risk. SE = std/√n. ddR = maximum drawdown of cumulative R.
- **Cost per trade at this scale.** The stop is 2 × ATR(H4, 14), a median of about $18 on dev. Spread is therefore about 0.015 R per trade and swap 5% about 0.04 R per trade.

## Final rules (DEFAULT_PARAMS)
| item | rule |
|---|---|
| bars | H4 in broker server time of a New-York-close broker (GMT+2/+3): bars open at 00,04,…,20 server time. The code derives this from the data clock (see "Data clock" below) |
| regime (H4, last completed bar) | up: EMA(50) > EMA(200); down: EMA(50) < EMA(200) |
| entry 1: flip | the regime turned up on this H4 bar → buy (short: mirror) |
| entry 2: reclaim (re-entry while the regime persists) | regime up, H4 close > EMA(20) and previous H4 close ≤ previous EMA(20) → buy (short: mirror) |
| entry conditions | only when flat (one position at a time). Decided at the H4 close and filled at the next tick (backtest: the M1 bar one minute after the close). Fills within 15 min of the daily reopen wait until reopen + 15 min |
| stop | 2.0 × ATR(14) of the signal H4 bar (MT5 iATR = SMA of TR), fixed at entry. No TP |
| trailing | every M1 bar: stop = max(stop, highest bid since entry − 3.0 × ATR_entry); shorts: min(stop, lowest ask since entry + 3.0 × ATR_entry). It starts tightening after +1 ATR (= +0.5 R) and never loosens. No breakeven step |
| exits | stop or trail; H4 close where the regime no longer agrees (exit at the next tick; rare); **Friday 20:00 UTC close-all**; 10 calendar days maximum (never binds) |
| filters | no new entries Friday ≥ 12:00 UTC; at most 2 entries per day in practice (dev max 2, 2024 max 1) |

## Results (final parameters, evaluate.py)
| run | trades | /month | win% | avg R | SE | PF | maxDD % (2% risk) | hold (d) | long / short R |
|---|---|---|---|---|---|---|---|---|---|
| dev 2022–23, no limits, swap 5 | 103 | 4.3 | 47.6 | **+0.193** | 0.111 | 1.52 | 10.0 | 2.0 | +0.252 (53) / +0.131 (50) |
| dev, swap 0 | 103 | 4.3 | 48.5 | +0.233 | 0.113 | 1.70 | 9.2 | 2.0 | +0.290 / +0.171 |
| dev, stress | 103 | 4.3 | 45.6 | +0.160 | 0.109 | 1.42 | 11.0 | 2.0 | +0.220 / +0.096 |
| dev, zero cost (diagnostic) | 103 | 4.3 | 49.5 | +0.245 | 0.114 | 1.71 | | | +0.30 / +0.18 |
| **val 2024, no limits, swap 5** | 56 | 4.7 | 39.3 | **+0.127** | 0.170 | 1.24 | 12.3 | 1.8 | +0.351 (41) / −0.486 (15) |
| val 2024, swap 0 | 56 | 4.7 | 41.1 | +0.156 | 0.172 | 1.30 | 11.7 | 1.8 | +0.378 / −0.449 |
| val 2024, stress | 56 | 4.7 | 39.3 | +0.102 | 0.169 | 1.17 | 12.9 | 1.8 | +0.328 / −0.513 |
| val 2024 warm-started (information) | 65 | 5.4 | 36.9 | +0.063 | 0.153 | 1.10 | | 1.8 | +0.24 (48) / −0.44 (17) |

By year (swap 5): 2022 +0.171 (53 trades), 2023 +0.216 (50), 2024 +0.127 (56).

By quarter: dev +0.19, +0.07, +0.05, +0.42, +0.31, +0.14, −0.10, +0.71; 2024 +0.80, 0.00, +0.38, −0.24.

**Exits on dev:** 45 time exits (almost all on the Friday close) at +0.80 R on average, 40 stops at −0.81 R, 18 trail exits at +0.88 R. The worst trade was −1.17 R, and only 1 trade lost more than 1.1 R, so there were no gap disasters.

**$50 cent account, default risk rules (2% risk, daily −5%, 3-loss stop, hard stop $35), swap 5:**
| period | return | maxDD | positive months | worst month | max losing streak | hard stopped | MC 6 m: P(hard stop) | MC median / p5 / p95 |
|---|---|---|---|---|---|---|---|---|
| dev 2022–23 | +39.6% | 10.0% | 56.5% | −4.7% | 4 | no | 0.0% | $54.97 / $45.54 / $67.41 |
| 2024 | +11.3% | 11.0% | 63.6% (11 months) | −6.7% | 8 | no | 0.0% | $52.94 / $43.82 / $68.50 |

The daily limits never trigger: no trades were skipped for "daily_loss" or "consec_losses". Growth is slow and lumpy: the 6-month MC median is +6–10%, and P(profit after 6 months) is 78% using dev trades and 64% using 2024 trades. At 2% risk an 8-loss streak (seen in 2024) costs about 15%. The hard stop at $35 is about 18 straight losses away, so P(hard stop) is about 0.

## Weekend hold vs Friday close
| variant | dev avg R (n, SE) | 2024 avg R (n, SE) | 2024 warm-start | hold (d) | swap R per trade | stress dev / 2024 |
|---|---|---|---|---|---|---|
| (b) Friday 20:00 UTC close (**chosen**) | +0.193 (103, 0.111) | +0.127 (56, 0.170) | +0.063 | 2.0 / 1.8 | 0.039 / 0.030 | +0.160 / +0.102 |
| (a) hold over weekends, 10-day max | +0.151 (94, 0.130) | +0.239 (49, 0.262) | +0.073 | 4.1 / 3.9 | 0.058 / 0.051 | +0.107 / +0.201 |

- **On dev**, weekend hold is worse.
- **On 2024** it is better, entirely from longs (+0.58 R) in the bull year.
- **Pooled** over both periods the two are the same (+0.17 vs +0.18 R).
- **Warm-started 2024** gives +0.06 vs +0.07 R, also the same.
- **Cost.** Weekend hold pays about 50% more swap per trade and carries weekend-gap risk, although the worst trade was −1.17 R in both variants.

It is not clearly better, so (b) is chosen.

Holiday Fridays: when the market is already shut at Friday 20:00 (Good Friday, for example), the backtest exits at the last bar before the gap. An EA needs a holiday rule to do the same; otherwise it holds over that weekend.

## How strong is the evidence?
- **Selection on dev.** The dev number is in-sample after 45 correlated combos. The mean over all 46 dev runs was +0.13 R (40 of 46 positive). Over the 24 runs of the EMA 50/200 family it was +0.17 R, and all 24 were positive, ranging from +0.07 to +0.29.
- **Random-entry benchmark** (random H4 bars in the regime direction, same count as the final signals, same exits, 200 draws):
  - dev: +0.051 ± 0.073, against the final's +0.193 (p = 0.025);
  - 2024: +0.087 ± 0.106, against +0.127 (**p = 0.33**). The entry-timing edge did not replicate.
- **"Always in regime" benchmark** (enter whenever flat and the regime agrees, same exits): +0.028 R on dev (221 trades) and +0.067 R on 2024 (105 trades; longs +0.24, shorts −0.37).
- **The flip trades carry dev.** The 11 regime-flip trades made 8.9 R of dev's 19.7 R (flip longs +1.44 R on 6 trades). The 92 reclaim re-entries averaged about +0.12 R on dev and +0.10 R on 2024, where reclaim longs made +0.30 and reclaim shorts −0.60.
- **Long bias may be luck of the regime.** Shorts were +0.13 R on dev (50 trades) and −0.49 R on 2024 (15 trades), about 0 combined. The rule says long-only should be considered only if shorts are clearly negative in both periods, and they are not, so both sides are kept. For information, long-only gives dev +0.250 (53 trades, SE 0.156, 2.2/month) and 2024 +0.351 (41 trades, SE 0.216).
- **The structure matters more than the exact parameters.**
  - The D1 regime (EMA 20/50) and fast H4 crosses (10/30) are flat or negative.
  - Keltner-breakout re-entries (buying a close above EMA20 + 1 ATR) are negative on both sides.
  - Only the slow H4 regime plus pullback-reclaim re-entries worked.

## Dev sweep (2022–2023, no limits, default costs + swap 5)
Defaults for runs 1–22: H4 EMA 20/50 regime, sl 2 ATR, trail 4 ATR, exit on regime flip, max 10 days. "fri" = Friday close; "wk" = weekend hold. "rec" = EMA20 reclaim re-entries; "kc" = close crossing EMA20 + 1 ATR; "state0" = enter whenever flat with the regime up and close > EMA20. Runs 27–38 use the EMA 50/200 + flip + reclaim + Friday close base with trail 4. Runs 39–46 use the candidate base (trail 3). Dev numbers in this table were run before the reopen-detection code change (see below), which moved the final from +0.191 to +0.193.

| # | variant | n | /m | win% | avg R | SE | PF | ddR | hold d | long / short | 2022 / 2023 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | H4 20/50 flip fri | 46 | 1.9 | 41.3 | +0.321 | 0.247 | 1.6 | 6.1 | 2.0 | +0.52(24) / +0.10(22) | +0.28 / +0.36 |
| 2 | H4 20/50 flip+rec fri | 133 | 5.5 | 42.1 | +0.101 | 0.114 | 1.19 | 10.5 | 2.1 | +0.23(68) / −0.04(65) | +0.07 / +0.14 |
| 3 | H4 20/50 flip+kc fri | 128 | 5.3 | 39.8 | +0.023 | 0.114 | 1.01 | 14.2 | 1.9 | +0.14(66) / −0.10(62) | −0.03 / +0.07 |
| 4 | H4 20/50 flip wk | 50 | 2.1 | 36.0 | +0.267 | 0.267 | 1.43 | 6.8 | 4.5 | +0.43(26) / +0.10(24) | +0.11 / +0.41 |
| 5 | H4 20/50 flip+rec wk | 104 | 4.3 | 38.5 | +0.152 | 0.157 | 1.24 | 11.5 | 4.8 | +0.39(54) / −0.11(50) | +0.20 / +0.11 |
| 6 | H4 20/50 flip+kc wk | 103 | 4.3 | 36.9 | +0.115 | 0.163 | 1.16 | 10.6 | 4.5 | +0.25(56) / −0.04(47) | +0.05 / +0.18 |
| 7 | D1 20/50 regime, flip fri | 11 | 0.5 | 18.2 | −0.472 | 0.362 | 0.39 | 6.5 | 1.8 | +0.01(6) / −1.04(5) | −1.02 / −0.27 |
| 8 | D1 regime, flip+rec fri | 96 | 4.0 | 40.6 | −0.024 | 0.115 | 0.92 | 13.0 | 2.2 | −0.06(50) / +0.02(46) | −0.02 / −0.03 |
| 9 | D1 regime, flip+kc fri | 87 | 3.6 | 34.5 | −0.105 | 0.122 | 0.77 | 16.6 | 1.8 | −0.10(44) / −0.11(43) | −0.17 / −0.05 |
| 10 | D1 regime, flip wk | 11 | 0.5 | 27.3 | −0.510 | 0.294 | 0.31 | 7.1 | 3.5 | −0.34(6) / −0.71(5) | −1.02 / −0.32 |
| 11 | D1 regime, flip+rec wk | 76 | 3.2 | 39.5 | +0.031 | 0.172 | 1.02 | 10.9 | 4.8 | −0.08(40) / +0.16(36) | +0.02 / +0.04 |
| 12 | D1 regime, flip+kc wk | 68 | 2.8 | 33.8 | −0.019 | 0.182 | 0.93 | 16.9 | 4.4 | −0.08(36) / +0.05(32) | −0.14 / +0.09 |
| 13 | H4 10/30 flip fri | 91 | 3.8 | 34.1 | −0.037 | 0.120 | 0.89 | 15.2 | 1.7 | +0.03(45) / −0.11(46) | −0.10 / +0.02 |
| 14 | H4 10/30 flip wk | 97 | 4.0 | 30.9 | +0.052 | 0.156 | 1.06 | 12.4 | 4.3 | +0.18(49) / −0.08(48) | −0.02 / +0.13 |
| 15 | H4 50/200 flip fri | 11 | 0.5 | 63.6 | +0.835 | 0.399 | 5.5 | 1.3 | 2.5 | +1.53(6) / +0.00(5) | +0.76 / +0.88 |
| 16 | H4 50/200 flip wk | 13 | 0.5 | 61.5 | +0.507 | 0.337 | 2.53 | 2.1 | 6.4 | +0.71(7) / +0.27(6) | +0.27 / +0.66 |
| 17 | H4 20/50 flip+state0 fri | 170 | 7.1 | 41.2 | +0.087 | 0.104 | 1.16 | 13.2 | 2.4 | +0.19(89) / −0.03(81) | −0.01 / +0.18 |
| 18 | H4 20/50 flip+state0 wk | 129 | 5.4 | 38.0 | +0.108 | 0.142 | 1.16 | 13.0 | 4.5 | +0.27(66) / −0.06(63) | +0.05 / +0.16 |
| 19 | H4 20/50 flip, no signal exit, fri | 44 | 1.8 | 40.9 | +0.311 | 0.264 | 1.53 | 6.8 | 2.0 | +0.47(24) / +0.12(20) | +0.25 / +0.37 |
| 20 | H4 20/50 flip, no signal exit, wk | 48 | 2.0 | 35.4 | +0.227 | 0.278 | 1.33 | 7.5 | 4.5 | +0.38(26) / +0.05(22) | +0.09 / +0.37 |
| 21 | H4 20/50 flip+rec, exit close<EMA20, fri | 198 | 8.3 | 31.3 | +0.063 | 0.072 | 1.18 | 10.0 | 1.2 | +0.15(98) / −0.02(100) | +0.05 / +0.08 |
| 22 | same, wk | 209 | 8.7 | 27.8 | +0.036 | 0.077 | 1.08 | 12.9 | 2.2 | +0.18(104) / −0.10(105) | −0.01 / +0.10 |
| 23 | **H4 50/200 flip+rec fri** (trail 4) | 98 | 4.1 | 45.9 | +0.154 | 0.116 | 1.39 | 5.6 | 2.2 | +0.23(51) / +0.07(47) | +0.12 / +0.19 |
| 24 | H4 50/200 flip+rec wk | 78 | 3.3 | 44.9 | +0.216 | 0.169 | 1.43 | 6.6 | 5.2 | +0.27(38) / +0.16(40) | +0.18 / +0.25 |
| 25 | H4 50/200 flip+state0 fri | 129 | 5.4 | 43.4 | +0.140 | 0.117 | 1.29 | 8.8 | 2.5 | +0.17(70) / +0.11(59) | +0.06 / +0.21 |
| 26 | H4 50/200 flip+state0 wk | 95 | 4.0 | 44.2 | +0.205 | 0.181 | 1.40 | 9.1 | 5.0 | +0.36(48) / +0.04(47) | +0.10 / +0.30 |
| 27 | #23 + reclaim EMA10 | 117 | 4.9 | 47.0 | +0.178 | 0.115 | 1.39 | 7.9 | 2.2 | +0.23(59) / +0.13(58) | +0.17 / +0.18 |
| 28 | #23 + reclaim EMA50 | 70 | 2.9 | 45.7 | +0.234 | 0.148 | 1.58 | 5.1 | 2.3 | +0.38(36) / +0.07(34) | +0.27 / +0.20 |
| 29 | #23 + sl 1.5 | 104 | 4.3 | 43.3 | +0.197 | 0.141 | 1.39 | 6.2 | 2.0 | +0.26(55) / +0.13(49) | +0.15 / +0.25 |
| 30 | #23 + sl 3 | 91 | 3.8 | 49.5 | +0.123 | 0.086 | 1.45 | 3.0 | 2.6 | +0.14(48) / +0.10(43) | +0.11 / +0.14 |
| 31 | #23 + trail 3 (= #39) | 103 | 4.3 | 47.6 | +0.191 | 0.111 | 1.52 | 5.4 | 2.0 | +0.25(53) / +0.13(50) | +0.17 / +0.21 |
| 32 | #23 + trail 5 | 97 | 4.0 | 44.3 | +0.133 | 0.129 | 1.29 | 6.4 | 2.3 | +0.18(50) / +0.08(47) | +0.09 / +0.18 |
| 33 | #23 + no trail | 96 | 4.0 | 44.8 | +0.100 | 0.130 | 1.20 | 6.7 | 2.4 | +0.11(50) / +0.09(46) | +0.05 / +0.15 |
| 34 | #23, no regime exit | 98 | 4.1 | 48.0 | +0.149 | 0.115 | 1.37 | 6.1 | 2.2 | +0.22(51) / +0.07(47) | +0.13 / +0.17 |
| 35 | #23, regime 30/200 | 105 | 4.4 | 43.8 | +0.138 | 0.120 | 1.32 | 8.3 | 2.2 | +0.14(55) / +0.14(50) | +0.12 / +0.16 |
| 36 | #23, regime 100/200 | 99 | 4.1 | 44.4 | +0.083 | 0.112 | 1.18 | 8.4 | 2.1 | +0.05(52) / +0.12(47) | +0.07 / +0.10 |
| 37 | #23, regime 50/100 | 110 | 4.6 | 42.7 | +0.088 | 0.121 | 1.17 | 9.9 | 2.2 | +0.13(59) / +0.04(51) | +0.06 / +0.11 |
| 38 | #23, regime 50/300 | 95 | 4.0 | 44.2 | +0.067 | 0.117 | 1.13 | 9.0 | 2.2 | +0.03(47) / +0.10(48) | +0.01 / +0.12 |
| **39** | **candidate = final** (50/200, flip+rec EMA20, sl 2, trail 3, fri) | 103 | 4.3 | 47.6 | **+0.191** | 0.111 | 1.52 | 5.4 | 2.0 | +0.25(53) / +0.13(50) | +0.17 / +0.21 |
| 40 | final, weekend hold | 94 | 3.9 | 41.5 | +0.148 | 0.130 | 1.33 | 7.0 | 4.1 | +0.22(46) / +0.08(48) | +0.12 / +0.18 |
| 41 | final, reclaim EMA10 | 121 | 5.0 | 49.6 | +0.207 | 0.104 | 1.51 | 6.7 | 2.1 | +0.29(60) / +0.13(61) | +0.22 / +0.20 |
| 42 | final, reclaim EMA50 | 71 | 3.0 | 49.3 | +0.287 | 0.142 | 1.85 | 5.0 | 2.2 | +0.44(36) / +0.13(35) | +0.29 / +0.29 |
| 43 | final, sl 3 | 98 | 4.1 | 50.0 | +0.160 | 0.078 | 1.71 | 2.5 | 2.2 | +0.19(50) / +0.13(48) | +0.14 / +0.18 |
| 44 | final, regime 30/200 | 109 | 4.5 | 46.8 | +0.139 | 0.106 | 1.34 | 9.2 | 2.0 | +0.19(55) / +0.08(54) | +0.14 / +0.13 |
| 45 | final, H4 grid shifted −2 h (UTC-aligned) | 105 | 4.4 | 48.6 | +0.220 | 0.115 | 1.55 | 6.0 | 2.0 | +0.36(56) / +0.06(49) | +0.23 / +0.21 |
| 46 | final, long only | 53 | 2.2 | 49.1 | +0.250 | 0.156 | 1.70 | 3.8 | 2.0 | +0.25(53) / – | +0.37 / +0.17 |

### What the sweep says
- **The regime has to be slow.** H4 EMA 10/30 crosses lose, and 20/50 is weakly positive. With 20/50, re-entries are about 0 R and shorts are negative. The 50/200 regime is the only one where re-entries and shorts were positive on dev. D1 20/50 regimes lose.
- **Re-entry type matters.** Re-entering on a pullback reclaim of EMA20 works. Re-entering on a Keltner breakout (close > EMA20 + 1 ATR) is negative on both sides, which looks like short-term mean reversion after an extended H4 bar.
- **Exits are second-order.** A chandelier trail of 3 ATR was best (trail 4 +0.15, trail 5 +0.13, none +0.10). The regime-flip exit barely matters with 50/200. A 3 ATR stop has the lowest variance (SE 0.078, ddR 2.5) but less R per trade.
- **The choices made.** The final keeps the a-priori round values: EMA20 reclaim and sl 2. Trail 3 was chosen inside a monotone plateau. Neighbours at reclaim EMA10/50, sl 3, regime 30/200 and the shifted grid were all positive on dev, from +0.14 to +0.29.

## Post-validation sensitivity on 2024 (information only; not used for any choice)
| variant | n | avg R | SE | long / short |
|---|---|---|---|---|
| final | 56 | +0.127 | 0.170 | +0.35 / −0.49 |
| reclaim EMA10 | 63 | +0.100 | 0.153 | +0.30 / −0.48 |
| reclaim EMA50 | 37 | −0.018 | 0.208 | +0.32 / −0.51 |
| sl 3 | 54 | +0.059 | 0.123 | +0.21 / −0.37 |
| trail 4 | 53 | +0.119 | 0.173 | +0.33 / −0.48 |
| regime 30/200 | 57 | +0.113 | 0.177 | +0.32 / −0.54 |
| regime 20/50 | 75 | +0.111 | 0.150 | +0.48 / −0.36 |
| H4 grid UTC-aligned | 58 | +0.094 | 0.167 | +0.31 / −0.47 |
| no regime exit | 56 | +0.120 | 0.170 | +0.34 / −0.49 |
| long only | 41 | +0.351 | 0.216 | +0.35 / – |

The final is not a lucky point within 2024. The whole neighbourhood is at about +0.1 R, carried by longs, and every variant loses on shorts.

## Data clock and implementation notes
- **Server-time bars.** H4 bars are built on broker server time, defined as New York wall time + 7 h. `_server_clock` detects whether the M1 index is true UTC (the daily break starts at 17:00 New York) or HistData's fixed "New York + 5 h" clock. The current `data/xauusd_m1.parquet` uses the fixed clock: its break is at 22:00 all year.
- **Prepared for a regenerated parquet.** The uncommitted `backtest/data.py` change converts to true UTC. If the parquet is regenerated with it, the module still builds the same H4 bars. This was tested on a synthetic true-UTC copy: the server clock and all entries were identical. Only the Friday 20:00 UTC exit moves by 1 h in summer (dev +0.198, 2024 +0.116 on the synthetic UTC data).
- **Reopen detection.** The daily reopen is now detected from the M1 gaps instead of assuming 23:00. This moved 5 dev entries by 14 min: dev went from +0.191 to +0.193, and 2024 was unchanged.
- **Data quality.** Feb–Jul 2023 has many intraday 1-hour holes in the M1 data. Over those months H4 bars are built from incomplete data, and stops inside a hole fill at the next bar's open.

## MQL5 port notes
- **Indicators.** iMA(H4, 50, EMA), iMA(H4, 200, EMA), iMA(H4, 20, EMA) and iATR(H4, 14), all read on bar index 1.
- **When to evaluate.** Check once per new H4 bar, first exits, then entries:
  - Regime exit: if a long is open and EMA50[1] ≤ EMA200[1], close it.
  - Flip entry: if flat and EMA50[1] > EMA200[1] and EMA50[2] ≤ EMA200[2], buy.
  - Reclaim entry: if flat and EMA50[1] > EMA200[1] and Close[1] > EMA20[1] and Close[2] ≤ EMA20[2], buy.
  - Shorts are the mirror image.
- **Order.** SL = Ask − 2 × ATR[1]; no TP. Store ATR_entry in a global variable so it survives restarts.
- **Trailing.** On every new M1 bar (or tick): newSL = highest Bid since entry − 3 × ATR_entry; modify only if it is tighter. For shorts use lowest Ask + 3 × ATR_entry.
- **Friday and reopen.** Close all on Friday at 20:00 UTC (22:00/23:00 server). No entries Friday ≥ 12:00 UTC. Skip the first 15 min after the daily reopen. Add a holiday early-close rule, or accept occasional weekend holds.
- **History.** EMA(200) on H4 needs about 200 bars (≈ 7 weeks). An EA has that history, so live behaviour corresponds to the warm-started numbers above, not the evaluate.py 2024 run, which is flat until 22 Feb.
