# Research 0008 — independent critique prompt: the multibagger framework (plan 0026)

Written 2026-10-16 (Amit: "give me an individual fair critique prompt of the multibagger framework that we have designed"). Paste everything below the line into a fresh reviewer (another model, a deep-research run, or a human analyst). It is self-contained: the reviewer needs no access to the repo. Sources: [plan 0026](../plans/0026-multibagger-desk.md), [study](../studies/multibagger-thesis-2026-10.md), [ADR 0075](../decisions/0075-multibagger-thesis-replaces-quality-funnel.md).

---

## Your role

You are an independent reviewer: a senior quant researcher with real experience in Indian small-cap equities, factor investing and backtest forensics. You did not design this framework and have no stake in it. Give a **fair** critique:
- Credit what is sound.
- Do not invent problems to look rigorous.
- Do not soften real flaws.
- When the facts below are not enough to judge something, say so and say what you would need.
- Separate what the numbers show from your opinion.

## What the framework is for

A private investor in India (CFA/FRM, quant background) wants a **shortlist of 30 small listed Indian companies that could return 3–10x over 2–5 years**. He will **hold 10 of them**, follow those 30 closely (results, filings, ownership, regulation, government links, new funding), and value each one with a "football field" of methods. The shortlist sits beside a separate daily factor model and two small-cap paper books; it does not change them.

## How it works (as live today)

**Universe:** ~2,450 NSE-listed stocks (ETFs excluded), tiered by market cap: LARGE = top 100, MID = 101–250, SMALL = the rest.

**Successive funnel:**

| stage | names | rule |
|---|---|---|
| 1 Safety gates ("pond") | ~755 today | market cap ≤ ₹5,000 crore · median daily traded value ≥ ₹0.5 crore · outside the 250 most-traded stocks · revenue > 0 · no statutory-auditor resignation or insolvency (CIRP) filing in 12 months · promoter pledge ≤ 50 % · not under GSM surveillance. **No quality hurdle** (no ROCE, debt or growth minimum). Forensic flags (Beneish, Altman) are shown, not used to cut. |
| 2 Thesis score → top 100 | 100 | equal-weight average of five within-pond percentiles: **smallness** (−log market cap); **cheapness** (mean percentile of book/price, sales/price, earnings/price from the latest annual report, lagged 150 days); **price trigger** (6-month return and price ÷ 52-week high); **business trigger** (latest quarter: EBITDA change vs a year ago scaled by revenue, and revenue growth year on year); **industry tailwind** (median 6-month return of the stock's industry inside the pond). A missing part takes the mean of the stock's other parts. Nothing is fitted. |
| 3 Evidence card → 30 candidates | 30 | the investor picks, by hand, from one-screen cards: score parts, known-investor entries, latest results, recent orders / fundraising / governance events, P/E and P/B against the stock's own history, forensic flags |
| 4 Deep dive on the 30 | 30 | valuation football field (own P/E, P/B and EV/EBITDA bands; industry peer multiples; a 10-year DCF bear/base/bull at 13–15 % cost of equity; reverse DCF; analyst targets; 52-week range), an LLM-written thesis / bull / bear / risks with numbers banned from the text, 12 quarters of results, ownership timeline, event timeline, government-link card, peers |
| 5 Hold 10 | 10 | the investor picks, each with a logged reason |

**Holding rules:** no stop-losses. The 30 are refreshed from the score at least yearly. The 10 are reviewed quarterly after results. A drawdown-and-relative-strength "conviction" signal is shown as a monitor only. The evidence grade shown on the page is **C: "a shortlist for judgement, not a ranking that picks the winner."**

## The evidence behind it

**A. What 10-year multibaggers looked like at the start** (Oct 2016 → Oct 2026):
- 127 of 995 surviving stocks went ≥ 10x (split / bonus / demerger adjusted, price only).
- **Odds by trait, full market including delisted stocks** (Oct start dates 2011–2021; labels: ≥ 5x in 5 years, ≥ 10x in 10 years):
  - least-liquid fifth 1.2–1.3× the base rate; most-liquid fifth 0.4–0.5×;
  - 6-month momentum, top fifth 1.1–1.2×, bottom fifth 0.85×;
  - lowest-volatility fifth 0.65×.
  - High volatility looked like 1.37× on survivors only, but ≈ 1.0× once delisted stocks were counted.
- **Oct-2016 survivors with fundamentals** (588 stocks, 74 went 10x):
  - market cap < ₹1,000 crore held 77 % of the 10x stocks;
  - P/B ≤ 1: 1.47×; ROCE ≥ 18 %: 0.65×.
  - The previous quality screen (ROCE ≥ 18 %, debt/equity ≤ 0.5, ₹1,000–20,000 crore, 3-year profit growth ≥ 20 %) caught 3 of the 74 (0.35×).
  - The median 10x stock at the start: ₹368 crore, P/B 1.1, P/E 13, ROCE 9 %.
  - Capital goods and iron & steel hit 28–33 % against 13 % overall.

**B. Thesis backtest** (rules written down before the first run; three code bugs fixed afterwards and logged):
- **Sample:** fundamentals exist only for today's listed universe, so the full thesis is tested on **survivors only**, from 2015. The quarterly business part exists from 2019.
- **T1 tail capture** (8 October anchors 2016–2023 with a 3-year outcome):
  - top-30 lift for ≥ 3x in 3 years: 1.24×;
  - for ≥ 5x in 5 years: 1.25×;
  - **for halving in 3 years: 0.28×**.
  - The pre-set bar (lift ≥ 1.5 with halving ≤ base in ≥ 70 % of anchors) **failed: 4 of 8**.
- **T2 book**: top 30, equal weight, rebalanced yearly, 12 staggered start months from late 2016, realistic costs from a liquidity-based impact model calibrated on the investor's own fills at ₹1 lakh per name (₹30 lakh book), 12.5 % tax on realised gains, against the NIFTY SMALLCAP 250 price index.
  - **+12.7 %/yr** median excess, t 1.90 (annual excess);
  - beat the index from 12 / 12 start months and in 4 of the last 5 calendar years;
  - **worst 12-month excess −33 %**.
  - The 2016–2020 half earned +10.2 %/yr, 2021–2026 +16.0 %/yr. Bad years were 2019 (small-cap bear) and 2025.
  - The deflated Sharpe ratio over the 21 variants tried in the same window is 0.961; PBO (probability of backtest overfitting, CSCV, 8 blocks) 0.29.
  - With a flat 31 bps cost: +13.6 %/yr.
- **Price-only version on the full market including delisted stocks:** +11.7 %/yr, t 2.22.
- **The grade rule** (the investor's own, ADR 0073): B needs t ≥ 1.5, DSR ≥ 0.90 or PBO ≤ 0.30, ≥ 3 of the last 5 years, ≥ 10 of 12 starts, and a worst 12 months ≥ −15 %. Everything passes except the last, so the grade is C.

**C. 25 pre-registered changes, none passed** (accept rule: ≥ 1 point better in both halves of the sample, tail capture not worse, worst year not > 5 points worse):

| change | effect |
|---|---|
| drop any one of the five parts | −0.5 to −2.2 pts or worse tails |
| any part alone | +4.7 to +8.4 %/yr |
| add known-superinvestor entry (15 named Indian small-cap investors, list frozen, entries 2016+) | −1.4 pts. Alone, their new stakes tripled 25 % of the time vs 20 % for the pond, halved about as often (12 % vs 11 %), median outcome 1.51x vs 1.47x; famous wins (Tejas Networks 13.7x, Indo Tech 10.3x) sit beside losses (Nahar Industries 0.14x, Best Agrolife 0.22x) |
| add results-day reaction, delivery-volume anomaly, accruals, retail-holder growth, quarterly margin change (2020+) | none helped |
| 5 slots for recent IPOs | −0.7 pts |
| no rebalance in a bear market / hold the index in a bear | no help / worst year −23 % but −6.9 pts in 2016–20 |
| hold 24 months / hold until the conviction signal breaks | −3.7 / −5.8 pts (a yearly refresh wins) |
| liquidity floor ₹1 crore / ₹2 crore a day | +5.2 % / +0.7 %/yr (**the edge sits in stocks trading ₹0.5–1 crore a day**) |
| top 10 instead of 30 | similar median, worst −36 % |
| ≤ 4 per industry; top 100 with superinvestor entries promoted into the 30; ₹0.25 crore floor | none passed (the lower floor lost the first half under doubled costs) |
| sector policy score | passed the rule, then **disqualified**: its input was a hand-curated 2026 list of policy events with hindsight weights |

- **Funnel width:** of 485 pond stocks that later tripled in 3 years (2017–2023 snapshots), the top 100 held 177 (158 expected by chance) and the top 30 held 63 (47 by chance).
- **Overlap** with the investor's two existing small-cap books: 2–10 % of names.

**D. Known limitations (stated by the designers):**
- Survivors-only fundamentals.
- Effectively 2–3 independent 3-year windows, dominated by the 2020–24 Indian small-cap boom.
- Some safety gates (pledge, GSM, SEBI orders) could not be applied historically.
- The backtest's market cap used annual share counts carried through splits × raw price, while live uses a different, consistent source.
- The cost model is calibrated at ₹1 lakh trades.
- Stage-3 and stage-5 human picks cannot be backtested.
- The superinvestor list is chosen with hindsight.
- The LLM narrative is untested as a decision aid.

## What to assess

1. **Statistical validity:** look-ahead, survivorship, multiple testing (about 37 variants plus earlier exploratory work), overlapping labels, effective sample size, regime dependence. Do the numbers support "grade C, a shortlist for judgement"? Too generous, or too harsh?
2. **Economic rationale:** is this an edge or a repackaged small-cap value + momentum + illiquidity premium (a risk premium that pays in bull markets and hurts in bears)? Would a cheap small-cap value-momentum index or fund capture most of it? What does Indian evidence say?
3. **Capacity and execution:** an edge that lives in stocks trading ₹0.5–1 crore a day. What breaks at ₹50 lakh, ₹2 crore or ₹10 crore? Circuit limits, impact, exit in a crash, tax drag.
4. **Funnel design:** a mechanical top 100 followed by human picks. Where does human judgement add value, and where does it add bias (narrative, recency, herding after superinvestors)? How should the human stages be measured so their value can be known within 2–3 years?
5. **Risk:** no stop-losses, 10 held names, a backtested worst year of −33 % against the index, yearly refresh. Is the sizing and review logic coherent? What kill switch would you set?
6. **What is missing:** signals, data, gates or tests that matter for Indian small caps (promoter quality and governance, related-party dealings, operator activity, SME-to-mainboard migration, F&O inclusion, index-inclusion flows, earnings quality, working-capital stress, government-order dependence). Only include what is plausibly testable with public Indian data.
7. **Falsification:** which forward results over the next 12–24 months should make the investor abandon or change this? Give concrete thresholds.
8. **The valuation football field:** are the methods sensible for small Indian companies (thin analyst coverage, short multiple histories, volatile cash flows)? What would you change?

## Output format

1. **Verdict** in 3 sentences: keep / modify / abandon, and why.
2. **What is sound.** At most 6 bullets, specific.
3. **Top 5 problems, ranked by impact on real money.** For each:
   - the issue;
   - the evidence in the facts above (quote the number);
   - how likely and how damaging it is;
   - the concrete fix or test, with a pass bar.
4. **Numbers that look implausible or inconsistent.** Say which, and why.
5. **Tests to run next.** At most 6, each with its data source, rule and pass bar, written so they can be pre-registered.
6. **Forward kill rules** for the live shortlist and the 10-name book.
7. **Open questions** you could not judge from this brief.

Keep it under 1,500 words. Cite published research where you rely on it (author, year), Indian evidence first. Say "I don't know" rather than guess.
