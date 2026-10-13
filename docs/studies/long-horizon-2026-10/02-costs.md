# 02 — What one trade really costs (Zerodha delivery account)

Plan 0024, step 2. Built 2026-10-12. Code: `tools/lh_costs.py`. Numbers: `data/lh/costs.json`.
Prices up to 2026-10-09. Panel date 2026-10-09. Read-only: nothing in the DB, config or live book changed.

## The answer

One-way cost: the average of one buy and one sell. A round trip costs twice this. Each stock is costed at its own liquidity, and the table gives the tier median.

| Tier | Placeholder in `config.TIERS` | ₹50k trade | ₹1L trade | ₹2L trade | ₹1L, 1 in 10 stocks pays more than | ₹1L stress case (spread and impact ×2) |
|---|---|---|---|---|---|---|
| LARGE | 30 bps | **16.1 bps** | **15.7 bps** | **15.8 bps** | 17.3 bps | 19.5 bps |
| MID | 50 bps | **18.0 bps** | **17.9 bps** | **18.5 bps** | 23.3 bps | 24.0 bps |
| SMALL | 150 bps | **28.0 bps** | **30.5 bps** | **34.7 bps** | 66.5 bps | 49.1 bps |
| MICRO (not pickable) | none | 73.0 bps | 93.2 bps | 122.4 bps | 215.1 bps | 174.6 bps |

What this means in plain words:
- **The placeholders are too high.** At these trade sizes the real one-way cost is about half of the LARGE placeholder, about a third of MID's, and about a fifth of SMALL's. Even the stress case stays well below all three.
- **Fees are most of the bill for LARGE and MID.** About 12 of the 16–18 bps are fees, and 10 of those 12 are STT. No trading skill can reduce them. The only way to pay less is to trade less.
- **SMALL costs depend on the stock, not the tier.** A typical SMALL stock costs about 30 bps. The least liquid tenth costs 67 bps or more at ₹1L and 85 bps or more at ₹2L. For 23% of SMALL stocks a ₹1L trade is more than 1% of a day's trading.
- **What turnover costs.** The daily book trades about 189% of its value one way each month (plan 0024). At 30.5 bps per one-way trade in SMALL, that is roughly 2 × 22.7 × 30.5 bps ≈ 13.8% a year. The pass bar's 100% a year costs about 0.6% a year. *This is a rough illustration; step 3 runs the real simulation.*

The same numbers by liquidity, all tiers together. ADTV is the median daily traded value over 20 sessions.

| ADTV | Stocks | ₹50k | ₹1L | ₹2L |
|---|---|---|---|---|
| under ₹0.5 cr | 680 | 69.7 | 88.7 | 115.7 |
| ₹0.5–1 cr | 183 | 43.0 | 50.9 | 62.7 |
| ₹1–2 cr | 220 | 34.8 | 39.8 | 47.5 |
| ₹2–5 cr | 312 | 29.1 | 32.1 | 37.0 |
| ₹5–10 cr | 233 | 26.0 | 27.8 | 31.0 |
| ₹10–25 cr | 289 | 23.0 | 24.0 | 26.0 |
| ₹25–100 cr | 301 | 19.5 | 19.8 | 20.8 |
| ₹100–500 cr | 179 | 16.5 | 16.1 | 16.3 |
| over ₹500 cr | 19 | 15.3 | 14.7 | 14.5 |

## How the cost is built

**cost = fees + half the bid-ask spread + market impact.** Market impact is how far the price moves against you because of your own trade.

### 1. Fees (Zerodha charges page, read 2026-10-12)
| Charge | Rate | Side |
|---|---|---|
| Brokerage | ₹0 (delivery, individual account) | both |
| STT | 0.1% | buy and sell |
| NSE transaction charge | 0.00307% (BSE 0.00375%) | both |
| SEBI fee | ₹10 per crore | both |
| IPFT | ₹0.01 per crore (as quoted on the page; negligible) | both |
| GST | 18% on brokerage + transaction charge + SEBI fee | both |
| Stamp duty | 0.015% | buy only |
| DP charge | ₹15.34 per stock per day you sell, GST included (₹3.5 CDSL + ₹9.5 Zerodha + ₹2.34 GST) | sell only |

The task suggested about ₹15.93 for the DP charge. Zerodha's page says ₹15.34, so this study uses ₹15.34. Fees for one trade:

| Trade | Buy | Sell | One-way |
|---|---|---|---|
| ₹50k | 11.87 bps | 13.44 bps | 12.66 bps |
| ₹1L | 11.87 bps | 11.91 bps | 11.89 bps |
| ₹2L | 11.87 bps | 11.14 bps | 11.51 bps |

Tax (20% STCG, 12.5% LTCG) is not part of this model. The book simulation (H3) charges it separately.

### 2. Half the bid-ask spread, by liquidity
- **The panel's spread proxy is far too wide.** `bidask_spread_proxy` is the Corwin-Schultz estimate from daily highs and lows. It puts the median full spread at 49 bps for the most liquid stocks (over ₹500 cr ADTV) and 124 bps for the least liquid. Mostly it is measuring how much the price moves within a day, not the spread.
- **A better measure comes from the 1-minute bars in the Kite archive.** The Roll estimator measures how much the price bounces between the bid and the ask from one minute to the next. Using the last 20 sessions of minute bars, the median full spread comes out at 2.9 bps for stocks over ₹500 cr, 4.9 bps for ₹25–100 cr and 9.4 bps for ₹2–5 cr. This study covers 335 stocks with minute bars. The archive backfill is still running, and today it covers almost no stock under ₹2 cr ADTV.
- **How the two are combined.** A stock with minute bars uses its Roll spread. Every other stock uses its Corwin-Schultz value scaled by the bucket's Roll ÷ Corwin-Schultz ratio, which runs from 0.06 for liquid stocks to 0.10 for illiquid ones. A bucket with fewer than 10 Roll stocks borrows the nearest bucket's ratio, so every stock under ₹2 cr uses 0.10.
- **A third estimator was tried and dropped.** The Abdi-Ranaldo estimator, from daily close, high and low, moved the opposite way to Roll: correlation −0.24 across 331 stocks. It is not used.
- **Floor.** The half-spread is never less than half a price tick. The tick is assumed to be ₹0.01 below ₹250 and ₹0.05 above. The floor almost never binds.

### 3. Market impact
**impact = 1.0 × daily volatility × √(trade ÷ ADTV).** This is the standard square-root law. Daily volatility is the standard deviation of daily log returns over 60 sessions, leaving out moves of 20% or more (splits and bonuses in raw closes). The coefficient 1.0 is a literature value of about 1 and is not fitted here: today's fills were too small relative to ADTV to estimate it.

### 4. Earlier years
The backtest runs from 2019. `one_way_cost_bps(..., year=Y)` scales the spread and impact by each tier's median Corwin-Schultz value in year Y divided by its 2026 median:

| Tier | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|
| LARGE | 1.278 | 1.541 | 1.347 | 1.183 | 0.984 | 1.173 | 0.993 |
| MID | 1.347 | 1.492 | 1.385 | 1.197 | 1.063 | 1.226 | 1.075 |
| SMALL | 1.103 | 1.161 | 1.182 | 1.076 | 0.985 | 1.079 | 1.008 |

Corwin-Schultz mostly tracks volatility, which is why 2020 shows up as costly. Volatility drives impact too, so it is a fair stand-in. The 2019 figure rests on a single anchor (2019-12). Fees are held at today's rates: STT on delivery has been 0.1% the whole time, and the other charges changed by fractions of a basis point.

## Checked against the real sells of 2026-10-12

Sources, all read-only: Kite `trades()` and `orders()`, plus one `quote()` call that gave the day's VWAP, high, low and close for each stock. No order was placed, changed or cancelled.
- 25 completed sells were in our universe; one ETF (LIQUIDBEES) was left out. Total value was ₹11.0 L.
- 15 were market orders and 10 were limit orders.
- All were tiny next to daily trading: the largest was 0.5% of ADTV.
- The cost is (reference price − fill price) ÷ reference price for a sell, so a positive number means the sale cost us money.

| Measure | Median cost |
|---|---|
| vs the day's VWAP, all 25 | 11.3 bps (90% bootstrap range −6.8 to 21.0) |
| vs the day's VWAP, 15 market orders | 13.3 bps (model 4.0) |
| vs the day's VWAP, 10 limit orders | −12.1 bps (model 10.3) |
| vs the day's VWAP, weighted by value | 8.1 bps |
| vs (high + low + close) ÷ 3 | 11.3 bps |
| vs the day's close | −11.6 bps (prices fell after the sales) |
| **vs the last 1-minute close before the fill (6 liquid market orders)** | **1.7 bps (model 2.5)** |
| Model: half-spread + impact, all 25 | 7.4 bps |

How to read this:
- **The comparisons with the whole day are noisy.** One stock's cost ranges from −95 to +164 bps, mostly because prices moved during the day. The VWAP median of 11.3 bps cannot be told apart from the model's 7.4.
- **The cleanest measure agrees with the model.** The price one minute before each fill could be checked for 6 orders, all liquid market orders. The fills averaged 1.7 bps worse, against the model's 2.5.
- **The rule was set before looking.** It was: raise the spread when real fills look dearer than the model, never lower it, because one day of sells cannot prove trading is cheaper than the model. Following it, the spread is multiplied by **1.53** (11.3 ÷ 7.4). That leans towards higher costs. Every number above includes it.
- **Limit orders did better than VWAP.** Patient selling paid about nothing beyond fees on this day.

## What is weak, and what would fix it
1. **Illiquid stocks (under ₹2 cr ADTV) have no direct spread evidence.** Their spread is a ratio borrowed from more liquid stocks. The pickable SMALL median sits at ₹4.13 cr ADTV, where minute bars exist, but the least liquid tenth of SMALL, and MICRO, depend on the borrowed ratio. Use `stress=True`, which doubles spread and impact, as the sensitivity check for SMALL. *The fix is a single `kc.quote()` call during market hours, about five calls for the whole universe. It returns live best bid and ask, so it gives true quoted spreads for every stock. It was not done here because it was 01:45 IST, and the minute-bar backfill harvester was running, so more Kite history calls would have broken the one-harvester-at-a-time rule.*
2. **The fills are one day of sells only.** No buys, and the stamp duty side is not checked against fills. The impact coefficient comes from the literature and is not fitted.
3. **The minute-bar coverage changes as the backfill runs.** A rerun (`python -m tools.lh_costs --calibrate`) will pick up more SMALL stocks. The fills are saved in `data/lh/fills_2026-10-12.json`, so a rerun does not need Kite.
4. **These are costs at today's liquidity.** The year scale only roughly accounts for 2019–2022 being dearer.

## How to use it (H3 book simulation)
```python
from tools.lh_costs import one_way_cost_bps, cost_breakdown
one_way_cost_bps(adtv_inr, price, trade_value_inr, tier)                 # today's liquidity
one_way_cost_bps(adtv_inr, price, trade_value_inr, tier, year=2021)      # that year's spreads
one_way_cost_bps(adtv_inr, price, trade_value_inr, tier, stress=True)    # sensitivity case
one_way_cost_bps(None, price, trade_value_inr, "SMALL")                  # no ADTV → tier median
```
`side="buy"` or `side="sell"` gives each side's cost; the default is their average. ADTV is the 20-session median of `volume × close` (₹), because `stock_prices.traded_value` is empty. In a simulation, compute ADTV at each rebalance date from prices up to that date.
