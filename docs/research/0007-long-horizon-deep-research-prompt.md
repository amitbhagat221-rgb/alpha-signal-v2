# Deep research brief: slow factors, investor playbooks and thesis monitors for 3–12-month holds in Indian equities

## Your role and the goal
You are a senior quantitative equity researcher with deep knowledge of Indian markets and of the academic and practitioner literature. Help us redesign a working factor-ranking system so that its picks are **held for at least 3 months (63 trading sessions), typically 6–12 months**, and earn their keep after real costs and Indian tax. Today's model was tuned to a 1-month horizon and churns. We need:
1. **Slow signals**, from feature engineering on what we already have and from new data.
2. **Investor playbooks** whose holding period matches ours, turned into testable rules.
3. **Thesis monitors**: signals that should force us to re-examine a holding before its review date.

All three must survive an honest out-of-sample test. Cite sources, grade the evidence, and never invent a number.

## The setting
- **Market:** NSE, 2,448 stocks with ETFs excluded. Ranked only within cap tiers:
  - LARGE: top 100 by market cap;
  - MID: ranks 101–250;
  - SMALL: the rest;
  - MICRO: an illiquid slice that is never picked.
- **Investor:**
  - long-only retail account of ₹30–40 lakh at Zerodha;
  - monthly review, no shorting;
  - liquidity floor about ₹1 crore traded a day.
- **Costs we measured:** one-way, for a ₹1 lakh trade, delivery fees plus half-spread plus impact:
  - LARGE 15.7 bps;
  - MID 17.9 bps;
  - SMALL 30.5 bps.
  About 10 bps of that is STT, which only trading less avoids.
- **Tax:**
  - short-term gains (held under 12 months): 20%;
  - long-term gains: 12.5% above ₹1.25 lakh a year;
  - set-off: long-term losses only against long-term gains; short-term losses against any gain.
  The 12-month line matters for any rule that holds 3–12 months.
- **Data budget:** free sources plus about ₹5,000 a month of paid data.

## Data and infrastructure we already have
- **Factor panel:** point-in-time, monthly anchors from December 2019 to October 2026 (83 anchors). Prices are adjusted for splits, bonuses and dividends. Returns are labelled from the next session's close.
  - Fundamentals have about 10–11 years of statements, but many derived fundamental factors start only in September 2024.
  - The fundamentals universe is today's: survivorship bias. Delisted names exist in an unlisted panel and in NSE bhavcopy back to the 1990s.
- **Price and trading data:**
  - NSE bhavcopy with delivery % (daily);
  - F&O bhav, with implied volatility and skew derivable from 2019;
  - bulk and block deals; short-selling disclosures;
  - Kite minute bars, 2015 onwards, survivors only.
- **Disclosures and ownership:**
  - BSE corporate announcements from 2018, including delisted firms: results dates, resignations, credit ratings, pledges;
  - shareholding categories from 2016, including FII, DII, MF, promoter and retail holder counts;
  - insider trades from 2024.
- **Analyst data:**
  - Yahoo consensus EPS estimate vs actual back to 2015 for small caps. Not yet verified as point-in-time.
  - Monthly analyst price-target snapshots. Daily PT history is unusable: an earlier artifact came from look-ahead.
- **Other:**
  - earnings-call transcripts, with dated availability so they can be used without look-ahead;
  - news sentiment;
  - mutual-fund portfolio snapshots;
  - macro series: oil, metals, INR, gold, rates, credit.

## The factor inventory: 106 registered, 12 used for ranking
- **Used for ranking:**
  - Piotroski F-score (MID, SMALL);
  - cash-flow accruals (MID, negative);
  - 30-day average delivery % (SMALL);
  - delivery % anomaly z-score (SMALL);
  - sector tilt (SMALL);
  - 25-delta IV skew (LARGE, MID);
  - announcement-window abnormal return (all tiers);
  - forward-looking language in transcripts (LARGE);
  - analyst consensus and EPS revisions (MID);
  - asset growth (LARGE, negative);
  - 12-1 residual momentum (MID, SMALL);
  - consensus beat rate over the last 4 results (MID).
- **Quality and profitability:** ROE, ROA, ROIC, ROIIC, gross profitability, profit margin, FCF margin, margin slope, earnings persistence, quality composite, Altman Z, interest coverage.
- **Accruals, forensics and working capital:** balance-sheet accruals, Sloan full accruals, Beneish M-score, cash-conversion cycle, working-capital intensity, DSO and DIO changes, NWC to revenue, SG&A to revenue change, capex to depreciation, goodwill to assets, asset tangibility.
- **Leverage:** debt to equity, debt structure.
- **Growth:** revenue and EPS growth, 5-year revenue volatility, relative growth, growth composite.
- **Value:** earnings yield, book to price, FCF yield, value composite.
- **Price and momentum:**
  - momentum: 6-month and 12-month adjusted, momentum composite, sector momentum;
  - position in the 52-week range, MACD;
  - risk and reversal: 252-day low volatility, 21-day reversal, lottery (max daily return);
  - share momentum, relative turnover.
- **Microstructure:** smart-money score, intraday range compression, closing strength, opening-gap frequency, VWAP deviation, bid-ask spread proxy, Kyle's lambda.
- **Derivatives:** IV term structure, IV vs realised spread, IV percentile, put-call ratio (OI and volume), max-pain distance, OI build-up, FII/DII F&O positioning.
- **Earnings events:** beat rate, surprise standardised by its volatility, 60-day post-earnings drift, price-target upside, price-target revision (dropped).
- **Ownership and flows:** promoter holding change and 4-quarter trend, pledge quality, insider signal, bulk-deal signal, short-selling signal, FII/DII cash flows.
- **Events and text:** governance resignations, corporate-action density, buybacks, call-tone change, uncertainty words, news sentiment and volume, regulatory and macro sector signals.
- **Macro betas:** oil, metals, INR, gold, rates, credit.
- **Banks and NBFCs:** financial quality, financial recovery.

## What we found
These come from the October 2026 studies. All tests are within-tier and point-in-time, with multiple-testing haircuts.
1. **The paper book churns.** It is rebuilt daily (buy in the top 5, sell below rank 8). One-way turnover is 9% a day, and a stock is typically held 5 sessions. Every factor was chosen and weighted on 20-session rank IC.
2. **How long the factors work (rank IC by horizon):**
   - Fast: the delivery-anomaly z-score peaks at one month and fades by 6–12 months (SMALL t 7.2 at 21 sessions, 1.1 at 252).
   - Slow: Piotroski strengthens with horizon (MID IC 0.046 at 1 month, 0.131 at 12 months).
   - Also lasting to 6 months in SMALL: consensus beat rate, value composite, sector tilt, delivery %.
   - A haircut over 1,094 tests, counting the overlap between 6-month windows (about 13 effective independent windows, not 77), leaves only SMALL consensus beat rate standing at 6 months. Overlap inflates long-horizon t-stats badly.
3. **Slow composite, walk-forward.** Factors were chosen on 126-session returns, with a 7-month gap between training and test.
   - Out-of-sample 126-session IC t: MID 5.68, SMALL 3.29, LARGE −0.11.
   - MID's skill sits in the bottom deciles (weak firms underperform); its top 15 beat the tier by only +0.67% over 6 months.
   - SMALL's top 15 beat the tier by +4.9% over 126 sessions.
   - Fast signals added nothing at 6 months and made the top of the list less stable.
4. **Long-hold books, after costs and tax.** 48 rule variants per tier, out of sample from June 2022 to October 2026. No tier passed (bar: t ≥ 2 after the haircut for variants tried).
   - The best SMALL book was: monthly review, top 10, sell below rank 30, 3-month average score, 12-month minimum hold. It made +18.3%/yr over the Smallcap 250 with t 1.81, 12.9-month median hold, 88%/yr turnover and 98% long-term gains.
   - That figure is fragile: the same rule on another slow score set made +3.6%.
   - MID's best book made +5.2% (t 1.44); LARGE's +7.1% (t 1.26).
   - Proving one fixed rule at that volatility would take about 5 years.
5. **Other findings:**
   - Non-linear models (boosted trees, random forests, splines) add nothing over ridge regression.
   - No LARGE factor has out-of-sample skill.
   - FII, MF and DII ownership flows don't predict returns; retail holder growth predicts underperformance in SMALL (t −3.48).
   - The core earnings-drift test fails even with real announcement dates; the announcement-window return is the version that works.
   - A survivorship check showed SMALL's 30-day delivery % loses its 6-month evidence on the full market (t 4.00 → 1.75).
   - Our playbook screens, with backtests: Munger/Pabrai avoid list, promoter and insider buying, Buffett-style compounders, Pabrai cloning, O'Neil/Minervini breakouts, Graham deep value, Lynch categories, Fisher say-vs-do on management. Several have under 3 years of input history.

## Research questions

### A. Slow signals through feature engineering on what we have
Which transformations of our 106 factors are most likely to predict 3–12-month returns in Indian mid and small caps? Consider:
- persistence and consistency: counts over 8–12 quarters, multi-year stability of ROCE and margins;
- trends and acceleration;
- score smoothing, and factor momentum or decay;
- revision breadth over 3 months;
- cash conversion and its trend;
- reinvestment rate × ROIIC, and capital allocation;
- interactions: quality × momentum, value × quality, quality × low leverage;
- industry-relative versions;
- conditioning on regime or liquidity.

For each idea give:
- the mechanism;
- evidence, with citations, saying whether it is from India, other emerging markets or the US;
- the expected horizon;
- whether it can be built point-in-time from our data;
- a precise definition we can code.

### B. New slow data worth adding
Free or cheap Indian sources that carry slow information. Examples:
- annual-report text and changes over time;
- related-party transactions;
- auditor changes and qualifications;
- credit-rating trajectories;
- capex and order-book disclosures;
- segment data;
- employee counts;
- promoter pledge history;
- government procurement wins;
- trademark or patent activity;
- export data;
- management tenure.

For each: where to get it, how far back it goes, its point-in-time traps, and the evidence that it predicts returns.

### C. Investor playbooks matched to a 3–12-month horizon
Cover these, and any others with documented Indian track records:
- Coffee Can (Marcellus / Ambit);
- Motilal Oswal QGLP and Raamdeo Agrawal's 100x;
- Basant Maheshwari;
- Ambit Good & Clean;
- Buffett/Munger quality at a fair price;
- Fisher;
- Lynch categories;
- Greenblatt's magic formula;
- Piotroski on low price-to-book;
- O'Neil CANSLIM and Minervini trend templates;
- Pabrai cloning.

For each:
- the codified entry rule, holding period and **sell rule**;
- what is known about its out-of-sample record in India, from SEBI-registered PMS results, published fund records or academic tests;
- whether we can test it point-in-time with our data;
- what is folklore rather than evidence.

### D. Thesis monitors: what should force a re-look before the review date
Build a catalogue of events and signals shown to predict underperformance over the next 3–6 months. Areas to cover:
- **Governance:** auditor or CFO resignation, rising pledges, promoter selling, related-party transactions, SEBI orders.
- **Fundamentals:** results misses, guidance cuts, estimate-revision collapses, working-capital blow-ups, cash flow diverging from profit, margin compression.
- **Credit:** rating downgrades or watch.
- **Market:** momentum crashes, delivery collapse, block-deal exits, F&O-ban entry.
- **Ownership:** retail crowding.

For each:
- the evidence grade;
- the typical lead time;
- the false-alarm rate where known;
- whether it should trigger a review or an exit.

Then design the system: tiered alerts, how to control false alarms, how often to check, and how to avoid turning the monitor back into churn.

### E. Portfolio construction for 3–12-month holds
Cover:
- entry bands and exit bands (buy/hold spreads);
- minimum-hold rules;
- tax-aware sale timing around the 12-month line;
- concentration, and equal vs conviction weighting;
- turnover budgets;
- combining a quantitative screen with a short qualitative check ("model-assisted discretionary").

Relevant literature includes Gârleanu–Pedersen, Novy-Marx–Velikov and DeMiguel et al., plus practitioner evidence.

### F. Validating with short history
With about 83 monthly anchors, a 6-month label has roughly 13 independent windows. What is the most credible protocol? Consider:
- Using longer histories: price-based factors back to the 1990s through bhavcopy, 10–11 years of statements.
- Pooling across tiers.
- Bayesian shrinkage toward published factor premia.
- Corrections for overlapping returns: effective degrees of freedom, non-overlapping subsamples.
- Placebo tests and the deflated Sharpe ratio.
- Pre-registered forward paper tests.

How should we decide with limited power without fooling ourselves?

## What we want back
1. **A ranked shortlist of at most 15 slow features or signals.** For each: hypothesis, definition, data and point-in-time feasibility, horizon, evidence (citations, with India vs elsewhere marked) and a test spec.
2. **Playbook rule cards** for the 5 most promising, with sell rules.
3. **A thesis-monitor catalogue** with evidence grades and review vs exit actions.
4. **A construction recipe** for a 3–12-month book.
5. **A validation protocol** that works with our short history.
6. **A "do not do" list.**
7. **A prioritised 90-day research plan.**

Grade every claim: peer-reviewed, working paper, practitioner report or anecdote. Flag where US evidence may not carry over to India because of retail-heavy small caps, promoter ownership, circuit limits, T+1 settlement or STT. If evidence is thin, say so rather than filling the gap.
