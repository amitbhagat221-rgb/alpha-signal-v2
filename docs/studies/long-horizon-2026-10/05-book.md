# Long horizon, step 4 — does a long-hold book earn after costs and Indian tax? (H3) — 2026-10-12

Plan 0024, H3. Read-only on the DB. Tool: `python -m tools.lh_book` (under a minute, including a 17-second read-only load). It follows the rules fixed in `03-design.md` before any result. The plan's pass bars are not moved. Machine-readable: `data/lh/book_results.json`, one row per run in `data/lh/book_variants.csv`, and the monthly after-tax values of every run in `data/lh/book_monthly.parquet`.

## Verdict
**H3 fails in all three tiers. No variant clears the plan's bar, so by the plan's rule each tier is the index.**

| tier | verdict | variants run | best variant (slow_select) | excess after tax, %/yr | t (Newey-West) | t after the 48-variant haircut | median hold | one-way turnover | worst 12-month excess |
|---|---|---|---|---|---|---|---|---|---|
| LARGE | **fail** | 48 | quarterly · top 20 · exit below 80 · raw score · 6-month hold | +7.05 | 1.26 | 0.00 | 27.0 months | 26 %/yr | −13.4 % |
| MID | **fail** | 48 | monthly · top 15 · exit below 45 · raw score · 6-month hold | +5.17 | 1.44 | 0.00 | 10.1 months | 72 %/yr | −6.2 % |
| SMALL | **fail** | 48 | monthly · top 10 · exit below 30 · 3-month average score · 12-month hold | +18.30 | 1.81 | 0.00 | 12.9 months | 88 %/yr | −12.2 % |

*Excess = the book's after-tax CAGR minus the benchmark's, both sold at the end. Window: 52 months, 2022-06-02 → 2026-10-05 (trade dates). ₹10 lakh per book. A tier passes only if one variant has a haircut t ≥ 2.0, a median hold ≥ 9 months, one-way turnover ≤ 100 %/yr and a worst 12-month excess ≥ −15 %.*

What this means, in plain words:

1. **The books were run 144 times (48 per tier), and none came close to the t bar after the haircut.** For 48 tries the raw t has to be about 3.5 before the haircut leaves 2.0. The highest raw t anywhere in the grid was 2.61 (SMALL, monthly, top 20, exit below 40, 3-month average, 6-month hold). Its haircut t is 0.57, and it also fails the holding bar (median 6.0 months) and the turnover bar (158 %/yr). The best variant that meets the other three bars has t 1.81 in SMALL. That is below 2.0 even before any haircut.
2. **SMALL looks good but is not proven.** 47 of its 48 variants beat the Smallcap 250 after costs and tax. The grid's median is +9.8 %/yr with a median t of 1.35. The best variant that meets the holding, turnover and drawdown bars returned 35.1 % a year after tax, against 16.8 % for the index. The return is large, but it swings so much from month to month that 52 months cannot separate it from luck at the bar the plan set. Three things make it weaker than it looks:
   - **Survivorship.** The fundamentals cover only stocks that are still listed today. Against the tier's own equal-weight average, which shares that bias, the same book's excess drops to +15.0 %/yr (t 1.57).
   - **Not every year.** The book lost to the index in 2023 (−2.4 %).
   - **Fast is no better.** The other score sets on the same rule did worse: `slow_icw` +3.6 %/yr, `blend` −0.6 %, `fast_select` +4.0 %, and `live` +9.5 % (t 1.30), even though `live` was chosen on this history.
3. **MID: nothing reliable.** The grid's median excess is −0.3 %/yr (t 0.03), and 21 of 48 variants beat the benchmark. H2 had warned that MID's out-of-sample skill sits at the bottom of the ranking, not the top. The best MID variant, +5.2 %/yr, is the kind of result you get by picking the best of 48 tries.
4. **LARGE: as expected.** The best variant, +7.05 %/yr (t 1.26), comes from a 20-name book that almost never sells: its exit is at rank 80 of 100. That is close to holding the index's top half. The grid's median t is 0.49.
5. **Long holding works mechanically.** The variants with a 12-month minimum hold do what they are meant to:
   - SMALL's best hold has a median of 12.9 months, 98 % of its realised gains were long-term, and costs were 105 bps a year.
   - All 21 sales that were deferred for tax turned long-term before they were sold.
   - Turnover falls from 676 %/yr for the status-quo 5-in / 8-out band to 88 %/yr.

   So the long-hold machinery is sound. The model's edge is what is not proven.

**The status quo is far worse on cost and tax.** The status-quo row runs today's band on the same out-of-sample scores: buy the top 5, sell below rank 8, every month, with no minimum hold and no tax deferral. Its one-way turnover is 305–921 %/yr. Its realised gains are almost all short-term (0 % long-term in five of the six rows; MID `slow_select` 24 %). In SMALL (`slow_select`) it paid ₹6.64 lakh in costs on a ₹10 lakh book over 4.3 years. Even this monthly version turns over far less than the real daily band, which turned over about 189 % *a month* (2026-07-06 → 2026-10-12, plan 0024).

## The best variant per tier, in full
| | LARGE | MID | SMALL |
|---|---|---|---|
| rule | Q · N20 · k4 · raw · hold 6 | M · N15 · k3 · raw · hold 6 | M · N10 · k3 · avg3 · hold 12 |
| CAGR pre-tax (no tax at all, same rules) | 16.85 % | 25.21 % | 39.50 % |
| CAGR after tax (sold at the end) | 15.20 % | 22.19 % | 35.10 % |
| benchmark | NIFTY 50 + dividends | Midcap: tier equal-weight to 2023-05, then NIFTY MIDCAP 150 + dividends | NIFTY SMALLCAP 250 + dividends |
| benchmark CAGR pre-tax / after tax | 8.88 % / 8.15 % | 18.71 % / 17.02 % | 18.47 % / 16.79 % |
| excess after tax, CAGR gap / mean monthly × 12 | +7.05 % / +7.17 % | +5.17 % / +4.81 % | +18.30 % / +16.71 % |
| excess pre-tax (CAGR gap) | +7.96 % | +6.50 % | +21.03 % |
| t (NW lag 3, 52 months) / haircut t (×48) | 1.26 / 0.00 | 1.44 / 0.00 | 1.81 / 0.00 |
| deflated Sharpe (pass ≥ 0.95) | 0.66 | 0.59 | 0.85 |
| vs the tier equal-weight average: excess (t) | +2.66 % (0.80) | +4.23 % (1.31) | +15.04 % (1.57) |
| median hold, Kaplan-Meier / closed positions only / mean of closed | 27.0 / 14.0 / 15.9 months | 10.1 / 8.0 / 11.4 months | 12.9 / 12.9 / 12.6 months |
| one-way turnover | 26 %/yr | 72 %/yr | 88 %/yr |
| worst 12-month excess / max drawdown (after-tax value) | −13.4 % / −21.6 % | −6.2 % / −18.9 % | −12.2 % / −26.7 % |
| tax paid / costs paid (₹) | 1,09,616 / 10,027 | 2,19,124 / 27,884 | 3,56,706 / 99,213 |
| costs, bps of the book a year | 15.2 | 35.3 | 105.4 |
| long-term share of realised gains | 92 % | 65 % | 98 % |
| positions (closed) / red-flag sales / tax deferrals (all turned long-term) | 44 (24) / 0 / 3 | 65 (50) / 0 / 4 | 47 (37) / 0 / 21 |
| average cash | 3.8 % | 3.1 % | 6.5 % |
| final after-tax value, book / benchmark (₹) | 18,48,509 / 14,05,204 | 23,87,309 / 19,78,541 | 36,92,328 / 19,62,254 |

**Year by year (after-tax value, book vs benchmark):**
- **LARGE:** 2022 (Jun–Dec) +3.2 %, 2023 −2.8 %, 2024 +14.3 %, 2025 +1.3 %, 2026 (Jan–Oct) +13.3 %.
- **MID:** +3.0 %, −0.1 %, +13.3 %, −5.3 %, +9.4 %.
- **SMALL:** +19.3 %, −2.4 %, +17.4 %, +12.4 %, +22.5 %.

**Checks on the best variant.** None of these can pass the tier. All are in the tables below.
- **Tax deferral off:** SMALL's excess falls to +15.2 %/yr and its long-term share from 98 % to 36 %. Deferral is worth about 3 points a year after tax there.
- **Stress costs** (spread and impact doubled): SMALL +17.5 %/yr, with costs ₹1.71 L instead of ₹0.99 L.
- **₹50 lakh book:** SMALL +17.2 %/yr.
- **Tax rules in force at the time:** SMALL +18.4 %/yr.
- **Benchmark charged an index-fund fee:** SMALL +18.6 %/yr.
- **No check moves any tier's t near 2.0.**

## Other score sets on the best rule (comparison, not eligible to pass; haircut over 52 tries)
| tier | slow_select (the grid) | slow_icw | blend | fast_select | live (in-sample) |
|---|---|---|---|---|---|
| LARGE | +7.05 % (t 1.26) | +9.12 % (1.20) | +1.73 % (0.46) | +1.50 % (0.37) | +9.11 % (1.68) |
| MID | +5.17 % (1.44) | +4.18 % (0.78) | +0.12 % (0.10) | +2.02 % (0.35) | +10.46 % (2.13) |
| SMALL | +18.30 % (1.81) | +3.58 % (0.73) | −0.55 % (0.07) | +3.97 % (0.55) | +9.52 % (1.30) |

*Excess after tax, %/yr, with the raw t.*

Fast signals do not help a long-hold book. `blend` and `fast_select` are the weakest in every tier. MID `live` reaches t 2.13 on the same rule. Its weights were chosen on this history, and it turns over 103 %/yr with a median hold of 8.1 months, so it would fail two other bars anyway.

## How the grid behaved (medians over the 48 variants)
| tier | median t | median excess %/yr | variants with excess > 0 | median turnover | variants meeting hold + turnover + worst-12m |
|---|---|---|---|---|---|
| LARGE | 0.49 | +2.4 | 36 / 48 | 75 %/yr | 3 |
| MID | 0.03 | −0.3 | 21 / 48 | 59 %/yr | 41 |
| SMALL | 1.35 | +9.8 | 47 / 48 | 155 %/yr | 6 |

- **Holding.** In SMALL, a 6-month hold is not enough: with the 6-month minimum, the median position is sold the day the minimum ends (Kaplan-Meier median 6.0 months), and turnover is 124–176 %/yr. Only the six variants with a 12-month hold meet the holding and turnover bars.
- **The 3-month average score helps in LARGE and SMALL** (median t 0.62 vs −0.02 and 1.50 vs 0.93) and cuts turnover, as the literature expects. In MID the raw score is slightly better (0.27 vs −0.02).
- **Monthly beats quarterly in SMALL** (median t 1.56 vs 1.07). Quarterly beats monthly in LARGE (0.62 vs 0.32).

## Method (what was simulated)
- **Clock.**
  - 53 monthly anchors, 2022-06-01 → 2026-10-01: the H2 out-of-sample window.
  - Trades fill at the entry of `pit.forward_returns`, the close of the first session after the anchor: 2022-06-02 → 2026-10-05.
  - Positions are marked month to month by `fwd_next_anchor`, adjusted closes, dividends reinvested.
  - 52 monthly returns.
- **Scores.** `data/lh/oos_scores.parquet`: `slow_select` for the grid, the others for comparison. Ranks are within the tier at each anchor. `avg3` is the mean of the last three monthly scores; a stock needs a score this month. A held stock that has moved tier keeps its band test as a percentile of its new tier, against k·N ÷ the size of its home tier. A held stock with no score (for example one moved to MICRO) counts as outside the band; there were 3 such exits in SMALL's best variant.
- **Rules.**
  - Equal weight at entry; no trimming; leftover cash earns 0 %.
  - Buy only from the top N, only names with a 20-session traded value, never a flagged name.
  - Red flag: `forensic_penalty` ≤ −0.20 in the panel at the anchor, which forces a sale at once.
  - Minimum hold counted in anchors.
  - Tax deferral: a sale at a short-term gain that turns long-term within 42 days waits; it is re-tested every month, also in quarterly variants.
  - Quarterly variants refill a forced or deferred sale's slot at once.
- **Costs.** `tools.lh_costs.one_way_cost_bps`, buy or sell side, that year's liquidity scale, on each trade's rupee value. ADTV is the median of volume × close over the 20 sessions up to the anchor. **Note for `lh_costs`:** `stock_prices.traded_value` is in ₹ lakh where it is filled (from 2022-07) and NULL elsewhere. Using it as rupees made ADTV about 100,000× too small and costs absurd in the first run of this tool. `lh_costs.stock_liquidity` falls back to volume × close only when `traded_value` is NULL, which it is at 2026-10. Its calibration date is therefore unaffected, but any historical call that reads `traded_value` would be.
- **Tax** (today's rules in every year):
  - STCG 20.8 %, LTCG 13.0 % above ₹1.25 L a year, dividends 31.2 % (rates include the 4 % cess).
  - Within-year set-off: short-term losses against either kind of gain, long-term losses against long-term gains only.
  - Losses carry forward 8 years, oldest first.
  - A reserve is held from each sale. The bill is paid at the first anchor after 31 March; a shortfall is raised by selling losses first, then long-term lots, then short-term lots.
  - Dividends for tax: `corporate_adjustments` rows with `inds = 'DIVIDEND'`. 9 rows mixing a dividend with a split or bonus were skipped.
- **Benchmark.**
  - The index is bought once and held, with no fees in the main case.
  - It is credited each month with the tier's cap-weighted dividend yield: 0.126 %/month for LARGE, 0.084 % for MID and 0.071 % for SMALL. The cap weights approximate the market cap at each anchor as today's `stocks.market_cap_cr` × (close then ÷ close now) × later split and bonus factors. They are used only to weight that credit.
  - MID uses the tier equal-weight average for its first 12 months (to 2023-06) and NIFTY MIDCAP 150 for the last 40.
  - The benchmark is taxed only on the final sale (long-term, above ₹1.25 L).
  - A second benchmark, reported but not used for the pass, is the tier equal-weight average from the labels. It shares the book's survivorship bias.
- **Judging.**
  - x = monthly change in after-tax liquidation value, book minus benchmark. After-tax liquidation value = cash + sale proceeds after costs − the tax owed this year if everything were sold now.
  - Newey-West t with lag 3 (`tools.backtest_pit._newey_west_se`), df 51.
  - Bonferroni: two-sided p × 48, converted back to a t.
  - Median hold is Kaplan-Meier, with positions still open at the end treated as censored. Where the curve never falls to 0.5 it is shown as "> the longest lifetime".
  - Turnover = ½ × (buys + sells) ÷ average book value, per year. The first build and the final sale are left out; sales to pay tax count.
  - Worst 12-month excess = the minimum over rolling 12-anchor windows of (1 + book) ÷ (1 + benchmark) − 1, on after-tax value.
- **"Best variant" rule (fixed before the run).** The highest raw t among the variants that meet the hold, turnover and worst-12-month bars, or the highest t overall if none do. The comparisons and checks below use that rule.
- **Pre-tax CAGR** = the same rules run with every tax rate set to zero.
- **Check of the engine.** With costs and tax switched off and a pure monthly top-10 book (k = 1, no hold), the simulator ended at 3.62× in SMALL. Re-buying the top 10 in equal weight each month by hand gave 3.64×; the gap is weight drift, since the simulator does not trim. In LARGE the two were 1.55× and 1.65×.

## Limits
- **Survivorship** (as in H1/H2): the fundamentals hold today's listed firms only. This flatters every book against a cap-weighted index. The equal-weight benchmark shares the bias, and against it SMALL's best excess is +15.0 %/yr (t 1.57).
- **One short window:** 52 months, and the 2020 crash never falls in a test month. A 12-month minimum hold leaves about 4 independent holding periods.
- **Cash at 0 % and tax paid on 31 March** (instead of advance tax) are small biases in opposite directions.
- **Approximations:** the "historical" tax check applies the old rates to FY 2022-23 and 2023-24 and today's from FY 2024-25 (sales from April to July 2024 were really at the old rates). The dividend credit's cap weights are approximate.
- **The status quo here is monthly.** The real book is daily, and the monthly 5/8 band understates its turnover.

## Full grid and tables
Rule codes: M/Q = monthly or quarterly rebalance; N = names bought; k = exit below rank k·N; raw/avg3 = score or its 3-month average; hold = minimum hold in months. `nodefer` = no tax deferral. Bars: t = haircut t ≥ 2; hold = median ≥ 9 months; turn = turnover ≤ 100 %/yr; w12 = worst 12-month excess ≥ −15 %. Tax and costs are in ₹ lakh on a ₹10 lakh start.

### Comparison: other score sets on the best rule — LARGE

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| slow_icw · Q · N20 · k4 · raw · hold6 | 19.3 | 17.3 | +9.1 | 1.20 | 0.00 | +4.7 (1.05) | >52 | 10 | -14.6 | -22.5 | 1.48 | 0.07 | 99 | fail: t |
| blend · Q · N20 · k4 · raw · hold6 | 11.4 | 9.9 | +1.7 | 0.46 | 0.00 | -2.7 (-0.62) | 23.9 | 30 | -14.2 | -20.4 | 0.89 | 0.10 | 87 | fail: t |
| fast_select · Q · N20 · k4 · raw · hold6 | 10.9 | 9.7 | +1.5 | 0.37 | 0.00 | -2.9 (-0.57) | 24.1 | 30 | -18.0 | -21.2 | 0.72 | 0.10 | 90 | fail: t,w12 |
| live · Q · N20 · k4 · raw · hold6 | 19.2 | 17.3 | +9.1 | 1.68 | 0.00 | +4.7 (1.50) | 23.9 | 33 | -10.2 | -20.0 | 1.26 | 0.13 | 95 | fail: t |

### Comparison: other score sets on the best rule — MID

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| slow_icw · M · N15 · k3 · raw · hold6 | 24.0 | 21.2 | +4.2 | 0.78 | 0.00 | +3.2 (0.67) | 9.1 | 75 | -18.2 | -30.4 | 1.75 | 0.31 | 80 | fail: t,w12 |
| blend · M · N15 · k3 · raw · hold6 | 20.4 | 17.1 | +0.1 | 0.10 | 0.00 | -0.8 (-0.14) | 6.1 | 127 | -13.8 | -21.5 | 1.90 | 0.37 | 27 | fail: t,hold,turn |
| fast_select · M · N15 · k3 · raw · hold6 | 23.9 | 19.0 | +2.0 | 0.35 | 0.00 | +1.1 (0.15) | 7.0 | 145 | -13.4 | -19.0 | 2.74 | 0.41 | 14 | fail: t,hold,turn |
| live · M · N15 · k3 · raw · hold6 | 31.3 | 27.5 | +10.5 | 2.13 | 0.00 | +9.5 (1.90) | 8.1 | 103 | -8.9 | -16.4 | 2.73 | 0.38 | 61 | fail: t,hold,turn |

### Comparison: other score sets on the best rule — SMALL

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| slow_icw · M · N10 · k3 · avg3 · hold12 | 22.4 | 20.4 | +3.6 | 0.73 | 0.00 | +0.3 (0.42) | 12.1 | 83 | -24.8 | -41.1 | 1.89 | 0.92 | 90 | fail: t,w12 |
| blend · M · N10 · k3 · avg3 · hold12 | 18.1 | 16.2 | -0.5 | 0.07 | 0.00 | -3.8 (-0.45) | 12.9 | 95 | -19.3 | -32.4 | 1.08 | 0.55 | 96 | fail: t,w12 |
| fast_select · M · N10 · k3 · avg3 · hold12 | 23.4 | 20.8 | +4.0 | 0.55 | 0.00 | +0.7 (0.07) | 12.9 | 98 | -23.6 | -23.5 | 1.61 | 0.60 | 87 | fail: t,w12 |
| live · M · N10 · k3 · avg3 · hold12 | 28.9 | 26.3 | +9.5 | 1.30 | 0.00 | +6.2 (0.89) | 12.1 | 94 | -9.7 | -27.4 | 2.16 | 0.79 | 91 | fail: t |

### Status quo (monthly 5-in / 8-out, no hold, no deferral) — LARGE

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| slow_select · M · N5 · k1.6 · raw · hold0 · nodefer | 3.9 | 1.9 | -6.2 | -0.75 | 0.00 | -10.6 (-1.73) | 1.9 | 522 | -28.1 | -27.2 | 0.90 | 0.86 | 0 | fail: t,hold,turn,w12 |
| live · M · N5 · k1.6 · raw · hold0 · nodefer | 22.2 | 16.8 | +8.6 | 1.33 | 0.00 | +4.2 (0.94) | 1.9 | 547 | -12.6 | -19.7 | 3.65 | 1.46 | 0 | fail: t,hold,turn |

### Status quo (monthly 5-in / 8-out, no hold, no deferral) — MID

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| slow_select · M · N5 · k1.6 · raw · hold0 · nodefer | 15.4 | 12.8 | -4.2 | -0.65 | 0.00 | -5.1 (-0.81) | 2.0 | 305 | -21.8 | -29.3 | 1.59 | 0.90 | 24 | fail: t,hold,turn,w12 |
| live · M · N5 · k1.6 · raw · hold0 · nodefer | 33.9 | 26.1 | +9.1 | 1.32 | 0.00 | +8.2 (1.17) | 2.0 | 501 | -19.8 | -26.3 | 4.77 | 1.64 | 0 | fail: t,hold,turn,w12 |

### Status quo (monthly 5-in / 8-out, no hold, no deferral) — SMALL

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| slow_select · M · N5 · k1.6 · raw · hold0 · nodefer | 36.5 | 29.1 | +12.3 | 1.70 | 0.00 | +9.1 (1.24) | 1.1 | 676 | -14.6 | -21.6 | 5.73 | 6.64 | 0 | fail: t,hold,turn |
| live · M · N5 · k1.6 · raw · hold0 · nodefer | 29.2 | 23.6 | +6.8 | 0.71 | 0.00 | +3.6 (0.38) | 1.0 | 921 | -28.6 | -38.0 | 4.06 | 6.03 | 0 | fail: t,hold,turn,w12 |

### Checks on the best variant — LARGE

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| slow_select · Q · N20 · k4 · raw · hold6 · nodefer | 16.3 | 14.6 | +6.4 | 1.15 | 0.00 | +2.1 (0.67) | 21.1 | 30 | -13.6 | -21.6 | 1.09 | 0.11 | 88 | fail: t |
| slow_select · Q · N20 · k4 · raw · hold6 · stress=True | 16.8 | 15.2 | +7.0 | 1.26 | 0.00 | +2.6 (0.79) | 27.0 | 26 | -13.4 | -21.6 | 1.09 | 0.13 | 92 | fail: t |
| slow_select · Q · N20 · k4 · raw · hold6 · capital=5000000.0 | 16.8 | 14.6 | +6.7 | 1.21 | 0.00 | +2.3 (0.71) | 27.0 | 26 | -13.5 | -21.6 | 7.53 | 0.51 | 92 | fail: t |
| slow_select · Q · N20 · k4 · raw · hold6 · tax=historical | 16.9 | 15.2 | +7.1 | 1.25 | 0.00 | +2.7 (0.80) | 27.0 | 26 | -14.0 | -22.2 | 1.10 | 0.10 | 92 | fail: t |
| slow_select · Q · N20 · k4 · raw · hold6 · bench_fee=0.002 | 16.9 | 15.2 | +7.2 | 1.29 | 0.00 | +2.7 (0.80) | 27.0 | 26 | -13.3 | -21.6 | 1.10 | 0.10 | 92 | fail: t |

### Checks on the best variant — MID

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| slow_select · M · N15 · k3 · raw · hold6 · nodefer | 23.1 | 19.8 | +2.8 | 0.72 | 0.00 | +1.9 (0.53) | 10.0 | 73 | -10.4 | -18.6 | 2.06 | 0.27 | 52 | fail: t |
| slow_select · M · N15 · k3 · raw · hold6 · stress=True | 25.0 | 22.0 | +5.0 | 1.40 | 0.00 | +4.1 (1.27) | 10.1 | 72 | -6.3 | -18.9 | 2.17 | 0.38 | 65 | fail: t |
| slow_select · M · N15 · k3 · raw · hold6 · capital=5000000.0 | 25.1 | 21.5 | +4.7 | 1.32 | 0.00 | +3.7 (1.16) | 10.1 | 72 | -6.9 | -19.0 | 13.29 | 1.61 | 65 | fail: t |
| slow_select · M · N15 · k3 · raw · hold6 · tax=historical | 25.2 | 22.4 | +5.4 | 1.47 | 0.00 | +4.5 (1.34) | 10.1 | 72 | -6.2 | -18.8 | 2.08 | 0.28 | 65 | fail: t |
| slow_select · M · N15 · k3 · raw · hold6 · bench_fee=0.003 | 25.2 | 22.2 | +5.5 | 1.52 | 0.00 | +4.2 (1.31) | 10.1 | 72 | -5.9 | -18.9 | 2.19 | 0.28 | 65 | fail: t |

### Checks on the best variant — SMALL

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| slow_select · M · N10 · k3 · avg3 · hold12 · nodefer | 38.7 | 32.0 | +15.2 | 1.53 | 0.00 | +11.9 (1.17) | 12.0 | 87 | -20.3 | -25.0 | 4.90 | 0.91 | 36 | fail: t,w12 |
| slow_select · M · N10 · k3 · avg3 · hold12 · stress=True | 38.6 | 34.3 | +17.5 | 1.76 | 0.00 | +14.2 (1.50) | 12.9 | 88 | -12.6 | -26.7 | 3.44 | 1.71 | 99 | fail: t |
| slow_select · M · N10 · k3 · avg3 · hold12 · capital=5000000.0 | 38.6 | 33.8 | +17.2 | 1.75 | 0.00 | +13.9 (1.48) | 12.9 | 88 | -12.3 | -26.7 | 19.66 | 8.34 | 99 | fail: t |
| slow_select · M · N10 · k3 · avg3 · hold12 · tax=historical | 39.5 | 35.2 | +18.4 | 1.77 | 0.00 | +15.2 (1.54) | 12.9 | 88 | -12.7 | -26.6 | 3.55 | 1.00 | 98 | fail: t |
| slow_select · M · N10 · k3 · avg3 · hold12 · bench_fee=0.003 | 39.5 | 35.1 | +18.6 | 1.84 | 0.00 | +15.0 (1.57) | 12.9 | 88 | -11.9 | -26.7 | 3.57 | 0.99 | 98 | fail: t |

### The 48-variant grid — LARGE

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M · N10 · k2 · avg3 · hold6 | 16.1 | 13.3 | +5.1 | 0.73 | 0.00 | +0.8 (0.29) | 7.0 | 126 | -27.1 | -30.5 | 1.58 | 0.28 | 24 | fail: t,hold,turn,w12 |
| M · N10 · k2 · raw · hold6 | 8.1 | 6.3 | -1.8 | -0.07 | 0.00 | -6.2 (-0.94) | 6.0 | 157 | -24.2 | -30.3 | 1.03 | 0.30 | 6 | fail: t,hold,turn,w12 |
| M · N10 · k3 · avg3 · hold6 | 12.5 | 10.8 | +2.6 | 0.51 | 0.00 | -1.8 (-0.08) | 7.1 | 93 | -23.1 | -29.1 | 0.89 | 0.22 | 53 | fail: t,hold,w12 |
| M · N10 · k3 · raw · hold6 | 7.9 | 6.6 | -1.6 | -0.02 | 0.00 | -6.0 (-0.84) | 6.0 | 134 | -25.4 | -30.4 | 0.70 | 0.26 | 28 | fail: t,hold,turn,w12 |
| M · N10 · k4 · avg3 · hold6 | 10.7 | 8.9 | +0.8 | 0.25 | 0.00 | -3.6 (-0.60) | 10.1 | 75 | -20.0 | -26.7 | 0.85 | 0.17 | 50 | fail: t,w12 |
| M · N10 · k4 · raw · hold6 | 6.5 | 5.4 | -2.7 | -0.15 | 0.00 | -7.1 (-0.99) | 7.0 | 109 | -27.3 | -30.4 | 0.48 | 0.22 | 42 | fail: t,hold,turn,w12 |
| M · N15 · k2 · avg3 · hold6 | 11.3 | 9.4 | +1.3 | 0.33 | 0.00 | -3.1 (-0.42) | 7.1 | 103 | -24.5 | -27.3 | 0.89 | 0.22 | 40 | fail: t,hold,turn,w12 |
| M · N15 · k2 · raw · hold6 | 5.1 | 4.1 | -4.1 | -0.43 | 0.00 | -8.4 (-1.58) | 6.0 | 140 | -23.9 | -28.0 | 0.47 | 0.27 | 25 | fail: t,hold,turn,w12 |
| M · N15 · k3 · avg3 · hold6 | 10.1 | 9.1 | +0.9 | 0.29 | 0.00 | -3.5 (-0.51) | 10.0 | 72 | -23.2 | -28.0 | 0.50 | 0.17 | 64 | fail: t,w12 |
| M · N15 · k3 · raw · hold6 | 6.8 | 5.7 | -2.5 | -0.23 | 0.00 | -6.9 (-1.23) | 7.1 | 101 | -24.3 | -27.8 | 0.54 | 0.21 | 42 | fail: t,hold,turn,w12 |
| M · N15 · k4 · avg3 · hold6 | 11.0 | 10.0 | +1.8 | 0.39 | 0.00 | -2.6 (-0.33) | 13.0 | 54 | -23.4 | -28.2 | 0.51 | 0.14 | 78 | fail: t,w12 |
| M · N15 · k4 · raw · hold6 | 8.2 | 7.3 | -0.8 | 0.02 | 0.00 | -5.2 (-0.95) | 10.0 | 75 | -22.9 | -27.4 | 0.43 | 0.17 | 62 | fail: t,w12 |
| M · N20 · k2 · avg3 · hold6 | 12.0 | 10.5 | +2.4 | 0.51 | 0.00 | -2.0 (-0.38) | 8.1 | 96 | -17.7 | -21.6 | 0.74 | 0.22 | 53 | fail: t,hold,w12 |
| M · N20 · k2 · raw · hold6 | 8.6 | 7.0 | -1.2 | -0.07 | 0.00 | -5.6 (-1.40) | 6.9 | 122 | -18.5 | -21.6 | 0.84 | 0.26 | 23 | fail: t,hold,turn,w12 |
| M · N20 · k3 · avg3 · hold6 | 12.8 | 11.2 | +3.0 | 0.61 | 0.00 | -1.4 (-0.19) | 13.0 | 57 | -18.9 | -22.6 | 0.70 | 0.15 | 75 | fail: t,w12 |
| M · N20 · k3 · raw · hold6 | 8.5 | 7.3 | -0.8 | -0.04 | 0.00 | -5.2 (-1.35) | 9.1 | 79 | -18.0 | -21.5 | 0.55 | 0.18 | 56 | fail: t,w12 |
| M · N20 · k4 · avg3 · hold6 | 14.4 | 12.8 | +4.7 | 0.84 | 0.00 | +0.3 (0.19) | 33.0 | 26 | -16.0 | -21.4 | 0.91 | 0.10 | 90 | fail: t,w12 |
| M · N20 · k4 · raw · hold6 | 12.7 | 11.3 | +3.2 | 0.65 | 0.00 | -1.2 (-0.22) | 18.1 | 34 | -15.6 | -21.6 | 0.78 | 0.11 | 85 | fail: t,w12 |
| Q · N10 · k2 · avg3 · hold6 | 13.3 | 11.2 | +3.0 | 0.54 | 0.00 | -1.3 (-0.03) | 6.0 | 118 | -24.3 | -30.5 | 1.04 | 0.27 | 35 | fail: t,hold,turn,w12 |
| Q · N10 · k2 · raw · hold6 | 7.0 | 5.9 | -2.3 | -0.13 | 0.00 | -6.7 (-1.01) | 6.0 | 143 | -26.4 | -30.3 | 0.53 | 0.27 | 23 | fail: t,hold,turn,w12 |
| Q · N10 · k3 · avg3 · hold6 | 14.7 | 12.8 | +4.7 | 0.74 | 0.00 | +0.3 (0.21) | 9.0 | 82 | -19.2 | -26.7 | 0.92 | 0.20 | 56 | fail: t,w12 |
| Q · N10 · k3 · raw · hold6 | 7.0 | 6.0 | -2.2 | -0.10 | 0.00 | -6.6 (-0.97) | 6.0 | 110 | -28.0 | -30.4 | 0.51 | 0.22 | 41 | fail: t,hold,turn,w12 |
| Q · N10 · k4 · avg3 · hold6 | 16.7 | 14.4 | +6.2 | 0.93 | 0.00 | +1.8 (0.48) | 12.9 | 66 | -15.7 | -26.7 | 1.27 | 0.18 | 62 | fail: t,w12 |
| Q · N10 · k4 · raw · hold6 | 9.0 | 7.6 | -0.5 | 0.10 | 0.00 | -4.9 (-0.67) | 8.0 | 105 | -28.0 | -30.4 | 0.63 | 0.21 | 47 | fail: t,hold,turn,w12 |
| Q · N15 · k2 · avg3 · hold6 | 13.4 | 11.8 | +3.6 | 0.61 | 0.00 | -0.8 (0.01) | 9.0 | 94 | -21.8 | -26.6 | 0.76 | 0.22 | 53 | fail: t,hold,w12 |
| Q · N15 · k2 · raw · hold6 | 8.3 | 7.0 | -1.2 | -0.02 | 0.00 | -5.6 (-0.93) | 6.1 | 117 | -25.2 | -28.4 | 0.64 | 0.24 | 37 | fail: t,hold,turn,w12 |
| Q · N15 · k3 · avg3 · hold6 | 13.1 | 11.7 | +3.5 | 0.63 | 0.00 | -0.9 (-0.02) | 12.1 | 65 | -19.5 | -26.6 | 0.72 | 0.17 | 70 | fail: t,w12 |
| Q · N15 · k3 · raw · hold6 | 9.6 | 8.7 | +0.6 | 0.24 | 0.00 | -3.8 (-0.63) | 9.1 | 75 | -23.5 | -27.6 | 0.41 | 0.17 | 64 | fail: t,w12 |
| Q · N15 · k4 · avg3 · hold6 | 14.7 | 13.2 | +5.1 | 0.81 | 0.00 | +0.7 (0.30) | 14.0 | 48 | -18.6 | -27.7 | 0.92 | 0.14 | 79 | fail: t,w12 |
| Q · N15 · k4 · raw · hold6 | 11.3 | 10.2 | +2.0 | 0.44 | 0.00 | -2.4 (-0.33) | 15.1 | 56 | -21.5 | -27.5 | 0.58 | 0.14 | 82 | fail: t,w12 |
| Q · N20 · k2 · avg3 · hold6 | 13.9 | 12.4 | +4.2 | 0.80 | 0.00 | -0.1 (0.09) | 12.0 | 71 | -15.2 | -21.4 | 0.75 | 0.19 | 67 | fail: t,w12 |
| Q · N20 · k2 · raw · hold6 | 11.4 | 9.6 | +1.4 | 0.34 | 0.00 | -2.9 (-0.63) | 8.0 | 101 | -19.7 | -22.1 | 0.92 | 0.23 | 42 | fail: t,hold,turn,w12 |
| Q · N20 · k3 · avg3 · hold6 | 14.4 | 12.8 | +4.7 | 0.82 | 0.00 | +0.3 (0.20) | 14.9 | 47 | -15.7 | -22.3 | 0.94 | 0.14 | 80 | fail: t,w12 |
| Q · N20 · k3 · raw · hold6 | 10.5 | 9.6 | +1.4 | 0.36 | 0.00 | -3.0 (-0.72) | 12.1 | 64 | -16.5 | -21.6 | 0.48 | 0.16 | 73 | fail: t,w12 |
| Q · N20 · k4 · avg3 · hold6 | 14.7 | 13.2 | +5.1 | 0.92 | 0.00 | +0.7 (0.33) | >52 | 10 | -12.7 | -21.4 | 0.96 | 0.07 | 99 | fail: t |
| Q · N20 · k4 · raw · hold6 | 16.9 | 15.2 | +7.0 | 1.26 | 0.00 | +2.7 (0.80) | 27.0 | 26 | -13.4 | -21.6 | 1.10 | 0.10 | 92 | fail: t |
| M · N10 · k3 · avg3 · hold0 | 11.8 | 10.1 | +1.9 | 0.43 | 0.00 | -2.5 (-0.19) | 6.0 | 128 | -24.7 | -29.2 | 0.75 | 0.28 | 50 | fail: t,hold,turn,w12 |
| M · N10 · k3 · avg3 · hold12 | 10.1 | 9.1 | +1.0 | 0.30 | 0.00 | -3.4 (-0.44) | 13.0 | 61 | -17.9 | -26.1 | 0.46 | 0.15 | 90 | fail: t,w12 |
| M · N15 · k3 · avg3 · hold0 | 11.8 | 10.6 | +2.5 | 0.48 | 0.00 | -1.9 (-0.18) | 8.1 | 91 | -23.3 | -28.0 | 0.50 | 0.21 | 64 | fail: t,hold,w12 |
| M · N15 · k3 · avg3 · hold12 | 10.0 | 9.4 | +1.2 | 0.32 | 0.00 | -3.1 (-0.46) | 15.1 | 50 | -21.9 | -27.8 | 0.31 | 0.13 | 97 | fail: t,w12 |
| M · N20 · k3 · avg3 · hold0 | 12.9 | 11.5 | +3.3 | 0.66 | 0.00 | -1.1 (-0.11) | 10.1 | 68 | -20.3 | -22.6 | 0.74 | 0.18 | 76 | fail: t,w12 |
| M · N20 · k3 · avg3 · hold12 | 12.8 | 11.7 | +3.6 | 0.75 | 0.00 | -0.8 (-0.09) | 17.0 | 42 | -16.1 | -21.4 | 0.60 | 0.13 | 97 | fail: t,w12 |
| Q · N10 · k3 · avg3 · hold0 | 13.5 | 12.1 | +3.9 | 0.65 | 0.00 | -0.4 (0.07) | 6.1 | 101 | -18.3 | -26.8 | 0.64 | 0.24 | 60 | fail: t,hold,turn,w12 |
| Q · N10 · k3 · avg3 · hold12 | 11.6 | 10.7 | +2.6 | 0.50 | 0.00 | -1.8 (-0.20) | 13.0 | 53 | -17.9 | -26.1 | 0.43 | 0.14 | 90 | fail: t,w12 |
| Q · N15 · k3 · avg3 · hold0 | 13.1 | 11.8 | +3.7 | 0.63 | 0.00 | -0.7 (0.02) | 9.0 | 73 | -19.4 | -26.6 | 0.65 | 0.19 | 68 | fail: t,w12 |
| Q · N15 · k3 · avg3 · hold12 | 12.7 | 11.4 | +3.2 | 0.60 | 0.00 | -1.2 (-0.09) | 15.1 | 42 | -18.1 | -27.2 | 0.78 | 0.12 | 95 | fail: t,w12 |
| Q · N20 · k3 · avg3 · hold0 | 14.8 | 13.2 | +5.1 | 0.88 | 0.00 | +0.7 (0.30) | 13.0 | 48 | -15.7 | -22.3 | 0.97 | 0.14 | 82 | fail: t,w12 |
| Q · N20 · k3 · avg3 · hold12 | 13.8 | 12.5 | +4.4 | 0.83 | 0.00 | +0.0 (0.13) | 18.1 | 39 | -12.9 | -21.4 | 0.77 | 0.12 | 96 | fail: t |

### The 48-variant grid — MID

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M · N10 · k2 · avg3 · hold6 | 14.7 | 13.0 | -4.0 | -0.82 | 0.00 | -4.9 (-0.98) | 7.1 | 85 | -13.9 | -19.9 | 0.94 | 0.26 | 52 | fail: t,hold |
| M · N10 · k2 · raw · hold6 | 19.9 | 16.7 | -0.4 | 0.04 | 0.00 | -1.3 (-0.16) | 7.0 | 93 | -13.2 | -17.9 | 1.86 | 0.31 | 34 | fail: t,hold |
| M · N10 · k3 · avg3 · hold6 | 16.6 | 14.8 | -2.2 | -0.38 | 0.00 | -3.1 (-0.56) | 10.0 | 77 | -13.0 | -22.0 | 1.05 | 0.25 | 70 | fail: t |
| M · N10 · k3 · raw · hold6 | 19.6 | 17.2 | +0.2 | 0.15 | 0.00 | -0.8 (-0.07) | 10.0 | 82 | -10.7 | -18.3 | 1.44 | 0.29 | 55 | fail: t |
| M · N10 · k4 · avg3 · hold6 | 22.4 | 19.9 | +2.9 | 0.75 | 0.00 | +2.0 (0.50) | 13.0 | 60 | -10.4 | -18.8 | 1.60 | 0.23 | 75 | fail: t |
| M · N10 · k4 · raw · hold6 | 17.4 | 15.4 | -1.6 | -0.26 | 0.00 | -2.5 (-0.44) | 11.0 | 70 | -10.7 | -20.2 | 1.20 | 0.26 | 71 | fail: t |
| M · N15 · k2 · avg3 · hold6 | 16.9 | 14.8 | -2.3 | -0.39 | 0.00 | -3.2 (-0.61) | 9.0 | 81 | -9.8 | -21.0 | 1.37 | 0.27 | 53 | fail: t,hold |
| M · N15 · k2 · raw · hold6 | 22.4 | 19.3 | +2.3 | 0.56 | 0.00 | +1.4 (0.43) | 8.0 | 86 | -10.5 | -19.3 | 2.00 | 0.32 | 50 | fail: t,hold |
| M · N15 · k3 · avg3 · hold6 | 20.2 | 18.0 | +1.0 | 0.36 | 0.00 | +0.0 (0.12) | 11.0 | 58 | -8.4 | -20.1 | 1.55 | 0.22 | 70 | fail: t |
| M · N15 · k3 · raw · hold6 | 25.2 | 22.2 | +5.2 | 1.44 | 0.00 | +4.2 (1.31) | 10.1 | 72 | -6.2 | -18.9 | 2.19 | 0.28 | 65 | fail: t |
| M · N15 · k4 · avg3 · hold6 | 15.8 | 14.3 | -2.7 | -0.79 | 0.00 | -3.6 (-1.01) | 14.0 | 40 | -8.6 | -20.7 | 0.83 | 0.16 | 92 | fail: t |
| M · N15 · k4 · raw · hold6 | 21.9 | 19.1 | +2.1 | 0.61 | 0.00 | +1.2 (0.40) | 10.0 | 57 | -6.6 | -19.6 | 1.72 | 0.23 | 67 | fail: t |
| M · N20 · k2 · avg3 · hold6 | 18.8 | 16.9 | -0.1 | 0.02 | 0.00 | -1.1 (-0.25) | 9.1 | 68 | -9.6 | -18.9 | 1.33 | 0.24 | 62 | fail: t |
| M · N20 · k2 · raw · hold6 | 24.6 | 21.2 | +4.2 | 1.09 | 0.00 | +3.2 (0.95) | 9.0 | 82 | -8.3 | -18.3 | 2.12 | 0.31 | 51 | fail: t |
| M · N20 · k3 · avg3 · hold6 | 18.9 | 17.0 | +0.0 | 0.08 | 0.00 | -0.9 (-0.23) | 13.0 | 44 | -7.2 | -19.5 | 1.22 | 0.18 | 77 | fail: t |
| M · N20 · k3 · raw · hold6 | 22.2 | 19.7 | +2.7 | 0.75 | 0.00 | +1.8 (0.57) | 12.0 | 58 | -7.3 | -19.4 | 1.79 | 0.23 | 66 | fail: t |
| M · N20 · k4 · avg3 · hold6 | 19.8 | 18.1 | +1.1 | 0.47 | 0.00 | +0.1 (0.12) | 20.0 | 31 | -5.8 | -16.0 | 1.19 | 0.15 | 93 | fail: t |
| M · N20 · k4 · raw · hold6 | 20.5 | 18.2 | +1.2 | 0.39 | 0.00 | +0.2 (0.10) | 13.0 | 46 | -7.6 | -17.1 | 1.51 | 0.19 | 76 | fail: t |
| Q · N10 · k2 · avg3 · hold6 | 16.2 | 14.5 | -2.5 | -0.51 | 0.00 | -3.5 (-0.72) | 9.0 | 83 | -12.8 | -21.6 | 1.08 | 0.27 | 58 | fail: t,hold |
| Q · N10 · k2 · raw · hold6 | 19.6 | 16.3 | -0.7 | -0.07 | 0.00 | -1.6 (-0.28) | 6.1 | 94 | -13.4 | -15.3 | 1.90 | 0.31 | 35 | fail: t,hold |
| Q · N10 · k3 · avg3 · hold6 | 18.2 | 16.1 | -0.9 | -0.10 | 0.00 | -1.9 (-0.28) | 9.0 | 77 | -13.9 | -21.1 | 1.25 | 0.25 | 69 | fail: t |
| Q · N10 · k3 · raw · hold6 | 17.9 | 15.8 | -1.2 | -0.18 | 0.00 | -2.1 (-0.40) | 9.1 | 75 | -14.6 | -21.5 | 1.14 | 0.26 | 61 | fail: t |
| Q · N10 · k4 · avg3 · hold6 | 22.2 | 19.7 | +2.7 | 0.77 | 0.00 | +1.8 (0.51) | 12.9 | 53 | -11.3 | -19.7 | 1.71 | 0.21 | 81 | fail: t |
| Q · N10 · k4 · raw · hold6 | 15.8 | 14.1 | -2.9 | -0.64 | 0.00 | -3.8 (-0.78) | 12.0 | 59 | -14.2 | -19.0 | 0.90 | 0.21 | 81 | fail: t |
| Q · N15 · k2 · avg3 · hold6 | 17.7 | 15.4 | -1.6 | -0.25 | 0.00 | -2.6 (-0.48) | 9.0 | 77 | -8.6 | -21.1 | 1.31 | 0.27 | 57 | fail: t |
| Q · N15 · k2 · raw · hold6 | 19.4 | 16.8 | -0.2 | 0.04 | 0.00 | -1.1 (-0.23) | 9.0 | 81 | -8.9 | -19.4 | 1.53 | 0.29 | 54 | fail: t |
| Q · N15 · k3 · avg3 · hold6 | 19.8 | 17.7 | +0.7 | 0.30 | 0.00 | -0.3 (0.07) | 12.9 | 54 | -7.8 | -20.8 | 1.26 | 0.21 | 80 | fail: t |
| Q · N15 · k3 · raw · hold6 | 18.2 | 16.4 | -0.6 | -0.12 | 0.00 | -1.6 (-0.35) | 12.0 | 55 | -9.1 | -20.0 | 1.06 | 0.22 | 84 | fail: t |
| Q · N15 · k4 · avg3 · hold6 | 18.3 | 16.4 | -0.6 | -0.04 | 0.00 | -1.5 (-0.32) | 15.1 | 31 | -8.1 | -17.4 | 1.26 | 0.14 | 86 | fail: t |
| Q · N15 · k4 · raw · hold6 | 19.1 | 17.1 | +0.1 | 0.08 | 0.00 | -0.9 (-0.15) | 12.1 | 44 | -9.6 | -19.7 | 1.27 | 0.18 | 80 | fail: t |
| Q · N20 · k2 · avg3 · hold6 | 17.1 | 15.4 | -1.6 | -0.37 | 0.00 | -2.5 (-0.66) | 12.0 | 60 | -8.3 | -20.8 | 1.12 | 0.22 | 66 | fail: t |
| Q · N20 · k2 · raw · hold6 | 22.3 | 19.5 | +2.5 | 0.77 | 0.00 | +1.5 (0.54) | 9.0 | 79 | -9.4 | -18.4 | 1.73 | 0.28 | 51 | fail: t |
| Q · N20 · k3 · avg3 · hold6 | 18.5 | 16.5 | -0.6 | -0.14 | 0.00 | -1.5 (-0.46) | 15.1 | 39 | -8.2 | -18.7 | 1.29 | 0.16 | 79 | fail: t |
| Q · N20 · k3 · raw · hold6 | 21.3 | 18.9 | +1.9 | 0.58 | 0.00 | +1.0 (0.32) | 12.1 | 48 | -7.1 | -17.4 | 1.54 | 0.20 | 72 | fail: t |
| Q · N20 · k4 · avg3 · hold6 | 19.8 | 18.0 | +1.0 | 0.41 | 0.00 | +0.0 (0.09) | 24.1 | 28 | -7.6 | -17.1 | 1.16 | 0.14 | 93 | fail: t |
| Q · N20 · k4 · raw · hold6 | 21.9 | 19.6 | +2.6 | 0.72 | 0.00 | +1.6 (0.48) | 15.1 | 38 | -10.2 | -16.9 | 1.60 | 0.17 | 81 | fail: t |
| M · N10 · k3 · avg3 · hold0 | 18.9 | 16.9 | -0.2 | 0.08 | 0.00 | -1.1 (-0.07) | 9.0 | 84 | -14.2 | -21.0 | 1.32 | 0.29 | 69 | fail: t |
| M · N10 · k3 · avg3 · hold12 | 14.7 | 13.5 | -3.5 | -0.72 | 0.00 | -4.4 (-0.87) | 13.0 | 54 | -13.1 | -24.0 | 0.70 | 0.19 | 99 | fail: t |
| M · N15 · k3 · avg3 · hold0 | 17.6 | 16.0 | -1.0 | -0.13 | 0.00 | -2.0 (-0.33) | 10.0 | 66 | -13.8 | -21.7 | 1.23 | 0.24 | 69 | fail: t |
| M · N15 · k3 · avg3 · hold12 | 17.4 | 15.8 | -1.2 | -0.26 | 0.00 | -2.1 (-0.47) | 13.0 | 48 | -8.4 | -21.0 | 0.92 | 0.18 | 92 | fail: t |
| M · N20 · k3 · avg3 · hold0 | 16.7 | 15.1 | -1.9 | -0.55 | 0.00 | -2.8 (-0.84) | 14.0 | 46 | -9.2 | -20.5 | 0.95 | 0.18 | 82 | fail: t |
| M · N20 · k3 · avg3 · hold12 | 19.2 | 17.6 | +0.6 | 0.29 | 0.00 | -0.4 (-0.01) | 14.9 | 39 | -8.8 | -22.4 | 1.13 | 0.17 | 98 | fail: t |
| Q · N10 · k3 · avg3 · hold0 | 18.7 | 16.5 | -0.6 | -0.01 | 0.00 | -1.5 (-0.18) | 9.0 | 84 | -15.6 | -21.7 | 1.38 | 0.28 | 67 | fail: t,hold,w12 |
| Q · N10 · k3 · avg3 · hold12 | 17.7 | 16.4 | -0.6 | 0.02 | 0.00 | -1.5 (-0.18) | 15.0 | 52 | -12.0 | -22.9 | 0.88 | 0.19 | 100 | fail: t |
| Q · N15 · k3 · avg3 · hold0 | 18.3 | 16.6 | -0.4 | 0.01 | 0.00 | -1.4 (-0.22) | 12.1 | 61 | -8.7 | -21.2 | 1.08 | 0.23 | 80 | fail: t |
| Q · N15 · k3 · avg3 · hold12 | 19.8 | 18.1 | +1.0 | 0.39 | 0.00 | +0.1 (0.14) | 14.9 | 47 | -7.8 | -21.7 | 1.13 | 0.19 | 98 | fail: t |
| Q · N20 · k3 · avg3 · hold0 | 18.8 | 16.7 | -0.4 | -0.03 | 0.00 | -1.3 (-0.32) | 15.1 | 41 | -10.1 | -21.2 | 1.23 | 0.17 | 82 | fail: t |
| Q · N20 · k3 · avg3 · hold12 | 18.8 | 17.1 | +0.1 | 0.13 | 0.00 | -0.8 (-0.17) | 15.1 | 38 | -9.2 | -20.9 | 1.13 | 0.16 | 98 | fail: t |

### The 48-variant grid — SMALL

| variant | CAGR pre-tax % | CAGR after tax % | excess after tax %/yr | t (NW) | haircut t | excess vs EW %/yr (t) | median hold, months | turnover %/yr | worst 12m excess % | max DD % | tax ₹L | costs ₹L | LT share of gains % | bars |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M · N10 · k2 · avg3 · hold6 | 34.7 | 27.4 | +10.6 | 1.18 | 0.00 | +7.3 (0.76) | 6.0 | 170 | -10.2 | -22.0 | 4.74 | 1.66 | 9 | fail: t,hold,turn |
| M · N10 · k2 · raw · hold6 | 35.5 | 28.1 | +11.3 | 1.44 | 0.00 | +8.0 (1.00) | 6.0 | 176 | -10.3 | -23.6 | 5.04 | 1.52 | 6 | fail: t,hold,turn |
| M · N10 · k3 · avg3 · hold6 | 36.1 | 28.3 | +11.5 | 1.23 | 0.00 | +8.2 (0.82) | 6.0 | 155 | -8.3 | -20.9 | 5.03 | 1.55 | 14 | fail: t,hold,turn |
| M · N10 · k3 · raw · hold6 | 35.5 | 28.1 | +11.3 | 1.45 | 0.00 | +8.0 (1.01) | 6.0 | 172 | -10.3 | -23.6 | 5.09 | 1.46 | 6 | fail: t,hold,turn |
| M · N10 · k4 · avg3 · hold6 | 45.1 | 36.5 | +19.7 | 2.08 | 0.00 | +16.5 (1.66) | 6.0 | 143 | -8.6 | -19.7 | 6.37 | 1.58 | 27 | fail: t,hold,turn |
| M · N10 · k4 · raw · hold6 | 35.9 | 28.6 | +11.8 | 1.55 | 0.00 | +8.6 (1.13) | 6.0 | 167 | -9.4 | -24.5 | 5.07 | 1.36 | 6 | fail: t,hold,turn |
| M · N15 · k2 · avg3 · hold6 | 34.5 | 27.7 | +10.9 | 1.48 | 0.00 | +7.6 (0.94) | 6.0 | 167 | -7.0 | -21.3 | 4.67 | 1.39 | 9 | fail: t,hold,turn |
| M · N15 · k2 · raw · hold6 | 33.3 | 26.6 | +9.8 | 1.56 | 0.00 | +6.5 (1.03) | 6.0 | 173 | -7.7 | -21.8 | 4.37 | 1.15 | 7 | fail: t,hold,turn |
| M · N15 · k3 · avg3 · hold6 | 42.6 | 34.8 | +18.0 | 2.01 | 0.00 | +14.7 (1.57) | 6.0 | 143 | -14.5 | -21.6 | 5.89 | 1.37 | 21 | fail: t,hold,turn |
| M · N15 · k3 · raw · hold6 | 31.8 | 25.7 | +8.9 | 1.46 | 0.00 | +5.7 (0.93) | 6.0 | 171 | -6.9 | -23.9 | 4.12 | 1.17 | 8 | fail: t,hold,turn |
| M · N15 · k4 · avg3 · hold6 | 37.0 | 30.4 | +13.7 | 1.68 | 0.00 | +10.4 (1.22) | 6.1 | 142 | -16.7 | -20.3 | 4.66 | 1.21 | 24 | fail: t,hold,turn,w12 |
| M · N15 · k4 · raw · hold6 | 32.6 | 27.0 | +10.2 | 1.58 | 0.00 | +7.0 (1.08) | 6.0 | 160 | -4.4 | -24.5 | 4.21 | 1.13 | 14 | fail: t,hold,turn |
| M · N20 · k2 · avg3 · hold6 | 40.7 | 33.2 | +16.4 | 2.61 | 0.57 | +13.2 (2.10) | 6.0 | 158 | +0.0 | -21.0 | 5.41 | 1.41 | 22 | fail: t,hold,turn |
| M · N20 · k2 · raw · hold6 | 29.5 | 23.5 | +6.8 | 1.21 | 0.00 | +3.5 (0.63) | 6.0 | 172 | -7.7 | -23.3 | 3.78 | 0.99 | 6 | fail: t,hold,turn |
| M · N20 · k3 · avg3 · hold6 | 32.2 | 26.5 | +9.7 | 1.61 | 0.00 | +6.5 (1.02) | 6.0 | 146 | -10.9 | -22.1 | 3.67 | 1.06 | 22 | fail: t,hold,turn |
| M · N20 · k3 · raw · hold6 | 32.6 | 26.8 | +10.0 | 1.67 | 0.00 | +6.7 (1.15) | 6.0 | 165 | -5.6 | -22.8 | 4.16 | 1.04 | 12 | fail: t,hold,turn |
| M · N20 · k4 · avg3 · hold6 | 33.6 | 27.7 | +10.9 | 1.68 | 0.00 | +7.6 (1.08) | 6.0 | 133 | -12.0 | -21.9 | 3.96 | 1.00 | 28 | fail: t,hold,turn |
| M · N20 · k4 · raw · hold6 | 25.3 | 20.6 | +3.8 | 0.65 | 0.00 | +0.5 (0.13) | 6.0 | 164 | -14.5 | -21.4 | 3.03 | 0.92 | 10 | fail: t,hold,turn |
| Q · N10 · k2 · avg3 · hold6 | 33.0 | 26.6 | +9.8 | 1.28 | 0.00 | +6.5 (0.84) | 6.0 | 152 | -9.9 | -25.1 | 4.39 | 1.40 | 19 | fail: t,hold,turn |
| Q · N10 · k2 · raw · hold6 | 19.3 | 15.4 | -1.4 | 0.08 | 0.00 | -4.6 (-0.29) | 6.0 | 164 | -18.5 | -28.7 | 2.39 | 1.15 | 11 | fail: t,hold,turn,w12 |
| Q · N10 · k3 · avg3 · hold6 | 32.1 | 25.9 | +9.1 | 1.23 | 0.00 | +5.9 (0.78) | 6.0 | 146 | -11.6 | -25.1 | 4.11 | 1.35 | 21 | fail: t,hold,turn |
| Q · N10 · k3 · raw · hold6 | 24.1 | 19.7 | +2.9 | 0.47 | 0.00 | -0.3 (0.15) | 6.0 | 160 | -18.5 | -29.4 | 2.74 | 1.11 | 13 | fail: t,hold,turn,w12 |
| Q · N10 · k4 · avg3 · hold6 | 31.7 | 26.1 | +9.3 | 1.27 | 0.00 | +6.0 (0.84) | 6.0 | 141 | -16.0 | -24.8 | 3.68 | 1.34 | 31 | fail: t,hold,turn,w12 |
| Q · N10 · k4 · raw · hold6 | 24.6 | 20.3 | +3.5 | 0.52 | 0.00 | +0.3 (0.19) | 6.0 | 152 | -19.4 | -30.0 | 2.63 | 1.09 | 19 | fail: t,hold,turn,w12 |
| Q · N15 · k2 · avg3 · hold6 | 35.9 | 29.1 | +12.3 | 1.71 | 0.00 | +9.0 (1.20) | 6.0 | 157 | -5.4 | -23.0 | 4.79 | 1.39 | 13 | fail: t,hold,turn |
| Q · N15 · k2 · raw · hold6 | 28.2 | 22.8 | +6.0 | 0.88 | 0.00 | +2.8 (0.42) | 6.0 | 164 | -16.9 | -22.3 | 3.24 | 1.02 | 14 | fail: t,hold,turn,w12 |
| Q · N15 · k3 · avg3 · hold6 | 32.2 | 26.6 | +9.8 | 1.31 | 0.00 | +6.6 (0.89) | 6.0 | 137 | -11.8 | -23.7 | 3.83 | 1.10 | 26 | fail: t,hold,turn |
| Q · N15 · k3 · raw · hold6 | 23.7 | 19.6 | +2.8 | 0.49 | 0.00 | -0.5 (0.03) | 6.0 | 156 | -16.2 | -24.4 | 2.41 | 0.98 | 17 | fail: t,hold,turn,w12 |
| Q · N15 · k4 · avg3 · hold6 | 28.4 | 23.6 | +6.8 | 0.98 | 0.00 | +3.5 (0.51) | 6.0 | 124 | -11.6 | -24.6 | 3.13 | 0.97 | 27 | fail: t,hold,turn |
| Q · N15 · k4 · raw · hold6 | 23.8 | 19.7 | +2.9 | 0.51 | 0.00 | -0.3 (0.08) | 6.0 | 146 | -13.2 | -25.6 | 2.50 | 0.98 | 20 | fail: t,hold,turn |
| Q · N20 · k2 · avg3 · hold6 | 35.2 | 29.0 | +12.2 | 1.98 | 0.00 | +9.0 (1.50) | 6.0 | 152 | -1.9 | -22.9 | 4.38 | 1.28 | 23 | fail: t,hold,turn |
| Q · N20 · k2 · raw · hold6 | 27.5 | 22.3 | +5.5 | 0.95 | 0.00 | +2.3 (0.39) | 6.0 | 161 | -13.5 | -22.2 | 3.09 | 0.96 | 14 | fail: t,hold,turn |
| Q · N20 · k3 · avg3 · hold6 | 31.9 | 26.7 | +9.9 | 1.55 | 0.00 | +6.7 (0.98) | 6.0 | 134 | -6.3 | -23.2 | 3.58 | 0.97 | 30 | fail: t,hold,turn |
| Q · N20 · k3 · raw · hold6 | 27.3 | 22.5 | +5.7 | 0.92 | 0.00 | +2.5 (0.42) | 6.0 | 142 | -11.7 | -23.2 | 2.92 | 0.87 | 23 | fail: t,hold,turn |
| Q · N20 · k4 · avg3 · hold6 | 27.9 | 23.4 | +6.6 | 1.08 | 0.00 | +3.3 (0.55) | 6.0 | 128 | -9.4 | -24.8 | 3.00 | 0.88 | 26 | fail: t,hold,turn |
| Q · N20 · k4 · raw · hold6 | 24.2 | 20.1 | +3.2 | 0.58 | 0.00 | -0.0 (0.07) | 6.0 | 138 | -14.5 | -22.9 | 2.54 | 0.83 | 24 | fail: t,hold,turn |
| M · N10 · k3 · avg3 · hold0 | 36.7 | 29.6 | +12.8 | 1.39 | 0.00 | +9.5 (0.96) | 3.0 | 322 | -8.2 | -20.8 | 5.24 | 3.58 | 6 | fail: t,hold,turn |
| M · N10 · k3 · avg3 · hold12 | 39.5 | 35.1 | +18.3 | 1.81 | 0.00 | +15.0 (1.57) | 12.9 | 88 | -12.2 | -26.7 | 3.57 | 0.99 | 98 | fail: t |
| M · N15 · k3 · avg3 · hold0 | 27.3 | 22.8 | +6.0 | 1.06 | 0.00 | +2.7 (0.51) | 3.0 | 285 | -5.9 | -22.5 | 3.01 | 2.13 | 18 | fail: t,hold,turn |
| M · N15 · k3 · avg3 · hold12 | 32.8 | 28.9 | +12.2 | 1.62 | 0.00 | +8.9 (1.29) | 13.0 | 83 | -8.2 | -26.7 | 2.79 | 0.73 | 98 | fail: t |
| M · N20 · k3 · avg3 · hold0 | 29.9 | 25.2 | +8.4 | 1.52 | 0.00 | +5.1 (0.96) | 3.0 | 259 | -7.0 | -22.3 | 3.30 | 1.99 | 26 | fail: t,hold,turn |
| M · N20 · k3 · avg3 · hold12 | 30.1 | 26.9 | +10.1 | 1.71 | 0.00 | +6.8 (1.20) | 13.0 | 80 | -7.4 | -24.2 | 2.37 | 0.63 | 93 | fail: t |
| Q · N10 · k3 · avg3 · hold0 | 42.5 | 33.9 | +17.1 | 2.06 | 0.00 | +13.8 (1.64) | 3.0 | 232 | -10.4 | -22.9 | 6.28 | 2.68 | 10 | fail: t,hold,turn |
| Q · N10 · k3 · avg3 · hold12 | 31.6 | 28.0 | +11.2 | 1.21 | 0.00 | +8.0 (0.98) | 13.0 | 76 | -10.1 | -27.2 | 2.62 | 0.78 | 98 | fail: t |
| Q · N15 · k3 · avg3 · hold0 | 27.1 | 22.4 | +5.7 | 1.01 | 0.00 | +2.4 (0.47) | 3.0 | 215 | -7.1 | -24.6 | 2.96 | 1.56 | 20 | fail: t,hold,turn |
| Q · N15 · k3 · avg3 · hold12 | 28.2 | 24.9 | +8.2 | 1.17 | 0.00 | +4.9 (0.81) | 13.0 | 75 | -9.4 | -26.7 | 2.23 | 0.60 | 93 | fail: t |
| Q · N20 · k3 · avg3 · hold0 | 30.7 | 25.6 | +8.8 | 1.65 | 0.00 | +5.6 (1.04) | 3.0 | 199 | -2.4 | -21.4 | 3.46 | 1.48 | 24 | fail: t,hold,turn |
| Q · N20 · k3 · avg3 · hold12 | 25.6 | 22.9 | +6.2 | 1.05 | 0.00 | +2.9 (0.63) | 13.0 | 78 | -11.1 | -24.7 | 1.95 | 0.57 | 95 | fail: t |
