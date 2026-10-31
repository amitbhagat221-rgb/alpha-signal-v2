# Additional intraday-derived cross-sectional anomalies (beyond research 0009's menu) for an NSE factor model

Scope: candidate factors that can be built from 1-minute CLOSE + VOLUME bars (2015-02 → 2026-10, ~2,420 NSE survivors), excluding everything already on the research 0009 menu (realized skew/kurtosis, signed jumps, day/night momentum split, tug-of-war, late-volume share, semibetas, BVC imbalance, closing pressure, true VWAP deviation, overnight sentiment, spread/Amihud/Kyle cost model, circuit bands, capacity, HKS periodicity).

Method note: this session made 21 search and fetch calls. Every figure below comes from a fetched page or a search-result abstract. The full text was read only for Baltussen–Da–Soebhag (2025). Other results come from abstracts or secondary summaries, and each is flagged as such. Items with no source found are under "Gaps" or labelled "inference" and carry no numbers.

## Q1. Which published intraday-derived anomalies exist beyond our menu? (catalogue)

### Takeaway
I found eight families with published cross-sectional evidence that are not on the menu. Ranked by how relevant they are to our holding horizon:
1. Day-vs-night beta gap and asynchronous beta, as an information-delay premium.
2. Jump beta vs continuous beta, which the literature contradicts.
3. Intraday price delay.
4. Liquidity variability, whose sign is contested.
5. India-specific intraday overreaction / speed of price adjustment.
6. End-of-day reversal. It is very strong but purely intraday and fully reverses overnight.
7. Volume–return dynamics (LMSW), better used as a conditioning variable.
8. Vol-of-vol, whose published version uses option-implied vol.

Minute-level "zeros" / price staleness is well developed as an econometric object, but I found no cross-sectional pricing test of it.

### Cited Findings

**C1. Day-vs-night beta gap and asynchronous beta (information delay). Slow, monthly.**
- Yang & Yin (2024, *International Review of Economics & Finance* 96) compare a stock's beta on intraday market returns ("day beta") with its beta on overnight market returns ("night beta"). They report a large gap between the two, plus a non-trivial "asynchronous beta" that captures slow diffusion of information. Long-short portfolios sorted on the day-night gap earn 0.8 %/month raw and 0.77 %/month alpha. Sorted on asynchronous beta, they earn 0.39 % raw and 0.28 % alpha — [IDEAS/RePEc abstract](https://ideas.repec.org/a/eee/reveco/v96y2024ipbs1059056024006610.html)
- Per the same abstract, the result is robust to controls for size, book-to-market, liquidity, investor recognition and limits to arbitrage. It is strongest among small, value, less visible, illiquid and high limits-to-arbitrage firms, and it adds information beyond Hou–Moskowitz (2005) price delay. The abstract does not state the sample (market or period) — [IDEAS/RePEc](https://ideas.repec.org/a/eee/reveco/v96y2024ipbs1059056024006610.html)

**C2. Jump (discontinuous) beta vs continuous beta. Slow.**
- Bollerslev, Li & Todorov (2016, *JFE* 120(3), 464–490) use high-frequency data on almost 1,000 stocks over two decades. The jump beta and the overnight beta earn risk premia; the continuous intraday beta does not. The premia survive a long list of firm-characteristic controls — [Duke Scholars](https://scholars.duke.edu/publication/1227892); [CREATES WP](https://repec.econ.au.dk/repec/creates/rp/14/rp14_48.pdf)
- Contradicted by Hemauer & Mörke (AEA 2022 preliminary paper), who report positive pricing of continuous betas and negative pricing of overnight market betas, "contradicting" Bollerslev et al. (2016) — [AEA 2022 program](https://aeaweb.org/conference/2022/preliminary/paper/s3fzN82A)

**C3. Price delay (Hou–Moskowitz) and its intraday analogue. Slow.**
- Hou & Moskowitz (2005, *RFS* 18(3), 981–1020) find that the most delayed firms command a large premium not explained by size, liquidity or microstructure effects, nor by CAPM, FF3 or Carhart. They attribute it to weak investor recognition (Merton 1987) — summarised in [CXO Advisory](https://www.cxoadvisory.com/?p=29112) and [PolyU record](https://research.polyu.edu.hk/en/publications/price-delay-premium-and-liquidity-risk/) (secondary summaries; full text not read)
- Lin, Singh, Sun & Yu (2014) argue that the delay premium reflects liquidity risk: high-delay firms have more difficulty attracting traders — [PolyU record "Price delay premium and liquidity risk"](https://research.polyu.edu.hk/en/publications/price-delay-premium-and-liquidity-risk/); [St Thomas record](https://researchonline.stthomas.edu/esploro/outputs/journalArticle/Price-Delay-Premium-and-Liquidity-Risk/991015132254303691)

**C4. Liquidity / trading-activity variability. Slow. The sign is contested.**
- Chordia, Subrahmanyam & Anshuman (2001, *JFE* 59(1), 3–32) find a "negative and surprisingly strong" cross-sectional relation between returns and the variability of dollar volume and turnover. It holds after controls for size, B/M, momentum and the level of volume or turnover, and it runs against their own hypothesis — [CFA Institute RF reprint](https://rpc.cfainstitute.org/-/media/documents/book/rf-publication/2001/rf-v2001-n3-3915-pdf.pdf); [IIMB repository](https://repository.iimb.ac.in/handle/2074/11853)
- Akbas, Armstrong & Petkova (2011 working paper) find a POSITIVE relation between the volatility of Amihud illiquidity (daily) and expected returns. It is distinct from covariance-based liquidity risks, and its idiosyncratic part is priced. I found no final journal version — [OU working paper PDF](https://www.ou.edu/content/dam/price/Finance/CFS/paper/pdf/Petkova%20Paper.pdf); [TAMU repository](https://tdl-ir.tdl.org/handle/1969.1/150946)
- Pereira & Zhang (2010) find higher liquidity volatility goes with lower returns (as cited in) — [arXiv 2306.15807](https://arxiv.org/pdf/2306.15807)
- Feng, Kang & Zhang (2023, *J. Int. Money & Finance* 139) find liquidity volatility predicts LOWER returns across international markets, over several liquidity metrics, and not because of idiosyncratic volatility. The negative premium disappears once a "liquidity decrease" variable enters the model. The liquidity-decrease effect is stronger in less efficient, higher-arbitrage-cost markets and periods. The abstract does not name the countries or the period — [IDEAS/RePEc](https://ideas.repec.org/a/eee/jimfin/v139y2023ics0261560623001675.html)

**C5. India: intraday over/under-reaction (speed of price adjustment). Fast, next day.**
- Siddiqui & Misra (2025, *Journal of Asset Management* 26(5), 523–534) study the Indian market. They measure intraday over- and under-reaction with a speed-of-price-adjustment measure "robust to non-trading bias".
  - Intraday overreaction has a significant positive relation with next-day returns.
  - A factor long overreaction and short underreaction earns a positive premium that market, size, value, momentum and illiquidity factors do not explain.
  - The factor explains about a quarter of the 25 size-value portfolios.
  - The abstract does not state the universe, period or data frequency — [IDEAS/RePEc](https://ideas.repec.org/a/pal/assmgt/v26y2025i5d10.1057_s41260-025-00418-y.html)

**C6. End-of-day reversal (stock-level, cross-section). Intraday only.**
- Baltussen, Da & Soebhag ("End-of-Day Reversal", April 2025 draft; US, Jan 1993 – Dec 2019) define the signal as ROD3, the return from the previous close to one hour before today's close. It negatively predicts the last-half-hour (LH) return; the second-to-last half hour is skipped to avoid bid-ask bounce.
  - Value-weighted low-minus-high quintile spread: 3.78 bps/day (t = 10.69), about 9.5 %/yr.
  - Equal-weighted: 6.86 bps/day, about 17.3 %/yr.
  - Six-factor alpha: 3.71 bps/day (t = 10.61) — [Notre Dame PDF](https://academicweb.nd.edu/~zda/EOD.pdf)
- The reversal survives 5×5 conditional sorts on size, volume, Amihud, 5-minute realized vol, overnight vol and mispricing score.
  - Smallest-20 % firms: six-factor alpha 14.71 bps/day (t = 27.20).
  - Largest-20 % firms: 3.41 bps/day (t = 10.61).
  - It also appears among the most liquid and least volatile stocks — [same PDF](https://academicweb.nd.edu/~zda/EOD.pdf)
- The effect is asymmetric. It comes from intraday LOSERS: the ROD3×I[ROD3<0] term has t = −6.97, while the plain ROD3 term drops to t = 0.23 — [same PDF](https://academicweb.nd.edu/~zda/EOD.pdf)
- Crucially for our horizons, the coefficient on ROD3 goes to −0.12 (t = −0.47) when the next overnight return is added to LH, and to 0.58 (t = 1.42) when the window is extended to the close of t+1. The LH reversal is temporary price pressure that undoes itself overnight. The authors attribute it to attention-driven retail buying and short-seller end-of-day risk management, not to liquidity provision or gamma hedging — [same PDF](https://academicweb.nd.edu/~zda/EOD.pdf)
- At the market level the sign is the opposite: the first-half-hour return predicts a same-sign last-half-hour return (Gao, Han, Li & Zhou 2018, S&P 500 ETF 1993–2013; stronger on volatile and high-volume days) — [Alpha Architect summary](https://alphaarchitect.com/2014/08/attention-prop-traders-the-first-half-hour-of-trading-predicts-the-last-half-hour/); [working paper PDF](https://c.mql5.com/forextsd/forum/173/intraday_momentum_-_the_first_half-hour_return_predicts_the_last_half-hour_return.pdf)
- A University of Southampton output reports that first-half-hour return and first-half-hour volatility have strong cross-sectional predictive power for the last half-hour, with significant alphas, in an international setting. This comes from a search-result snippet; the page returned 403 and the details were not verified — [Southampton eprints 452387](https://eprints.soton.ac.uk/452387)

**C7. Volume–return dynamics (Llorente, Michaely, Saar & Wang 2002). Fast, conditioning.**
- In the LMSW model (*RFS* 2002), returns driven by risk-sharing trades reverse and returns driven by speculative trades continue. The cross-sectional variation in the volume × return-autocorrelation coefficient tracks informed trading, and stocks with more analyst coverage show less continuation after high-volume days — [NYU archive WP](https://archive.nyu.edu/handle/2451/26698); [NBER w8312](https://img.nber.org/papers/w8312)
- Firms with greater information-asymmetry risk (smaller, higher spread, fewer analysts) lean to continuation. The relation persists after market-wide variation is removed — [OSU follow-up paper](https://files.fisher.osu.edu/department-finance/public/2006-11.pdf); [NYU archive](https://archive.nyu.edu/handle/2451/26698)
- Replications: a Taiwan study is consistent with LMSW. An Australian study finds the effect strongest for medium-size trades (trade-size data we do not have) — [NCCU thesis](https://thesis.lib.nccu.edu.tw/detail/8032c8bc014f30620a23b0facbbbb0ac/); [Monash record](https://research.monash.edu/en/publications/information-asymmetry-trade-size-and-the-dynamic-volume-return-re/)

**C8. Volatility of volatility. Slow.**
- Baltussen, van Bekkum & van der Grient (2018, *JFQA* 53(4)) measure vol-of-vol on OPTION-IMPLIED volatility. High vol-of-vol stocks underperform low vol-of-vol stocks by 8 %/yr. The effect is distinct from at least 20 known predictors, holds in the US and across European markets, and points to preference-based explanations. The working-paper test period was 1996–2009 — [JFQA PDF](https://personal.eur.nl/vanbekkum/2018JFQA_unknown_unknowns.pdf); [Cambridge](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/unknown-unknowns-uncertainty-about-risk-and-stock-returns/6E0E98349D20C1DCF67F3A0452361B80); [Quantpedia](https://vvv.quantpedia.com/?p=520)

**C9. Minute-level zero returns / price staleness. Slow, liquidity.**
- Bandi et al. (2017) show that a large share of high-frequency returns are abnormally small, and that zero returns ("zeros") are the main sign of staleness. Staleness is driven mainly by low volume and price discreteness — [arXiv 2410.07607 (literature review)](https://arxiv.org/pdf/2410.07607)
- Kolokolov, Livieri & Pirino find that the time-varying zero-return probability is driven mainly by transaction volume and is almost unaffected by bid-ask spread and realized volatility — [SNS PDF](https://ricerca.sns.it/retrieve/e3aacdfd-f331-4c98-e053-3705fe0acb7e/MS2018440_Kolokolovetal.pdf)
- Bandi, Pirino & Renò distinguish systematic and idiosyncratic staleness (secondary source). I found no cross-sectional pricing result — [arXiv 2410.07607](https://arxiv.org/pdf/2410.07607)
- The daily zero-return family is validated as a cost proxy. Fong, Holden & Trzcinka (2017, *Review of Finance* 21, 1355–1401) introduce the FHT measure, a simplification of Lesmond et al.'s zero-return measure, that "performs just as well as the best existing measures". Amihud and FHT Impact tie as the best monthly cost-per-dollar-volume proxies — [RePEc](https://ideas.repec.org/a/oup/revfin/v21y2017i4p1355-1401..html); [author PDF](https://host.kelley.iu.edu/cholden/Fong%20Holden%20and%20Trzcinka%20(2017).pdf)

**C10. PIN (probability of informed trading). Listed so it is NOT built.**
- Duarte & Young (2009, *JFE* 91(2), 119–138) split PIN into an asymmetric-information part and an illiquidity part. Only the illiquidity part is priced; the information part carries no pricing weight. Periodic volume spikes ("liquidity events") drive much of the signal — [IDEAS/RePEc](https://ideas.repec.org/a/eee/jfinec/v91y2009i2p119-138.html); [UW Foster (Fama-DFA prize)](https://blog.foster.uw.edu/?p=51620)

### Inferences
- **Strongest new slow candidate for us: C1, the day-vs-night beta gap.** It needs the stock's daily open and close plus an intraday and overnight market return. The market's open-to-close and close-to-open can come from the cap-weighted LARGE synthetic series already planned for `semibeta_neg_1y` (S5). The "asynchronous beta" needs lagged intraday market returns, so it does need minute bars. It is economically distinct from the already-listed semibetas, which split by sign, whereas C1 splits by session and timing.
- **C2 and C1 overlap.** Both use "overnight beta" vs "intraday beta". Pre-register only one, C1 being the more recent with explicit liquidity controls, or test both as one family so they count once in the multiple-testing tally (ADR 0043).
- **Intraday price delay (inference; no paper found using minute data).** Regress 5- or 15-minute stock returns on the contemporaneous and k lagged synthetic-market returns. Delay = 1 − R²(restricted) / R²(unrestricted), monthly. Expected sign: + (delay premium). It is very likely a size/illiquidity/visibility proxy (Lin et al. 2014; Yang–Yin's "strongest among small, illiquid"), so it must be tested within tier and against `amihud`.
- **Liquidity variability (C4).** Two of the four sources say negative, one says positive, and one says the negative sign is an omitted "liquidity decrease" effect. Pre-register the sign as negative and add a "liquidity-decrease" control (the change in minute-Amihud). Minute data lets us build a daily Amihud from minute |r|/₹volume, then take its 21- or 63-day coefficient of variation. A close-only construction is fine.
- **EOD reversal (C6) is not a factor at our horizon.** It reverses fully overnight. It also maps oddly onto NSE, where the official close is the 15:00–15:30 VWAP, which is the LH window itself. Its main use is execution: avoid buying intraday losers in the last half hour, or time planned trades. At most, run an India check of whether ROD3 (prev close → 14:30) predicts the 15:00–15:30 VWAP vs the 14:30–15:00 price. Keep it apart from F4 `close_pressure_5d`.
- **C5 (Siddiqui–Misra) is the only India-specific next-day intraday factor found.** Its formula is not public in the abstract, so it cannot be reproduced without the full text.
- **C7, the LMSW coefficient,** is cheap from minute data. Use 30-minute or daily returns with turnover: regress r(t+1) on r(t) and r(t)·volume_detrended(t) per stock over 6–12 months. The coefficient on the interaction is the signal. I found no cross-sectional return test, so treat it as a conditioning variable for the reversal and the BVC imbalance rather than as a standalone factor.
- **C8, vol-of-vol, from minute data (inference).** Take the 63-day std of daily realized variance divided by its mean, from 5-minute closes. This is a REALIZED analogue. The paper's evidence is for IMPLIED vol-of-vol, so realized vol-of-vol is an untested proxy. It is almost certainly correlated with size and with the level of volatility, and low-vol already failed in-house.
- **Other close+volume constructions with no published pricing evidence found this session.** These are candidates only; all are probably proxies:
  - Minute-volume entropy or Herfindahl (concentration) → likely an illiquidity/attention proxy.
  - Share of zero-return minutes → illiquidity (C9).
  - Roll (1984) spread from the negative autocovariance of minute returns → cost model, already on the menu.
  - Variance ratio VR(30 min / 1 min) → efficiency, related to C3.
  - Intraday-path "information discreteness" (Da–Gurun–Warachka style) applied to minute returns → its daily-return version is published, but I could not retrieve it this session.

### Gaps
- No source found for cross-sectional pricing of minute-level zero-return share, intraday volume entropy or concentration, intraday variance ratios, or realized idiosyncratic volatility estimated from intraday data. These remain untested ideas, not literature-backed anomalies.
- Yang & Yin (2024): sample market and period not given in the abstract.
- Siddiqui & Misra (2025): universe, period, frequency and measure formula not in the abstract.
- The Southampton cross-sectional first-half-hour result: page returned 403, so its sample and magnitudes are unverified.
- Liquidity commonality betas (Chordia–Roll–Subrahmanyam; Karolyi–Lee–van Dijk) as priced characteristics: I did not retrieve pricing evidence this session.
- Da–Gurun–Warachka (2014) "frog in the pan": search failed to retrieve it, so no figures or international replications.

## Q2. Do they survive controls (size, illiquidity, volatility, short-term reversal), hold outside the US, and replicate?

### Takeaway
Most of the new candidates survive the controls their authors chose. The two with independent replication or international evidence are liquidity variability (international, but with the sign flipped against one study) and LMSW (Taiwan, Australia). Several are strongest among small and illiquid names, which is a warning for MICRO/SMALL. India-specific intraday evidence exists but is thin: small samples, liquidity patterns, and one next-day overreaction factor.

### Cited Findings
- **C1:** controls for size, B/M, liquidity, investor recognition and limits to arbitrage; strongest in small, illiquid, less visible firms — [IDEAS](https://ideas.repec.org/a/eee/reveco/v96y2024ipbs1059056024006610.html)
- **C2:** survives many firm-characteristic controls, but a later study contradicts it on the same question — [Duke](https://scholars.duke.edu/publication/1227892); [AEA 2022](https://aeaweb.org/conference/2022/preliminary/paper/s3fzN82A)
- **C3:** not explained by size, liquidity or microstructure per the original paper; reinterpreted as liquidity risk by Lin et al. (2014) — [PolyU](https://research.polyu.edu.hk/en/publications/price-delay-premium-and-liquidity-risk/)
- **C4:** CSA controls for size, B/M, momentum and the volume level. The international evidence (Feng–Kang–Zhang 2023) finds a negative premium that is not IVOL, explained by liquidity decreases — [CFA RF](https://rpc.cfainstitute.org/-/media/documents/book/rf-publication/2001/rf-v2001-n3-3915-pdf.pdf); [IDEAS](https://ideas.repec.org/a/eee/jimfin/v139y2023ics0261560623001675.html)
- **C5 (India):** not explained by market, size, value, momentum or illiquidity factors — [IDEAS](https://ideas.repec.org/a/pal/assmgt/v26y2025i5d10.1057_s41260-025-00418-y.html)
- **C6:** survives size, volume, Amihud, realized-vol, overnight-vol and mispricing sorts; US only (1993–2019) — [ND PDF](https://academicweb.nd.edu/~zda/EOD.pdf)
- **C7:** replicated in Taiwan (consistent) and Australia (strongest in medium trades) — [NCCU](https://thesis.lib.nccu.edu.tw/detail/8032c8bc014f30620a23b0facbbbb0ac/); [Monash](https://research.monash.edu/en/publications/information-asymmetry-trade-size-and-the-dynamic-volume-return-re/)
- **C8:** distinct from more than 20 predictors; holds in the US and Europe — [JFQA PDF](https://personal.eur.nl/vanbekkum/2018JFQA_unknown_unknowns.pdf)

**India and emerging-market context, including evidence on items already on our menu:**
- Krishnan & Mishra (2012) use one year of intraday data on 20 NIFTY stocks. Most volume and spread liquidity measures show an intraday U-shape, and the evidence for commonality in liquidity is only weak (search-result summary) — [NEP listing](https://nep.repec.org/nep-mst/2012-09-30); [IISc microstructure page](https://mgmt.iisc.ac.in/cm/SS/rakhi.html)
- Kumar, Misra, Pant & Rahman (2024) measure commonality in liquidity for NIFTY50 stocks with high-frequency data. A 2018 limit-order-book study of 50 mid-caps found high co-movement with market and industry liquidity (search summary) — [IIT Jodhpur record](https://research.iitj.ac.in/publication/commonality-in-liquidity-evidence-from-indias-national-stock)
- A Nifty 500 daily study (2000–2018) reports a negative liquidity–expected-return relation at NSE, i.e. an illiquidity premium. This is consistent with our in-house Amihud/Kyle result in LARGE and MID — [NMIMS Management Review](https://management-review.nmims.edu/?p=737)
- An NSE intraday study reports reversals within a few minutes of extreme price rises and falls (search-result summary attributes it to Tripathi & Aggarwal 2015) — [Int. J. Financial Management, "Prior return effect in Indian stock market: an intra-day analysis"](https://publishingindia.com/archive/ijfm/prior-return-effect-in-indian-stock-market-an-intra-day-analysis)
- Paital & Sharma (2016) use 5-minute data on 50 Indian stocks and report that volume and bid-ask spread carry information useful for predicting returns (search summary) — [IDEAS](https://ideas.repec.org/a/asi/aeafrj/v6y2016i3p135-150id1470.html)

### Inferences
- The recurring pattern is "strongest in small, illiquid stocks" (C1, C3, C6 at 14.71 vs 3.41 bps). Every new candidate must be ranked within tier, and SMALL results must be netted against the per-stock cost model before anything is believed.
- India's weak intraday liquidity commonality in large caps (Krishnan & Mishra) suggests a liquidity-commonality beta may have little cross-sectional spread among NIFTY names. This is inference from a 20-stock, one-year sample.

### Gaps
- No India or EM replication found for C1, C2, C3, C6 or C8.
- The Finnish replication of CSA (Aalto thesis) was found but its results were not retrieved — [Aalto](https://aaltodoc.aalto.fi/items/0fd26225-8b4a-4823-a7ca-7c316ee9890d)
- No short-term-reversal control is reported in the abstracts for C1, C4 or C5. Our in-house 21-day reversal failed, but each candidate should still be orthogonalised against it.
- Bekaert–Harvey–Lundblad (2007) emerging-market zero-return liquidity: page returned 403, so no figures.

## Q3. Which can be computed honestly from minute CLOSE + VOLUME only?

### Takeaway
All eight families can be built from close + volume, given a synthetic market minute series for the beta-type measures. None strictly needs per-minute high/low or quotes, except the trade-size refinement of LMSW and true PIN (which needs trade direction; Duarte–Young show its priced part is illiquidity anyway).

### Cited Findings
- C1's inputs are day and night betas plus a lagged-market "asynchronous" beta. All are return-based — [IDEAS](https://ideas.repec.org/a/eee/reveco/v96y2024ipbs1059056024006610.html)
- C2's jump vs continuous betas come from high-frequency price returns (the original uses ~1,000 US stocks' high-frequency prices) — [Duke](https://scholars.duke.edu/publication/1227892)
- C6 uses only interval returns (ROD3, LH), with the second-to-last half hour skipped to avoid bid-ask bounce. This makes it close-only and bounce-safe — [ND PDF](https://academicweb.nd.edu/~zda/EOD.pdf)
- C7 uses returns and volume only. The original uses daily volume and first-order autocorrelation — [NYU archive](https://archive.nyu.edu/handle/2451/26698)
- C8's published version needs option-implied vol. NSE stock options exist only for F&O names — [JFQA PDF](https://personal.eur.nl/vanbekkum/2018JFQA_unknown_unknowns.pdf)
- C9: zero returns are a close-only staleness measure, driven mainly by volume — [SNS PDF](https://ricerca.sns.it/retrieve/e3aacdfd-f331-4c98-e053-3705fe0acb7e/MS2018440_Kolokolovetal.pdf)
- PIN needs signed order flow, and its priced component is illiquidity — [IDEAS](https://ideas.repec.org/a/eee/jfinec/v91y2009i2p119-138.html)

### Inferences

| ID | Construction from minute close + volume | Horizon | Expected sign | Close-only caveat |
|---|---|---|---|---|
| C1a `beta_daynight_gap_1y` | β on synthetic-market open→close minus β on market close→open, 252 days | slow (monthly) | + (paper's sort direction; check the full text) | Our "open" is the 09:15 first bar plus `stock_prices.open`; there is no pre-open auction bar |
| C1b `beta_async_1y` | Sum of β on lagged 5- or 15-minute market returns | slow | + | Lagged-market betas pick up non-trading. Floor at a minimum bars-per-day |
| C2 `beta_jump_1y` | β on market 5-minute returns flagged as jumps (threshold > k·σ̂ bipower) | slow | contested | Needs many jump days for each stock; noisy |
| C3 `intraday_delay_1m` | 1 − R²_restricted / R²_with_lags, 5-minute returns | slow | + | Proxy for illiquidity. Must beat `amihud` within tier |
| C4 `illiq_cv_3m` | CV of daily minute-Amihud (Σ\|r\| / ₹vol), 63 days | slow | − (pre-register) | Add a Δilliq control (Feng et al.) |
| C5 India overreaction | Not reproducible without the full text | fast (1 day) | + | Formula unknown |
| C6 EOD reversal | ROD3 → 15:00–15:30 VWAP | intraday | − | Not a factor; execution rule only |
| C7 `lmsw_c2_6m` | Per-stock OLS r_{t+1} ~ r_t + r_t·V̂_t | conditioning | continuation = informed | Trade-size split impossible |
| C8 `rvolvol_3m` | std(RV_daily) / mean(RV_daily), 5-minute RV | slow | − | Realized, not implied; untested proxy |
| C9 `zero_min_share_1m` | Share of zero-return minutes among traded minutes | slow | + (illiquidity) | Tick-size discreteness differs by price level, so normalise by tick / price |

### Gaps
- I did not verify which direction of the C1 gap (day > night or night > day) is the long leg; the abstract does not say.
- No published guidance found on the jump-detection threshold for 1-minute close-only Indian data.

## Q4. Which are known to fail, be fragile, or be absorbed by others?

### Takeaway
Treat the whole "trading frictions" family with suspicion. Hou–Xue–Zhang find 96 % of trading-frictions anomalies fail a t ≥ 1.96 hurdle once microcaps are controlled. Chen–Zimmermann find that clearly significant original predictors do replicate. That points to "real but concentrated in small stocks" rather than "fake". PIN is absorbed by illiquidity. Price delay is arguably absorbed by liquidity risk. Liquidity variability flips sign across studies. The jump-beta pricing is contradicted. EOD reversal is real but transient.

### Cited Findings
- Hou, Xue & Zhang ("Replicating Anomalies", *RFS* 2020, 452 anomalies) report that 96 % of the trading-frictions category fails the single t ≥ 1.96 hurdle. The NBER WP version has 95 of 102 frictions variables failing, about 93 %. With a 2.78 multiple-testing hurdle, 82 % of all anomalies fail. Replicated effects are much smaller than originally reported — [NBER w23394](https://www.nber.org/papers/w23394.pdf); [IDEAS RFS record](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html); [CXO summary](https://cxoadvisory.com/?p=29802)
- A critique says the HXZ result mainly restates that anomalies concentrate in small stocks — [Alpha Architect](https://alphaarchitect.com/5-surprising-things-we-learned-from-a-factor-investing-expert/)
- Chen & Zimmermann (*Critical Finance Review* 2022): 98 % of the 161 characteristics that were clearly significant in the original papers reach t > 1.96. Of the 114 that were originally insignificant or were HXZ modifications, most fail — [CFR](https://nowpublishers.com/article/Details/CFR-0112); [SSRN](https://papers.ssrn.com/abstract=3604626)
- The Pástor–Stambaugh liquidity-risk (aggregate liquidity beta) result was independently replicated by Li, Novy-Marx & Velikov (2017) and Pontiff & Singla (2019), with similar premium estimates (per the authors' "Liquidity Risk After 20 Years") — [NBER w25774](https://www.nber.org/system/files/working_papers/w25774/w25774.pdf)
- PIN is absorbed by illiquidity (Duarte–Young 2009) — [IDEAS](https://ideas.repec.org/a/eee/jfinec/v91y2009i2p119-138.html)
- Price delay is reinterpreted as liquidity risk (Lin et al. 2014) — [PolyU](https://research.polyu.edu.hk/en/publications/price-delay-premium-and-liquidity-risk/)
- Liquidity variability: negative in CSA 2001, Pereira–Zhang 2010 and Feng et al. 2023; positive in Akbas et al. 2011 — [CFA RF](https://rpc.cfainstitute.org/-/media/documents/book/rf-publication/2001/rf-v2001-n3-3915-pdf.pdf); [arXiv 2306.15807](https://arxiv.org/pdf/2306.15807); [IDEAS JIMF](https://ideas.repec.org/a/eee/jimfin/v139y2023ics0261560623001675.html); [OU WP](https://www.ou.edu/content/dam/price/Finance/CFS/paper/pdf/Petkova%20Paper.pdf)
- Jump and overnight beta pricing is contradicted by Hemauer & Mörke — [AEA 2022](https://aeaweb.org/conference/2022/preliminary/paper/s3fzN82A)
- EOD reversal reverts overnight (t = −0.47 including the next overnight). The authors say frequent rebalancing may make it unexploitable for many investors after costs — [ND PDF](https://academicweb.nd.edu/~zda/EOD.pdf)
- Related prior from HKS (on our list as periodicity): a stock's intraday return over an interval is negatively related to its returns over recent intervals (as cited in BDS 2025) — [ND PDF](https://academicweb.nd.edu/~zda/EOD.pdf)

### Inferences
- **Probably just proxies for size, illiquidity or volatility:**
  - Zero-return-minute share (C9) and FHT → illiquidity; volume drives staleness.
  - Intraday price delay (C3) → illiquidity and visibility.
  - Liquidity variability (C4) → liquidity decreases.
  - PIN → illiquidity.
  - Realized vol-of-vol (C8) → volatility level.
  - Volume entropy/concentration → illiquidity and attention.

  Since daily Amihud/Kyle already works in LARGE and MID in-house, these should be tested as INCREMENTAL to `amihud` within tier. Otherwise they will re-discover it.
- **Least likely to be a pure proxy:** C1, the day/night beta gap, because the authors control for liquidity and investor recognition and show it adds beyond HM delay. C7, LMSW, is a conditional-dynamics measure, not a level.
- **Testing burden:** each family adds to the ~269-hypothesis count behind our HLZ bar (|t| ≈ 4.2 Bonferroni, ADR 0043). Pre-register at most C1 (one variant), C4 (one, sign negative), C3 or C9 (one illiquidity-family entry, judged only as incremental to Amihud), and C7 as a conditioning interaction, not a standalone factor. Park C2, C6, C8 and C5 for the reasons above.

### Gaps
- The search did not establish whether "price delay", "zero-trade", "volume variability" or "liquidity beta" signals in the Chen–Zimmermann dataset clear t > 1.96 individually. That would need the CZ signal-documentation file, which was not fetched.
- Jensen–Kelly–Pedersen (2023) replication results for frictions/liquidity clusters were not retrieved this session.
- No known-failure literature found specifically for the day/night beta gap (C1); it is recent (2024) and unreplicated as far as found.
