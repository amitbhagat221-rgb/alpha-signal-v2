# Liquid fund vs SMALL book as collateral for the strangle, after tax (2026-10-28)

**Question (Amit):** with ₹75 L, how much should sit in a liquid fund and how much in a SMALL stock book (slow or fast), both pledged for the weekly strangle, to get the most return for the risk, after tax? Tested on the last 5–6 years.

**Verdict**
1. **Size the options by a crash budget, not by margin.** At full margin, a 2020-style −13.9 % gap would have cost the naked strangle **70 % of total wealth on average (95 % at worst)**. With the 1.75 % wings it cost 18–34 %. Under any crash budget (20 / 30 / 40 % of wealth), winged beats naked in every cell: the naked book uses up the budget on a handful of lots.
2. **More SMALL raises return and drawdown together.** At a 30 % crash budget, with wings, after tax:

| Liquid share of ₹70 L | 2022-06 → 2026-10 (honest fast) | | 2019-12 → 2026-10 (fast in-sample) | |
|---|---|---|---|---|
| | CAGR | max drawdown | CAGR | max drawdown |
| 0 % (all SMALL) | 30.3 % | −18 % to −22 % | 35.1–35.8 % | −36 % to −39 % |
| 25 % | 29.4–30.0 % | −12 % to −16 % | 33.6–33.7 % | −27 % to −29 % |
| **50 %** | **27.6–28.4 %** | **−7 % to −10 %** | **30.8–31.3 %** | **−18 % to −19 %** |
| 75 % | 24.7–25.5 % | −6 % | 26.8–27.6 % | −9 % |
| 100 % (all liquid) | 20.9 % | −6 % | 20.0 % | −7 % |

3. **Fast vs slow nearly ties after tax at this size** (fast +0.5 to +1 point a year). The fast book's edge falls with its size (2022–26: 28.1 %/yr at ₹17.5 L → 24.2 % at ₹70 L, slow 24.5 → 24.0 %): measured market-impact costs and 20 % STCG on nearly every gain. Its monthly churn also left 10–16 days of margin shortfall around rebalances (new shares not yet pledged). **The slow book is the better collateral.**
4. **Practical optimum: 50 % liquid / 50 % SMALL slow, winged, 30 % crash budget.** About **27–31 %/yr after tax** in these windows, drawdown −10 % (2022–26) / −19 % (incl. 2020). Going to 25 % liquid adds about 2 points for twice the drawdown.

**Read with care:** 2020–24 was an unusually strong small-cap run (the SMALL books made 24–31 %/yr after tax, the Smallcap 250 17–21 %), and no crash happened while trades were open (the VIX guard sat out March–May 2020). Plan on lower numbers: the equity sleeve nearer the index (~12 %/yr long run) plus a few points, the options as in the backtest.

## Method (fixed before results; `tools/combined_book_study.py` docstring)
- ₹75 L = ₹5 L cash + ₹70 L split: liquid share w (Axis Liquid direct growth) and the SMALL book (tools.lh_book at the sleeve's capital: costs, STCG / LTCG with set-off; between monthly anchors it moves with the Smallcap 250). Slow = slow_v2, top 20, sell below 60, 3-month average, 12-month hold. Fast = top 20, sell below 40, monthly; fast_v1 (in-sample) in the long window, fast_select (walk-forward) in 2022–26.
- Options: the backtest's exp2 0.05Δ trades (EOD settle, 1 % slippage, date charges), NIFTY every week, SENSEX from 2024-01, naked or + longs 1.75 % of the forward beyond. Lots at each entry: margin room (collateral − 15 % spare − margin in use, Kite's 2026-10-28 margin per lot scaled with VIX for naked, + the 4 % expiry-day ELM from 2024-11-20), the VIX guard, and the crash budget: stress loss of open trades (−13.9 % gap; winged capped at the wing) + 25 % of the SMALL book ≤ budget × total value.
- Collateral: liquid 90 %, SMALL 65 %, cash 100 %; fast book 25 % for 3 sessions after each rebalance. 50:50 rule shortfall interest 0.035 %/day; debit interest 0.05 %/day. Option profits swept to the liquid fund monthly.
- Tax: options P&L − interest + liquid gains (as if redeemed yearly) at FY 2025-26 new-regime slabs with rebate, surcharge, cess; losses carried forward. SMALL book taxes inside lh_book (final value = after-tax liquidation value).

## Other findings
- Margin-only sizing (no budget): naked 23.9 % → all-SMALL 35.7 % (2022–26), winged 2–3 points lower, because the wings never paid out in-sample. That table is the "return if nothing ever goes wrong" view; the crash stress above is what it hides.
- A 60-lot cap (first run, `combined_results_cap60.csv`) made wings look worse still: both books hit the cap, so the wings' margin benefit was capped away. Lot caps are also not comparable across years (lot sizes 75 → 50 → 25 → 75 → 65).
- Tax paid on options + liquid gains: ₹12 L over 4.3 years at 50 / 50 slow (2022–26); the slow book defers most of its own tax (LTCG).

## Not modelled
Intraday margin calls / forced exits (shortfall days counted only), wing fill quality on far strikes (settle prices), fills at 100–200+ lots as capital compounds, a calm-start crash while positions are open, the paper sleeve's ₹1 Cr liquidity floor.

Files: `data/lh/v2/combined_results*.csv` (all cells; `_budget0.2/0.3/0.4`, `_cap60`), `combined_books_{L,S}.parquet`, `combined_trades_{strangle,condor}.parquet`. Run: `python -m tools.combined_book_study [--stress-budget 0.3] [--window S]` (~5 min with the caches).
