# asia_range: research log (Asian range play around the London open)

**Verdict: NOT VIABLE.** None of the variants has a robust edge after costs. Neither the breakout nor the
sweep fade works as specified. The best remaining sub-setup (fading a break in the first 15 minutes
after the London open) is statistically zero (t = 0.6 over 146 trades in 2022-2024), it trades only
3-5 times a month, and it turns negative under stress costs.

Protocol: tuning used 2022-01-01..2024-01-01 only. The final choice was run once on 2024. There was no
revision after validation. 32 parameter combinations were backtested on dev (all listed below). Four
exploratory event studies were also run on dev, with about 25 conditioning cuts in total.

## 1. Data clock finding (affects every session-time strategy)

`data/xauusd_m1.parquet` is **not true UTC**. Its timestamps are New York wall-clock + 5h:
- the 08:30 ET US-data spike (NFP, CPI, claims) appears at **13:30 all year**. True UTC would put it at
  12:30 during US daylight saving (checked week by week for 2022-2024: almost every week shows 13:30).
- the 17:00 ET daily break sits at 22:00-23:00 in both July and January.
- the London-open volatility jump appears at 08:00 in both summer and winter. In true UTC it would be
  07:00 in summer.

So while US DST is in force (about 8 months a year) every bar is stamped 1h later than true UTC.
`backtest/data.py` assumes a fixed UTC-5 offset, but the HistData export evidently follows US DST.
Consequences:
* A strategy that computes London/NY opens with zoneinfo and applies them directly to the index is 1h off
  in summer. Example: a "09:30 ET NY open" computed as 13:30 UTC lands on the 08:30 ET news bar.
* `CostModel.rollover_hours_utc=(21,22)` covers 16:00-17:59 ET on this clock. The real post-break
  spread blow-out (18:00 ET reopen = 23:00 on this clock) is charged normal spread.

`asia_range` handles this as follows. Session instants are computed in true UTC with zoneinfo
(`Europe/London` 08:00), then mapped to the data clock (`data_clock="ny+5"`). An MQL5 port should
work from `TimeGMT()` and use `data_clock="utc"` semantics.

## 2. Event studies (dev, H1 ATR(24) units, mid-price, no costs)

Range = 00:00 UTC to the London open. Median H1 ATR at the London open was $4.29. The median range width
was 2.0 ATR (10-90%: 1.4-3.2).
* The range was broken (M1 close beyond) on 75% of days within 3h of the London open.
* **Continuation after the first break:** mean forward move in the break direction was
  +0.02 / +0.01 / +0.04 / +0.05 ATR at 15 / 30 / 60 / 120 min. That is zero, and the cost is about
  0.06-0.07 ATR per round trip.
* An H1 EMA50 / EMA200 trend-alignment filter made no difference. Narrow ("compressed") ranges did not
  break out better; wide ranges were slightly better.
* **Breaks inside the first 15 min after the London open reverse.** For M5-close breaks the 60/90 min
  forward move was -0.135 / -0.151 ATR (n=123). Breaks that came later continued mildly
  (+0.1 to +0.18 ATR at 90 min).
* **Sweep then close back inside (the archetype's fade)**: forward drift *against* the fade was
  -0.07 ATR at 60 min (n=353). After a reclaim, price tends to break out again, so the classic
  liquidity-sweep fade has negative expectancy here.
* Post-open direction is unpredictable from where London opens inside the range or from the Asian-session
  drift (correlations |r| < 0.07).

## 3. Backtests on dev (no limits, default costs)

Rows 1-10 used the original defaults: stop 1.0 ATR, tp 1.5R, 180-min window, 90-min time exit, reclaim
fade with sweep_min=0, max_sweep_bars=6, sl_buf=0.1 ATR. Later rows list everything that differs from
those defaults. Row 20 is the final choice.

| # | overrides | trades | /mo | win% | avg R | avg win R | PF | maxDD% | hold min | 2022 R | 2023 R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | mode=fade | 316 | 13.2 | 27.8 | -0.364 | 1.21 | 0.41 | 90.5 | 31.9 | -0.434 | -0.292 |
| 2 | mode=bo | 376 | 15.7 | 39.9 | -0.081 | 0.68 | 0.77 | 54.5 | 78.8 | -0.041 | -0.129 |
| 3 | mode=bo, bo_start_min=30 | 310 | 12.9 | 40.6 | -0.042 | 0.67 | 0.84 | 35.2 | 81.9 | -0.062 | -0.019 |
| 4 | mode=bo, bo_start_min=30, bo_sl_atr=0.75, tp_r=1.5 | 310 | 12.9 | 40.6 | -0.048 | 0.88 | 0.86 | 44.1 | 70.6 | -0.044 | -0.054 |
| 5 | mode=bo, bo_start_min=30, bo_sl_atr=0.75, tp_r=1.0 | 310 | 12.9 | 44.5 | -0.043 | 0.77 | 0.87 | 39.0 | 63.3 | -0.046 | -0.039 |
| 6 | mode=fade, fade_trigger=break, fade_end_min=30, tp_r=1.0 | 162 | 6.8 | 56.8 | 0.052 | 0.59 | 1.18 | 21.2 | 70.1 | -0.099 | 0.221 |
| 7 | mode=fade, fade_trigger=break, fade_end_min=30, tp_r=1.5 | 162 | 6.8 | 56.2 | 0.047 | 0.59 | 1.17 | 24.1 | 76.9 | -0.11 | 0.225 |
| 8 | mode=fade, fade_trigger=break, fade_end_min=15, tp_r=1.0 | 107 | 4.5 | 58.9 | 0.129 | 0.65 | 1.52 | 9.4 | 67.4 | -0.023 | 0.272 |
| 9 | mode=fade, fade_trigger=break, fade_end_min=60, tp_r=1.0 | 243 | 10.1 | 53.1 | -0.008 | 0.56 | 0.95 | 23.2 | 72.0 | -0.092 | 0.09 |
| 10 | mode=bo+fade, fade_trigger=break, fade_end_min=30, bo_start_min=30, tp_r=1.0 | 403 | 16.8 | 49.1 | 0.014 | 0.62 | 1.03 | 30.6 | 74.2 | -0.073 | 0.115 |
| 11 | mode=bo, bo_start_min=30, sl_atr=0.5, tp_r=1.5 | 310 | 12.9 | 37.4 | -0.078 | 1.24 | 0.84 | 55.5 | 47.2 | -0.041 | -0.121 |
| 12 | mode=bo, bo_start_min=30, sl_atr=0.75, tp_r=1.25, window_min=300 | 399 | 16.6 | 41.1 | -0.092 | 0.84 | 0.79 | 62.8 | 66.3 | -0.058 | -0.13 |
| 13 | mode=fade, fade_trigger=break, fade_end_min=30, sl_atr=0.5, tp_r=1.5 | 162 | 6.8 | 43.8 | -0.02 | 1.14 | 0.94 | 23.9 | 43.2 | -0.094 | 0.064 |
| 14 | mode=fade, fade_trigger=reclaim, sweep_min_atr=0.1, max_sweep_bars=3, sl_buf_atr=0.25, min_sl_atr=0.5, tp_r=1.0 | 223 | 9.3 | 40.8 | -0.182 | 0.84 | 0.66 | 58.2 | 48.7 | -0.152 | -0.215 |
| 15 | mode=bo, bo_start_min=0, sl_atr=0.75, tp_r=1.25, data_clock=utc | 408 | 17.0 | 40.7 | -0.106 | 0.91 | 0.8 | 69.5 | 61.2 | -0.024 | -0.191 |
| 16 | mode=bo, range_end_min=-60, window_min=180, sl_atr=0.75, tp_r=1.25 | 427 | 17.8 | 42.4 | -0.083 | 0.89 | 0.83 | 62.1 | 60.9 | -0.035 | -0.133 |
| 17 | mode=fade, fade_trigger=break, fade_end_min=30, sl_atr=0.75, tp_r=1.0 | 162 | 6.8 | 53.7 | 0.019 | 0.74 | 1.04 | 24.4 | 54.9 | -0.132 | 0.189 |
| 18 | mode=bo, bo_start_min=30, bo_buf_atr=0.2, sl_atr=0.75, tp_r=1.25 | 265 | 11.0 | 43.4 | -0.096 | 0.77 | 0.79 | 56.4 | 65.8 | 0.021 | -0.227 |
| 19 | mode=bo, bo_start_min=30, max_w_atr=1.75, sl_atr=0.75, tp_r=1.25 | 124 | 5.2 | 43.5 | -0.058 | 0.75 | 0.84 | 28.5 | 68.3 | -0.056 | -0.061 |
| 20 | mode=fade, fade_trigger=break, fade_end_min=15, sl_atr=0.5, tp_r=1.25 | 107 | 4.5 | 47.7 | 0.028 | 1.07 | 1.03 | 18.0 | 34.6 | 0.006 | 0.048 |
| 21 | mode=fade, fade_trigger=break, fade_end_min=15, sl_atr=0.5, tp_r=1.5 | 107 | 4.5 | 43.9 | -0.007 | 1.17 | 0.96 | 22.1 | 39.8 | -0.081 | 0.064 |
| 22 | mode=fade, fade_trigger=break, fade_end_min=15, sl_atr=0.75, tp_r=1.25 | 107 | 4.5 | 52.3 | 0.07 | 0.85 | 1.18 | 18.7 | 56.8 | -0.126 | 0.256 |
| 23 | mode=fade, fade_trigger=break, fade_end_min=15, sl_atr=0.75, tp_r=1.5 | 107 | 4.5 | 52.3 | 0.083 | 0.87 | 1.2 | 20.3 | 61.7 | -0.14 | 0.294 |
| 24 | mode=fade, fade_trigger=break, fade_end_min=30, sl_atr=0.5, tp_r=1.25 | 162 | 6.8 | 46.9 | -0.0 | 1.05 | 0.98 | 21.0 | 38.4 | -0.029 | 0.033 |
| 25 | mode=fade, fade_trigger=break, fade_end_min=30, sl_atr=0.75, tp_r=1.25 | 162 | 6.8 | 52.5 | 0.018 | 0.77 | 1.02 | 28.3 | 60.7 | -0.155 | 0.213 |
| 26 | mode=fade, fade_trigger=break, fade_end_min=30, sl_atr=0.75, tp_r=1.5 | 162 | 6.8 | 51.9 | 0.025 | 0.79 | 1.05 | 31.0 | 64.4 | -0.172 | 0.247 |
| 27 | mode=fade, fade_trigger=break, fade_end_min=10, sl_atr=0.5, tp_r=1.25 | 83 | 3.5 | 50.6 | 0.099 | 1.09 | 1.2 | 9.9 | 35.6 | -0.019 | 0.204 |
| 28 | mode=fade, fade_trigger=break, fade_end_min=20, sl_atr=0.5, tp_r=1.25 | 122 | 5.1 | 47.5 | 0.02 | 1.05 | 1.02 | 15.9 | 37.4 | -0.04 | 0.08 |
| 29 | mode=fade, fade_trigger=break, fade_end_min=15, sl_atr=0.4, tp_r=1.25 | 107 | 4.5 | 44.9 | -0.032 | 1.15 | 0.93 | 21.9 | 23.4 | 0.017 | -0.078 |
| 30 | mode=fade, fade_trigger=break, fade_end_min=15, sl_atr=0.6, tp_r=1.25 | 107 | 4.5 | 50.5 | 0.058 | 0.96 | 1.12 | 15.2 | 46.1 | -0.054 | 0.164 |
| 31 | mode=fade, fade_trigger=break, fade_end_min=15, sl_atr=0.5, tp_r=1.0 | 107 | 4.5 | 51.4 | -0.004 | 0.91 | 0.98 | 17.2 | 28.1 | -0.033 | 0.024 |
| 32 | mode=fade, fade_trigger=break, fade_end_min=15, sl_atr=0.5, tp_r=1.25, max_hold_min=60 | 107 | 4.5 | 43.0 | -0.029 | 1.05 | 0.92 | 18.7 | 29.8 | -0.056 | -0.004 |

The same breakout configurations with zero costs (diagnostic) came to -0.025R (row 2) and +0.021R
(row 3). The breakout has no gross edge at all.

Summary by family:
* (a) Breakout continuation: -0.04 to -0.11R in all 9 variants. The variants were the start delay
  (0/30 min), stop/target 0.5-1.0 ATR / 1.0-1.5R, a 300-min window, a Frankfurt-anchored range,
  a 0.2 ATR buffer and a narrow-range filter. Average wins are mostly below 0.9R because the time exit
  dominates.
* (b) Sweep / reclaim fade: -0.18 to -0.36R. Clearly negative.
* (b') Early-break fade (opening stop-hunt), the only family near or above zero: -0.03 to +0.13R,
  with a sign flip between years in most variants. 2022 was mostly negative and 2023 positive.

## 4. Final choice (row 20) and its neighbours

Fade the first fresh M5 close beyond the Asian range that occurs within 15 minutes of the London open.
Stop 0.5 x H1 ATR(24), target 1.25R, time exit 90 min.
I chose it because it is the centre of its neighbourhood, satisfies avg-win >= 0.9R and hold <= 90 min,
and is the only variant with both dev years >= 0. It was not chosen as the dev maximum. Rows 8, 23 and 27
had higher avg R, but they break the R:R rule or flip sign by year.

Neighbours, avg R on dev:
- fade_end_min 10 / **15** / 20 / 30: +0.099 / **+0.028** / +0.020 / -0.000
- sl_atr 0.4 / **0.5** / 0.6 / 0.75: -0.032 / **+0.028** / +0.058 / +0.070 (the last at tp 1.25)
- tp_r 1.0 / **1.25** / 1.5: -0.004 / **+0.028** / -0.007
- max_hold 60: -0.029

The neighbourhood is flat around zero. That is consistent with no edge, not with a robust plateau.

| run | trades | /mo | win% | avg R | avg win R | PF | maxDD% | hold | notes |
|---|---|---|---|---|---|---|---|---|---|
| dev 2022-23 no-limits | 107 | 4.5 | 47.7 | +0.028 | 1.07 | 1.03 | 18.0 | 34.6 | 2022 +0.006R, 2023 +0.048R; long +0.022 / short +0.034 |
| **val 2024 no-limits** | 39 | 3.2 | 51.3 | +0.118 | 1.09 | 1.25 | 9.4 | 42.8 | long +0.268 / short +0.003 (bull year: buying failed downside breaks) |
| val 2024 account (2%, $50 cent) | 39 | 3.2 | 51.3 | +0.118 | 1.09 | 1.25 | 9.4 | 42.8 | +8.6%, 58% positive months, worst month -4.0%, not hard-stopped |
| val 2024 MC 6m (day bootstrap) | | | | | | | | | P(hard stop) 0.0%, median $52.23, p5 $44.87, p95 $61.11, P(profit) 67% |
| stress 2024 (0.40 / 1.2 bps / 0.10 slip) | 39 | 3.2 | 46.2 | -0.048 | 0.98 | 0.88 | 13.0 | 46.3 | -4.4% |
| dev account | 107 | 4.5 | | | | 1.01 | 14.6 | | +1.4% over two years |

Significance: dev t = 0.28, val t = 0.71, all 2022-2024 t = 0.61 (mean +0.052R, sd 1.04R, n = 146).
The 2024 result is within noise, comes almost entirely from long trades in a strong gold uptrend, and
disappears under stress costs. The setup also misses the frequency target (15-120 trades/month) by a
factor of 3-5. That is inherent to it: it needs a range break inside a 15-minute window.

## 5. Conclusion

The Asian-range play around the London open has no exploitable edge on 2022-2024 XAUUSD M1 data after
retail cent-account costs. This holds for breakout continuation, the liquidity-sweep fade, and the
early-break fade, which is merely the least bad. Do not deploy it. The one durable observation is that
**breaks in the first ~15 minutes after the London open tend to fail (Judas swing)**. That is useful as
a filter for other strategies: do not chase the first London-open break of the Asian range. It is not
enough on its own.
