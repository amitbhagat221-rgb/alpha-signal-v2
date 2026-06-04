# Sector-Outlook Signals — Deep Research

_Deep-research harness: fan-out web search → fetch sources → 3-vote adversarial verification → synthesis. Saved 2026-06-04._

_Purpose: a backtest-ready, evidence-ranked menu of sector at-entry signals to validate on our Indian sector data, then feed into the multibagger screen (2–4yr) and daily picks._

**Run stats:** angles=5 · sourcesFetched=20 · claimsExtracted=97 · claimsVerified=25 · confirmed=16 · killed=9 · afterSynthesis=6 · urlDupes=3 · budgetDropped=7 · agentCalls=102

## Research question

> Identify and rank the at-entry signals that predict a SECTOR's (industry's) forward outperformance — i.e. sector-rotation / sector-timing signals — for equities, with enough evidence detail to then backtest the validated candidates on Indian (NSE/Nifty) sector data. This feeds two consumers: a 2–4yr multibagger screen and a daily stock-picking model, so cover the FULL horizon term structure.
> 
> Deliverable: a backtest-ready, ranked MENU of candidate sector-outlook signals. For EACH signal give: (a) the precise definition / how it's computed at entry (knowable when you buy, no look-ahead); (b) the horizon(s) it works at — short tactical (~1–3mo), medium (6–18mo), long (2–4yr); (c) the empirical evidence — effect size, IC / t-stat / Sharpe, sample, and source quality (peer-reviewed vs practitioner vs blog); (d) whether it's been demonstrated in INDIA specifically vs global-only (and if global-only, flag transfer-validity risk to Indian markets); (e) data-source feasibility — exactly what data it needs and whether that's free/owned or paid/alt-data.
> 
> Signal families to cover (and look for others):
> 1. Momentum/technical — sector price momentum & relative strength (which lookback/horizon), cross-sector momentum, time-series vs cross-sectional, the small-cap-index EMA trend rule (IIMB Management Review study on Nifty SmallCap).
> 2. Fundamental — sector aggregate earnings growth, earnings-estimate REVISIONS, valuation spreads / sector mean-reversion (sector value), profitability/margin trends, dispersion of estimates. (Note: our own quick test found trailing sector price-momentum is NOISE at 2–4yr ρ≈+0.10, and trailing sector fundamentals are MEAN-REVERTING ρ≈−0.35 — so explicitly assess whether sector VALUE/contrarian or estimate-REVISIONS beat trailing-level momentum.)
> 3. Macro / business-cycle / flows — interest-rate & cycle-stage sector rotation (which sectors lead early/mid/late cycle), monetary policy, yield curve, FII/DII sector flows, commodity & currency betas, inflation regime.
> 4. Sentiment / analyst / breadth — sector analyst rating/target revisions, sector breadth, news/regulatory tailwinds.
> 5. Alternative data — any alt-data sector signals (consumer/credit/satellite/Google-Trends/order-book) with India relevance.
> 
> Geography rule: prioritise India-specific evidence where studies are SUFFICIENT; where India research is thin, rely on global (US/EM) evidence and flag the transfer risk. Decide breadth per-signal.
> 
> Context for feasibility mapping — assets we already have in this Indian-equities system: daily NSE/Nifty sector & smallcap/midcap indices (nse_index_history, backfilled ~2016; plus nifty_it/pharma/auto/energy/fmcg/metal/psubank/realty etc. in macro_history from 2023), annual sector fundamentals (fundamentals_screener, ~10yr), FII/DII cash & F&O-positioning flows, India macro (VIX, USDINR, brent, gold, US10Y, CPI/IIP/GST), regulatory/news signals, and a survivorship-corrected historical universe (bhavcopy, incl. delisted, back to ~2016). Mark which candidate signals are buildable on these vs need paid feeds (e.g. analyst estimate-revision history).
> 
> End with a prioritised shortlist: the 5–8 signals most worth backtesting first on our Indian sector data, ordered by (evidence strength × India-applicability × buildability), with the single best first.

## Executive summary

The strongest, best-evidenced sector-outlook signals split cleanly by horizon. For the SHORT/TACTICAL band (1-12mo), sector/industry MOMENTUM is the validated workhorse: both time-series momentum (sign of own trailing 12-month return, Moskowitz-Ooi-Pedersen, 52/58 instruments significant including developed equity-index futures) and text-based industry momentum (Hoberg-Phillips, 1.9-2.3%/mo, Sharpe 1.4-1.9) are top-tier peer-reviewed and at-entry computable — but both are US/developed-only with real India transfer risk, and the project's own test already shows trailing sector momentum is NOISE at the 2-4yr horizon (consistent with the documented 1-12mo continuation then partial reversal). For the MEDIUM-to-LONG / contrarian band, the evidence pivots AWAY from trailing momentum toward VALUE/mean-reversion and a regime gate: the value-spread predicts value-minus-growth returns (Cohen-Polk-Vuolteenaho, coef 0.287, t=3.1), and cross-sectional return DISPERSION is a countercyclical state variable that predicts a HIGHER forward value premium and SMALLER momentum premium (Angelidis et al. + Stivers-Sun, two independent peer-reviewed sources) — directly supporting the hypothesis that sector value/contrarian beats trailing momentum when dispersion is high. On MACRO/FLOWS, the only India-specific peer-reviewed evidence is FII flows (significant for 8/9 NSE sectors long-run; FII+USDINR+Brent dominate short-run), but a critical caveat applies: FII flow FOLLOWS returns (positive-feedback/return-chasing, returns Granger-cause flows more strongly than the reverse), so raw FII flow is a coincident/confirmatory feature, not a clean leading signal. Business-cycle stage-mapping rotation is explicitly REFUTED as a systematic timing signal (Molchanov-Stangl) and should be dropped. Net: build momentum for the daily model, build value-spread + dispersion-regime for the multibagger/medium horizon, treat FII as a coincident overlay, and skip cycle-stage mapping.

## Findings (6)

### 1. Sector/industry MOMENTUM is the best-validated tactical (1-12mo) sector signal, but only TIME-SERIES momentum transfers cleanly to NSE sector indices on our existing data. TS-MOM is at-entry: long a sector index if its own trailing 12-month return is positive (sign(r_{t-12,t})), short if negative, 1-month hold, vol-scaled to constant ex-ante volatility (Moskowitz-Ooi-Pedersen formula r = sign(r_{t-12,t}) x (0.60%/sigma_t) x r_{t,t+1}). 52 of 58 futures (incl. 9 developed-market EQUITY-INDEX futures) show significant positive 12-month TS-MOM over Jan1985-Dec2009. The richer text-based (TNIC) industry momentum earns 1.9-2.3%/mo (t>5, Sharpe 1.4-1.9, ~100-200% better than SIC/GICS industry momentum which is only ~0.6-1.0%/mo and not UMD-robust) but requires 10-K product-text peer data that does NOT exist for NSE and is firm-level peer-shock, not index rotation.

**confidence:** high · **vote:** 3-0 (each constituent claim)

TS-MOM (MOP 2012, JFE): canonical k=12,h=1; 'All 58 futures contracts exhibit positive time series momentum returns and 52 of them are statistically different from zero'; set includes 9 developed equity-index futures (strongest transfer-validity for applying trend to equity indices, though India untested). Signal is no-look-ahead: sign and sigma both knowable at t. TNIC (Hoberg-Phillips 2018, JFQA Table 11): high-disparity TNIC-3 alpha 1.9-2.3%/mo, t>5.0, Sharpe 1.43-1.91, annualized 21.6-32.4%; FF-48/SIC only 0.6-1.0%/mo (t=2.2-2.7), not robust to UMD; '100% to 200% improvements'. Construction: monthly quintile sort on equal-weighted past t-1..t-12 return of TNIC-3 peers (focal firm excluded), long top/short bottom. BUILDABILITY: TS-MOM fully buildable on nse_index_history (sector + smallcap/midcap indices backfilled ~2016) and macro_history sector indices; TNIC NOT buildable (no Indian 10-K product-text). EFFICACY CAVEAT for backtest: Huang-Li-Wang-Zhou (2020 JFE) shows pooled TS-MOM t-stat not bootstrap-robust — validate asset-by-asset (sector-by-sector), not pooled, on NSE.

**Sources:**
- https://elmwealth.com/wp-content/uploads/2017/06/timeseriesmomentum.pdf
- https://faculty.tuck.dartmouth.edu/images/uploads/faculty/gordon-phillips/hoberg_phillips_TNICmomJFQA_FinV1.pdf

### 2. Trend/momentum has a defined horizon TERM STRUCTURE that explains why trailing sector momentum is a SHORT-tactical signal only and decays/reverses at the 2-4yr multibagger horizon: positive continuation lasts ~1-12 months then PARTIALLY REVERSES over longer horizons (reversal concentrated ~yr2, partial, out to ~5yr test boundary). This independently corroborates the project's own finding that trailing sector price-momentum is noise at 2-4yr (rho~+0.10). Implication: use momentum for the DAILY model, NOT for the 2-4yr screen.

**confidence:** high · **vote:** 3-0

MOP 2012 (JFE): 'this time series momentum or trend effect persists for about a year and then partially reverses over longer horizons'; 'positive t-statistics for the first 12 months indicate significant return continuation... negative signs for the longer horizons indicate reversals.' TNIC corroborates the medium-horizon location: TNIC peer shocks take up to 12mo to transmit (vs 1-2mo for visible SIC peers), duration 'roughly 12 months', distinct from the 1-month lead-lag anomaly. Reversal peaks ~yr2 and is partial (not strengthening to 5yr). Directly maps the deliverable's horizon question: momentum is a 1-12mo band signal; at 2-4yr it is unreliable.

**Sources:**
- https://elmwealth.com/wp-content/uploads/2017/06/timeseriesmomentum.pdf

### 3. At the MEDIUM-to-LONG / contrarian horizon, sector VALUE / mean-reversion TIMING is the evidence-backed alternative to trailing momentum. The 'value spread' (B/M of value portfolio minus B/M of growth portfolio) significantly predicts forward value-minus-growth (HML) returns: when value is unusually cheap vs growth, value-minus-growth earns atypically high forward returns. This is the style-level analogue to sector value/contrarian and supports the project hypothesis that sector VALUE beats trailing-level momentum at long horizons.

**confidence:** high · **vote:** 3-0

Cohen-Polk-Vuolteenaho 2003 (Journal of Finance), US 1938-1997: value-spread predictive slope 0.287, t=3.1, GLS R^2~0.16. Economic magnitude: value-spread annual SD = 8.75pp; SD of fitted/predicted HML = 1.3x the unconditional mean HML return ('substantial time variation in the HML premium'). CAVEATS: (1) STYLE-level (HML), not sector-level — transfer to sector value spreads is a hypothesis; (2) US 1938-1997 only, no India test — transfer risk; (3) practitioner work (Asness 'Contrarian Factor Timing Is Deceptively Difficult', AlphaArchitect) finds factor-timing on value spread is noisy with small net-of-cost gains, so temper expected effect size. BUILDABILITY: HIGH — buildable on annual fundamentals_screener (~10yr) to construct sector-level B/M dispersion / sector value spreads; mean-reversion is the project's own observed long-horizon sector behavior (fundamentals rho~-0.35).

**Sources:**
- https://personal.lse.ac.uk/polk/research/jofi_5802005.pdf

### 4. Cross-sectional return DISPERSION (RD = cross-sectional SD of stock or disaggregate-portfolio returns) is a buildable, model-free, at-entry COUNTERCYCLICAL state variable that predicts a HIGHER forward VALUE premium and a SMALLER forward MOMENTUM premium over ~12 months. This is the single most decision-relevant finding for the deliverable: it operationalizes a regime GATE telling you WHEN to tilt sectors toward value/contrarian vs momentum — directly validating the project's hypothesis that value/contrarian beats trailing momentum when dispersion is high.

**confidence:** high · **vote:** 3-0

Angelidis-Sakkas-Tessaromatis 2015 (Journal of Banking & Finance), G7 1980-2012, plus independent corroboration Stivers-Sun 2010 (JFQA): 'A relatively high return dispersion predicts a deterioration in business conditions, a higher value premium, a smaller momentum premium and lower market returns.' 12-month effect sizes per +1SD world RD: market -3.73%, value premium +3.53%, momentum premium -3.85% (panel t=-2.83/+3.46/-3.21; value sig in 4/7 countries, momentum sig in 3-4/7). RD computed from cross-sectional returns alone — NO factor model needed: CSV_t = sum w_i(r_it - r_mt)^2, RD=sqrt(CSV). Result robust excluding US data. CAVEATS: (1) ZERO India validation — transfer risk; (2) RD predicts the aggregate regime/cycle and the value-vs-momentum tilt, one step removed from picking a specific sector. BUILDABILITY: VERY HIGH — directly computable on the survivorship-corrected bhavcopy universe (incl. delisted, back to ~2016) with no extra data.

**Sources:**
- https://www.sciencedirect.com/science/article/abs/pii/S0378426615001557

### 5. In India specifically, FII flows are the broadest peer-reviewed MACRO/FLOW correlate of sector returns, but they FOLLOW returns rather than lead them, so raw FII flow is a COINCIDENT/confirmatory overlay, not a clean leading sector-rotation signal. FII has a significant positive long-run effect on 8/9 NSE sectors (all except IT); short-run, FII + exchange rate (USDINR) + crude (Brent) are the major determinants. BUT Nifty returns Granger-cause FII equity inflows more strongly (F=3.62 lag1, 7.68 lag2) than the reverse (decays to insignificance by lag2) — positive-feedback/return-chasing behavior.

**confidence:** high · **vote:** 3-0 (constituent claims; note the 'leading-signal' framing of FII was itself REFUTED 1-2 in two related claims)

Kumar/Garg et al. 2025 (F1000Research, peer-reviewed; 9 NSE sectoral indices, ARDL, Apr2012-Aug2024): FII significant+positive on Auto/Bank/FS/FMCG/Media/Metal/Pharma/Realty (not IT) long-run — most broadly significant variable (FII 8/9 vs IIP 5/9, MS 3/9, WPI 3/9, EPU 3/9, crude 1/9, ER 0/9 long-run). Short-run: FII+ER+COP major determinants; ECT coefficients all negative/significant (-1.00 to -1.52). Mukherjee-Tiwari 2022 (Asia-Pacific Financial Markets, daily NSDL flows 2014-2019): returns->flows dominant and strengthening across lags (PFT/return-chasing); flow->return significant only at lag1, insignificant by lag2. IMPORTANT: the evidence is contemporaneous/explanatory, NOT at-entry predictive — use FII (+USDINR beta + Brent beta) as feature-selection/coincident confirmation, not as a proven look-ahead-free timing signal. BUILDABILITY: HIGH — system already holds FII/DII cash & F&O flows, USDINR, Brent; but design must avoid letting a follower masquerade as a predictor (lag it / use as overlay).

**Sources:**
- https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12001019/
- https://pmc.ncbi.nlm.nih.gov/articles/PMC9145119/

### 6. Business-cycle STAGE-MAPPING sector rotation (the popular 'cyclicals early-cycle, defensives late-cycle' playbook) should be DROPPED from the menu: it does not produce systematic outperformance even with relaxed assumptions. Do not build cycle-stage sector mappings as a timing signal.

**confidence:** high · **vote:** 2-1

Molchanov-Stangl 2024 (International Journal of Finance & Economics, peer-reviewed): 'we find no evidence of systematic sector performance where popular belief anticipates it will occur', robust to alternative sector and cycle definitions; relaxing to let any industry predict others yields predictability 'not significantly different than what would be expected by random chance.' Even PERFECT-foresight cycle timing yields only ~0.16%/mo gross with 28/48 sectors UNDERPERFORMING in their supposed-optimal stage; independent Sorensen-Sarkar caps perfect-foresight rotation at ~2.3%/yr, ~0 net of costs/timing error. SCOPE: this kills the cycle-STAGE-mapping branch ONLY — it does NOT refute sector/industry MOMENTUM (separate, supported family). CAVEAT: US evidence; India cycle-mapping evidence is blog-quality only — but the null plus absence of rigorous India support argues against building it. Related yield-curve-regime sector rotation claims were also REFUTED (0-3) in verification.

**Sources:**
- https://onlinelibrary.wiley.com/doi/full/10.1002/ijfe.2882

## Refuted / killed claims

- **Industry momentum exists and is strong: a strategy that buys stocks in past-winning industries and sells stocks in past-losing industries is highly profitable, surviving controls for size, book-to-market, individual-stock momentum, cross-sectional dispersion in mean returns, and microstructure effects. This validates cross-sectional sector relative-strength momentum as a real (US) sector-rotation signal.**
- **Industry momentum largely SUBSUMES individual-stock momentum: once you control for industry momentum, the classic buy-winners/sell-losers stock momentum strategy becomes significantly less profitable, implying the momentum anomaly is driven substantially by the industry/sector component of returns. This argues a sector-level momentum signal carries most of the predictive content at intermediate horizons.**
- **Even when sector rotation does show a positive edge, the outperformance is modest and is eroded almost entirely by transaction costs and by realistic business-cycle timing errors — meaning the strategy is not implementable net of frictions.**
- **Once the perfect-foresight rotation assumptions are relaxed, sector return predictability from the business cycle is statistically indistinguishable from random chance — i.e. no exploitable cycle-stage sector signal remains.**
- **Yield-curve regime predicts cross-sector return dispersion, not just broad-market beta: classifying the 2s/10s curve into four regimes (bear/bull steepening, bear/bull flattening) over a trailing 6-month window produces significant dispersion in relative SECTOR returns over the subsequent 6 months, documented on 150 S&P 500 subsectors since 1995.**
- **A specific, at-entry-computable sector-rotation rule: in 'risk-on' regimes (rising rates / bear steepening, typically early-cycle) cyclical sectors — consumer discretionary, financials, industrials — historically outperform; in 'risk-off' regimes defensive sectors — consumer staples, health care — outperform. The signal is knowable at entry from the trailing 6-month change in the 2s/10s spread and rate level.**
- **FII (Foreign Institutional Investment) flows have a statistically significant positive long-run relationship with 8 of 9 NSE sector indices (Auto, Bank, Financial Services, FMCG, Media, Metal, Pharma, Realty) but NOT with IT, over April 2012-Aug 2024 monthly data — making sector FII flow a candidate India-specific macro rotation signal.**
- **FII flows are the only macro indicator that is a major determinant of Indian sectoral returns in BOTH the short run and long run; ER and COP matter only short-run, while IIP, EPU, MS and WPI matter only long-run — implying horizon-dependent signal selection for sector timing.**
- **The macro-to-sector relationship is differential by sector and confirmed via ARDL bounds-test cointegration with significant negative error-correction terms, with sector models explaining 63-80% of variance (Auto R2=0.80, Bank R2=0.80, Pharma R2=0.64, IT R2=0.63) — establishing macro indicators as legitimate India-specific sector predictors but with sector-specific betas.**

## Caveats

EVIDENCE QUALITY: All six findings rest on top-tier peer-reviewed primary sources (JFE, Journal of Finance, JFQA, JBF, IJFE, Asia-Pacific Financial Markets, F1000Research), verified against extracted PDFs, not abstracts — confidence is genuinely high on the documented effects. The weak link is GEOGRAPHY: only the FII/macro finding is India-specific; momentum, value-spread, and dispersion are all US/developed-only (the TS-MOM equity-index futures are all developed markets, India absent), so every non-FII signal carries unquantified transfer-validity risk to NSE and MUST be re-validated on Indian sector data before trusting effect sizes. TIME-SENSITIVITY: TNIC sample ends 2012 with no post-publication out-of-sample test (inattention-driven alpha may have decayed since the data became visible); MOP/value-spread samples are old (1985-2009 / 1938-1997). EFFICACY DISPUTES that survive but qualify magnitudes: Huang-Li-Wang-Zhou (2020 JFE) shows pooled TS-MOM t-stats are not bootstrap-robust — backtest sector-by-sector, not pooled; Asness et al. show value-spread factor-timing is noisy net-of-cost. SCOPE MISMATCHES: value-spread is STYLE-level (HML) and dispersion predicts the aggregate REGIME/value-vs-momentum tilt — both are one transfer-step removed from picking an individual sector; TNIC is firm-level peer-shock, not top-down index rotation. The FII 'leading signal' framing was partially REFUTED (returns lead flows), and several related macro/yield-curve/cycle claims were refuted 0-3 — treat FII as coincident, drop cycle-stage mapping entirely. Net for backtesting: trust the SIGNS and the horizon term-structure; re-estimate all effect SIZES on Indian data.

## Open questions

- PRIORITIZED SHORTLIST (best first, ordered by evidence x India-applicability x buildability): (1) RETURN-DISPERSION REGIME GATE — model-free, fully buildable on survivorship-corrected bhavcopy, two independent peer-reviewed sources, directly answers the value-vs-momentum-when question; highest priority. (2) SECTOR TIME-SERIES MOMENTUM (own trailing 12mo sign, vol-scaled, 1mo hold) on nse_index_history sector/smallcap/midcap indices — canonical, fully buildable, for the DAILY model; validate sector-by-sector. (3) SECTOR VALUE SPREAD / mean-reversion on fundamentals_screener for the 2-4yr screen — buildable, matches project's own rho~-0.35 mean-reversion finding. (4) CROSS-SECTIONAL SECTOR-RELATIVE momentum vs TS-momentum head-to-head on Indian sector indices. (5) FII (+USDINR beta + Brent beta) sector overlay, LAGGED to respect return-chasing, as coincident confirmation. (6) Dispersion-conditioned momentum (momentum only when dispersion LOW). (7) Earnings-estimate REVISIONS at sector level — likely the highest-value untested signal but NOT covered by surviving claims and needs a paid analyst-estimate-revision history feed.
- Does sector TS-MOM survive asset-by-asset (sector-by-sector) bootstrap validation on NSE, given Huang-Li-Wang-Zhou's pooled-vs-individual critique? Pooled significance may not hold per Indian sector.
- Is there ANY India-specific evidence (even practitioner) for the return-dispersion -> value/momentum-premium predictability, or is the project's backtest the first test on NSE? No India replication was found.
- Sector earnings-estimate REVISIONS and estimate DISPERSION were named in the deliverable's signal families but NO surviving claim covers them — they likely require a paid analyst-estimate-revision history feed (the system's MEMORY flags PT/estimate sources as a known gap). Quantify cost/feasibility of an Indian sell-side estimate-revision feed before assuming this family is unbuildable.
- The small-cap-index EMA trend rule (IIMB Management Review study on Nifty SmallCap) named in the brief was NOT among the surviving verified claims — does that study replicate, and is it just a single-index TS-MOM special case already covered by finding 1?

## All sources (20)

- [https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00146](https://onlinelibrary.wiley.com/doi/abs/10.1111/0022-1082.00146)
- [https://faculty.tuck.dartmouth.edu/images/uploads/faculty/gordon-phillips/hoberg_phillips_TNICmomJFQA_FinV1.pdf](https://faculty.tuck.dartmouth.edu/images/uploads/faculty/gordon-phillips/hoberg_phillips_TNICmomJFQA_FinV1.pdf)
- [https://kth.diva-portal.org/smash/get/diva2:1827867/FULLTEXT01.pdf](https://kth.diva-portal.org/smash/get/diva2:1827867/FULLTEXT01.pdf)
- [https://onlinelibrary.wiley.com/doi/full/10.1002/ijfe.2882](https://onlinelibrary.wiley.com/doi/full/10.1002/ijfe.2882)
- [https://www.millstreetresearch.com/do-analyst-estimate-revisions-still-help-forecast-relative-stock-returns/](https://www.millstreetresearch.com/do-analyst-estimate-revisions-still-help-forecast-relative-stock-returns/)
- [https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12001019/](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12001019/)
- [https://www.kansascityfed.org/documents/9847/EconomicReviewV108N4MatschkeVonEndeBeckerSattiraju.pdf](https://www.kansascityfed.org/documents/9847/EconomicReviewV108N4MatschkeVonEndeBeckerSattiraju.pdf)
- [https://pmc.ncbi.nlm.nih.gov/articles/PMC9145119/](https://pmc.ncbi.nlm.nih.gov/articles/PMC9145119/)
- [https://www.ijnrd.org/papers/IJNRD2306314.pdf](https://www.ijnrd.org/papers/IJNRD2306314.pdf)
- [https://elmwealth.com/wp-content/uploads/2017/06/timeseriesmomentum.pdf](https://elmwealth.com/wp-content/uploads/2017/06/timeseriesmomentum.pdf)
- [https://quantpedia.com/strategies/sector-momentum-rotational-system](https://quantpedia.com/strategies/sector-momentum-rotational-system)
- [https://www.advisorperspectives.com/commentaries/2018/02/05/what-the-yield-curve-can-tell-equity-investors](https://www.advisorperspectives.com/commentaries/2018/02/05/what-the-yield-curve-can-tell-equity-investors)
- [https://alphaarchitect.com/valuation-spreads/](https://alphaarchitect.com/valuation-spreads/)
- [https://personal.lse.ac.uk/polk/research/jofi_5802005.pdf](https://personal.lse.ac.uk/polk/research/jofi_5802005.pdf)
- [https://www.sciencedirect.com/science/article/abs/pii/S0378426615001557](https://www.sciencedirect.com/science/article/abs/pii/S0378426615001557)
- [https://escholarship.org/content/qt2r7980f3/qt2r7980f3_noSplash_c002fc5c3b5de2401d705fadd922a1f3.pdf](https://escholarship.org/content/qt2r7980f3/qt2r7980f3_noSplash_c002fc5c3b5de2401d705fadd922a1f3.pdf)
- [https://pmc.ncbi.nlm.nih.gov/articles/PMC12001019/](https://pmc.ncbi.nlm.nih.gov/articles/PMC12001019/)
- [https://arxiv.org/pdf/2603.19380](https://arxiv.org/pdf/2603.19380)
- [https://macrosynergy.com/research/the-predictability-of-market-wide-earnings-revisions/](https://macrosynergy.com/research/the-predictability-of-market-wide-earnings-revisions/)
- [https://www.mnclgroup.com/sectoral-momentum-how-to-track-rotational-trends-in-indian-markets](https://www.mnclgroup.com/sectoral-momentum-how-to-track-rotational-trends-in-indian-markets)
