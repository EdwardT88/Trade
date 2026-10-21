# intraday_h1_basket: research log (H1 momentum vs short-term reversal, FX basket + gold)

**Verdict: marginal.** The final rule clears the pre-registered gates 1–4 in `results/MULTI_MARKET_PLAN.md`, but only
after one disclosed revision, and its validation result is weak (+0.07 R, t = 0.56, 81 trades).
- **Reversal loses after costs.** RSI(2) fades in the direction of the D1 trend lose −0.06 to −0.11 R per trade
  (t ≈ −10 to −21), on every pair and in every year.
- **Momentum holds up.** Continuation after an unusually large H1 move ("news shock") keeps a gross edge after
  cent-account costs on dev.
- **Final rule.** Trade a one-hour shock larger than 4 × ATR(120), and only when at least one other FX pair shocks
  in the same hour. Stop 2 ATR, target 2 R, exit by time after at most 12 h. Median hold is 6–7 h on dev and 4 h on validation.
- **Results.** Dev 2013–2019: +0.29 R/trade, t = 6.1 (4.0 when trades on the same day are clustered). Validation
  2020–2022: +0.07 R (stress +0.055), not statistically significant: 81 trades on 24 distinct days, 2020 negative,
  2021–22 positive.
- **Next step.** Treat it as a candidate for the 2026 holdout only, not as a proven edge.

## Protocol
- Dev: 2013-01-01 .. 2020-01-01 (all tuning and the pair-set choice). Validation: 2020-01-01 .. 2022-03-05.
- Engine: `backtest/engine.py` with `research_risk()` (R-based, no account limits). Costs: `markets.cost_model`
  (cent spreads EURUSD 1.3 … GBPJPY 3.0 pips, gold max($0.25, 0.8 bps), ×3 spread 16:30–18:30 New York,
  0.2 pip stop slippage, swap 3 %/yr FX / 5 % gold). Stress = `--stress 1.5`.
- Bars: FX M15 (signals on H1 resampled from M15, filled at the next M15 open); gold H1 before 2022, M1 after.
- **Budget:** 52 distinct parameter sets were run in the engine on dev, listed below. Roughly 350 descriptive
  event-study cells (conditional forward returns, dev only) were used to choose which families to run.
- Validation was run twice: once for the original choice and once for the single disclosed revision.

## Step 1: the dichotomy (event study on dev, all 11 pairs, H1 closes; forward moves in ATR units)
Measured cost: the median spread is 0.09–0.22 × ATR14(H1) (EURUSD/GBPUSD 0.09, EURCHF 0.22).
- **Reversal.** Fading RSI(2) < 10 / > 90 in the direction of the D1 trend is real but tiny. Gross is +0.03 to
  +0.07 ATR over 1–8 h (t ≈ 6–7), while the spread is ≈ 0.13 ATR, so it is negative net of spread in almost
  every hour of the day. Without the trend filter it is half as large.
- **Momentum.** Continuation after large H1 or multi-hour moves is the larger effect.

  | lookback | move threshold | gross continuation over 4 / 8 / 12 h |
  |---|---|---|
  | 3 h | > 4 × ATR14 | +0.17 / +0.21 / +0.30 ATR (t ≈ 4–5) |
  | 3 h | > 5 × ATR14 | +0.26 / +0.37 / +0.57 ATR |

  Continuation is not larger when the shock goes with the D1 trend (k12: +0.22 with, +0.40 against).
- **Day-open momentum.** Holding the day's direction from the 17:00 NY open (cut at 03:00–12:00 NY) does not cover the spread.
- **Normaliser.** ATR(120) on H1, about 5 days of hourly range and independent of the hour of day, beats
  ATR(14). A quiet Asian ATR14 turns ordinary London-open volatility into false "shocks".

## Step 2: engine sweep on dev
Runs S1–S7 use all 11 FX pairs (EURCHF from 2015-03). S8 is gold alone. S9 uses the chosen set (10 FX + gold).
Default exits apply unless a row says otherwise: no target, no trend filter. Blocked entries: H1 closes at
16:00–18:59 NY, weekends, Friday after 12:00 NY. All positions are flat by Friday 16:00 NY.

| run | params (momentum unless noted) | n | /month | avg R | t | PF | med hold h |
|---|---|---|---|---|---|---|---|
| S1 | L=3, thr=4 ATR14, sl=1.5, hold 4 | 1802 | 21.5 | +0.009 | 0.32 | 1.02 | 4.0 |
| S1 | L=3, thr=4 ATR14, sl=1.5, hold 8 | 1798 | 21.4 | −0.005 | −0.15 | 0.99 | 6.9 |
| S1 | L=3, thr=4 ATR14, sl=1.5, hold 12 | 1797 | 21.4 | +0.016 | 0.47 | 1.03 | 6.8 |
| S1 | L=3, thr=4 ATR14, sl=2.5, hold 4 | 1767 | 21.0 | +0.014 | 0.76 | 1.05 | 4.0 |
| S1 | L=3, thr=4 ATR14, sl=2.5, hold 8 | 1762 | 21.0 | +0.007 | 0.34 | 1.02 | 8.0 |
| S1 | L=3, thr=4 ATR14, sl=2.5, hold 12 | 1761 | 21.0 | +0.020 | 0.84 | 1.05 | 12.0 |
| S1 | L=3, thr=4 ATR14, sl=4, hold 4 | 1762 | 21.0 | +0.005 | 0.40 | 1.03 | 4.0 |
| S1 | L=3, thr=4 ATR14, sl=4, hold 8 | 1755 | 20.9 | −0.003 | −0.20 | 0.99 | 8.0 |
| S1 | L=3, thr=4 ATR14, sl=4, hold 12 | 1754 | 20.9 | −0.001 | −0.03 | 1.00 | 12.0 |
| S1 | L=3, thr=4 ATR14, sl=1.5, tp=1R, hold 8 | 2124 | 25.3 | −0.004 | −0.18 | 0.99 | 1.8 |
| S1 | L=3, thr=4 ATR14, sl=2.5, tp=1R, hold 8 | 1896 | 22.6 | +0.020 | 1.10 | 1.06 | 6.0 |
| S1 | **REVERSAL** RSI(2)<10 with D1 EMA20 trend, sl=1.5, tp=1R, hold 8 | 29445 | 350.7 | **−0.108** | −20.8 | 0.77 | 3.0 |
| S1 | **REVERSAL** RSI(2)<10 with D1 EMA20 trend, sl=2.5, hold 8 | 23501 | 279.9 | **−0.058** | −10.2 | 0.84 | 8.0 |
| S2 | L=3, thr=4 ATR14, 2 consecutive closes, sl=2.5, hold 8 | 671 | 8.0 | +0.050 | 1.62 | 1.17 | 8.0 |
| S2 | same, hold 12 | 670 | 8.0 | +0.076 | 2.17 | 1.25 | 12.0 |
| S2 | same, tp=1R, hold 12 | 692 | 8.2 | +0.060 | 2.10 | 1.20 | 7.0 |
| S3 | L=3, thr=4 ATR120, sl=2, hold 6 | 2678 | 31.9 | +0.010 | 0.47 | 1.03 | 6.0 |
| S3 | L=3, thr=4 ATR120, sl=2, hold 12 | 2639 | 31.4 | +0.030 | 1.19 | 1.06 | 12.0 |
| S3 | L=3, thr=4 ATR120, sl=3, hold 6 | 2627 | 31.3 | +0.004 | 0.23 | 1.01 | 6.0 |
| S3 | L=3, thr=4 ATR120, sl=3, hold 12 | 2584 | 30.8 | +0.008 | 0.45 | 1.02 | 12.0 |
| S3 | L=3, thr=5 ATR120, sl=2, hold 6 | 1219 | 14.5 | +0.079 | 2.11 | 1.19 | 6.0 |
| S3 | L=3, thr=5 ATR120, sl=2, hold 12 | 1208 | 14.4 | +0.116 | 2.78 | 1.25 | 12.0 |
| S3 | L=3, thr=5 ATR120, sl=3, hold 6 | 1192 | 14.2 | +0.051 | 1.93 | 1.18 | 6.0 |
| S3 | L=3, thr=5 ATR120, sl=3, hold 12 | 1179 | 14.0 | +0.064 | 2.14 | 1.19 | 12.0 |
| S4 | L=3, thr=5, sl=2, tp=1R, hold 12 | 1488 | 17.7 | +0.031 | 1.34 | 1.08 | 2.5 |
| S4 | L=3, thr=5, sl=2, tp=2R, hold 12 | 1327 | 15.8 | +0.090 | 2.87 | 1.20 | 5.8 |
| S4 | L=3, thr=4.5, sl=2, hold 12 | 1755 | 20.9 | +0.072 | 2.25 | 1.16 | 12.0 |
| S4 | L=3, thr=5.5, sl=2, hold 12 | 839 | 10.0 | +0.146 | 2.80 | 1.32 | 12.0 |
| S4 | L=3, thr=6, sl=2, hold 12 | 591 | 7.0 | +0.213 | 3.23 | 1.46 | 12.0 |
| S4 | L=2, thr=5, sl=2, hold 12 | 807 | 9.6 | +0.196 | 3.65 | 1.43 | 12.0 |
| S4 | L=4, thr=5, sl=2, hold 12 | 1633 | 19.4 | +0.037 | 1.13 | 1.08 | 12.0 |
| S5 | L=2, thr=4.5, sl=2, hold 12 | 1160 | 13.8 | +0.122 | 2.92 | 1.27 | 12.0 |
| S5 | L=2, thr=5.5, sl=2, hold 12 | 575 | 6.8 | +0.229 | 3.38 | 1.50 | 12.0 |
| S5 | L=1, thr=3.5, sl=2, hold 12 | 1261 | 15.0 | +0.114 | 2.84 | 1.24 | 11.0 |
| S5 | L=1, thr=4, sl=2, hold 12 | 808 | 9.6 | +0.215 | 4.01 | 1.49 | 12.0 |
| S5 | L=2, thr=5, sl=2, tp=2R, hold 12 | 869 | 10.3 | +0.175 | 4.31 | 1.40 | 5.0 |
| S5 | L=2, thr=5, sl=2, hold 6 | 813 | 9.7 | +0.147 | 3.07 | 1.36 | 6.0 |
| S5 | L=2, thr=5, sl=3, hold 12 | 791 | 9.4 | +0.130 | 3.37 | 1.39 | 12.0 |
| S5 | L=2, thr=5, sl=1.5, hold 12 | 835 | 9.9 | +0.187 | 2.88 | 1.33 | 5.8 |
| S6 | **L=1, thr=4, sl=2, tp=2R, hold 12** (original choice) | 849 | 10.1 | +0.168 | 4.21 | 1.39 | 6.2 |
| S6 | same, hold 8 | 849 | 10.1 | +0.146 | 3.84 | 1.36 | 6.2 |
| S6 | same, only with D1 trend | 401 | 4.8 | +0.129 | 2.28 | 1.30 | 6.8 |
| S6 | same, only against D1 trend | 448 | 5.3 | +0.202 | 3.62 | 1.48 | 6.0 |
| S6 | same, ATR(72) | 811 | 9.7 | +0.208 | 5.09 | 1.51 | 7.0 |
| S6 | same, ATR(240) | 865 | 10.3 | +0.111 | 2.81 | 1.24 | 5.8 |
| S7 | thr=4.5 | 566 | 6.7 | +0.200 | 4.02 | 1.47 | 5.8 |
| S7 | sl=1.5 | 849 | 10.1 | +0.111 | 2.53 | 1.21 | 2.0 |
| S7 | sl=2.5 | 842 | 10.0 | +0.144 | 4.02 | 1.39 | 9.8 |
| S7 | tp=1.5R | 849 | 10.1 | +0.145 | 4.01 | 1.35 | 4.5 |
| S7 | tp=3R | 839 | 10.0 | +0.171 | 3.87 | 1.39 | 7.2 |
| S8 | original choice on XAUUSD only | 102 | 1.2 | +0.125 | 1.08 | 1.28 | 5.0 |
| S9 | original choice, chosen set (10 FX + gold) | 936 | 11.1 | +0.166 | 4.38 | 1.39 | 6.0 |
| S9 | + ≥1 other FX pair with a shock > 3 ATR120 in the same hour | 771 | 9.2 | +0.197 | 4.67 | 1.47 | 6.2 |
| S9 | **+ ≥1 other FX pair with a shock > 4 ATR120 in the same hour (final)** | 629 | 7.5 | +0.289 | 6.11 | 1.75 | 6.8 |

What the sweep shows:
- **Parameters.** The faster and larger the shock, the stronger the continuation. Around L=1, thr=4, ATR(120),
  sl=2, tp=2R the neighbourhood is smooth: +0.11 to +0.21 R, t 2.5–5.1.
- **Trend filter.** The D1 trend filter does not help, so it is off.
- **Pair set (dev only).** Gold is included: +0.125 R, n=102, same mechanism. EURCHF is excluded for three reasons:
  - it is an SNB-managed currency;
  - its spread/ATR (0.22) is about twice that of the other pairs;
  - it was negative in almost every variant (−0.02 to −0.57 R), though on few trades.

## Final rules (DEFAULT_PARAMS in `strategies/intraday_h1_basket.py`)
Instruments: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, EURGBP, EURJPY, GBPJPY, AUDJPY, XAUUSD.
Each instrument is traded independently, with at most one position each.
1. On every H1 close, compute `move = close[1] − close[2]` on completed bars, i.e. the hour that just closed.
   The previous bar must start exactly 1 h earlier, which rules out the weekend gap. Use
   `ATR = iATR(H1, 120)`, the SMA of true range including the bar that just closed.
2. **Shock:** |move| > 4.0 × ATR.
3. **Peer confirmation:** in the same hour, at least one *other* FX pair from the 10-pair list has
   |its own move| > 4.0 × its own ATR(120). The peer's direction does not matter, and gold counts all 10 FX pairs as peers.
4. **Entry:** market order at the open of the next H1 bar, in the direction of the move.
5. **Entry blocks:** no new entries when the H1 close falls at 16:00–18:59 New York time, on a Saturday or Sunday
   (New York calendar, which skips the Sunday-evening open), or on Friday at or after 12:00 New York.
6. **Stop** = 2.0 × ATR from the fill. **Target** = 2R (4.0 × ATR). **Time exit** 12 h after entry, and in any case at
   Friday 16:00 New York. No breakeven and no trailing.
7. **MT5 clock:** on a "New York close" server (GMT+2 winter / GMT+3 summer, which follows US DST), server time is
   New York time + 7 h. The blocks become:
   - no entries for H1 closes at 23:00–01:59 server time;
   - Friday cut-off at 19:00 server time;
   - Friday flat at 23:00 server time.

   With any other server offset, convert from TimeGMT() with US DST rules.
8. The EA has to read H1 bars of all 10 FX pairs for step 3 even when it trades fewer instruments.

## Results with final rules (research risk, R units)
| sample | n | avg R | se | t | win % | PF | med hold h | trades/month |
|---|---|---|---|---|---|---|---|---|
| dev 2013–2019, base | 629 | +0.289 | 0.047 | 6.11 | 52.8 | 1.75 | 6.8 | 7.5 |
| dev, stress 1.5 | 629 | +0.247 | 0.047 | 5.23 | 51.8 | 1.61 | 6.0 | 7.5 |
| validation 2020–2022-03, base | 81 | +0.071 | 0.127 | 0.56 | 49.4 | 1.15 | 4.2 | 3.1 |
| validation, stress 1.5 | 81 | +0.055 | 0.126 | 0.43 | 48.1 | 1.12 | 4.2 | 3.1 |
| dev + validation, base | 710 | +0.264 | 0.044 | 5.95 | 52.4 | 1.67 | 6.0 | 6.5 |

Correlation between same-day trades (one macro release triggers several pairs) shrinks the t-statistics.
With standard errors clustered by entry date:

| sample | t | days |
|---|---|---|
| dev | 4.0 | 184 |
| validation | 0.38 | 24 |
| dev + validation | 3.9 | 208 |

The validation result rests on about 24 independent days.

Average R by year:

| sample | 2013 | 2014 | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 |
|---|---|---|---|---|---|---|---|---|---|---|
| dev | +0.36 | +0.37 | +0.10 | +0.49 | +0.41 | −0.06 | +0.21 | | | |
| validation | | | | | | | | −0.56 (n=30) | +0.35 (n=48) | +1.98 (n=3) |

The 2020 losses are spread over Feb–Dec 2020, not one event.

Per pair, shown as avg R / n:

| pair | dev | validation |
|---|---|---|
| EURUSD | +0.330/97 | −0.208/14 |
| GBPUSD | +0.444/78 | +0.052/10 |
| USDJPY | +0.279/58 | −0.305/8 |
| AUDUSD | +0.067/49 | −0.086/7 |
| USDCAD | +0.008/31 | −0.472/4 |
| USDCHF | +0.285/70 | −0.012/7 |
| EURGBP | +0.279/73 | +0.739/7 |
| EURJPY | +0.441/47 | +0.343/7 |
| GBPJPY | +0.235/49 | +0.428/7 |
| AUDJPY | +0.277/38 | −0.094/5 |
| XAUUSD | +0.321/39 | +0.606/5 |

On validation the FX pairs alone made +0.036 R (n=76) and gold made +0.61 R (n=5).

## Disclosed revision
- **Original choice** (S9, no peer filter): dev +0.166 R (t 4.38, stress +0.129). On validation it scored +0.002 R
  (n=126) and −0.011 R under stress, so it **failed gate 3**. FX alone was −0.08 R; 2020 was −0.49 and 2021 +0.21.
- **Revision.** I then added the peer-confirmation filter. It came from dev data only: on dev, a shock in a single
  pair (no other pair moving in the same hour) earned −0.09 R (n=300), while shocks shared by ≥ 2 pairs earned
  +0.24 to +0.36 R. The mechanism is that macro news moves a whole currency, while single-pair spikes are local
  liquidity events. Two peer thresholds were run on dev, 3 and 4, giving +0.20 and +0.29 R. Threshold 4 equals
  the own-shock threshold, so it was taken without a further choice, and run once on validation.
- **Caveat.** The revision was made *because* the original failed. Its validation number is therefore biased upward,
  and it is the only one I am allowed to make.
- **Mixed descriptive evidence.** Splitting the dev event study by peer threshold did not give a monotone picture.
  Signals with no other pair above 3 or 2 ATR still showed continuation. The peer filter is plausible, not proven.

## Caveats for the owner
- **Frequency is low:** about 7.5 trades a month across 11 instruments on dev, but only 3 a month in 2020–22,
  because ATR(120) was high. On a $50 cent account this is roughly one trade a week.
- **The edge decays over time:** 2013–2017 strong, 2018–2022 about +0.1 R and not significant.
  News-shock continuation may be a regime that comes and goes.
- **The engine may flatter execution:** fills at the next M15 open right after a news hour. A real EA will see
  wider spreads and slippage in the first seconds after releases. The stress 1.5 run covers part of that.
- **The 2026 holdout will use fewer peers:** it has no GBPJPY/AUDJPY files, so the filter runs with 7 peers per
  pair instead of 9. The module reads peer files from `data/markets/<SYM>_m15_2026.parquet`, or from `peer_dir`.
