# Timeframe check (gold M1 2022-2025, swap-free, max hold 3 days)

`python scripts/timeframe_check.py`. Columns: period, cost stress, trades, avg R, t-stat, trades/month, median hold (h).
R/yr = avg R x trades/month x 12 (normal costs). sqrt-growth score = trades/month x (avg R / sd R)^2 matters for compounding.

| Config | 2022-23 avg R (t) | 2024-25 avg R (t) | trades/mo | R/yr 22-23 / 24-25 | median hold |
|---|---|---|---|---|---|
| **EA: H4 trend / H1 entry** | **+0.43 (2.9)** | **+0.24 (1.9)** | 3-4 | 16.5 / 12.0 | 32-38 h |
| H4 / M30 entry | +0.24 (2.3) | +0.07 (0.8) | 6-8 | 18.3 / 5.9 | 35 h |
| H4 / M15 entry | +0.10 (1.4) | +0.16 (2.2) | 10 | 11.5 / 19.3 | 31-34 h |
| H2 / M30 (all x0.5) | +0.15 (1.3) | +0.07 (0.7) | 6-8 | 11.3 / 6.2 | 25 h |
| H1 / M15 (all x0.25) | -0.07 | +0.03 | 13 | negative / 4.8 | 12 h |
| M30 / M5 | -0.01 | +0.04 | 28-30 | ~0 / 15 (t 0.8) | 7 h |
| M15 / M5 | -0.13 (-2.6) | +0.06 (1.0) | 30-31 | -46 / 20 | 3 h |

Caveat: 2022-23 is the EA's own development period (favours H4/H1). Conclusion: keep H4/H1. Lower entry TFs give more
trades with a smaller edge per trade (worse for Kelly compounding and execution); lowering the whole system shortens
holds but the edge goes to ~0 after costs, same as the earlier scalping research.
