# Non-factor uses of 1-minute bars (close + volume) in an NSE equity model

Scope: risk, volatility forecasting, transaction-cost / impact models, execution, portfolio construction, regime signals, options inputs, data quality. Data fixed: 2015-02 to 2026-10, ~2,420 NSE survivors, per-minute close and volume only (no high/low, quotes or trade sign), no index minute bars, session 09:15-15:29. Model fixed: monthly long-only tier books, weekly SMALL tactical book, multibagger book in the Rs 0.5-1 Cr/day ADTV band, paper NIFTY short-strangle book. Costs today are flat 16/18/31 bps, plus a 150 bps SMALL placeholder.

Convention: "Cited Findings" are sourced facts. "Inferences" are my reasoning about how a finding applies to our data and books, including proposed computation recipes. They are not literature results. Any arithmetic marked "illustrative" uses hypothetical inputs, not measured values.

---

## 1. Risk: realized volatility, covariance and beta from intraday data (HAR vs GARCH, Epps effect, thin stocks)

### Takeaway
Intraday realized variance (RV) is the standard input for volatility forecasting: HAR-RV fitted by OLS is the benchmark that daily GARCH-type models are compared against, and 5-minute RV is hard to beat across asset classes. For our **monthly-rebalanced** books, though, the published portfolio gain from intraday *covariance* estimates mostly vanishes once you use 12 months or more of daily data. For illiquid names, intraday beta is distorted by asynchronous trading (Epps effect), and the best-tested broad-universe beta is still daily, exponentially weighted and shrunk. Use the minute bars first for volatility forecasts (risk targeting, sizing, the option book). Use them for beta and covariance only in liquid names, or with short estimation windows.

### Cited Findings
- ABDL (2003) set out the framework for turning high-frequency intraday data into measures and forecasts of daily and lower-frequency volatility and return distributions. A simple long-memory Gaussian VAR on log daily RV "perform[s] admirably", and paired with a lognormal-normal mixture it gives well-calibrated density and quantile forecasts. The authors list large covariance matrices for asset allocation and risk management as applications. — [Econometrica 71(2) 579-625](https://www.econometricsociety.org/publications/econometrica/2003/03/01/modeling-and-forecasting-realized-volatility)
- Corsi (2009) HAR-RV is an additive cascade of daily, weekly and monthly RV components, reported to give "remarkably good forecasting performance". It is estimated by plain OLS rather than numerical optimisation. — [J. Financial Econometrics 7(2):174](https://academic.oup.com/jfec/article/7/2/174/856522); [SSRN](https://papers.ssrn.com/abstract=1365738)
- Out-of-sample evidence on HAR vs GARCH is mostly favourable but varies:
  - A master's thesis on the AEX (2000-2018) found HAR-RV beat GARCH(1,1) and the VAEX implied-vol index on MSE and MAE, including in crisis subperiods and on S&P 500 / Nikkei robustness checks (252-day training window). — [thesis repository](https://theses.ubn.ru.nl/handle/123456789/8385)
  - A Tehran Stock Exchange study found simple HAR-RV beat alternatives only at the monthly horizon. — [Financial Research Journal](https://jfr.ut.ac.ir/m/article_68613.html?lang=en)
  - A 2025 paper still treats HAR as the benchmark new models must beat. — [arXiv 2506.07928](https://arxiv.org/pdf/2506.07928)
- HARQ (Bollerslev, Patton, Quaedvlieg 2016, J. Econometrics 192(1):1-18) uses realized quarticity as a proxy for RV measurement error. Coefficients vary with that error, so forecasts lean more on recent RV when it is measured precisely. It is still OLS. — [Maastricht record](https://cris.maastrichtuniversity.nl/en/publications/exploiting-the-errors-a-simple-approach-for-improved-volatility-f/). Secondary work reports HARQ beating plain HAR and HAR-with-jumps. — [Bekierman & Manner WP](https://static.uni-graz.at/fileadmin/_Persoenliche_Webseite/manner_hans/Publikationen/Bekierman_and_Manner_WP.pdf). The magnitude was not retrieved (see Gaps).
- Sampling frequency: Liu, Patton & Sheppard (2015) and Bollerslev, Hood, Huss & Pedersen (2018) "show that the 5-minute realized volatility tends to perform very well across different asset classes". The Fed paper citing them also uses 30-minute RV as a robustness check against microstructure noise, with cleaning in the spirit of Barndorff-Nielsen, Hansen, Lunde & Shephard (2009). — [Jahan-Parvar & Zikes, FEDS 2019-051](https://www.federalreserve.gov/econres/feds/files/2019051pap.pdf)
- Portfolio value of intraday covariance:
  - Fleming, Kirby & Ostdiek (2003, JFE) estimate a risk-averse investor would pay **50-200 bps per year** to switch from daily to intraday returns when estimating the conditional covariance matrix for volatility timing. The gain is robust to transaction costs, estimation risk in expected returns and measurement horizon. — [abstract reproduced by SUFE newsletter (aggregator)](https://academicnewsletter.sufe.edu.cn/info/357738)
  - Q. Liu (2009, J. Applied Econometrics 24(4):560-582), tracking the S&P 500 with the 30 DJIA stocks: **with monthly rebalancing and at least 12 months of history, daily data can match high-frequency data**. Gains are substantial only with daily rebalancing or an estimation window under six months. Results hold after transaction costs. — [IDEAS](https://ideas.repec.org/a/jae/japmet/v24y2009i4p560-582.html); [ZBW replication data](https://journaldata.zbw.eu/dataset/30606726-21dc-4c9f-88c4-f5362704e596)
- Beta:
  - Hollstein, Prokopczuk & Wese Simen (J. Financial Markets 2019, 44:91-118), across the whole US universe over 50+ years: the best forecast of future beta was daily returns with exponential weighting plus simple shrinkage. Adjustments for asynchronous trading, macro conditions or regression combinations typically gave very high prediction errors. — [Liverpool repository](https://livrepository.liverpool.ac.uk/3052274/)
  - Commentary on their 2017 working paper says high-frequency (sub-daily) data estimate beta more precisely for S&P 500 firms but are reliable only for the most liquid stocks. — [CXO Advisory](https://www.cxoadvisory.com/equity-premium/smartest-beta/)
  - A dissertation chapter concludes the value of high-frequency data for beta estimation is limited. — [TIB repository](https://edocs.tib.eu/files/e01dh15/845012401.pdf)
  - A Duke honors thesis found the best (frequency, window) pair for large liquid stocks as short as 1 minute and 1 week. — [DukeSpace](https://dukespace.lib.duke.edu/items/59c12d37-0d0f-42e6-85f2-7777141c179f)
- Epps effect and asynchrony:
  - Measured correlations fall as sampling frequency rises, and asynchronous observation is the main statistical cause. Previous-tick interpolation onto a fixed grid (e.g. 5-minute) is biased. Hayashi-Yoshida (summing products over all overlapping return intervals) fixes the asynchrony bias and equals realized covariance when data are synchronous. — [arXiv 2011.11281](https://arxiv.org/pdf/2011.11281)
  - Hayashi-Yoshida becomes inconsistent and unreliable in high dimensions. — [arXiv 2201.00119](https://arxiv.org/pdf/2201.00119)
  - One abstract reports that the bias of the usual covariance estimator is larger for less liquid assets, derives an optimal sampling frequency, and proposes a two-scale estimator that cancels Epps to first order. Authors and journal not verified. — [SciSpace topic page](https://scispace.com/topics/epps-effect-39py2tbz)

### Inferences
- **Highest-value risk use: an HAR(Q)-RV volatility forecast per stock and for a synthetic NIFTY.** Compute daily RV as the sum of squared 5-minute log returns built from the 1-minute closes. Five-minute sampling fits the literature, and the 1-minute grid allows subsampling: average the five offset 5-minute grids to cut noise. Keep the overnight return (prev official close to 09:15 or 09:20) as a separate HAR regressor rather than adding it to RV. Uses:
  - vol-scaled position sizing / risk parity inside each book
  - a portfolio-level ex-ante vol target
  - the RV leg of the strangle book's VRP (section 5)

  Effort: low (OLS, a few hundred lines). Risk: low. The model is standard; the main trap is the 15:00-15:30 closing-VWAP window and the open (see section 6).
- **Covariance for monthly books: expect little.** Liu (2009) says daily data with 12 months or more match intraday data at monthly rebalancing. The 50-200 bps FKO figure is for volatility *timing* and does not carry over to monthly long-only factor books. Intraday covariance is worth it only if we want a fast-reacting risk estimate: a 1-3 month window, the weekly SMALL tactical book, or crisis de-risking. That is when Liu finds gains.
- **Beta for thin SMALL / multibagger names: don't use minute data naively.** A Rs 0.5-1 Cr/day stock may go many minutes without a trade, so minute closes repeat (stale) and correlations with the index are biased toward zero (Epps). Options, in rising effort:
  - Default: daily or 30-minute returns with Dimson-style lead/lag terms, or exponentially weighted daily plus shrinkage (the Hollstein et al. winner).
  - Hayashi-Yoshida on trade-time returns, using minutes with volume > 0 as "trades", for single-stock beta against the synthetic index. Fine in 2-asset form; the high-dimensional failure applies to full covariance matrices, not single betas.
  - Hard rule: estimate the sampling frequency per liquidity bucket by plotting average beta against frequency (1, 5, 15, 30, 65 minutes). The frequency where beta stabilises is the usable one. This Epps-signature plot is cheap and data-driven.
- **Survivorship affects the risk model.** A synthetic index built from survivors misses constituents that delisted or merged. Index-level RV in years with such exits will be slightly mis-weighted. Validate the synthetic index's daily close-to-close returns against the official NIFTY daily series; daily index data is available even though minute index data is not.

### Gaps
- No published NSE study found that quantifies HAR-RV vs GARCH forecast gains on Indian stocks or NIFTY. The Indian intraday-volatility papers found (section 3) describe intraday shape, not forecast accuracy.
- The out-of-sample loss reductions of HAR or HARQ over GARCH were not retrieved from the primary papers. Only qualitative "outperforms" statements are sourced.
- No study found on intraday beta for Indian small caps, or for stocks at our ~Rs 1 Cr ADTV level.
- The FKO 50-200 bps figure comes via an aggregator copy of the abstract; the asset set and rebalancing frequency were not verified from the paper.

---

## 2. Costs: spread and market impact from close + volume bars; capacity

### Takeaway
Close-only (or close/high/low) spread estimators work best in exactly the stocks we care about most: illiquid, wide-spread names. Abdi-Ranaldo gets cross-sectional correlations of 0.74-0.86 with TAQ effective spreads. In liquid large caps, the same estimators are **heavily upward-biased**, because volatility dominates when the true spread is small: biases of 150% to over 2,000% of the true spread. With 1-minute data we can compute intraday versions (Roll on 1-minute returns, a noise-variance spread, minute-level Amihud), which the Fed paper suggests track true costs better than daily ones. Impact should be modelled as roughly square-root in participation (Q/ADV), scaled by daily volatility. That is the piece that decides capacity and the 150 bps SMALL question. Measured spreads and true impact still need a calibration anchor (our own fills, or NSE's published impact cost).

### Cited Findings
- Abdi & Ranaldo (2017, RFS 30(12):4437-4480) estimate the spread from daily close, high and low; it resembles Roll but does not rely on bid-ask bounce. — [IDEAS](https://ideas.repec.org/a/oup/rfinst/v30y2017i12p4437-4480..html). Results from the paper:
  - Monthly average cross-sectional correlation with daily-TAQ effective spreads is **0.74**, against **0.37-0.65** for HL (Corwin-Schultz), Roll, Gibbs, EffTick and FHT.
  - On monthly TAQ 1993-2003: **0.86** vs **0.61-0.83**.
  - Best for small-to-mid caps and medium-to-large spreads, i.e. less liquid stocks.
  - By trade-frequency decile, average bias ranges from **-80 to +84 bps** for CHL vs **-146 to +78 bps** for HL (Corwin-Schultz). CHL's negative bias is much smaller in the less liquid deciles.
  - Source: [paper PDF, Univ. St. Gallen](https://www.alexandria.unisg.ch/server/api/core/bitstreams/dfb85399-5bcf-465c-8b63-9bfc97ad2ee0/content)
- Jahan-Parvar & Zikes (Fed FEDS 2019-051) compared daily-data cost measures with high-frequency benchmarks. — [paper](https://www.federalreserve.gov/econres/feds/files/2019051pap.pdf)
  - For US equities, daily-data measures are "highly upward biased and imprecise", the bias is a function of volatility, and volatility, not cost, mainly drives these proxies in the cross-section and over time.
  - S&P 1500 monthly: true TAQ spread averages **12.4 bps**, while low-frequency measures average **26.4 bps (Corwin-Schultz, "CSM") to 168 bps (HL)**. Abdi-Ranaldo variants average **82.2 bps (ARD)** and **157 bps (ARP)**.
  - Simulation (390 trades/day, 3% daily vol): with a true spread of 10 bps, bias runs from **35 bps (CSM) to 236 bps (ARP)**, i.e. **250% to 2,260%** of the true spread. When the spread is large, the bias is "reasonable".
  - At annual frequency: DJIA 30 CSM falls from 16 to 11 bps against a 4 bps TAQ spread (still ~156% bias). S&P 600 small caps go from 36 to 27 bps against 20 bps TAQ, so the bias shrinks much more for small caps.
  - Using low-frequency proxies in asset-pricing tests can give sizable biases and spurious inferences about pricing of liquidity or volatility risk.
- Frazzini, Israel & Moskowitz, "Trading Costs": AQR live executions, ~$1.7 trillion across 21 developed markets. Realized costs are about an order of magnitude smaller than earlier studies suggested. — [SSRN 3229719](https://papers.ssrn.com/abstract=3229719)
  - Secondary summaries: trade size as a fraction of daily volume is the main determinant of impact, which rises at a diminishing (concave) rate. — [etf.com (Swedroe)](https://www.etf.com/sections/index-investor-corner/swedroe-trading-cost-truths)
  - Average market impact is "just under 9 bps" for trades completed within a day, ~85% of it permanent. — [Alpha Architect summary](https://alphaarchitect.com/the-best-research-paper-ever-written-on-trading-costs/); page returned 403 on fetch, figure taken from the search excerpt, unverified against the paper.
  - Later work notes this literature usually models impact as a function of the square root of order size and cites FIM's estimates. — [Goyal, Jegadeesh & Wu, JFQA](https://jfqa.org/wp-content/uploads/2026/01/25551_Price_Impact.pdf)
- Square-root law: Tóth et al. (2011, Phys. Rev. X) give empirical support for "square-root" metaorder impact. They explain it by a V-shaped latent supply/demand profile that vanishes near the price. — [arXiv 1105.1694](https://www.arxiv.org/abs/1105.1694v3)
  - Search summaries of the paper give the form impact ≈ Y·σ_daily·√(Q/V_daily) with Y "of order unity", and the exponent varies somewhat across datasets. The abstract fetched did not contain the formula, so treat the exact form as needing confirmation from the PDF.
  - A 2025 Tokyo SE study argues the impact is essentially mechanical. — [IDEAS 2502.16246](https://ideas.repec.org/p/arx/papers/2502.16246.html)
- Almgren, Thum, Hauptmann & Li (2005, Risk 18:57-62), Citigroup US desk data: reject square-root *temporary* impact as a function of trade rate in favour of a **3/5 power law**. — [Risk.net](https://www.risk.net/derivatives/structured-products/1500270/equity-market-impact); [PDF](https://www.cis.upenn.edu/~mkearns/finread/costestim.pdf)
  - A Chinese-market study found the impact exponent roughly constant at **~0.7** across stocks. — [J. of Risk](https://www.risk.net/journal-of-risk/5861701/equity-market-impact-modeling-an-empirical-analysis-for-the-chinese-market)
  - A secondary source in the search results reported Almgren et al.'s coefficient η = 0.141 and β = 0.6. I could not confirm which paper this came from; treat η as unverified.
- NSE "impact cost": the percentage gap between the average execution price of a predefined order size and the ideal price (the mid of best bid and ask), computed separately for buys and sells. A penal impact cost applies when a stock is not liquid enough. — [NSE indices impact cost](https://www.nseindia.com/static/products-services/indices-impact-cost); [NIFTY Indices concept page](https://niftyindices.com/resources/index-concepts/impact-cost) (fetch timed out; content via search summary)
  - A third-party glossary states NIFTY 50 eligibility requires impact cost ≤ 0.50% on a Rs 10 crore basket order, on ≥ 90% of observations over six months. Not confirmed against NSE methodology. — [EquitiesIndia](https://equitiesindia.com/glossary/impact-cost)

### Inferences
Proposed computation recipes for our data:
- **(a) Intraday Roll spread:**
  - Formula: s = 2·√(−Cov(Δp_t, Δp_{t−1})), on 1-minute log returns per stock-day, keeping only minutes with volume > 0 so stale repeats don't contaminate it.
  - Aggregation: average the autocovariance over a month before taking the root, to avoid many days with positive autocovariance.
  - Why it works: the minute close is a last-trade price, so bid-ask bounce is in it.
  - Weakness: Roll is biased when returns have genuine intraday serial correlation.
- **(b) Noise-variance spread (signature-plot method):**
  - Formula: RV at 1-minute minus RV at 15- or 30-minute, divided by 2n, estimates the noise variance ω². For bounce noise, the implied effective half-spread is ~ω. This is the logic behind the Hansen-Lunde noise literature; it is my derivation, not a sourced number.
  - Strength: uses the full minute grid and is less volatility-contaminated than daily CHL. JPZ's critique is that daily measures pick up volatility; intraday measures separate the two by frequency.
- **(c) Intraday Abdi-Ranaldo / Corwin-Schultz:**
  - Method: build pseudo-high/low per 5- or 15-minute bar from the max/min of 1-minute closes, and run CHL on those bars.
  - Caveat: max/min of minute closes understates the true range. CS and AR assume the true high and low, so this pushes spread estimates down. Validate against (a)/(b).
- **(d) High-frequency Amihud:** |r| / (Rs value traded) per 5- or 15-minute bucket, median per day/month. It is a price-impact-per-rupee measure, which links directly to the impact model.
- **(e) Impact model:**
  - Form: cost_bps = half-spread (from a-c) + Y·σ_daily·(Q/ADV)^δ, with δ in 0.5-0.7 (square-root to Almgren/China exponents). σ_daily comes from section 1's HAR forecast; ADV from minute volume, excluding the closing window if we don't trade there.
  - Y and δ cannot be estimated from public bars alone: they need parent-order data (our own fills) or published benchmarks. Start with literature-type values, flag them as assumptions, and calibrate on paper-book fills or a broker's TCA report.
  - **This replaces the flat 16/18/31 bps and the 150 bps placeholder with per-stock, per-trade-size costs.**
- **Illustrative arithmetic only (hypothetical inputs):** a multibagger name with σ_daily = 3% and an order at 10% of ADV, Y = 1, δ = 0.5, has impact ≈ 3% × √0.1 ≈ 95 bps before spread. At 20% of ADV, ≈ 134 bps.
  - On a Rs 0.5 Cr/day stock, 10% of ADV is Rs 5 lakh per day. Position size is capped by days-to-trade × participation.
  - This is why the 150 bps placeholder is plausible for that band but needs per-stock values. The minute data provides σ and ADV; it does not provide Y.
- **Capacity:** per book, invert the impact model. Find the AUM where expected alpha minus expected cost (spread + impact at the participation needed to rebalance in N days) = 0. Report it per tier and per book. This is a direct, cheap output once (e) exists.
- **Where bars are enough vs where quotes are needed:**
  - Bars are enough for relative cost rankings across stocks and over time (good for cost-aware portfolio construction).
  - Bars are not enough for absolute levels in liquid LARGE names, where JPZ's results say low-frequency proxies overstate costs several-fold. There the true spread is probably a few bps, and NSE impact-cost data or a quote snapshot is the better anchor.
- **Effort/risk:** (a), (b), (d) are low effort, a vectorised pass over the minute table. (e) is medium effort. The main risk is false precision in Y; mitigate by reporting a band (δ = 0.5 and 0.7, Y range) and making the go/no-go decision robust to the band.

### Gaps
- No study found that tests Roll, Corwin-Schultz, Abdi-Ranaldo or intraday estimators against true NSE effective spreads. The accuracy figures above are all US (TAQ).
- No published NSE estimate of square-root impact coefficients (Y, δ) for Indian small caps was found.
- FIM's full coefficient tables (impact by % of ADV bucket, break-even capacity of value, momentum and size) were not retrieved; the paper page returned 403.
- NSE does publish stock-level impact cost for index work, but I could not confirm public historical per-stock impact-cost files that could serve as a calibration target. This is worth checking on nseindia.com / niftyindices.com.
- No primary source retrieved for the "Hansen-Lunde noise variance → spread" mapping; it is presented as my derivation.

---

## 3. Execution: VWAP/TWAP scheduling, volume-profile forecasting, time of day in India, the closing VWAP

### Takeaway
The minute volume field is exactly what a VWAP scheduler needs: a per-stock intraday volume profile and a daily-volume forecast. Indian intraday volatility is U- or reverse-J-shaped: high at the open, with the close elevated less than in other markets. NSE's official close is the VWAP of the last 30 minutes, which makes "trade the closing window" a natural benchmark-matching execution for a model that marks to the official close. A secondary source reports this window moved to 15:10-15:40 from 3 Aug 2026, with a closing auction for F&O stocks. **Verify before relying on 15:00-15:30.**

### Cited Findings
- Singh & Gangwar (2018), 1-minute NIFTY 50 futures, Jan 2011-Aug 2018: U-shaped intraday volatility (highest at start and end of session), with hourly volatility declining over the period. Working paper. — [MPRA 89689](https://mpra.ub.uni-muenchen.de/89689/1/MPRA_paper_89689.pdf)
- IIMA working paper (2012), high-frequency NSE stock data with FFF regressions: Indian stocks show a **"reverse J"** intraday volatility shape, with much higher intraday variation than reported in other markets. It also finds higher volatility after weekends and holidays, and around trading halts and derivatives expiry days. — [IIMA WP](https://iima.ac.in/sites/default/files/rnpfiles/19191060542012-11-03.pdf)
- NSE closing price = volume-weighted average of trades in the last 30 minutes (traditionally 15:00-15:30), falling back to last traded price if no trades. — [EquitiesIndia glossary](https://equitiesindia.com/glossary/closing-price-weighted-average); [Motilal Oswal](https://www.motilaloswal.com/learning-centre/2023/7/why-is-there-a-difference-between-the-ltp-and-closing-price-on-nse)
- A broker blog reports that NSE extends the F&O close to 15:40 from **3 Aug 2026**, that the 30-minute VWAP close method stays but the window moves to **15:10-15:40**, and that a Closing Auction Session initially applies to stocks with derivatives. No circular number is cited and CAS timings appear only in an image. — [Arihant Plus](https://www.arihantplus.com/blogs/market-updates/nse-extends-f-and-o-market-close-to-3-40-pm-what-traders-must-know)
- FIM: impact rises concavely with trade size as a fraction of daily volume, so spreading an order over more volume reduces cost. — [etf.com summary](https://www.etf.com/sections/index-investor-corner/swedroe-trading-cost-truths)

### Inferences
- **Volume-profile forecast (low effort, high practical value):**
  - Profile: per stock, the fraction of daily volume in each 5/15-minute bucket, averaged over the trailing 20-60 days, shrunk toward the tier-average profile for thin names. Special-day profiles for expiry days, results days and index rebalance days.
  - Total-volume forecast: a HAR-style regression of log daily volume.
  - Together these give the VWAP schedule and the expected participation for any order, which feeds section 2's impact model.
- **Best time of day:**
  - Measure, don't assume. For each tier, compute by bucket the intraday Roll / noise spread and the minute Amihud (section 2).
  - The literature's reverse-J shape implies the open is the costliest/most volatile window and the close is relatively cheaper in India.
  - For a model whose returns are measured close-to-close on the official close, executing across the closing VWAP window minimises tracking error to the backtest price.
  - Quantify the "official close vs our achievable price" gap. From minute bars, compute the VWAP of 15:00-15:29 (or 15:10-15:40 post-Aug-2026) and compare it to the official close (section 6); this is also a data check.
- **Backtest realism for SMALL / multibagger:** simulate each rebalance as a participation-capped VWAP over N days (e.g. ≤ 10-20% of forecast minute volume). Record the fill price vs the official close, and the number of days needed. This turns the "edge sits in Rs 0.5-1 Cr/day names" finding into a capacity-and-delay-adjusted return. Effort: medium.
- **Risk:** the closing auction change (if confirmed) alters the closing window's microstructure for F&O stocks from Aug 2026. Profiles estimated pre-change may not hold. Our stated session (09:15-15:29) may not cover 15:30-15:40 for the cash market post-change. Check what the feed now records.

### Gaps
- No NSE study found that directly measures the intraday **volume** U-shape, or effective spread by time of day, for cash equities.
- The 3 Aug 2026 closing-window and CAS change is from a secondary broker source; the NSE circular, auction timings and whether continuous cash-market hours changed were not confirmed.
- No published Indian evidence on VWAP-vs-close slippage for small-cap institutional orders was found.

---

## 4. Regime / market state: market intraday momentum, breadth, dispersion, realized correlation

### Takeaway
Market intraday momentum (the first half-hour return predicts the last half-hour) is well documented in the US: R² 1.6%, OOS R² 1.4%, timing Sharpe 1.08. It is significant in 12 of 16 developed markets, strongest on high-volatility days and in less liquid instruments. Indian evidence is thin: one paper suggests reversal rather than momentum patterns on NSE, and India was not in the main international samples. It is a test we can run on a synthetic NIFTY. Practically, it informs execution timing and the option book's intraday risk more than our monthly books. Realized correlation, dispersion and breadth from minute data are cheap state variables, but I found no published evidence quantifying their timing value for an Indian long-only book.

### Cited Findings
- Gao, Han, Li & Zhou (JFE 2018), SPY data: [paper PDF](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/ee7dac49-530b-4950-b5d0-e0b5eee08f2e.pdf); [SSRN 2440866](https://ssrn.com/abstract=2440866)
  - The first half-hour return predicts the last half-hour return with **R² = 1.6%**, rising to **2.6%** when the 12th half-hour return is added.
  - OOS R² is **1.4%** (first half-hour alone) and **0.9%** (12th half-hour alone).
  - Certainty-equivalent gains are **6.02%** per annum, or **6.18%** with the 12th half-hour.
  - The sign-timing strategy earns **6.67%/yr** with s.d. **6.19%** (Sharpe **1.08**), against buy-and-hold **6.04%** with s.d. **20.57%**. Always-long in the last half-hour earns **−1.11%/yr**.
  - Predictability rises with first half-hour volatility: R² **0.6%** (low), **1.0%** (mid), **3.3%** (high).
  - The pattern also holds for micro, small and large stock portfolios. On less liquid ETFs, OOS predictability and CE gains are often *greater* than on SPY.
  - The paper discusses transaction costs and reports significance remains after accounting for them.
- Li, Sakkas & Urquhart (international ITSM), 16 **developed** markets (Hong Kong and Singapore excluded; **India not included**). — [working paper](http://wp.lancs.ac.uk/fofi2020/files/2020/04/FoFI-2020-092-Zeming-Li.pdf)
  - The first half-hour predicts the last half-hour in **12 of 16** markets, and slopes are larger in crises and recessions.
  - ITSM alphas have annualised appraisal ratios from **0.52 (UK) to 0.99 (Norway)**.
  - The US first half-hour predicts other markets' last half-hour in **9 of 16**.
- APAC: intraday momentum found mainly in Chinese and Japanese ETFs, weak in South Korea, absent in Hong Kong and Singapore, and weaker during COVID-19. India not sampled. — [RMIT repository](https://research-repository.rmit.edu.au/articles/journal_contribution/Market_intraday_momentum_APAC_evidence/27573486)
- S&P 500 vs CSI 300: during the pandemic shock the last half-hour effect was not significant. — [ZCU repository](https://dspace5old.zcu.cz/handle/11025/46501?locale=en)
- India: Motwani, Burrin & Sharma ("Hedging Demand and Intraday Momentum within the Indian Stock Market") split the NSE session into half-hours. Their models fit better when the overnight-plus-first-half-hour return and the rest-of-day return have **opposite** signs, i.e. reversal/correction. Only a search snippet was available (page 403), so sample and magnitudes are unverified. — [ResearchGate](https://www.researchgate.net/publication/383567351_Hedging_Demand_and_Intraday_Momentum_within_the_Indian_Stock_Market)
- IIMA: higher NSE volatility around derivatives expiry days, weekends and holidays. — [IIMA WP](https://iima.ac.in/sites/default/files/rnpfiles/19191060542012-11-03.pdf)

### Inferences
- **Test, don't import:**
  - Build a synthetic free-float-weighted NIFTY 50 from constituent minute closes. Weights from our market-cap data; validate daily returns against official NIFTY closes.
  - Run the GHLZ regression (r_last30 on r_first30, r_12th-half-hour) for 2015-2026, split by first half-hour volatility tercile and expiry vs non-expiry days.
  - The US result predicts momentum, but the one Indian snippet hints at reversal. Either result is useful.
  - Effort: low. Risk: synthetic index error from missing delisted constituents and stale small prints. Use large caps only.
- **How it helps our books (no new factor):**
  - Execution timing: a strong first-half-hour signal tells you whether to front- or back-load the day's VWAP for buys vs sells.
  - Strangle book: predicts end-of-day direction and gamma risk on the day.
  - Our monthly books gain little from a ~1-2% R² half-hour predictor.
- **Realized correlation / dispersion / breadth (cheap state variables):**
  - Daily average pairwise realized correlation among large caps from 5-30-minute returns (sampling chosen by the Epps signature in section 1).
  - Cross-sectional dispersion of intraday returns.
  - Intraday breadth: the share of stocks above their 09:30 price at 15:00.
  - Uses: risk-model regime flags (high correlation → diversification collapse → cut gross / tighten vol target) and a NIFTY-option input. High realized correlation with lower single-stock implied vol is the classic dispersion relation, but we only have index options, so only the index side applies.
  - Treat as monitored state, not a trading signal, until tested. The memory notes record that prior "monitors" were noise in plan 0025.
- **Survivorship caution:** breadth computed on survivors only is biased upward in past periods (stocks that later died are missing). That matters for regime-level comparisons across years.

### Gaps
- No peer-reviewed India / NIFTY replication of Gao et al. with full statistics was found. The one India paper was unreadable (403).
- No published evidence found that intraday realized correlation or intraday breadth improves timing of Indian long-only books or option selling.

---

## 5. Options: intraday RV for the variance risk premium, expiry effects, stop-loss tests for short strangles

### Takeaway
VRP research uses implied variance minus **high-frequency realized variance**, not close-to-close variance, and Indian studies find a positive, priced VRP for NIFTY. Intraday RV of a synthetic NIFTY gives the strangle book a less noisy realized leg. It also lets us decompose RV into continuous and jump parts (only the continuous part predicted Indian variance-swap returns in one study) and split day vs night risk: short NIFTY option premia mainly compensate overnight risk. Minute bars make intraday stop-loss rules testable on an index proxy. I found no rigorous published test of such stops on NIFTY strangles, only practitioner material.

### Cited Findings
- Bollerslev, Tauchen & Zhou: the VRP (model-free implied variance minus realized variance from high-frequency intraday data) explains over 15% of quarterly excess-return variation over 1990-2005, and over 25% combined with P/E. Predictability is strongest at the quarterly horizon. — [Fed FEDS 2007-11](https://www.federalreserve.gov/pubs/feds/2007/200711/index.html); published RFS 2009 22(11) per [Duke scholars](https://scholars.duke.edu/publication/732839)
  - Per the search summary, Pyun (2016) reports weak out-of-sample VRP performance despite in-sample predictability up to six months. — source not cleanly identified; [AEA 2017 paper page from the same search](https://swlb1.aeaweb.org/conference/2017/preliminary/paper/GDde2yiy); treat as unverified.
- India: Sankar, Ramachandran & Lukose (2020, Int. Rev. Econ. & Finance) find variance risk is priced in India, a market with high retail participation. Splitting realized variance into continuous and jump parts, **only the continuous component predicts short-term synthetic variance-swap returns**. — [Manipal research portal](https://researcher.manipal.edu/en/publications/dynamics-of-variance-risk-premium-evidence-from-india/)
- India: the premium earned by short NIFTY option sellers is mainly compensation for **overnight** risk, with intraday option returns going the other way. — [vLex abstract, "The asymmetry in day and night option returns: Evidence from an emerging market"](https://law-journals-books.vlex.com/vid/the-asymmetry-in-day-1115554990)
- India: Chakrabarti & Kumar (2017, Multinational Finance Journal) link vega-weighted NIFTY option order imbalance to VRP changes. The direction of VRP change carries information about subsequent realized-volatility surprises. — [MFJ](https://sites.uwasa.fi/mfjuva/?p=2597)
- Expiry days: higher NSE intraday volatility around derivatives expiry days. — [IIMA WP](https://iima.ac.in/sites/default/files/rnpfiles/19191060542012-11-03.pdf)
- Short straddles and strangles with intraday stops: only practitioner sources found.
  - Retail rules: sell ATM at 09:20 with a 40-50% per-leg stop, closing only the stopped leg. — [Kotak Securities](https://www.kotaksecurities.com/investing-guide/articles/nifty-short-strangle-strategy); [TradingQnA](https://tradingqna.com/t/atm-short-straddle-intraday-strategy-nifty-bank-nifty/88032)
  - One-month 1-minute backtests. — [TradingQnA](https://tradingqna.com/t/reports-of-the-death-of-920-short-straddle-are-greatly-exaggerated/179061)
  - Warnings that crowded stop levels get "stop-hunted", and that costs and slippage dominate live results. — [Marketcalls](https://www.marketcalls.in/futures-and-options/how-the-9-20-intraday-straddlers-are-being-gamed.html)

### Inferences
- **Better realized leg for the strangle book (low effort):** replace daily close-to-close RV with
  - intraday RV from 5-minute synthetic-NIFTY returns (subsampled), plus
  - a separately measured overnight squared return.

  Report VRP = IV² − (intraday RV + overnight). Use bipower variation for the continuous part and RV − BV for jumps, in line with the Indian finding that only the continuous part predicts. The overnight-risk finding means the overnight term must not be dropped. The book's P&L comes mostly from carrying overnight risk.
- **Stop-loss testing on an index proxy (medium effort, important caveat):**
  - With synthetic-NIFTY minute prices and daily implied vol (we have daily IV from bhavcopy settle inversion, per the memory note), approximate option prices intraday with Black-Scholes. Hold IV at the day's level, or interpolate between consecutive daily IVs.
  - Then test path-dependent rules: per-leg % stops, index-move stops (e.g. exit if the index moves k × the day's expected σ), time stops.
  - Caveats:
    - Intraday IV moves (vol spikes as the index falls) are missing, so the proxy **understates** stop triggers on down-moves. Treat results as an optimistic bound, or apply a spot-vol beta.
    - Bid-ask on far-OTM strikes at the moment of a stop is unknown without option quotes. Stop fills are the worst-case part.
    - Minute closes (no high/low) miss intra-minute spikes, so stop-trigger counts are underestimated.
  - The existing finding that the 2-days-before-expiry 0.05Δ strangle holds up (memory note, 2026-10-09) can be stress-tested this way: does adding a stop improve worst-case loss without killing the premium?
- **Expiry-day and event filters:** minute bars give expiry-day intraday RV profiles and a measure of "pin" behaviour (index realized range in the last hour on expiry). They are inputs to the existing "event/VIX vetoes fail" finding: one can check whether intraday-RV-based vetoes differ from daily ones.
- **Flag:** anything needing option quotes (true intraday IV, the skew path, fill prices) is out of scope for our data.

### Gaps
- No peer-reviewed study found that tests intraday stop-loss rules for NIFTY short strangles.
- I did not retrieve the Indian VRP papers' sampling frequency or magnitudes (VRP level, R²); only abstract-level claims are sourced.
- The 5-minute sampling for BTZ's realized variance was not confirmed from the source text.

---

## 6. Data quality: validating daily OHLC, bad prints, corporate-action errors

### Takeaway
Minute bars give an independent second source for every daily field we already use: the official close (the closing-window VWAP is recomputable), daily volume (the sum of minute volume), and open/high/low bounds. They also give exact timestamps for gaps and jumps, which separates corporate-action splits (a jump between days with no volume reaction, at the ex-date) from genuine news jumps or bad prints. I found no academic paper on exactly this use; the realized-measure literature only supplies standard tick-cleaning practice.

### Cited Findings
- High-frequency research applies explicit cleaning before computing realized measures, "in the spirit of Barndorff-Nielsen, Hansen, Lunde, and Shephard (2009)". — [Jahan-Parvar & Zikes, FEDS 2019-051](https://www.federalreserve.gov/econres/feds/files/2019051pap.pdf)
- International intraday studies must handle stale closing observations: one uses the timestamp of the first observation as the open and the last *actively changed* observation as the close, because prices sit unchanged near close in early data. — [Li, Sakkas & Urquhart WP](http://wp.lancs.ac.uk/fofi2020/files/2020/04/FoFI-2020-092-Zeming-Li.pdf)
- NSE official close = VWAP of the last 30 minutes (LTP if no trades), with a reported window shift to 15:10-15:40 from 3 Aug 2026 for F&O. — [EquitiesIndia](https://equitiesindia.com/glossary/closing-price-weighted-average); [Arihant Plus](https://www.arihantplus.com/blogs/market-updates/nse-extends-f-and-o-market-close-to-3-40-pm-what-traders-must-know)

### Inferences
Proposed health checks, each able to fail today, in line with ADR 0060:
1. **Close reconciliation:** VWAP(minute close × volume, 15:00-15:29) vs official daily close. Flag > X bps (tier-specific X).
   - Caveats: minute close × minute volume only approximates the true VWAP, since we lack per-trade prices. The 15:29 bar may not cover 15:30, and the post-Aug-2026 window changes.
   - Expected noise floor: small for liquid names, larger for thin names. Calibrate X from the distribution.
2. **Volume reconciliation:** Σ minute volume vs daily bhavcopy volume. A ratio far from 1 indicates missing minutes, the pre-open or block-deal window not in the bars, or unit errors.
3. **Range bounds:** max/min of minute closes must lie within the daily high/low. Violations are bad prints in one of the two sources.
4. **Bad-print detector:** a minute return > k × the stock's robust minute σ (MAD-based) that reverses within 1-3 minutes on tiny volume is a likely bad print. Exclude it from RV, Roll and stops.
5. **Corporate-action detector:**
   - Pattern: an overnight gap with ratio ≈ a split/bonus ratio (2:1, 1:1, 5:1 ...), with no matching jump in turnover in rupees (shares traded jump inversely).
   - Check: compare to our corporate-actions table and to bhavcopy PREVCLOSE/CLOSE(t-1). The memory note says this ratio is the adjustment factor.
   - Value: catches missing or wrong adjustments, which otherwise create phantom momentum/reversal values and fake RV spikes.
6. **Staleness / halt detector:** runs of zero-volume minutes or identical closes. They feed the liquidity-bucket assignment for the Epps-safe sampling frequency (section 1) and flag suspensions. A "price exists but nothing traded" day can be caught directly.

Effort: low for 1-3 and 6, medium for 4-5. Risk: false positives in thin names. Gate by liquidity bucket. Every check needs a fire drill, per project rules.

### Gaps
- No academic or NSE source found on using minute bars to audit daily OHLC or corporate actions; the checks above are design proposals.
- Whether our minute feed includes pre-open (09:00-09:15) or closing-session trades, and how the official close is treated after the Aug-2026 change, could not be verified from external sources.

---

## 7. Ranked practical list (synthesis for the report writer)

### Takeaway
Ranked by value to our books per unit effort, using only close + volume minute bars:
1. Per-stock cost/impact model and capacity (replaces the flat 16/18/31 bps and 150 bps placeholder)
2. HAR(Q)-RV vol forecasts for sizing and the strangle book
3. Minute-bar data-quality checks
4. Volume-profile / participation-capped execution simulation for SMALL and multibagger
5. Intraday RV/jump/overnight decomposition and stop-loss proxy tests for the strangle book
6. Intraday-momentum replication on a synthetic NIFTY
7. Realized-correlation regime monitors
8. Intraday covariance/beta for the monthly books: lowest value, because Liu (2009) finds daily data match at monthly rebalancing.

### Cited Findings
- Cost estimators from bars are most accurate for illiquid, wide-spread stocks (Abdi-Ranaldo correlation 0.74-0.86 vs TAQ) and most biased for liquid, low-spread stocks (bias 150% to 2,260% of the true spread). — [Abdi-Ranaldo PDF](https://www.alexandria.unisg.ch/server/api/core/bitstreams/dfb85399-5bcf-465c-8b63-9bfc97ad2ee0/content); [Jahan-Parvar & Zikes](https://www.federalreserve.gov/econres/feds/files/2019051pap.pdf)
- Trade size relative to daily volume is the main driver of impact, which is concave in size. — [etf.com summary of FIM](https://www.etf.com/sections/index-investor-corner/swedroe-trading-cost-truths); exponent 0.6 per [Almgren et al. 2005](https://www.risk.net/derivatives/structured-products/1500270/equity-market-impact), ~0.7 in China per [J. of Risk](https://www.risk.net/journal-of-risk/5861701/equity-market-impact-modeling-an-empirical-analysis-for-the-chinese-market)
- Intraday covariance adds 50-200 bps/yr for volatility timing ([FKO 2003 via aggregator](https://academicnewsletter.sufe.edu.cn/info/357738)), but nothing at monthly rebalancing with ≥12 months of data ([Liu 2009](https://journaldata.zbw.eu/dataset/30606726-21dc-4c9f-88c4-f5362704e596)).
- Market intraday momentum: US Sharpe 1.08 timing strategy, 12 of 16 developed markets. — [Gao et al.](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/ee7dac49-530b-4950-b5d0-e0b5eee08f2e.pdf); [Li et al.](http://wp.lancs.ac.uk/fofi2020/files/2020/04/FoFI-2020-092-Zeming-Li.pdf). Indian evidence hints at reversal. — [ResearchGate snippet](https://www.researchgate.net/publication/383567351_Hedging_Demand_and_Intraday_Momentum_within_the_Indian_Stock_Market)

### Inferences
- **Needs quotes / order book (flag, can't do with our data):**
  - true quoted or effective spreads in LARGE (bars overstate them)
  - order-imbalance / trade-sign based impact (Lee-Ready, Kyle lambda from signed flow)
  - intraday option IV and option fill prices for stop-loss tests
  - absolute calibration of the impact constant Y (needs our own parent-order fills)
- **The single biggest decision this unlocks:** whether the SMALL / multibagger books are profitable after realistic costs. Per-stock spread (intraday Roll / noise) plus σ and ADV-based square-root impact turns the 150 bps placeholder into a per-trade estimate with a band. Combined with a participation-capped VWAP simulation, it also gives capacity in rupees.
- **Biggest implementation risks:**
  - stale minutes in thin names (Epps, fake low vol, fake negative autocorrelation)
  - closing-window rule change (Aug 2026, unverified)
  - survivorship in synthetic indices and breadth
  - false precision in impact constants

### Gaps
- No Indian validation exists for any of the US accuracy numbers above. The first internal study should calibrate the bar-based spread and impact estimates against an external Indian anchor: NSE impact cost, a broker TCA, or our own fills.
