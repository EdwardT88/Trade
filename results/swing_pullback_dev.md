# swing_pullback: research log (H4 trend, H1 RSI pullback, XAUUSD)

**Verdict: a marginal, unproven candidate. It is not a proven edge.** After spread and a 5%/yr swap it is positive on dev 2022–2023 and on 2024. It stays positive with swap 0 and under the stress cost model. It also stays positive for all four 2024 neighbours that were checked. Three things weaken it:

- **It trades rarely.** It makes about 3–4 trades a month, which leaves wide error bars. 2024 alone gives +0.27 R ± 0.23 (t ≈ 1.1).
- **The long side carries it.** Shorts made +0.23 R on dev but lost −0.46 R on 2024 (15 trades).
- **The pullback timing did not help in 2024.** Random entries in the trend direction, with the same exits, made +0.20 R in 2024 (p = 0.33 that random does at least as well). On dev the same test gave p < 0.003. So in 2024 most of the profit came from "H4 trend + hold until Friday" during a strong gold bull year. It did not come from the pullback trigger.

## Protocol
- **Development and validation.** Dev ran on 2022-01-01 .. 2024-01-01. Validation was one run of the final choice on 2024. There was **no revision after validation.**
- **Number of runs.** 39 parameter combos were run on dev (C1–C38 plus long-only I). Diagnostics came on top of that: 1 zero-cost run, 3 "trend-only" benchmarks and 2 permutation tests with 300 random draws each. After validation, 4 neighbouring parameter sets were run on 2024 for information only, and none of them was used for selection.
- **Costs.**
  - Base: default `CostModel` + swap 5%/yr, charged on longs and shorts, x3 on Wednesday.
  - Swap-free: swap 0.
  - Stress: `--spread-fixed 0.40 --spread-bps 1.2 --slippage 0.10 --swap 8`.
- **Sweep sizing.** Sweeps used `RiskConfig(initial_equity=1e6, min_size=1e-6, size_step=1e-6)` with no limits. In the table, R = pnl / risk and SE = std/√n.
- **Cost per trade at this scale.** The stop is about $17 (2 × ATR(H4,14)). Spread is therefore only about 0.015 R per trade. Swap 5% costs about 0.035–0.04 R per trade (average hold is 2 days).

## Final rules (DEFAULT_PARAMS)
| item | rule |
|---|---|
| trend (H4, last completed bar) | long: close > EMA(40) and EMA(40) > EMA(40) 6 bars ago; short: mirror |
| entry (H1 close) | long: RSI(14) crosses back up through 40 (prev < 40 ≤ now); short: RSI crosses down through 60. Fill at next M1 open |
| stop | 2.0 × ATR(14) of last completed H4 bar (SMA of TR = MT5 iATR), fixed at entry. 98.6% of stops end up beyond the 10-bar H1 pullback extreme, a median 1.3 ATR beyond it |
| trailing | every M1 bar: stop = max(stop, highest bid since entry − 3.0 × ATR_H4_at_entry); shorts mirror on ask lows. Distance fixed at entry. Starts tightening after +1 ATR (+0.5 R). Never loosens |
| time | close everything Friday 20:00 UTC; max hold 10 days (never binding) |
| filters | no new entries Fri ≥ 12:00 UTC; no fills 21:00–23:59 UTC; one position at a time; no TP, no breakeven |

H4 bars are UTC-aligned. If the H4 grid is shifted by 2 h (as on GMT+2 servers), dev changes from +0.551 to +0.541 R (C37). The rule therefore does not depend on the broker's server time.

## Results (final parameters)
| run | trades | /month | win% | avg R | SE | PF | maxDD% (2% risk) | hold (d) | long / short R |
|---|---|---|---|---|---|---|---|---|---|
| dev 2022–23, no limits, swap 5 | 69 | 2.9 | 58.0 | **+0.551** | 0.169 | 3.13 | 6.3 | 2.0 | +0.850 (36) / +0.226 (33) |
| dev, swap 0 | 69 | 2.9 | 58.0 | +0.590 | | 3.38 | 5.7 | | +0.888 / +0.265 |
| dev, stress | 69 | 2.9 | 55.1 | +0.500 | | 2.73 | 8.7 | | +0.814 / +0.158 |
| **val 2024, no limits, swap 5** | 45 | 3.7 | 40.0 | **+0.268** | 0.234 | 1.59 | 7.0 | 1.7 | +0.632 (30) / −0.462 (15) |
| val 2024, swap 0 | 45 | 3.7 | 44.4 | +0.302 | | 1.70 | 6.6 | | +0.667 / −0.428 |
| val 2024, stress | 45 | 3.7 | 40.0 | +0.239 | | 1.48 | 7.4 | | +0.602 / −0.487 |

By year (swap 5): 2022 +0.311 (38 trades), 2023 +0.847 (31), 2024 +0.268 (45).

By quarter, dev: +0.37, −0.23, +0.45, +0.66, +1.38, +0.27, −0.19, +1.37. 2024: +0.22, +0.64, +0.22, −0.02.

**The result rests on a few big winners.** On dev the top 5 trades make 19.6 of the 38 R and the median trade is +0.25 R.

**$50 cent account, default risk rules (2% risk, daily −5%, 3-loss stop, hard stop $35), swap 5:**
| period | return | maxDD | positive months | worst month | hard stopped | MC 6 m: P(hard stop) | MC median / p5 / p95 |
|---|---|---|---|---|---|---|---|
| dev 2022–23 | +99.1% | 6.3% | 62.5% | −4.4% | no | 0.0% | $59.6 / $49.6 / $74.2 |
| 2024 | +23.8% | 7.0% | 41.7% | −4.6% | no | 0.0% | $55.1 / $44.7 / $72.0 |

The daily risk limits never trigger, so the account run equals the no-limits run. Growth is lumpy: in 2024 only 5 of 12 months were positive.

## Weekend hold vs Friday close
| variant | dev avg R (n, SE) | 2024 avg R (n, SE) | hold | swap R/trade |
|---|---|---|---|---|
| (b) Friday 20:00 UTC close (**chosen**) | +0.551 (69, 0.169) | +0.268 (45, 0.234) | 2.0 / 1.7 d | 0.039 / 0.034 |
| (a) hold over weekends, 10-day max | +0.457 (69, 0.197) | +0.290 (46, 0.263) | 4.6 / 4.0 d | 0.064 / 0.054 |

Holding over weekends is not clearly better: it is lower on dev, the same on 2024, and pays more swap. It also carries weekend-gap risk, although the worst trade in the sample was only −1.18 R. So (b) is chosen.

Six dev trades fell on holiday or early-close Fridays. They exit at the last bar before the market closes, which uses knowledge of the close time. An EA needs a holiday rule to do the same; otherwise those positions are held over the weekend.

## How strong is the evidence?
- **Selection on dev.** The dev number is in-sample: the parameters were picked among 39 correlated combos. trend_len 40 was picked after seeing dev; rsi_lo 40, sl 2, trail 3, slope 6 and Friday close were the a-priori defaults.
- **2024 alone.** 2024 gives t ≈ 1.15. Pooling dev and 2024 gives 114 trades at about +0.44 R, but that pool contains the in-sample dev data.
- **Random in-trend entries.** This benchmark draws random H1 entries in the trend direction (same number of signals, same exits, 300 draws):
  - dev: +0.121 ± 0.106, against the strategy's +0.551 (p < 0.003);
  - 2024: +0.202 ± 0.142, against +0.268 (**p = 0.33**). The entry-timing edge did not replicate.
- **"Always in trend" benchmark.** Entering whenever flat and the trend agrees, with the same exits, gives +0.035 R on dev (240 trades) and +0.133 R on 2024 (116 trades).
- **Long bias may be luck of the regime.** Gold rose strongly in 2023–2024. Shorts are about 0 over both periods combined (+0.23 on 33 trades, then −0.46 on 15). The rule says long-only should be considered only if shorts are clearly negative in both periods, and they are not, so both sides are kept. For information, long-only gives dev +0.850 (36 trades, SE 0.27, 1.5/month) and 2024 +0.632 (30 trades, SE 0.33, 2.5/month).

## Dev sweep (2022–2023, no limits, default costs + swap 5)
C1–C25 use the original base: trend_len **50**, rsi_lo 40, sl 2 ATR, trail 3 ATR, Friday close. Rows that say "tl40" use trend_len 40 as their base. C27 is the final choice.

| # | change | n | /m | win% | avg R | SE | PF | maxDD R | hold d | long / short | 2022 / 2023 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | base (tl50) | 80 | 3.3 | 52.5 | +0.372 | 0.155 | 2.06 | 4.6 | 2.0 | +0.71 / +0.00 | +0.22 / +0.55 |
| – | C1 at zero cost (diagnostic) | 79 | 3.3 | 51.9 | +0.429 | 0.159 | 2.26 | 4.1 | 2.0 | +0.76 / +0.05 | |
| C2 | rsi_lo 35 | 45 | 1.9 | 44.4 | +0.135 | 0.148 | 1.40 | 7.6 | 1.8 | +0.40 / −0.17 | −0.15 / +0.46 |
| C3 | rsi_lo 45 | 117 | 4.9 | 47.9 | +0.249 | 0.129 | 1.60 | 8.0 | 1.9 | +0.30 / +0.19 | +0.12 / +0.39 |
| C20 | rsi_lo 50 | 135 | 5.6 | 45.2 | +0.159 | 0.110 | 1.37 | 6.7 | 2.0 | +0.19 / +0.12 | +0.13 / +0.20 |
| C4 | EMA20-touch pullback (pb 5) | 175 | 7.3 | 42.9 | +0.101 | 0.091 | 1.24 | 10.4 | 1.9 | +0.22 / −0.03 | +0.05 / +0.15 |
| C5 | weekend hold | 79 | 3.3 | 44.3 | +0.246 | 0.174 | 1.53 | 8.8 | 4.2 | +0.64 / −0.16 | +0.09 / +0.43 |
| C25 | weekend hold, max 5 d | 89 | 3.7 | 48.3 | +0.299 | 0.149 | 1.73 | 6.1 | 3.3 | +0.60 / −0.03 | +0.17 / +0.46 |
| C23 | weekend hold, sl 3 | 72 | 3.0 | 45.8 | +0.163 | 0.131 | 1.47 | 6.6 | 5.0 | +0.46 / −0.15 | +0.09 / +0.24 |
| C24 | weekend hold, rsi45, sl 3 | 91 | 3.8 | 47.3 | +0.248 | 0.122 | 1.78 | 6.1 | 4.6 | +0.26 / +0.24 | +0.06 / +0.47 |
| C26 | trend_len 20 | 37 | 1.5 | 70.3 | +0.908 | 0.256 | 5.45 | 1.7 | 2.0 | +1.50 / +0.35 | +0.59 / +1.29 |
| C21 | trend_len 30 | 60 | 2.5 | 61.7 | +0.627 | 0.185 | 3.50 | 2.4 | 2.0 | +1.00 / +0.25 | +0.44 / +0.87 |
| **C27** | **trend_len 40 (final)** | 69 | 2.9 | 58.0 | **+0.551** | 0.169 | 2.95 | 3.4 | 2.0 | +0.85 / +0.23 | +0.31 / +0.85 |
| C6 | trend_len 100 | 100 | 4.2 | 49.0 | +0.239 | 0.134 | 1.59 | 10.6 | 1.9 | +0.65 / −0.16 | +0.21 / +0.27 |
| C7 | slope_bars 1 | 81 | 3.4 | 51.9 | +0.366 | 0.153 | 2.05 | 4.6 | 2.0 | +0.69 / +0.00 | +0.21 / +0.55 |
| C8 | sl 1.5 | 87 | 3.6 | 42.5 | +0.359 | 0.191 | 1.71 | 8.9 | 1.7 | +0.71 / −0.04 | +0.17 / +0.57 |
| C9 | sl 3 | 79 | 3.3 | 53.2 | +0.269 | 0.104 | 2.18 | 3.2 | 2.1 | +0.51 / −0.01 | +0.19 / +0.36 |
| C10 | trail 2 | 98 | 4.1 | 42.9 | +0.142 | 0.098 | 1.44 | 6.1 | 1.3 | +0.28 / −0.00 | +0.16 / +0.12 |
| C11 | trail 4 | 77 | 3.2 | 53.2 | +0.386 | 0.162 | 2.02 | 4.9 | 2.2 | +0.70 / +0.03 | +0.19 / +0.62 |
| C12 | no trail | 75 | 3.1 | 54.7 | +0.399 | 0.175 | 1.97 | 5.6 | 2.3 | +0.69 / +0.05 | +0.23 / +0.59 |
| C13 | breakeven at +1 R, then trail 3 | 80 | 3.3 | 60.0 | +0.355 | 0.150 | 2.06 | 4.8 | 2.0 | +0.66 / +0.02 | +0.23 / +0.50 |
| C22 | max hold 3 d | 82 | 3.4 | 56.1 | +0.385 | 0.146 | 2.19 | 3.7 | 1.8 | +0.72 / +0.04 | +0.21 / +0.59 |
| C14 | rsi45 sl3 | 111 | 4.6 | 51.4 | +0.196 | 0.092 | 1.71 | 5.8 | 2.1 | +0.23 / +0.16 | +0.08 / +0.32 |
| C15 | rsi45 no trail | 109 | 4.5 | 47.7 | +0.222 | 0.154 | 1.45 | 9.8 | 2.2 | +0.27 / +0.17 | +0.09 / +0.37 |
| C16 | rsi45 sl3 no trail | 99 | 4.1 | 55.6 | +0.220 | 0.114 | 1.69 | 6.9 | 2.7 | +0.22 / +0.22 | +0.12 / +0.33 |
| C17 | sl3 no trail | 71 | 3.0 | 60.6 | +0.336 | 0.123 | 2.34 | 4.2 | 2.7 | +0.52 / +0.10 | +0.30 / +0.38 |
| C18 | entry on M15 instead of H1 | 191 | 8.0 | 40.3 | +0.127 | 0.090 | 1.30 | 11.1 | 2.0 | +0.24 / −0.01 | +0.03 / +0.23 |
| C19 | entry on H4 | 3 | 0.1 | – | – | – | – | – | – | – | – |
| C28 | tl30 rsi45 | 106 | 4.4 | 47.2 | +0.286 | 0.143 | 1.67 | 7.9 | 1.8 | +0.37 / +0.20 | +0.15 / +0.44 |
| C29 | tl40 rsi45 | 110 | 4.6 | 45.5 | +0.261 | 0.138 | 1.61 | 8.9 | 1.8 | +0.30 / +0.21 | +0.11 / +0.44 |
| C30 | tl40 rsi35 | 34 | 1.4 | 44.1 | +0.133 | 0.169 | 1.42 | 5.5 | 1.7 | +0.30 / −0.03 | −0.07 / +0.50 |
| C31 | tl40 sl3 | 69 | 2.9 | 59.4 | +0.387 | 0.112 | 3.17 | 2.5 | 2.1 | +0.60 / +0.15 | +0.25 / +0.56 |
| C32 | tl40 no trail | 65 | 2.7 | 60.0 | +0.593 | 0.191 | 2.75 | 4.8 | 2.4 | +0.86 / +0.29 | +0.31 / +0.95 |
| C33 | tl40 trail 4 | 66 | 2.8 | 60.6 | +0.591 | 0.177 | 3.01 | 3.6 | 2.2 | +0.85 / +0.30 | +0.31 / +0.96 |
| C34 | tl40 slope 3 | 68 | 2.8 | 57.4 | +0.556 | 0.172 | 2.94 | 3.4 | 2.0 | +0.85 / +0.23 | +0.31 / +0.85 |
| C35 | tl40 weekend hold | 69 | 2.9 | 50.7 | +0.457 | 0.197 | 2.13 | 6.0 | 4.6 | +0.72 / +0.17 | +0.11 / +0.94 |
| C36 | tl40 swing stop (10-bar extreme + 0.5 ATR, clip 1–3 ATR) | 81 | 3.4 | 43.2 | +0.656 | 0.248 | 2.36 | 6.5 | 1.6 | +1.00 / +0.27 | +0.31 / +1.11 |
| C37 | tl40 H4 grid shifted 2 h (robustness) | 67 | 2.8 | 55.2 | +0.541 | 0.171 | 2.86 | 2.9 | 2.1 | +0.87 / +0.18 | +0.46 / +0.63 |
| C38 | tl40 EMA20-touch pullback | 176 | 7.3 | 42.0 | +0.088 | 0.093 | 1.20 | 9.8 | 1.9 | +0.17 / −0.01 | +0.01 / +0.18 |
| I | tl40 long only | 36 | 1.5 | 58.3 | +0.850 | 0.268 | 4.62 | 2.7 | 2.1 | +0.85 / – | +0.57 / +1.13 |
| D | benchmark: tl50, enter whenever flat in the trend (no pullback) | 235 | 9.8 | 40.4 | +0.068 | 0.080 | 1.15 | 13.3 | 2.0 | +0.10 / +0.03 | |
| D | same, no trail | 178 | 7.4 | 41.6 | +0.147 | 0.116 | 1.28 | 12.7 | 2.6 | +0.19 / +0.10 | |
| D | same, tl40 | 240 | 10.0 | 37.5 | +0.035 | 0.080 | 1.07 | 21.9 | 1.9 | +0.08 / −0.02 | |

### What the sweep says
- **The RSI(14) cross back through 40 is what works.** Shallower triggers (45, 50) add trades but lower R per trade. 35 is too deep: fewer trades and weaker. An EMA20-touch trigger (C4, C38) and M15 entries (C18) are close to zero. **So the result depends on this specific entry definition, which is a fragility.**
- **Trend EMA length is a smooth trade-off.** Shorter EMAs give fewer but better trades: 20/30/40/50/100 give +0.91/+0.63/+0.55/+0.37/+0.24 R on 37/60/69/80/100 trades. Total R peaks at 30–40. Choosing 40 is mild selection along that curve.
- **Exits matter little once there is a Friday close.** Trail 3, 4 or none all land at about +0.55–0.59 (tl40). Only a tight trail (2 ATR) hurts. A 3 ATR stop has lower variance and lower R per trade, with about the same return/drawdown.
- **The edge is not a cost artefact.** Zero cost gives +0.43, base +0.37 (tl50). Spread is negligible at these stop sizes; swap is the main cost.

## Post-validation sensitivity on 2024 (information only; not used for any choice)
| variant | n | avg R | SE | long / short |
|---|---|---|---|---|
| final (tl40) | 45 | +0.268 | 0.234 | +0.63 / −0.46 |
| tl50 (a-priori default) | 47 | +0.285 | 0.229 | +0.64 / −0.47 |
| tl30 | 38 | +0.426 | 0.267 | +0.90 / −0.48 |
| rsi_lo 45 | 70 | +0.112 | 0.159 | +0.46 / −0.41 |
| sl 3 ATR | 44 | +0.165 | 0.158 | +0.36 / −0.22 |

All neighbours are positive, so the chosen point is not a lucky outlier in 2024. Every neighbour loses on shorts in 2024.

## MQL5 port notes
- **Indicators.** Use iMA(H4, 40, EMA, close), iRSI(H1, 14), and iATR(H4, 14). All are read on bar index 1, the last completed bar.
- **When to evaluate.** Check once per new H1 bar. With RSI[1] ≥ 40 > RSI[2] and an H4 uptrend, buy at market with SL = Ask − 2 × ATR.
- **Trailing.** Update on every new M1 bar (or tick): newSL = highest Bid since entry − 3 × ATR_entry, and modify only if it is tighter. Keep ATR_entry in a global or global variable so it survives restarts.
- **Friday close.** Close at Friday 20:00 UTC; the EA's server-time helpers can be reused. Block entries Friday ≥ 12:00 UTC and at 21:00–23:59 UTC. Add a holiday early-close rule, or accept occasional weekend holds.
