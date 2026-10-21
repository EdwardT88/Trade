# calendar_flows: calendar / time-of-day flows, FX M15 — research log

**Verdict: MARGINAL PASS of the pre-registered gates 1-4, with low confidence.** One structural effect survived
dev: on the last London business day of the month, the JPY crosses keep moving in their month-to-date (MTD)
direction into the London 4pm fix. Dev result: +0.171 R per trade, t = 4.9 (t = 4.0 when trades on the same
day are clustered). Validation, run once with no revision, was positive but statistically zero: +0.043 R
(t 0.56), and +0.024 R under stress. USDJPY flipped to −0.40 R while the three crosses stayed positive. The
classic flow ideas from the task (gotobi / Tokyo fix, the daily London fix, intraday drifts) are real in gross
terms but smaller than one cent-account spread.

Protocol: every choice was made on dev 2013-01-01..2020-01-01, including the pair set (USDJPY EURJPY GBPJPY
AUDJPY). Validation 2020-01-01..2022-03-05 was run once on the frozen choice. Costs come from
`backtest/markets.cost_model` (cent spreads, 0.2 pip slippage on stop and time exits, swap 3 %/yr); stress
is 1.5×. Engine backtests: **21 distinct parameter / pair-set combinations** (listed in §3). There were also
about 12 exploratory event studies on dev bid prices at zero cost. One of them scanned 2,376 London-time
windows (11 pairs × start 00:00-20:30 × length 1-6 h).

## 1. Event studies (dev, zero cost, pips on bid opens)

| effect | finding | tradeable? |
|---|---|---|
| Gotobi: USDJPY 00:00→00:45 UTC (into the 09:55 JST fix) | +0.35 pips (t 0.6) on gotobi days, ≈0 on other days. Negative in 2013-2016, positive only in 2017-2019. EURJPY / AUDJPY / GBPJPY similar | no: < ¼ spread. Engine: −0.029 R, t −4.6 |
| Gotobi from 21:45-22:45 UTC | +1.2 to +2.5 pips, but the start sits in the ×3 rollover window, and the bid is depressed there | no (rollover artefact) |
| Post-Tokyo-fix USDJPY decline 00:45→03:00 UTC | −1.4 pips all days (t −2.8) | no: ≈ 1 spread |
| Hourly drifts (11 pairs × 24 London hours) | every real hour < 1 spread. The 21:00-23:00 London "effects" (t up to 14) are bid distortion from rollover spread widening | no |
| Multi-hour scan, 2,376 windows | only EUR (and GBP) European-morning weakness passed \|t\|≥3, ≥6/7 years and ≥1.5 spreads. EURUSD 09:00→13:00 London: −2.97 pips, t −4.8, negative in **all 7 years** (including 2017, when EURUSD rose 1,600 pips) and on every weekday. This is the Breedon-Ranaldo "home currency depreciates in home hours" effect | gross yes, net no (§3) |
| Daily London 4pm fix (non-month-end) | fading the pre-fix move ≈ 0 to +1 pip | no |
| Month-end 4pm fix, post-fix reversal (fade 14:00→16:00, hold 16:00→18:00) | +2 to +9 pips on 9/11 pairs, ≈0 on non-month-end days; across pairs positive in 6/7 years | weak (§3) |
| **Month-end MTD continuation into the fix** (trade the sign of MTD from 12:00 to 16:00 London) | JPY crosses: USDJPY +6.2, EURJPY +16.1, GBPJPY +21.6, AUDJPY +8.7 pips. JPY basket = **5.9 spreads per event, t 4.7 (84 month-ends)**. Robust to entry 10-14 h and exit 15:45-16:15. Works in up AND down months (USDJPY +7.9 / −4.4, EURJPY +15.4 / −17.2). Larger when \|MTD\| is large; ex-2013 still t 2.0-2.8 per pair | **yes** |
| Placebo for the above | same rule 1, 2 or 3 business days before month-end and on the 1st business day of the next month: ≈ 0 (one cell t 2.35 out of 16) | effect is month-end specific |
| Same rule on ordinary days | +0.4 to +2.4 pips (generic trend persistence) | no |
| USD pairs / EURGBP / EURCHF / gold, MTD continuation | mixed signs, \|t\| < 2 (USDCAD negative; XAUUSD +$0.28, t 0.4) | no |

Proposed mechanism: month-end hedge rebalancing at the WM/R fix. Foreign holders of hedged Japanese equities
must sell more JPY after a month in which Japanese stocks rose. In 2013-2019 the JPY crosses rose and fell
with the Nikkei, so the crosses' MTD sign predicted the direction of the flow.

## 2. Final rules (frozen before validation) — `strategies/calendar_flows.py` DEFAULT_PARAMS

* Pairs: USDJPY, EURJPY, GBPJPY, AUDJPY. M15 bars. Times are Europe/London local time, DST-aware.
* Day: the last London business day of the month, meaning the last Mon-Fri. In May and August, if that day is a
  Monday it is the UK bank holiday (last Monday of the month), so the Friday before is used instead.
  Easter is not handled.
* 12:00 London, at the open of the M15 bar starting 12:00:
  `mtd = close of the bar ending 12:00 − open of the first M15 bar of the calendar month (UTC)`.
  BUY if mtd > 0, SELL if mtd < 0.
* Stop: 3.0 × ATR(24) on H1 (MT5 iATR = SMA of true range), from the last completed H1 bar (11:00-12:00).
  No target, no trailing, no breakeven.
* Exit: at the open of the M15 bar starting 16:00 London (at the fix), unless stopped earlier.
* That is one trade per pair per month and 4 trades/month in total. All 4 are on the same afternoon and are
  correlated, so treat them as about one bet.

## 3. Engine backtests on dev (no account limits, base costs)

| # | variant | pairs | n | avg R | t | med hold h |
|---|---|---|---|---|---|---|
| 1-3 | EURUSD short 09:00→13:00 London, SL {2,3,4}×ATR | 1 | 1813 | +0.018 / +0.016 / +0.014 | 0.9 / 1.2 / 1.4 | 4 |
| 4-5 | month-end post-fix fade 14→16 / 16→18, SL {2,3} | 11 | 902 | +0.024 / +0.019 | 1.4 / 1.7 | 2 |
| 6-7 | **MTD JPY 12:00→16:00, SL 2 / 3 (final = SL 3)** | 4 | 336 | +0.250 / **+0.171** | 5.0 / **4.9** | 4 |
| 8-9 | MTD JPY 14:00→16:00, SL 2 / 3 | 4 | 336 | +0.171 / +0.118 | 4.1 / 4.2 | 2 |
| 10 | MTD 12→16, all 11 pairs | 11 | 924 | +0.066 | 2.8 | 4 |
| 11-12 | entry 13:00 / 11:00 | 4 | 336 | +0.154 / +0.187 | 4.9 / 5.1 | 3 / 5 |
| 13-14 | exit 15:45 / 16:15 | 4 | 336 | +0.104 / +0.165 | 3.4 / 4.7 | 3.8 / 4.2 |
| 15-16 | SL 2.5 / 4 | 4 | 336 | +0.207 / +0.126 | 5.0 / 4.8 | 4 |
| 17-18 | MTD threshold 2 / 5 × ATR | 4 | 299 / 244 | +0.201 / +0.219 | 5.4 / 5.2 | 4 |
| 19 | ATR(14) instead of ATR(24) | 4 | 336 | +0.167 | 4.7 | 4 |
| 20 | MTD JPY + month-end fade on EURUSD GBPUSD AUDUSD USDCAD USDCHF | 9 | 746 | +0.108 | 5.8 | 2 |
| 21 | gotobi long 00:00→00:45 UTC, USDJPY EURJPY AUDJPY | 3 | 1494 | −0.029 | −4.6 | 0.8 |

Choices: run 7 was kept. The longer 12:00 entry carries the same cost on a larger gross move, so it is more
robust to stress than 14:00. SL 3 was chosen as a round value in the middle of a flat 2.5-4 region. No
threshold was used, to keep the rule simple. Run 20 was rejected because the USD-pair fade subset was picked
in-sample out of an all-pair result with t 1.7, and it was negative in 2013-14. The EURUSD morning effect is
real gross (≈3 pips) but nets ≈1.2 pips after a 1.5-pip round trip (t ≈ 1.3).

Dev checks on the final rule:
* Years: 6/7 positive (2016 −0.07 R).
* Direction: long +0.26 R (t 5.8), short +0.07 R (t 1.3).
* Quarter-end months +0.23 R; other months +0.14 R. Every weekday > 0.
* Season: winter +0.25 R, summer +0.11 R.
* Stops hit on 23 of 336 trades. No swap paid.
* Dev stress: +0.151 R, t 4.4. Day-clustered (84 month-ends): +0.685 R/day, t 4.0, 67 % of days positive.

## 4. Results

| sample | n | avg R | se | t | win % | PF | med hold h | trades / month |
|---|---|---|---|---|---|---|---|---|
| dev 2013-2019 | 336 | +0.171 | 0.035 | 4.94 | 62.2 | 1.95 | 4.0 | 4.0 |
| dev stress 1.5× | 336 | +0.151 | 0.034 | 4.39 | 60.4 | 1.81 | 4.0 | 4.0 |
| **validation 2020-01..2022-03** | 104 | **+0.043** | 0.076 | **0.56** | 55.8 | 1.15 | 4.0 | 4.0 |
| validation stress 1.5× | 104 | +0.024 | 0.076 | 0.31 | 55.8 | 1.08 | 4.0 | 4.0 |
| dev + validation | 440 | +0.141 | 0.032 | 4.39 | 60.7 | 1.68 | 4.0 | 4.0 |

Day-clustered: validation +0.172 R/day, t 0.55, only 42 % of month-ends positive. Dev + validation +0.564 R/day, t 3.7.

Per pair, avg R (n):

| pair | dev | validation | validation stress |
|---|---|---|---|
| USDJPY | +0.109 (84) | **−0.398 (26)** | −0.414 |
| EURJPY | +0.220 (84) | +0.167 (26) | +0.148 |
| GBPJPY | +0.196 (84) | +0.331 (26) | +0.310 |
| AUDJPY | +0.160 (84) | +0.071 (26) | +0.050 |

Validation by year: 2020 +0.095, 2021 +0.033, 2022 (2 month-ends) −0.213. Long +0.11, short −0.05.
Stops hit on 18 of 104 trades.

## 5. Assessment

* Gates 1-4 of `MULTI_MARKET_PLAN.md` pass:
  * dev > 0 and validation > 0 at base costs;
  * dev+validation t 4.4 (3.7 clustered), which is ≥ 2;
  * validation stress > 0;
  * median hold 4 h.
* The margin is thin. On its own, validation is indistinguishable from zero, and the per-trade edge fell by
  about 75 %.
* The USDJPY failure fits the mechanism breaking rather than pure noise. In 2020-21 the Nikkei rallied while
  USDJPY fell, so USDJPY's MTD sign stopped tracking Japanese equities. The crosses, which track global risk
  and the Nikkei better, held up (+0.19 R, t 2.2, n 78).
* That crosses-only number is **post-hoc**. It was not adopted, and no revision was made.
* A better signal would probably use the MTD return of a Nikkei CFD (JP225) instead of the FX pair. That is
  untested here because there is no equity data, and it must not be deployed without its own test.
* 2026 holdout: only USDJPY and EURJPY are in the hidden sample. That gives about 10 trades (May-Sep 2026),
  so it has almost no statistical power.
* Practical: 4 trades a month, all on one afternoon, so the stake is effectively one bet per month. Risk at most
  ≈1 % per pair (about 4 % per month-end day in total). The expected edge is small; at the validation rate it
  is ≈0.2 R per month-end day.
