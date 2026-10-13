# Long horizon, step 3 — how the long-hold book is built (H3 design brief) — 2026-10-12

Plan 0024, H3. Written before any book result exists. This note fixes the rules that the book simulator (`tools/lh_book.py`, step 4) must follow, so the variants cannot be tuned after the results come in. The pass bars are the plan's and are not moved here. Where the plan leaves a detail open, this note picks one and says why. Anything marked **assumption** is a modelling choice, not a measured number.

## Decisions in one screen
| # | Decision | Choice |
|---|---|---|
| 1 | Clock | Monthly anchors (`tools.backtest_pit._is_month_start_anchor`). Trades fill at the close of the first session after an anchor, the same entry as `pit.forward_returns`. Returns chain `fwd_next_anchor` from `data/lh/labels.parquet`. |
| 2 | Scores | Only the H2 walk-forward **out-of-sample** scores (step 2's output file). Never the live weights and never an in-sample fit. The simulation starts at the first anchor that has OOS scores. |
| 3 | Universe | The anchor's `cap_tier` in `daily_snapshots_pit`. MICRO and a NULL tier are never bought. Ranks are within the tier only. |
| 4 | Grid | 48 variants per tier: a 36-cell core plus a 12-cell min-hold block (below). Tax deferral is on in every variant. |
| 5 | Sizing | **Equal weight** at entry, then let the weights drift. Survivors are never trimmed or topped up. |
| 6 | Entry / exit | Buy from the top N. Hold while the rank ≤ k·N. Sell only below k·N, and only after the minimum hold, unless a red flag forces the sale. |
| 7 | Red flag | `forensic_penalty` ≤ −0.20 at the anchor (likely manipulator, distress zone, or both grey flags). The stock is sold at once, whatever the minimum hold or tax. It is never bought while flagged. |
| 8 | Tax deferral | A sale that would be short-term at a gain, and that would turn long-term within 42 calendar days, waits until the first anchor after it turns long-term. |
| 9 | Costs | `tools.lh_costs.one_way_cost_bps(adtv, price, trade_value, tier, side, year)` on every trade. The sensitivity run uses `stress=True` (spread and impact doubled). |
| 10 | Tax | Today's rules over the whole window: STCG 20 %, LTCG 12.5 % above ₹1.25 L per financial year, plus the 4 % cess (20.8 % / 13.0 %). Indian set-off rules, 8-year carry-forward. Dividends are taxed at 31.2 % (**assumption**: top slab plus cess, no surcharge). |
| 11 | Tax payment | A reserve is set aside from each sale's proceeds. The exact bill is settled on 31 March of each financial year from that reserve. Any shortfall is raised by selling, in the least-taxed order. |
| 12 | Capital | ₹10 lakh at the start, per tier book (**assumption**, close to the real 2026-10-12 sell list of about ₹11 lakh across 26 names). Sensitivity: ₹50 lakh. |
| 13 | Benchmark | The plan's tier index, bought once and held, taxed only when sold at the end. Dividends are added back (the NSE series are price indices). No fees in the main case. |
| 14 | Judging | Monthly change in **after-tax liquidation value**, strategy minus benchmark. Newey-West t with lag 3. Bonferroni haircut over the 48 variants. Every pass bar must hold on the same variant. |

## What the literature says (and what we take from it)
- **Buy/hold spread (banding).** Novy-Marx & Velikov (2016, *RFS*, "A Taxonomy of Anomalies and Their Trading Costs"): strategies that turn over more than about half the book a month rarely survive costs. Buying at a tight cut-off and holding until a wider one was the most effective simple fix they tested. → Our k·N exit band.
- **Trade partly toward the aim.** Gârleanu & Pedersen (2013, *JF*, "Dynamic Trading with Predictable Returns and Transaction Costs"): with trading costs, the best policy trades only part of the way toward an aim portfolio each period. That aim leans more on signals that decay slowly. → The band and the minimum hold are crude versions of "trade partially". The 3-month average score is the "lean on slow signals" part.
- **Costs change which factors to combine.** DeMiguel, Martín-Utrera, Nogales & Uppal (2020, *RFS*, "A Transaction-Cost Perspective on the Multitude of Firm Characteristics"): once costs count, combining many characteristics helps, because their trades partly cancel. Costs raise the number of characteristics worth using. → H2 builds one composite. We never run one book per factor.
- **The cost of a trade.** Frazzini, Israel & Moskowitz (2018, "Trading Costs"): real institutional costs are lower than many academic estimates, and price impact grows roughly with the square root of trade size relative to volume. → The impact term in `lh_costs`, calibrated on our 2026-10-12 fills.
- **IC decay and the horizon.** Qian, Hua & Sorensen (2007, *Quantitative Equity Portfolio Management*): a signal's IC at lagged dates sets how fast the book should trade. A slow-decaying signal can be traded less with little loss, and a signal should be judged at the horizon it is held. → Step 1 measured IC at 1 / 3 / 6 / 12 months. Step 2 fits on the 6-month label.
- **Smoothing the score.** This follows from the same two sources. A moving average of a persistent score keeps most of its IC and removes month-to-month noise, which is what turns into trades. → Score variant `avg3` = the mean of the last 3 monthly OOS scores.
- **1/N.** DeMiguel, Garlappi & Uppal (2009, *RFS*, "Optimal Versus Naive Diversification"): estimated weights rarely beat equal weights out of sample, because estimation error eats the gain. → Equal weight (decision 5).
- **Taxes and when to sell.** Constantinides (1983, *Econometrica*; 1984, *JFE*): defer gains, realise losses early, and sell short-term losers before they turn long-term when the rates differ. Berkin & Ye (2003, *FAJ*): loss harvesting adds measurable after-tax return. → The deferral rule (decision 8). Harvesting losses is **not** in the grid. The plan did not pre-register it, so it is reported only as an idea for later.
- **Many variants, one winner.** Harvey, Liu & Zhu (2016, *RFS*, "… and the Cross-Section of Expected Returns"): haircut a t-stat for the number of tries. Bailey & López de Prado (2014, *JPM*, "The Deflated Sharpe Ratio"): deflate the best Sharpe for the number and spread of the trials and for non-normal returns. → The judging section below.

## Indian tax rules used (listed shares, resident individual, STT paid)
- **Short-term:** held 12 months or less. Taxed at 20 % (Section 111A, rate since 23 July 2024; it was 15 % before).
- **Long-term:** held more than 12 months. Taxed at 12.5 % (Section 112A, since 23 July 2024; 10 % before), on the year's long-term gains above ₹1.25 lakh (₹1 lakh before FY 2024-25). Budget 2026 left both rates and the exemption unchanged. The section numbers are those of the 1961 Act, which the Income-tax Act 2025 replaced from 1 April 2026. The rates are what matter here.
- **Cess:** 4 % on the tax. Surcharge depends on total income and is capped at 15 % on these gains. It is ignored.
- **Set-off:** a short-term loss can absorb short-term or long-term gains. A long-term loss can absorb only long-term gains. Losses net within the year first. What is left carries forward 8 years, with the same rules, provided the return is filed on time. The ₹1.25 L exemption applies after set-off, to long-term gains only.
- **Dividends:** taxed as income at the slab rate since FY 2020-21.
- **The window rule:** the simulator applies **today's rules to every year**, as the plan specifies. The question is what this book earns from now on. The rules in force at the time (15 % / 10 % / ₹1 L before July 2024) are a sensitivity run.

## The simulation, step by step
**Inputs.** The H2 OOS score file `(sid, snapshot_date, cap_tier, score)`, with higher meaning better; whatever file step 2 writes is the source. Also `data/lh/labels.parquet` (`fwd_next_anchor`, `h_next_anchor`), `daily_snapshots_pit.forensic_penalty` and `cap_tier`, `stock_prices` (close, traded value, for ADTV and price), `corporate_adjustments` (dividend events) and `nse_index_history`. All DB reads use `mode=ro`.

**Period.** It runs from the first anchor with OOS scores in the tier to the last anchor with `fwd_next_anchor`. At the first anchor the book buys the top N with all its capital. That first build pays costs but does not count in turnover.

**Ranking at anchor t.** The signal is `s = score` (raw) or `s = mean(score at t, t−1, t−2)` (avg3, using the anchors that exist). Rank within the tier's members at t that have a score, with rank 1 the best. A held stock that has left the tier is placed by its percentile in its new tier. Its exit test becomes "percentile worse than k·N / (size of the old tier at t)". Flagged stocks are dropped from the buy list but keep their rank for the exit test.

**State of one position** (lots are tracked per buy): `buy_date`, `cost_basis_inr`, `qty_value` (marked to market each anchor), `age` = calendar days since `buy_date`, and `lt = (sell_date > buy_date + 1 year)`.

```
at each monthly anchor t (a quarterly variant runs steps 3-5 only at every 3rd anchor from its start;
steps 1-2 and 6 run every month):
 1. mark to market: value *= (1 + fwd_next_anchor of the previous month); book dividends (below)
 2. forced exits (every anchor): forensic_penalty <= -0.20  -> SELL now (no min-hold, no deferral)
                                 no price for 3 anchors running -> SELL at the last close, log it
 3. band exits: rank > k*N and age >= min_hold            -> candidate sell
 4. tax deferral on each candidate: if unrealised gain > 0 and not lt today
                                    and lt within 42 days  -> DEFER: re-test at every later anchor
                                    (a deferred name is sold at the first anchor where it is lt,
                                     still out of band and not a forced exit; back in band -> stays)
 5. buys: free = N - held; buy the best-ranked unheld, unflagged names in the top N, in rank order
    size each new buy = min(NAV/N, cash available / number of new buys)
 6. off-cycle (quarterly variants): a forced or deferred sale fills its slot at once from the top N
 7. leftover cash stays in cash at 0 % (conservative; report the average cash share)
```

- **Equal weight, no trimming.** Trimming a winner realises a short-term gain and pays costs twice a year for no evidence-backed reason. The book therefore drifts toward its winners, as a buy-and-hold investor's would. Score weighting is not in the grid for three reasons. The OOS IC is small, so the score says little about *how much* better rank 1 is than rank 10. Weights that move with the score force trades in names that are still held. And it would double the grid.
- **Dividends.** The labels are total returns: dividends are reinvested in the same stock through the adjusted close. The book keeps that. For tax, a position's dividend in a month = value × (1 − Π `factor`) over `corporate_adjustments` rows with `inds = 'DIVIDEND'` and an ex-date in (entry t−1, entry t]. Rows that mix a dividend with a split or bonus are skipped and counted. That dividend amount is taxed at 31.2 % at the financial-year end.
- **Costs.** Every buy and sell pays `one_way_cost_bps(adtv_inr, price, trade_value_inr, tier, side='buy'|'sell', year=t.year)` on its own rupee value. ADTV is the 20-session median traded value up to the anchor. The cost is taken out of the trade (a buy gets fewer shares; a sale gets lower proceeds).
- **Tax reserve and payment.** On each sale, gain = proceeds net of cost − cost basis (the buy cost is already in the basis). Short or long term is decided by the sale date against `buy_date`. The sale puts `max(gain, 0) × rate` into a reserve that is not reinvested. On 31 March (at the first anchor after it):
  1. net short-term and long-term gains and losses within the year;
  2. use the carried-forward losses (oldest first; long-term losses only against long-term gains);
  3. take the ₹1.25 L exemption off the long-term gains;
  4. tax = 20.8 % × short-term + 13.0 % × long-term + 31.2 % × dividends;
  5. pay the bill from the reserve and return any surplus to cash.

  If the reserve falls short, sell lots in this order until the bill is covered: losses first, then long-term lots with the lowest gain per rupee, then short-term lots with the lowest gain per rupee. The tax on those forced sales goes into next year's bill. Unused losses carry forward 8 years.
- **The benchmark.** The same ₹10 lakh buys the tier index once at the first anchor and holds it. No costs or fees in the main case, which makes the bar harder for the book. Dividends: the NSE series are price indices, while the stock labels include dividends. The benchmark is therefore credited each month with the tier's cap-weighted dividend yield. That yield comes from the same `corporate_adjustments` dividend rows over the tier's members, weighted by `signals._fundamentals.market_caps` at the anchor. Without this credit the excess return is overstated by roughly the index's dividend yield. The credit is reinvested untaxed, as it is inside a growth index fund.

  Indices: LARGE uses NIFTY 50. SMALL uses NIFTY SMALLCAP 250. MID uses NIFTY MIDCAP 150 from 2023-06, and before that, as the plan says, the tier's equal-weight average total return (from the labels), chained into one series. The benchmark is taxed only when it is sold at the end: long-term, 13.0 % on the gain above ₹1.25 L in that year.
- **Second benchmark, reported but not used for the pass.** The tier's equal-weight average total return, built from the same labels. It shares the book's survivorship bias, because the panel holds only today's listed firms. So it isolates selection skill better than an index that includes the firms that later failed. If the two benchmarks disagree, the note says so plainly.

**The end-date comparison.** At the last anchor, sell everything in both portfolios: the book pays its costs, the benchmark pays none. Settle the final year's tax with the rules above, including carried losses and that year's exemption. The headline is the **after-tax liquidation value** of each, and the gap between them as a CAGR. The mark-to-market value before any tax is reported beside it, together with the deferred tax that the strategy is carrying.

## How variants are judged
**Monthly series.** For each month, the after-tax liquidation value (ATLV) is the NAV, less what selling everything at that anchor would cost in charges and tax, less taxes still owed for the year. The pass test uses `x_t = r_ATLV,book − r_ATLV,bench`. The t-stat is the mean of x over its Newey-West standard error with lag 3, using the `tools/backtest_pit._newey_west_se` helper, and df = n − 1. Lag 3 absorbs the autocorrelation from the yearly tax settlement and the drifting tax provision.

**Haircut for 48 variants.** The primary test is Bonferroni, as in Harvey, Liu & Zhu (2016). Take the two-sided p of the best variant, multiply it by 48 (the variants tried in that tier), and convert back to a t. The tier passes only if the haircut t is ≥ 2.0. For orientation (normal p for t = 2 is 0.0455), the raw t needed is 3.52 at df = 48, 3.51 at df = 52 and 3.48 at df = 60 (3.31 with unlimited data). That is far above 2.0, and deliberately so. A second lens is reported but cannot overrule a Bonferroni fail: the deflated Sharpe ratio of Bailey & López de Prado (2014), on the best variant's monthly excess. It uses the Sharpe spread across the 48 variants, the skew and kurtosis of the returns, and N = 48 trials (an upper bound; the variants are highly correlated). Pass if DSR ≥ 0.95. Also reported: the grid's **median** variant t. A winner far above the median is fragile.

**All bars on one variant.** The t-test, plus:
- median holding ≥ 9 months, measured as the Kaplan-Meier median of position lifetimes, with positions still open at the end treated as censored. A median over closed positions alone would be biased short. Both are reported.
- one-way turnover ≤ 100 % a year = ½ × (buys + sells) ÷ average NAV, annualised. The initial build and the final sale are left out; sales to pay tax count. Amit's earlier rough target of about 25 % is reported beside it. It is not the pass bar, because the plan fixed 100 %.
- worst 12-month excess ≥ −15 %. This is the minimum over rolling 12-anchor windows of (1 + book ATLV return) / (1 + benchmark ATLV return) − 1.

## The variant grid (48 per tier)
- **Core, 36 cells:** rebalance {monthly, quarterly} × N {10, 15, 20} × k {2, 3, 4} × score {raw, avg3}. Every core cell uses a minimum hold of 6 months and tax deferral on.
- **Min-hold block, 12 cells:** minimum hold {0, 12 months} × rebalance {monthly, quarterly} × N {10, 15, 20}, with k = 3 and avg3.

The plan's full menu has 2 × 3 × 3 × 2 × 3 × 2 = 216 combinations, and its cap is 48. Two cuts, made before any result:
1. **Tax deferral is always on.** It only ever delays a sale of a winner by at most about 6 weeks, to cut the tax on that gain from 20.8 % to 13.0 %. Testing "off" would spend variants on a rule that is near-certainly helpful.
2. **The minimum hold is varied only around the middle setting (k = 3, avg3).** A minimum hold, a wide band, smoothing and a quarterly cadence all slow trading in the same way. The block checks whether a hold of 0 or 12 months changes the answer at the central setting.

These diagnostics are run **only on the winning variant** and are not eligible to pass: tax deferral off, stress costs (×2 spread and impact), ₹50 lakh capital, the tax rules in force at the time, and the benchmark with index-fund fees (an **assumption** of 0.2 % a year for NIFTY 50 and 0.3 % for the others; check against fund factsheets). The fast-signal timing overlay is tested separately, as the plan says, and never as membership.

## Things to log, so the verdict can be checked
For each variant: the number of trades, the forced (red-flag) exits, the deferred sales and how many of them became long-term, the share of the gain realised short-term versus long-term, the average cash share, the total tax paid, the carry-forward left at the end, the cost paid (bps a year), the skipped dividend rows, and any positions written off for lack of a price. Output: `data/lh/book_variants.csv` (one row per variant per tier) and `data/lh/book_monthly.parquet` (the ATLV series).

## Known limits (state them in the verdict)
- **Survivorship.** Fundamentals cover today's listed firms only. This flatters the book against a cap-weighted index. The equal-weight benchmark shares the bias.
- **A short window.** The OOS window starts after H2's 24 training anchors plus its embargo, so it is about four years. A 12-month minimum hold leaves few closed positions, which is why holding is measured with Kaplan-Meier.
- **Cash at 0 %** and **tax paid on 31 March** (instead of quarterly advance tax) are small biases in opposite directions.
- **The rank band at the edges.** With LARGE (100 names) and N = 20, k = 4 puts the exit at rank 80, so the book almost never sells. That is a valid variant, but its result there is close to buy-and-hold.

## Sources for the tax rules
- [5paisa — evolution of LTCG and STCG tax in India](https://www.5paisa.com/blog/evolution-of-ltcg-stcg-tax-in-india)
- [Bajaj Finserv — LTCG tax rate after Budget 2026](https://www.bajajfinserv.in/what-is-ltcg-tax-rate)
- [Motilal Oswal — Budget 2026 expectations on capital gains](https://www.motilaloswal.com/learning-centre/2026/1/pre-budget-2026-expectations-on-capital-gains-tax-for-equity-and-mutual-funds)
