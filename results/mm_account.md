# Account/broker side and cash-flow schedules (mm_account)

Code: `scripts/mm_account.py` (about 20 s; `--dev-only` prints only the dev grid). Trades: the fixed EA trade list from
`scripts/mm_sim.py` (603 trades, 2013-2026). Each period starts from a fresh $50.

## Protocol, combo count, disclosures
- **Account-side levers** (swap, spread, rebates, VPS, Pro account) are not tuned. The same signals are re-run
  with each cost set (MM_RESEARCH_PLAN), on every period. That is 14 cost sets + 2 VPS fees + 1 graduation rule,
  each under fixed 3%, the ladder 5/3/2 and C (rolling half-Kelly W60 from `mm_sizing.py`).
  - The swap clamp in `cost_model` was already fixed (commit df3504e), so `get_trades(swap=0)` is truly swap-free.
- **Cash-flow schedules** were tuned on dev 2013-19 only.
  - The grid has 15 schedules × 2 bases = 30 combos. The ladder base was run twice (see the disclosure below),
    so **45 dev evaluations** in all.
  - Finalists were picked by `pick_finalists()` from dev alone: per base and family, the best dev wealth that beats
    the base. A deposit schedule must also keep IRR ≥ the base's. Two fixed references always go through:
    "take 50% at each 2x" and "DCA $10/month".
  - Each finalist was then validated once.
- **Wealth** = $50 + net trading gain = equity + withdrawn − deposits after the start. For withdrawal-only
  schedules this is mm_sim's "total". IRR is the money-weighted return per year.
- **Disclosure: the ladder was run twice.**
  - First run: the ladder stepped at fixed $100/$200. Its validation for "take 50% at 2x" and "DCA $10" on the
    ladder was seen: $81.15 / $285.44 / $154.76 and $86.69 / $503.33 / $1,304.77 (dev / val sum / all).
  - I then read `GoldSwingCent.mq5`. On every deposit or withdrawal (DEAL_TYPE_BALANCE) the EA shifts its
    start-balance and peak globals, and the ladder uses balance / start.
  - The ladder now follows that EA rule. The old variant can be reproduced with `--ladder-fixed-thresholds`.
  - The same selection rule then also picked "take 33% at 2x" and "refill" for the ladder.
- **Bootstrap:** block bootstrap of dev trades only (blocks of 20, 1000 paths). It was not used for selection.

## 1. Account side: real levers that need a broker/account choice
Average R per trade: baseline +0.076. The $ columns are fixed 3% / ladder / C on the whole history 2013-26
(fresh $50), with max DD.

| scenario | ΔR/trade (all) | fixed 3%: dev / val sum / all / DD | ladder: dev / val sum / all / DD | C W60: all / DD |
|---|---|---|---|---|
| HFM Cent today (swap 5%/yr, model spread ≈ $0.34 at $4.2k gold) | 0 | 59.93 / 280.39 / 137.50 / 64.7% | 84.61 / 314.27 / 213.76 / 74.4% | 601.83 / 42.9% |
| **swap-free only** | **+0.033** | 83.63 / 321.20 / 248.73 / 57.1% | 107.26 / 356.82 / 302.53 / 65.5% | 1,294.89 / 48.1% |
| swap 2.5%/yr (if the real swap is half) | +0.017 | 70.80 / 299.99 / 184.96 / 61.0% | 94.31 / 335.70 / 245.98 / 70.0% | 903.04 / 45.4% |
| swap 8%/yr (if it is higher) | −0.020 | 49.06 / 258.84 / 96.30 / 68.6% | 42.80 / 293.68 / 110.56 / 85.8% | 362.95 / 44.2% |
| spread ×0.75 only (~$0.25) | +0.007 | 62.42 / 285.67 / 154.42 / 62.0% | 89.45 / 322.08 / 217.78 / 71.5% | 685.70 / 42.6% |
| spread ×0.6 only (~$0.20) | +0.012 | 64.27 / 289.47 / 168.85 / 59.7% | 83.72 / 322.38 / 224.27 / 70.5% | 801.79 / 42.2% |
| spread ×1.3 | −0.005 | 56.60 / 276.22 / 126.20 / 65.5% | 62.68 / 306.30 / 172.91 / 80.5% | 526.46 / 42.7% |
| HFM + IB rebate $0.12/oz, rebates < $0.01 not paid | +0.0085 | 65.89 / 286.33 / 156.97 / 63.0% | 82.95 / 318.55 / 212.68 / 75.6% | 696.55 / 42.0% |
| **Exness Std Cent: swap-free + spread ×0.75** | **+0.040** | **87.15 / 327.26 / 279.51 / 53.8%** | **112.06 / 358.99 / 316.53 / 60.1%** | **1,522.38 / 48.1%** |
| ... + rebate $0.06/oz (no sub-cent) | +0.044 | 90.17 / 329.24 / 292.77 / 53.0% | 115.18 / 365.22 / 362.06 / 47.9% | 1,648.15 / 47.6% |
| Exness swap-free, spread ×0.6 (optimistic) | +0.045 | 89.74 / 331.66 / 306.40 / 50.9% | 113.72 / 367.37 / 362.88 / 47.6% | 1,815.18 / 47.8% |
| Exness with swap-free revoked (×0.75, swap 5%) | +0.007 | same as spread ×0.75 | | |
| paid VPS $12/month from the account | – | **ruined in every period** (fees $36-45 before ruin), all 3 bases | | |
| paid VPS $5/month | – | ruined in dev, 2020-21 and 2022-25, all 3 bases | | |
| Pro account at equity ≥ 100 × 1-oz stop risk | – | never triggers from $50 within 13 years (needs $1.5k-7k equity) | | |

Notes:
- **Swap-free alone:** it is the only large lever, +0.033R per trade (+44% of the edge).
  - It improves every period, including the losing ones: 2020-21 −0.145→−0.115, 2026 −0.206→−0.188.
  - Exness swap-free with a ~25% tighter spread is "better" under the protocol for every base. It beats fixed 3%
    on dev and on val sum, and is never ruined.
  - Fixed 3% on Exness ($87 / $327) even beats the ladder on HFM ($85 / $314).
- **Swap size:** the lever's value is exactly the swap HFM really charges. The repo assumes 5%/yr on both sides.
  The owner should read swap long/short in the XAUUSDc specification. At 2.5%/yr the gain halves.
- **Rebates:** small (+0.004 to +0.009R in theory). At $50 the median trade is about 0.10 oz, so a rebate is
  $0.012 at $0.12/oz and $0.006 at $0.06/oz.
  - Only 13% of trades reach $0.01 at the $0.06 rate.
  - Over 13 years, fixed 3% collects about $10 (HFM rate) or $5 (Exness rate).
  - It is worth it only once equity is ≥ ~$200, when 90% of trades pay.
- **Ladder path dependence:** the ladder results do not always rise as costs fall (for example, spread ×0.6 dev
  $83.72 < $84.61). Its 2x/4x thresholds make it sensitive to the exact path.
- **VPS:** a paid VPS is the one account-side choice that destroys the account.

## 2. Cash-flow schedules (validation run once)
"better" means beating fixed 3% on dev wealth and on val sum without ruin. A deposit schedule must also keep its
IRR ≥ fixed 3%'s on dev and on the whole history.

| schedule [base] | dev | 20-21 | 22-25 | 2026 | val sum | all | all: equity/withdrawn/deposited | IRR %/yr dev/20-21/22-25/26/all | acct DD (TWR) | worst net $ | better | beats ladder |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| REF fixed 3% | 59.93 | 32.72 | 204.90 | 42.77 | 280.39 | 137.50 | 137.50/0/0 | 2.6/−19.1/42.3/−26.7/7.6 | 64.7% | −17.80 | – | – |
| REF ladder 5/3/2 | 84.61 | 23.61 | 252.47 | 38.19 | 314.27 | 213.76 | 213.76/0/0 | 7.8/−31.3/49.9/−41.4/11.2 | 74.4% | −26.79 | – | – |
| W take 50% at each 2x [fixed 3%] | 80.05 | 32.72 | 153.00 | 42.77 | 228.49 | 118.83 | 68.75/50.08/0 | 8.5/−19.1/51.5/−26.7/9.9 | 64.7% | −17.80 | no | no |
| D refill to $50, max $10/month [fixed 3%] | 70.36 | 29.38 | 222.16 | 42.42 | 293.96 | 187.23 | 207.18/0/19.95 | 3.8/−18.6/42.7/−27.2/8.3 | 64.7% | −21.44 | yes | no |
| D DCA $10/month [fixed 3%] | 137.77 | −14.24 | 725.04 | 34.74 | 745.54 | 2,204.42 | 3,844/0/1,640 | 2.6/−20.8/40.9/−33.3/11.0 | 64.7% | −378.25 | no | no |
| W take 33% at each 2x [ladder] | 92.77 | 23.61 | 171.31 | 38.19 | 233.11 | 143.04 | 107.55/35.49/0 | 11.4/−31.3/50.2/−41.4/10.7 | 56.3% | −26.79 | no | no |
| W take 50% at each 2x [ladder] | 81.15 | 23.61 | 219.94 | 38.19 | 281.74 | 154.76 | 46.12/108.64/0 | 10.3/−31.3/94.8/−41.4/14.1 | 83.9% | −26.79 | yes (by $1) | no |
| D refill to $50, max $10/month [ladder] | 109.11 | 14.17 | 287.33 | 37.21 | 338.71 | 324.43 | 358.68/0/34.25 | 8.2/−30.3/50.5/−42.7/11.3 | 76.4% | −36.73 | yes | yes |
| D DCA $10/month [ladder] | 163.72 | −50.79 | 1,019.63 | 25.35 | 994.19 | 3,417.56 | 5,058/0/1,640 | 3.3/−33.8/52.7/−50.1/14.4 | 80.6% | −591.93 | yes ($ only) | no |

No schedule was ruined. Every schedule except the fixed-3% DCA hits the EA's −30% hard stop in dev and in 2020-21.
"Take 50% at each 2x" on the ladder also hits it in 2022-25.

Dev bootstrap: wealth median / mean / P10, how often the schedule beats its base on the same path, and P(hit −30%).

| schedule | median | mean | P10 | beats base on same path | P(hit −30%) |
|---|---|---|---|---|---|
| fixed 3% | 57.2 | 72.7 | 24.7 | – | 49% |
| ladder | 57.4 | 84.0 | 13.0 | – | 67% |
| take 50% at each 2x [fixed 3%] | 61.5 | 69.0 | 24.7 | 16% | 61% |
| refill [fixed 3%] | 63.5 | 78.0 | 16.9 | 69% | 42% |
| take 50% at each 2x [ladder] | 71.3 | 79.7 | 13.2 | 19% | 92% |
| take 33% at each 2x [ladder] | 78.0 | 75.5 | 13.2 | 19% | 64% |
| refill [ladder] | 74.9 | 98.5 | −11.5 | 65% | 64% |
| DCA $10 [ladder] | 142.2 | 362.8 | −392.9 | 56% | 73% |

What the schedules do:
- **Withdrawals** (take x% at each doubling, free-roll, barbell, monthly/quarterly/annual sweeps) do not add
  return.
  - The dev "wins" came from banking at the 2016 peak before the 2016-19 slide.
  - On validation, both "take x% at 2x" variants lost to fixed 3% and to the ladder: val sum $228-282 against
    $280 / $314.
  - In the bootstrap, withdrawing raises the median a little but lowers the mean and the upper tail. This is the
    expected Kelly-plus-cash result: banking is a psychology and ruin tool, not a return lever.
- **DCA $10/month** raises dollars, not percent return. With fixed 3%, IRR is below no-DCA in every validation
  period (−20.8 vs −19.1, 40.9 vs 42.3, −33.3 vs −26.7).
  - Its all-history IRR (11.0% vs 7.6%) is luck of timing: deposits made in 2020-21 caught the 2022-25 boom.
  - The worst cumulative loss was −$378 with fixed 3% and −$592 with the ladder, on $1,640 deposited.
- **Refill to $50** (deposit up to $10 in a month that starts below $50) passes the protocol, and on the ladder
  it also beats the ladder. It put in only $20-34 over 13 years.
  - It is an account-level averaging-down. It made 2020-21 worse ($14 vs $24 on the ladder) and won in 2022-25
    because the system recovered.
  - The dev bootstrap shows a fatter left tail: P10 −$11.5 against +$13.0 for the ladder.
  - Treat it as optional ("keep the account topped up to $50 if you are happy to add money"), not as a
    recommended return lever.

## 3. EA facts that matter for withdrawals and deposits (mql5/GoldSwingCent.mq5)
- **Globals follow cash flows.** OnTradeTransaction shifts the start balance and peak globals by every deposit or
  withdrawal, so the hard stop and the drawdown brake keep working. If the start balance falls to ≤ 0, it is
  reset to the balance.
- **The ladder follows net capital in.** With InpRiskLadder it uses balance / start, so it measures growth
  against net money put in. Two side effects:
  - Partly withdrawing profits pushes the ladder down. For example, taking 33% at $100 leaves start = $16.7 and
    balance $66.7, a growth of 4.0x, so risk drops to 2%.
  - Deposits hold it at the 5% tier, so DCA under the ladder means 5% risk on a growing pot.
- **The hard stop also follows net capital.** It halts at a 30% loss of net contributed capital, so a $10
  deposit only moves the account $3 away from the stop.

## Verdict (what is real, and its size)
1. **Swap-free account (Exness Standard Cent, automatic for Indonesian residents): REAL and the largest lever,
   about +0.033R per trade.**
   - Together with Exness's (UNVERIFIED) ~25% tighter spread, it adds +0.040R per trade, about +53% of the edge.
   - Fixed 3% over 2013-26 goes from $138 to $280 (2.0x), with max DD 54% instead of 65%. The ladder goes from
     $214 to $317, and C from $602 to $1,522.
   - It needs the owner to switch broker and to confirm in MT5 that swap long/short = 0 on XAUUSDc.
   - Risks:
     - Exness can revoke swap-free status. If it does, the gain falls to the spread effect (+0.007R).
     - Exness is not licensed by Bappebti.
     - The size of the gain depends on the swap HFM really charges.
2. **Lower spread alone: real but small.** ×0.75 gives +0.007R and ×0.6 gives +0.012R. Log the live spreads for
   2 weeks before relying on the numbers.
3. **IB rebates: real but negligible at $50.** They add about $5-10 over 13 years under fixed 3%. Register only
   once equity is ≥ ~$200, and never deposit through an IB.
4. **No paid VPS:** a $5-12/month VPS ruins a $50 account in every base and period. **No bonuses:** not modelled,
   0R at best. **Pro/Raw account:** not reachable from $50 within the history.
5. **Withdrawal schedules: not a return lever.** None beat fixed 3% and the ladder on validation. Use them only if
   the owner prefers banked cash.
6. **Deposits: they add capital, not edge.** DCA multiplies dollar outcomes and dollar losses. "Refill to $50"
   passes the protocol but carries a worse left tail.
