# Research 0007 — findings, first pass (2026-10-13)

Answers [the brief](0007-long-horizon-deep-research-prompt.md) only in part. The generic deep-research workflow ran: 6 search angles, 24 sources, 93 claims extracted. It **checked only the top 25** (3 checker votes each: 18 kept, 7 refuted). The other 68 claims were never checked. They appear under "Leads not checked" and are not evidence yet.

**Bottom line.** Portfolio construction is well supported (US peer-reviewed): use a buy/hold band, trade partway toward a target, and give more weight to slow signals. Indian evidence backs three slow-signal priors: Piotroski F-score at 1 year, quality driven by profitability and payout, and value × quality. All are gross of costs, in-sample, from weak sources, and end by 2022. Treat them as priors to test, not effect sizes. Of the thesis monitors, only promoter pledging survived, and only as a crash-risk flag. Playbooks (C), new data (B) and the validation protocol (F) have no checked evidence.

## Coverage against the 7 deliverables

| # | Deliverable | Status |
|---|---|---|
| 1 | Slow-signal shortlist (≤15) | Partial: 3 checked priors (below) |
| 2 | Playbook rule cards | None checked; Marcellus claims refuted |
| 3 | Thesis-monitor catalogue | Pledging only; both credit-rating claims refuted |
| 4 | Construction recipe | Direction checked (3 US papers) |
| 5 | Validation protocol | None checked (good leads below) |
| 6 | Do-not-do list | Not produced |
| 7 | 90-day plan | Not produced |

## Checked findings

| Finding | Grade · region | Vote |
|---|---|---|
| **Quality premium in India.** QMJ 4-factor alpha 0.92%/mo; long-only top quality decile 0.69%/mo; long-only top-250 about 0.67%/mo (SE 0.201). Top 1,000 stocks, 1995–2021. Caveats: 1-month returns, gross, factor-model alpha (not vs tier), loads on size, premium weaker 2016–21, no top-100 test. [IIMA WP-2022-11-01](https://www.iima.ac.in/publication/performance-quality-factor-indian-equity-market) | Working paper · India | 3-0 |
| **Which part of quality.** Profitability (1.375%/mo) and payout (0.621%/mo) are significant; growth and safety are not. "Payout" here is mostly net equity/debt issuance, so it overlaps asset growth. Build a net-issuance/payout slow feature from 10–11 yrs of statements. Same source. | Working paper · India | 3-0 |
| **Value × quality beats quality alone.** BSE 2003–2020: quality alone gave no substantial risk-adjusted return; value + quality gave positive, significant alpha. Abstract only. Conflicts with IIMA long-only result (different universe and measure). [Kaur, Seth & Singh 2024, Managerial Finance](https://www.emerald.com/insight/content/doi/10.1108/MF-02-2023-0112/full/html) | Peer-reviewed (low/mid tier) · India | 3-0 |
| **Piotroski at 1 year.** About +4.93 pts of 1-yr market-adjusted return per F-score point among high-B/M stocks ([Singh & Kaur 2015](https://www.emerald.com/insight/content/doi/10.1108/IJLMA-09-2014-0055/full/html)); about +3.7%/pt, high-minus-low 14.2% (t 5.48), 2013–22 Prowess ([Rastogi 2025, ISB](https://eprints.exchange.isb.edu/id/eprint/2415/)). **Caveat:** the high F-score group's *median* excess return is +0.6% (mean 17.6% is skew), the middle group also beats Nifty 500 by 9.6%, and median market cap is about ₹156 cr. Direction matches our IC rising with horizon. | Low-tier peer-reviewed + dissertation · India | 3-0 |
| F-score works less well with high institutional ownership and better for smaller, less-covered firms. This fits wiring it on MID/SMALL only, but mapping it to our tiers is inference. Rastogi 2025. | Dissertation · India | 2-1 |
| **Pledging = crash-risk flag, not a return factor.** Higher pledging predicts higher crash risk and worse firm performance (257 BSE-500 firms, 2011–20). [Kalia 2024, JAMR](https://ideas.repec.org/a/eme/jamrpp/jamr-01-2023-0003.html). Univariate pledge-date reaction negative ([Bang, Sonti, Thirumalai, ISB](https://www.isb.edu/faculty-and-research/research-directory/market-reaction-to-share-pledges-evidence-from-india)); after controls the direction is unresolved. Use it as a **review** alert. | Peer-reviewed (mid tier) · India | 3-0 |
| **Buy/hold spread is the best single cost cut.** It beats trading only cheap stocks and staggered rebalancing. Anomalies under ~50% one-sided monthly turnover mostly keep net returns. [Novy-Marx & Velikov 2016, RFS](https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf). STT makes this stronger in India. | Peer-reviewed (top) · US | 3-0 |
| **Trade partway toward an aim portfolio; give slow-decaying signals more weight.** This means down-weighting the delivery-anomaly z-score against Piotroski. [Gârleanu & Pedersen 2013, JF](https://www.nber.org/papers/w15205). Quadratic-cost model, so bands are inferred from it, not derived. | Peer-reviewed (top), theory · US | 3-0 |
| **Costs favour more characteristics.** 15 significant with costs vs 6 without, because trades across signals partly cancel. Supports a multi-factor slow composite. [DeMiguel et al. 2020, RFS](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2180-2222..html). The counts don't carry over to India. | Peer-reviewed (top) · US | 3-0 |

## Refuted (don't cite)

- Marcellus CCP "98.2% / 18.6% CAGR" and its "ROCE + revenue consistency" screen (1-2): self-reported, no benchmark, no net/gross statement.
- "Quality mainly works as an avoid filter / QMJ comes from the junk leg" (0-3): over-inference from an abstract.
- "After controls, pledge reaction is positive" (0-3).
- Indian credit-rating event study (Dawar et al. 2023): "downgrade is a lagging trigger" and "downgrades matter, upgrades don't" (both 0-3). Its ±7-day window can't speak to 3–6 months. A checker cited [Dichev & Piotroski 2001, JF](https://onlinelibrary.wiley.com/doi/10.1111/0022-1082.00322) (US): about 10–14% negative abnormal return in the year after downgrades. That makes downgrades a plausible monitor, but it is untested in India.
- Novy-Marx–Velikov "10%/20% UMD band = 0.51%/mo, t 2.87" (0-3): cite the general result only.

## Leads not checked (extracted, never voted on)

Useful for a second pass. Do not cite as findings.

- **C, Coffee Can, live record** ([holisticinvestment.in](https://o.holisticinvestment.in/?p=55753), blog): net 12.8% CAGR since June 2017 vs Nifty 50 TRI 11.9%. Negative over 5/3/1 years. Beat the index in 47% of rolling 1-yr windows. Screen: 10+ yrs of >10% revenue growth and >15% ROCE; 3–5-yr horizon.
- **C, Marcellus CCP** (self-reported): 8–10-yr intended hold, no explicit sell rule. It doesn't match a 3–12-month horizon.
- **A/E, turnover and factors** ([freefincal](https://freefincal.com/does-factor-investing-outperformance-fail-for-high-turnover-stocks/), blog, Nifty 500 2006–25, net of costs and tax): low-scaled-turnover halves beat high-turnover halves for quality and momentum (momentum 15.04% vs 11.89% net CAGR). No difference for low-vol. This is a testable conditioning variable: liquidity/attention.
- **B, report-text change** ([Lazy Prices, JF 2020](https://www.nber.org/papers/w25084), US): firms whose filings change underperform. No price reaction on the filing date; the return comes over months. The non-changer long leg earns positive alpha. Most informative sections: CEO/CFO, litigation, risk factors. India would need annual-report PDFs.
- **B, NSE XBRL** ([nseindia.com/companies-listing/xbrl-information](https://nseindia.com/companies-listing/xbrl-information)): structured filings for Reg 23(9) related-party transactions, auditor/KMP/director changes and resignations, credit ratings, shareholding, results. This is a possible free, machine-readable route for B and D. Start dates and point-in-time behaviour are not yet probed.
- **F, overlap** ([Fed IFDP 853](https://www.federalreserve.gov/pubs/ifdp/2006/853/revision/ifdp853r.htm)): Newey-West long-horizon tests over-reject (~20% at nominal 5%). Simple fix: divide the OLS t by √(horizon in periods). Longer horizons give no power gain from a short sample.
- **F, deflated Sharpe** ([Bailey & López de Prado 2014](https://papers.ssrn.com/abstract=2460551)): log every trial; deflate by the effective number of independent trials (shrink correlated variants via their average correlation).
- **F, shrinkage** ([Jensen, Kelly & Pedersen 2023, JF](https://research-api.cbs.dk/ws/portalfiles/portal/95651880/theis_ingerslev_jensen_et_al_is_there_a_replication_crisis_in_finance_publishersversion.pdf)): empirical-Bayes shrinkage toward zero, borrowing from theme clusters and other countries. Factor alphas outside the US are of similar size. Out-of-sample alpha decays about 47% from in-sample. This is the basis for shrinking our 13-window estimates toward global premia.
- **F, long-horizon caution** ([Boudoukh, Israel & Richardson 2019, FAJ](https://ideas.repec.org/a/taf/ufajxx/v75y2019i1p17-30.html)): found by search, not fetched.

## Open questions

1. Does long-only profitability + net issuance/payout, combined with value, keep a within-tier edge at 6–12 months in our panel, net of 15.7/17.9/30.5 bps and tax? Can 10–11 yrs of statements extend the test? Does any of it hold in LARGE (top 100)?
2. How much of the Indian F-score effect is left above ₹1 cr/day liquidity, measured against the tier median rather than Nifty 500?
3. Is a rising pledge a 3–6-month return predictor or only a left-tail flag?
4. Which Indian playbooks have independent, benchmark-relative, net-of-fee records? Which validation protocol decides with ~13 effective windows?

---

# Second pass, part 1: playbooks (C) and validation (F) — 2026-10-13

Focused run: 24 sources, 108 claims, top 25 checked (20 kept, 5 refuted).

## C. Playbooks: what has a checked Indian record

- **NSE factor indices after launch: no significant alpha.** [Lalwani 2022/23, Applied Finance Letters 11:94–108](https://ojs.aut.ac.nz/applied-finance-letters/article/view/604) (peer-reviewed, low tier, India, 3-0). Nine indices, live ≥ 5 yrs, data to Aug 2022, 4-factor model.
  - Live monthly alpha: Quality 30 −0.1 % (t −0.33), Low Vol 30 −0.1 %, Low Vol 50 +0.1 %, Alpha 50 +0.2 % (t 0.97).
  - Six of nine had t > 2 in their **backtests**. Alpha fell significantly after launch in four (Quality 30 −0.9 %/mo, t −2.78; Growth Sectors 15 −1.3 %/mo, t −2.11), and none rose.
  - This is the best Indian evidence that backtests decay once live. Caveat: low power, and it misses the 2023–24 momentum run.
- **NSE's headline records are back-calculated and gross of fees** (practitioner/marketing, 3-0):
  - Nifty200 Quality 30: 18.2 % vs 12.9 % (2005–18), all backtest; it trailed in the 3 years before launch.
  - Nifty200 Momentum 30 TRI: 19.3 % vs 14.3 % (2005–Aug 2025). About 15 of those 20 yrs are backtest, and the last year was −19.5 % vs −4.0 %.
  - Multi-factor indices: 16–20 % vs 13.5 % (2005–17), all backtest.
- **Multi-factor index rule** (2-1, rebuildable in principle): 30 stocks from Nifty 100 + Midcap 50 (our LARGE + upper MID), equal-weight composites of alpha / quality (ROE, D/E, PAT change, 3 yrs positive PAT) / value / low vol, with an entry/exit buffer whose thresholds aren't published.
- **Nothing checked** for QGLP/100x, Good & Clean, Basant Maheshwari, magic formula, CANSLIM/Minervini, Pabrai, Lynch, Buffett/Munger, APMI PMS data or factor-fund NAVs. Unanswered, not refuted. The likely reason is that no audited, codified Indian record exists (judgment, not checked).
- Refuted: "Alpha 50 +8.1 %/yr live vs Nifty 500" (0-3); the Quality 30 rule as described (0-3); Momentum 30's trailing 3–15-yr leads (1-2).

## F. Validation with short history: checked methods (all peer-reviewed, not India)

- **The sample is ~13 independent 6-month windows, not 83** ([Boudoukh-Israel-Richardson, FAJ 2019](https://rpc.cfainstitute.org/en/research/financial-analysts-journal/2018/0015198X-2018-1547056); [Hjalmarsson, JFQA 2011](https://www.federalreserve.gov/pubs/ifdp/2006/853/revision/ifdp853r.htm)). Power grows with sample ÷ horizon and falls as the horizon lengthens.
- **Newey-West / Hansen-Hodrick t on overlapping labels over-reject.** Nominal 95 % intervals cover 76–78 % at k = 12, T = 100; expect roughly 80–90 % in our case (interpolated). **t/√horizon is not an exact fix (refuted 0-3).**
- **Fix: the Britten-Jones–Neuberger–Nolte transformed regression** ([JBFA 2011](https://openaccess.city.ac.uk/id/eprint/15212/1/JBFA%20Overlapping%20observations%20with%20BrittenJones.pdf)). Same coefficients, and OLS/White standard errors then give near-nominal coverage; it extends to Fama-MacBeth. Alternatively, use non-overlapping subsamples at each start offset.
- **Deflated Sharpe ratio** for a variant picked from many ([Bailey & López de Prado, JPM 2014](https://papers.ssrn.com/abstract=2460551)): estimate N from the correlation between variants (not 48), and use effective, not raw, observations.
- **Probability of backtest overfitting via CSCV** ([Bailey et al., J. Comp. Finance 2017](https://papers.ssrn.com/abstract=2326253)): use S = 6–8 blocks so each holds a full 6-month label. The authors' bar is PBO ≤ 0.05.
- **Minimum track record length** ([Bailey & López de Prado, J. Risk 2012](https://www.risk.net/journal-risk/2223785/sharpe-ratio-efficient-frontier)). Arithmetic (iid Normal, synthesis): years ≈ (1.645 / IR)².
  - IR 0.5 → 11 yrs; 0.8 → 4.2 yrs; 1.0 → 2.7 yrs.
  - Passing in 24 months needs IR ≥ 1.16; in 12 months, ≥ 1.65.
  - Our best SMALL book implies IR ≈ 0.7, so **a 12–24-month forward test would almost surely be inconclusive.**

### Protocol (synthesis; the thresholds are judgment)
1. Headline t's come from the BJNN regression or non-overlapping subsamples at all 6 offsets, never a Newey-West t on overlapping labels.
2. For a rule chosen from variants: require DSR ≥ 0.95 (with N estimated from correlations) and PBO ≤ 0.2 (S = 6–8).
3. If both pass, freeze the rule with its benchmark net of costs and tax, and set the forward horizon from MinTRL at **half** the backtest IR. Accept only at that horizon, with no peeking-and-stopping.
4. If either fails (as our 48-variant search already has), there is no forward test of "the best variant". Either test one rule pre-registered for economic reasons, or hold the index.

**Can be done now from our own data:** DSR and PBO for the 48 long-hold variants per tier (`data/lh/book_monthly.parquet`).

---

# Second pass, part 2: new data (B) and thesis monitors (D) — 2026-10-13

Focused run: 22 sources, 95 claims, top 25 checked (18 kept, 7 refuted). **Most of B and D are still unanswered.** Nothing checked came back on the format, history depth or point-in-time traps of any new source, and no Indian study measures a 3–6-month window. Every one measures days or same-period levels.

## Checked

| Signal | Evidence | Action for us |
|---|---|---|
| **How to exit** | [Akepanidtaworn, Di Mascio, Imas & Schmidt, JF 2023](https://conference.nber.org/conf_papers/f119118/f119118.pdf) (peer-reviewed, 783 institutional portfolios, not India, 2-1). Sells lose ~70–80 bps/yr vs random selling, while buys beat random by >100 bps. The loss sits in heuristic sells of extreme past winners and losers (~150 bps for the top quartile). Sells on the stock's own earnings-announcement day beat others by >200 bps/yr. | **Alerts trigger a review, never a price-based exit.** This is the clearest design rule we have. |
| Credit-rating downgrade | India: only announcement windows; bank stocks fall *before* the downgrade (Kushwah & Vigg 2023; Krishnan, Basu & Thampy 2019/20). Brazil: about −25 % over 12 months but −10 % (n.s.) at 6 months, on 42 downgrades clustered in 2015 (Baraccat et al. 2020). | Review, not exit. India 3–6-month drift is **untested**; we can test it with `tools/event_study.py` on the BSE rating stream. |
| Related-party transactions | India, same-period only. Intensity goes with lower ROA in large caps (Srinivasan, IIMB WP 2013); on average RPTs look like efficiency, not tunnelling (Rasheed et al. 2023, 2,294 firms); more disclosure goes with lower crash risk. | Not a blanket negative. Watch only loans, guarantees and asset transfers to promoter entities (untested for returns). |
| **Accruals / cash vs profit** | India BSE-500 1997–2010: high-accrual stocks did *not* underperform (2.3 % vs 1.9 %/mo, n.s.) ([Sehgal et al. 2012](https://businessperspectives.org/index.php/journals/investment-management-and-financial-innovations/issue-87/accruals-and-cash-flows-anomalies-evidence-from-indian-stock-market), low tier, old). | No accrual-based exit. Note the live MID weight on cash-flow accruals (−0.10) rests on our own test only. |
| **Beneish M-score** | The claim "flagged firms earn ~12 pts less over 12 months in India" was **refuted 1-2**; "concentrated in small caps" was refuted 0-3. | No outside support for the −0.2 forensic penalty. Consistent with the [winners post-mortem](../studies/winners-postmortem-2026-10.md). |
| ASM / GSM surveillance entry | NSE working papers: short-term ASM entrants have a +10.5 % 5-day run-up, then −0.9 %; GSM Stage I underperforms controls by 3–5 % over 5–10 days; Stage 0 has no effect. | A liquidity and governance review flag (GSM I restricts trading), not a return exit. |
| Annual-report text change | China only: higher year-on-year similarity goes with crash risk 2 yrs later (fragile); MD&A reuse has a conditional sign. No Indian evidence. | Low priority. |
| Auditor resignation | Anecdote only (2018: Manpasand, Atlanta, Vakrangee fell 29–64 %, mostly *before* the resignation; Vakrangee was later cleared). | Review flag; testable on BSE announcements since 2018, alongside our governance-resignation factor (MID t −3.82). |

Refuted, do not reuse: a weaker post-GFC rating reaction; positive bank returns after a downgrade; the ICRA "Issuer Not Cooperating" reading; NSE-IGIDR 3-day block-deal returns; the Beneish return gap (both versions); an expert view on mid-audit auditor resignation.

## Unanswered (needs a sourcing pass or our own test)
Audit qualifications / emphasis of matter, order books, segments, employee counts, GeM/CPPP wins, trademarks/patents, DGCI&S exports, management tenure, MCA21 charges. Monitors for earnings misses, guidance cuts, revision collapses, working-capital blow-ups, margin compression, momentum crashes, delivery collapse, promoter/fund block exits, F&O ban, circuit changes, CFO/CEO/independent-director resignations, SEBI orders. No false-alarm rates anywhere.

---

# Deliverable 6 — Do-not-do list (from all three passes + our studies)

1. **Don't report a Newey-West t on overlapping 6–12-month labels as evidence.** It over-rejects. Use non-overlapping subsamples or the BJNN regression. Don't use t/√h as an exact fix.
2. **Don't run a forward test of "the best of 48 variants".** It failed the haircut, and a 12–24-month test can't confirm IR ≈ 0.7.
3. **Don't trust NSE / AMC factor-index backtests as priors.** Live alphas after launch were ≈ 0, and four fell significantly.
4. **Don't sell on price extremes** (biggest winner or loser). Alerts open a review; the exit comes from the slow score falling below the hold band.
5. **Don't penalise fast growers with the Beneish M-score** (−0.2 is unsupported; the outside claim was refuted; it sank NETWEB). Don't add accrual-based exits (the Indian accrual anomaly runs the wrong way).
6. **Don't add plain growth factors.** Annual growth and acceleration don't predict 3–12 months (2019–26).
7. **Don't build a Coffee-Can-style "consistent high ROCE" book for MID.** It lost in every period since 2020. Value × quality, not quality alone.
8. **Don't treat a downgrade, ASM/GSM entry or RPT volume as an exit.** None has Indian 3–6-month evidence.
9. **Don't put fast signals (delivery anomaly z, announcement CAR) in a long-hold score.** They whipsaw ranks (TIMETECHNO 4th → 96th → 16th percentile) and add nothing at 6 months.
10. **Don't expect LARGE to beat the index.** No factor has out-of-sample skill; hold the index.

# Deliverable 7 — 90-day research plan (prioritised; each step is read-only until Amit approves a weight change)

| # | When | Work | Decides |
|---|---|---|---|
| 1 | Week 1 | **DSR + PBO on the 48 long-hold variants per tier** (`data/lh/book_monthly.parquet`, S = 6–8 blocks, N from correlations) | Is there anything to forward-test at all? |
| 2 | Week 1–2 | **Re-run the long-hold book on a slow-only score:** mom_6m + value × quality + Piotroski, no delivery or event signals (SMALL, MID) | Does the winners/growth evidence survive costs + tax? |
| 3 | Week 2 | **Re-test the forensic penalty on 2016+ history** (M-score and Altman Z rebuilt from annual Screener) → size it from evidence or convert it to a review alert | Removes the NETWEB failure mode |
| 4 | Week 3–4 | **Thesis-monitor event studies on our own data** (`tools/event_study.py`, BSE 2018+): rating downgrades, auditor / CFO resignations, GSM Stage I, promoter block exits, at 63–126 sessions with false-alarm rates | The monitor catalogue, with India evidence |
| 5 | Week 4–6 | **Design and replay review-then-exit** on the plan 0024 SMALL book: alerts open a review, exit only if the slow score also falls below the hold band; measure turnover and false alarms | The monitor system, without churn |
| 6 | Week 6–9 | **Longer quarterly history:** sourcing pass on BSE/NSE XBRL results 2018+ → quarterly margin expansion and acceleration over 6+ years | Settles the one fundamental lead (MID q_margin_chg) |
| 7 | Week 9–12 | **Extend price-only factors to the 1990s** via bhavcopy incl. delisted names (momentum, low vol, 52-week position) → more independent windows, survivorship-free | More power for the slow price signals |
| — | Throughout | Pre-register each test's features and bar in the tool docstring before running; log every test in the multiple-testing family | Keeps the haircut honest |
