# momentum_breakout: research log (M5 Donchian breakout scalp, XAUUSD)

**Verdict: NOT VIABLE.** An M5 Donchian breakout with volatility expansion has essentially no gross edge on
gold. At zero cost it averages -0.02 to +0.11 R per trade. Costs are about 0.05-0.07 R per trade at the stop
sizes that make sense, so every variant lands between -0.09 and +0.03 R net on dev. The best region
(New York morning, long channel) is a flat plateau around zero (t < 0.7). The frozen final choice was
**-0.012 R/trade on the 2024 validation year** (PF 0.95), and -0.047 R under stress costs. A $50 cent
account using it loses money slowly: -4% on dev, -7% in 2024.

## Protocol
- Development: 2022-01-01..2024-01-01 only. Validation: 2024, run once for the final choice. **No revision
  after validation.**
- 37 dev backtests, 36 of them distinct parameter sets (#24 duplicates #7), all listed below. There was one
  exploratory event study first: forward moves after M5/M15 Donchian breaks, cut by hour, ATR ratio, H1
  trend and direction (about 20 cuts).
- Default `CostModel` (spread max($0.25, 0.8 bps), x3 at 21-22 data-clock hours, $0.05 stop slippage).
  Stress test on 2024: spread max($0.40, 1.2 bps) and $0.10 slippage.
- All distances are in ATR units (ATR = MT5 iATR = SMA of true range).

## Data clock
I confirmed what the asia_range log reports. The 08:30 ET news spike sits at 13:30 on the data clock in
both summer and winter, so the parquet is stamped **New York wall-clock + 5h**, not true UTC. The strategy
therefore defines its session in New York local time. `data_clock="ny+5"` (the default, for this file)
converts the index by subtracting 5 h. `data_clock="utc"` converts true-UTC timestamps with
zoneinfo `America/New_York`, which is what an EA should use via `TimeGMT()`.

## Event study (dev, bid prices, no costs; forward move from the next M1 open, in $)
- Across all hours, M5 Donchian(12/24) and M15 Donchian(8/16) breaks continue by only $0.00-0.14 after
  15-60 min. The round-trip cost is about $0.30.
- Breaks between 06:00 and 09:00 New York (late London, pre-news) **reverse** by $0.2-0.8 over 60 min.
  Breaks between 09:00 and 13:00 New York continue by about $0.2-0.6 (≈ +0.03 to +0.14 H1-ATR). This is
  the only hint of momentum.
- The ATR(5)/ATR(50) ratio is not monotone. Breaks aligned with the H1 EMA50 trend did *worse* than
  counter-trend ones. Longs beat shorts, consistent with gold's uptrend.

## Dev sweep (no limits, default costs)
Original base: M5, Donchian 24, no vol filter, no trend filter, signal-bar close in NY 08:00-12:00,
stop 2.0 x ATR14(M5), TP 1.5 R, 60-min time exit. t = mean R / standard error (overlap ignored).

| # | overrides vs original base | trades | /mo | win% | avg R | t | avg win R | PF | maxDD% | hold | 2022 / 2023 R | long / short R | zero-cost R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | base | 1319 | 55.0 | 39.7 | -0.085 | -2.91 | 1.06 | 0.81 | 92.5 | 39.3 | -0.084 / -0.087 | -0.072 / -0.100 | -0.016 |
| 2 | fresh_only=True | 1203 | 50.2 | 40.5 | -0.085 | -2.79 | 1.04 | 0.81 | 90.4 | 39.3 | -0.091 / -0.079 | -0.074 / -0.096 | -0.015 |
| 3 | vol=1.2 | 1006 | 41.9 | 40.2 | -0.075 | -2.17 | 1.1 | 0.85 | 84.4 | 38.6 | -0.060 / -0.089 | -0.070 / -0.080 | -0.005 |
| 4 | trend_mode=1 | 805 | 33.6 | 40.4 | -0.082 | -2.16 | 1.05 | 0.81 | 79.6 | 38.1 | -0.096 / -0.067 | -0.084 / -0.080 | -0.004 |
| 5 | NY 9-12 | 801 | 33.4 | 44.3 | -0.036 | -1.01 | 0.9 | 0.89 | 53.1 | 47.1 | -0.050 / -0.020 | +0.032 / -0.102 | +0.023 |
| 6 | N=12 | 1749 | 72.9 | 39.9 | -0.088 | -3.58 | 1.01 | 0.83 | 96.2 | 40.8 | -0.084 / -0.092 | -0.064 / -0.112 | -0.003 |
| 7 | N=48 | 1039 | 43.3 | 41.5 | -0.065 | -1.96 | 1.04 | 0.86 | 81.4 | 40.3 | -0.049 / -0.081 | -0.040 / -0.090 | +0.009 |
| 8 | sl_atr=3.0 | 1188 | 49.5 | 42.8 | -0.055 | -2.17 | 0.78 | 0.83 | 79.2 | 52.3 | -0.064 / -0.045 | -0.047 / -0.063 | -0.004 |
| 9 | NY 9-12, tp_r=1.0 | 909 | 37.9 | 47.5 | -0.038 | -1.28 | 0.8 | 0.88 | 58.4 | 40.1 | -0.059 / -0.016 | +0.020 / -0.096 | +0.024 |
| 10 | NY 9-12, tp_r=2.0 | 766 | 31.9 | 43.0 | -0.037 | -1.0 | 0.95 | 0.88 | 52.5 | 49.9 | -0.060 / -0.013 | +0.059 / -0.130 | +0.033 |
| 11 | NY 9-12, tp_r=0.0 | 711 | 29.6 | 41.9 | -0.029 | -0.62 | 1.03 | 0.89 | 51.2 | 52.9 | -0.034 / -0.024 | +0.089 / -0.138 | +0.035 |
| 12 | NY 9-12, tp_r=3.0, be_r=1.0, trail_atr=2.0 | 740 | 30.9 | 47.0 | -0.029 | -0.78 | 0.83 | 0.9 | 44.8 | 47.4 | -0.052 / -0.005 | +0.076 / -0.129 | +0.023 |
| 13 | NY 9-12, hold=90 | 781 | 32.6 | 42.8 | -0.028 | -0.74 | 1.03 | 0.91 | 48.1 | 58.4 | -0.044 / -0.012 | +0.036 / -0.091 | +0.027 |
| 14 | NY 9-12, hold=30 | 895 | 37.3 | 45.1 | -0.038 | -1.38 | 0.67 | 0.85 | 55.8 | 27.7 | -0.055 / -0.019 | +0.030 / -0.104 | +0.032 |
| 15 | NY 9-12, vol=1.2 | 566 | 23.6 | 45.2 | -0.020 | -0.46 | 0.95 | 0.93 | 41.3 | 46.8 | -0.021 / -0.019 | +0.070 / -0.104 | +0.034 |
| 16 | NY 9-12, N=48 | 650 | 27.1 | 46.8 | +0.009 | 0.23 | 0.9 | 1.0 | 32.7 | 48.0 | +0.008 / +0.010 | +0.076 / -0.055 | +0.065 |
| 17 | NY 9-12, tf=15min, N=8 | 660 | 27.5 | 44.4 | -0.044 | -1.44 | 0.69 | 0.85 | 59.4 | 57.0 | -0.046 / -0.042 | -0.019 / -0.070 | +0.021 |
| 18 | NY 9-11 | 617 | 25.7 | 43.8 | -0.029 | -0.71 | 0.96 | 0.91 | 43.4 | 44.7 | -0.044 / -0.015 | +0.043 / -0.099 | +0.025 |
| 19 | NY 9-13 | 980 | 40.9 | 44.5 | -0.038 | -1.21 | 0.89 | 0.88 | 63.5 | 51.5 | -0.051 / -0.023 | +0.023 / -0.097 | +0.035 |
| 20 | **NY 9-12, N=48, vol=1.2 (FINAL)** | 491 | 20.5 | 46.2 | +0.013 | 0.27 | 0.95 | 1.0 | 35.7 | 47.5 | +0.023 / +0.004 | +0.110 / -0.078 | +0.065 |
| 21 | NY 9-12, N=72 | 580 | 24.2 | 46.0 | -0.001 | -0.03 | 0.89 | 0.97 | 27.9 | 48.8 | +0.005 / -0.007 | +0.039 / -0.041 | +0.056 |
| 22 | NY 9-12, N=96 | 541 | 22.6 | 47.3 | +0.017 | 0.4 | 0.88 | 1.02 | 25.4 | 48.7 | +0.018 / +0.017 | +0.073 / -0.037 | +0.075 |
| 23 | NY 9-12, N=36 | 699 | 29.1 | 45.5 | -0.010 | -0.26 | 0.91 | 0.95 | 41.8 | 47.5 | -0.010 / -0.009 | +0.038 / -0.057 | +0.046 |
| 24 | NY 8-12 (=base), N=48 (duplicate of #7) | 1039 | 43.3 | 41.5 | -0.065 | -1.96 | 1.04 | 0.86 | 81.4 | 40.3 | -0.049 / -0.081 | -0.040 / -0.090 | +0.009 |
| 25 | NY 9-12, N=48, tp_r=1.0 | 739 | 30.8 | 48.8 | -0.010 | -0.3 | 0.81 | 0.95 | 35.0 | 40.3 | -0.030 / +0.010 | +0.047 / -0.066 | +0.045 |
| 26 | NY 9-12, N=48, tp_r=2.0 | 621 | 25.9 | 45.2 | +0.006 | 0.13 | 0.95 | 0.99 | 33.5 | 50.7 | +0.004 / +0.007 | +0.098 / -0.084 | +0.068 |
| 27 | NY 9-12, N=48, sl_atr=1.5 | 725 | 30.2 | 43.6 | +0.016 | 0.38 | 1.16 | 1.01 | 40.8 | 35.7 | +0.001 / +0.030 | +0.095 / -0.062 | +0.106 |
| 28 | NY 9-12, N=48, sl_atr=3.0 | 601 | 25.1 | 47.4 | -0.012 | -0.37 | 0.64 | 0.95 | 33.8 | 58.7 | -0.011 / -0.012 | +0.054 / -0.073 | +0.034 |
| 29 | NY 9-12, N=48, trend_mode=1 | 444 | 18.5 | 45.9 | +0.004 | 0.08 | 0.91 | 0.98 | 35.0 | 46.5 | -0.024 / +0.035 | +0.031 / -0.024 | +0.061 |
| 30 | NY 9-12, N=48, hold=90 | 630 | 26.3 | 44.1 | +0.006 | 0.15 | 1.04 | 0.99 | 31.5 | 59.2 | +0.013 / -0.000 | +0.068 / -0.053 | +0.058 |
| 31 | NY 9-12, N=48, fresh_only=True | 592 | 24.7 | 47.1 | +0.006 | 0.15 | 0.89 | 0.99 | 30.4 | 47.9 | -0.025 / +0.039 | +0.065 / -0.050 | +0.070 |
| 32 | NY 9-12, N=48, vol=1.0 | 573 | 23.9 | 46.8 | +0.017 | 0.39 | 0.92 | 1.01 | 35.3 | 47.4 | +0.024 / +0.010 | +0.107 / -0.067 | +0.069 |
| 33 | NY 9-12, N=48, vol=1.5 | 350 | 14.6 | 46.9 | +0.029 | 0.52 | 0.96 | 1.04 | 32.9 | 49.0 | +0.045 / +0.018 | +0.156 / -0.082 | +0.088 |
| 34 | NY 9-12, N=48, vol=1.2, sl_atr=1.5 | 550 | 22.9 | 44.0 | +0.032 | 0.65 | 1.2 | 1.03 | 35.2 | 34.5 | +0.034 / +0.030 | +0.151 / -0.084 | +0.111 |
| 35 | NY 9-12, N=96, vol=1.2 | 409 | 17.1 | 46.9 | +0.030 | 0.58 | 0.94 | 1.05 | 22.8 | 48.0 | +0.022 / +0.037 | +0.149 / -0.083 | +0.089 |
| 36 | NY 9:30-12, N=48 | 546 | 22.8 | 45.4 | -0.013 | -0.31 | 0.87 | 0.95 | 36.8 | 49.1 | -0.006 / -0.019 | +0.051 / -0.078 | +0.049 |
| 37 | NY 9-12, N=48, sl_atr=1.0 | 896 | 37.4 | 38.3 | -0.071 | -1.8 | 1.38 | 0.84 | 79.4 | 18.4 | -0.074 / -0.067 | -0.013 / -0.126 | +0.047 |

### What the sweep says
- **No gross edge.** Zero-cost R is about 0 in the base window (#1-8) and +0.02 to +0.11 R in the best
  window. Costs are about 0.065 R at a 2 x ATR stop ($4.6 median on dev). Tighter stops raise gross R but
  raise cost per R faster (#37, sl 1.0: gross +0.047, net -0.071).
- **Session matters most.** Including 08:00-09:00 New York (the 08:30 data releases) costs about
  0.05-0.07 R (#7 vs #16, #24). Starting at 09:00 is the only thing that moves results from clearly
  negative to about zero. That window was chosen on dev and itself has some selection bias.
- **Longer channels help a little.** At NY 9-12, N = 24/36/48/72/96 give -0.036 / -0.010 / +0.009 / -0.001
  / +0.017 R. This is a plateau around 0, not a spike.
- **Volatility expansion helps slightly.** At N=48, vol 0/1.0/1.2/1.5 give +0.009 / +0.017 / +0.013 / +0.029 R.
  Every one of these is inside one standard error of 0.
- **Exit shape does not rescue it.** TP 1.0/1.5/2.0, no TP, BE plus trailing, and holds of 30/60/90 min all
  stay within ±0.04 R of each other (#9-14, #25-26, #30).
- **HTF trend filter**: neutral to slightly harmful (#4, #29). Fresh-break-only makes no difference (#2, #31).
  M15 signals are worse (#17).
- **The positive rows come entirely from longs** (+0.07 to +0.16 R; shorts -0.04 to -0.13 R) during a gold
  uptrend. I did not adopt a long-only filter, because that is a directional bet rather than a breakout
  edge. In 2024, a +27% gold year, the longs of the final choice were *negative* (-0.041 R).

## Final parameters (DEFAULT_PARAMS = row #20, the centre of the plateau, with the archetype's vol filter)
M5 bars. Long when the M5 close is above the highest high of the previous 48 M5 bars; short when it is
below the lowest low. Require ATR(5)/ATR(50) on M5 ≥ 1.2. The signal bar's close time must fall in
09:00-12:00 New York local time. Enter at the next M1 open. Stop 2.0 x ATR14(M5), TP 1.5 R, exit after
60 min, hard flat 15:30 NY. One position at a time.

## Results
| | trades | /month | win% | avg R | avg win R | PF | maxDD% | hold min | long / short R | zero-cost R |
|---|---|---|---|---|---|---|---|---|---|---|
| dev 2022-23, no limits | 491 | 20.5 | 46.2 | +0.013 | 0.95 | 1.00 | 35.7 | 47.5 | +0.110 / -0.078 | +0.065 |
| **val 2024, no limits** | 303 | 25.2 | 44.9 | **-0.012** | 0.96 | 0.95 | 39.9 | 39.8 | -0.041 / +0.016 | +0.037 |
| val 2024, stress costs | 304 | 25.3 | 43.8 | -0.047 | 0.94 | 0.87 | 46.8 | 39.1 | -0.072 / -0.023 | |

By year: 2022 +0.023 R, 2023 +0.004 R, 2024 -0.012 R. By NY hour on 2024: 09h -0.010 R (184 trades),
10h +0.032 R (90), 11h -0.161 R (29). There are at most 4 trades per day.

Account simulation ($50 cent, 2% risk, default rules):
- **dev:** -4.1%, max DD 23.6%, 45.8% positive months, worst month -10.2%, not hard-stopped.
  Monte Carlo over 6 months: P(hard stop) 0.34%, median $48.76.
- **2024:** -6.9%, max DD 26.2%, 50% positive months, worst month -10.3%, not hard-stopped.
  Monte Carlo over 6 months: **P(hard stop) 2.4%**, median $46.57, p5 $37.64, P(profit) 34.8%.

There was no revision after validation. The only levers left (long-only, re-picking the hour window or
the stop) would be fitted to 2024.

## Engine notes
- I found no engine bug. Fills happen only at M1 opens, so a stop-entry breakout (filling at the channel
  level) is approximated by close confirmation followed by a next-bar market order. That is what an
  EA would do on bar close anyway.
- `CostModel.rollover_hours_utc=(21,22)` is applied on the data clock (NY+5). The real 17:00 ET break is at
  22:00 on that clock, so 23:00 (the reopen) is charged normal spread. This is irrelevant here because the
  strategy only trades 09:00-13:00 NY.
