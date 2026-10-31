# Research 0008 — independent critique of the multibagger framework: findings

Written 2026-10-16 (Amit: "execute docs/research/0008-multibagger-critique-prompt.md"). The [critique prompt](0008-multibagger-critique-prompt.md) was run by a fresh reviewer agent that read only the prompt file (no plan, study, ADR, code or DB access) and could web-search to verify citations. The text below is its report, unedited. The designers' response and any tests adopted go in [plan 0026](../plans/0026-multibagger-desk.md) "Implementation notes", not here.

**Headline:** modify, size as a small satellite. Grade C is fair, but the statistical case is weaker than DSR 0.961 / PBO 0.29 suggests: wrong benchmark (cap-weighted SMALLCAP 250 vs a ≤ ₹5,000 crore equal-weight pond), nominal deflation (one-sided Φ(1.90) = 0.971 ≈ DSR), survivors-only halving lift, funnel-width arithmetic implying a ~300-name historical pond vs 755 live.

---

## 1. Verdict

**Modify, and size it as a small satellite.** The honest read of the numbers is that this is a well-documented small-cap value + illiquidity tilt with a mild momentum overlay (top-30 lift 1.24× against single-trait lifts of 1.2–1.5×), earning roughly what Indian factor literature says such a tilt earns, not a multibagger-finding edge. The grade-C label is fair, but the statistical case is weaker than "DSR 0.961 / PBO 0.29" makes it look (t 1.90 on ~9 effective years, benchmark mismatch, survivors-only value evidence), so capital should follow the risk budget, not the backtest.

## 2. What is sound

- Rules written before the first run; 25 changes pre-registered and all honestly rejected, including a passing variant disqualified for hindsight input. This is rarer than it should be.
- The pond deliberately drops the ROCE/debt/growth quality screen that caught only 3 of 74 ten-baggers (0.35×): consistent with the full-market finding that ROCE ≥ 18 % had 0.65× odds, and with the base-rate logic that multibaggers start cheap and unloved.
- Full-market, delisting-inclusive trait odds for the price-based traits, and the correct demotion of "high volatility" (1.37× survivors → ≈1.0× full market).
- Costs from a liquidity impact model calibrated on own fills, plus tax; the flat 31 bps result (+13.6 %) is close to the impact-model result (+12.7 %), so costs are not hiding the answer at ₹30 lakh.
- Equal-weight five-part score with no fitted weights; every part dropped costs 0.5–2.2 pts, which is what diversified noisy signals look like rather than a tuned one.
- The limitations list (D) is more candid than most sell-side factor papers.

## 3. Top 5 problems (ranked by impact on real money)

**1. The excess return is measured against the wrong benchmark, so "+12.7 %/yr" is largely the size and equal-weight premia.**
Evidence: pond = market cap ≤ ₹5,000 cr, outside the 250 most-traded; benchmark = NIFTY SMALLCAP 250 (cap-weighted, ranks 251–500 by full market cap, many names > ₹5,000 cr). "Any part alone +4.7 to +8.4 %/yr" including smallness alone. Agarwalla, Jacob & Varma (IIMA WP 2013-09-05; Vikalpa 2017) report large SMB and HML premia in India after survivorship correction; Amihud, Hameed, Kang & Zhang (JFE 2015) report an emerging-market illiquidity premium of roughly 1.1–1.3 %/month.
Likelihood high, damage moderate: you would still earn the premium, but you are paying attention costs for selection alpha that may be near zero.
Fix: re-run T2 against the **equal-weight pond** (same gates, no score). Pass bar: top-30 beats EW pond by ≥ 5 %/yr median with t ≥ 1.5 across the 12 starts; otherwise the score is a tilt, and a cheaper mechanical pond basket is the product.

**2. The multiple-testing correction is nominal.** Evidence: t 1.90 on annual excess; DSR 0.961; one-sided Φ(1.90) = 0.971, so the "deflation" over 21 variants removed almost nothing. That is only possible if the 21 variants have near-identical Sharpes (near-clones), in which case 21 is not the trial count. The real trials include the earlier quality funnel this replaced, the trait study that chose the five parts, and ~37 variants. Harvey, Liu & Zhu (RFS 2016) argue t ≥ 3 for a newly claimed factor; Bailey & López de Prado (JPM 2014) and Bailey, Borwein, López de Prado & Zhu (J. Comp. Finance 2017) warn PBO on correlated variants is uninformative.
Likelihood high that true t is < 1.5; damage moderate (the premium still exists; the selection layer may not).
Fix: recompute DSR with the trial count set to every configuration ever evaluated on this window (including the quality funnel) and report the variance of trial Sharpes. Pass: DSR ≥ 0.90 at the honest N. Also the pre-set T1 bar failed 4/8 and was superseded by the ADR 0073 grade rule; record that as a goalpost move.

**3. The edge lives where capacity and crash exits do not.** Evidence: ₹1 cr floor drops excess to +5.2 %/yr, ₹2 cr floor to +0.7 %/yr; ₹0.25 cr floor fails under doubled costs. Costs calibrated at ₹1 lakh per name. GSM/ESM/ASM frameworks put small caps on 5 % (or 2 %) bands and trade-for-trade settlement, and GSM stage II+ requires 100 % additional surveillance deposit (BSE GSM annexure; exchange circulars 2017). At a ₹2 cr book (₹6.7 lakh/name) you are 7–13 % of daily traded value; at ₹10 cr (₹33 lakh/name) you are 33–66 % and cannot exit a lower-circuit stock for days.
Likelihood certain if the book grows; damage high in a 2018-type bear (small-cap index fell ~36 % in 2018; many constituents 60–80 %).
Fix: cap the strategy at a book where the median name ≤ 5 % of 20-day ADTV (about ₹1 cr per ₹1 cr ADTV name → ~₹3 cr book). Re-run T2 with impact at 3× and 10× the calibrated size; pass if excess ≥ +5 %/yr at 3×.

**4. The value and quality evidence is survivors-only, and the halving result is too good.** Evidence: "P/B ≤ 1: 1.47×" and "halving 0.28×" come from the 588 survivors; delisted and suspended stocks (the typical fate of cheap, pledged, illiquid names) are absent from exactly the bucket the score favours. The price-only full-market run gives return (+11.7 %, t 2.22) but no halving lift. A 72 % cut in halving odds alongside only a 24 % rise in tripling odds is the signature of the price trigger (near 52-week high excludes already-distressed names) plus survivorship.
Likelihood high that true tail protection is weaker; damage high because "no stop-loss" rests on it.
Fix: compute the halving lift and the ≤ 0.3x lift on the full-market price-only sample, counting delistings at the last traded price. Pass: halving lift ≤ 0.7× including delisted.

**5. Ten hand-picked names with no stop-loss, no backtest of the human stage, and a 2–3 regime history.** Evidence: worst 12-month excess −33 % (top 10: −36 %); losers at 0.14x and 0.22x in the superinvestor sample; "Stage-3 and stage-5 human picks cannot be backtested"; 8 overlapping anchors ≈ 2–3 independent windows dominated by 2020–24. Human selection in a narrative-rich card environment tends to buy story and recency (the card shows known-investor entries, which the test showed add nothing).
Fix: run the 30 EW shortlist as the primary paper book and log the 10 against it from day one (section 6); size the 10 at ≤ 10 % of the equity portfolio; cap any name at 10 % of the book at cost.

## 4. Numbers that look implausible or inconsistent

- **Funnel width implies a historical pond of ~300 names, not 755.** 177 of 700 top-100 slots = 25 % hit; "158 by chance" = 22.6 % base rate; 485 triples / 22.6 % / 7 snapshots ≈ 307 pond names per snapshot. The live pond (755) is 2.5× the tested one, so the score is deployed on a population it was not tested on (the extra names are mostly those without historical fundamentals: the smallest). Also a 22.6 % three-year tripling base rate is itself a boom-period, survivors-only number.
- **Lifts disagree across tables.** Funnel width gives top-30 lift 63/47 = 1.34× and top-100 1.12×; T1 gives 1.24×. Different anchor sets, but the spread is as large as the claimed effect. Top-30 z ≈ 2.6 (binomial sd ≈ 6) before overlap correction; top-100 z ≈ 1.7.
- **DSR 0.961 vs t 1.90**: see problem 2; the deflation is ≈ 1 percentage point.
- **"77 % of 10x stocks had market cap < ₹1,000 cr"** is reported without the base share of sub-₹1,000 cr names among the 588. If that share is ~65 %, the lift is ~1.2×, not the headline it looks like.
- **t 1.90 with sd implied ≈ 20 %/yr** (12.7 × √9 / 1.9) is consistent with a −33 % worst year, so the dispersion figures hang together; it also means two forward years cannot statistically separate the strategy from zero (se ≈ 14 %).
- **Quarterly "business trigger" lag is not stated.** Annual data is lagged 150 days; if quarterly data is keyed to quarter-end rather than announcement date, the 2019+ results contain look-ahead.

## 5. Tests to run next (pre-registrable)

1. **EW pond benchmark.** Data: existing backtest. Rule: top-30 vs EW pond, 12 starts, same costs. Pass: ≥ +5 %/yr median, t ≥ 1.5.
2. **Full-market tail test.** Data: bhavcopy incl. delisted, price-only score. Rule: halving and ≤ 0.3x lifts for top 30 vs pond. Pass: halving ≤ 0.7×.
3. **Honest DSR.** Data: every configuration ever run on this window. Rule: DSR with full N and observed Sharpe variance. Pass: ≥ 0.90.
4. **Quarterly look-ahead audit.** Data: BSE announcement timestamps. Rule: rebuild the business trigger on announcement dates; compare T2. Pass: excess within 2 pts of current.
5. **Promoter-action overlay.** Data: BSE/NSE insider-trading (PIT) and SAST disclosures, quarterly shareholding patterns from 2016. Rule: add "promoter net buying / holding up over 4 quarters" as a sixth part. Pass: existing accept rule (≥ 1 pt both halves, tails not worse).
6. **Cash-conversion gate.** Data: annual CFO, EBITDA, receivable days. Rule: exclude bottom decile of 3-year CFO/EBITDA and top decile of receivable-day growth. Pass: same accept rule; report how many future 10x names it would have excluded (must be ≤ base rate).

## 6. Forward kill rules

- **Run three books in parallel from day one:** EW pond (gates only), EW top 30, the hand-picked 10. All logged at live fills.
- **Score kill:** if after 24 months the EW top 30 trails the EW pond by > 5 pts cumulative, the score adds nothing; drop stages 2–4 and hold a pond basket or an index.
- **Human kill:** if the 10 trail the EW 30 by > 10 pts cumulative at 24 months, or the hit rate of the 10 (names up ≥ 50 %) is below the 30's at 24 months, stop hand-picking.
- **Risk kill:** any rolling 12-month excess vs NIFTY SMALLCAP 250 below −35 % (beyond the backtest worst) halts new buying and triggers a redesign review, not a forced sale into lower circuits.
- **Name kill (process, not price):** auditor resignation, pledge > 50 %, GSM/ESM entry, promoter stake down > 5 pts in two quarters, or results not filed on time: exit on the next liquid session regardless of the thesis.
- **Capacity kill:** book grows so that any name > 10 % of 20-day ADTV: stop adding.

## 7. Open questions I could not judge

- How t 1.90 was computed: on non-overlapping annual excess per path, or pooled across 12 overlapping paths (which would inflate it ~√12).
- Returns on delisted names in the full-market run (last price? zero?).
- The base shares behind the trait odds (sub-₹1,000 cr, P/B ≤ 1) among the 588.
- Whether "industry" uses today's classification historically.
- What the 150-day annual lag does to the cheapness part in years when results were late or restated.
- Football field: a 13–15 % cost of equity is too low for ₹300 cr illiquid companies (add an illiquidity/size premium to 16–20 %), and a 10-year DCF on volatile cash flows is mostly terminal value. I would lead with reverse DCF and mid-cycle EV/EBITDA against a hand-chosen peer set, add EV/Sales for loss-makers and replacement-cost for capital goods and steel, and drop analyst targets where coverage is < 3 houses. Whether the existing bands are computed on normalised or reported earnings I cannot tell from the brief.

Citations verified via search: Agarwalla, Jacob & Varma (IIMA WP 2013-09-05; Vikalpa 2017); Amihud, Hameed, Kang & Zhang (JFE 2015); Bailey & López de Prado (JPM 2014); Bailey, Borwein, López de Prado & Zhu (J. Comp. Finance 2017); BSE GSM annexure and 2017 exchange circulars. Harvey, Liu & Zhu (RFS 2016) and the 2018 small-cap drawdown figure (~36 %, fund-house data citing NSE) are from memory and secondary sources respectively; treat the latter as approximate.
