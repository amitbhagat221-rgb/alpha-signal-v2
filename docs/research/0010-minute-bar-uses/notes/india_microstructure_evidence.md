# Indian equity microstructure and intraday behaviour: evidence for minute-bar signals (NSE/BSE)

Scope note: India only. Each finding gives the study period where known. Evidence from before 2015 is marked **[pre-2015, possibly stale]**: the market changed a lot after 2010 (co-location January 2010, opening call auction October 2010, retail surge 2020–24, T+1 in 2023, dynamic-band reform in 2024, closing auction in August 2026). "Our data" means 1-minute close and volume for about 2,420 surviving NSE stocks, 2015-02 to 2026-10, regular session 09:15–15:29.

**Most important new fact for our data:** since **3 August 2026**, F&O stocks close through a Closing Auction Session (CAS). For those stocks, continuous trading stops at 15:15 and the official close is no longer the 15:00–15:30 VWAP. See section 3.

---

## 1. Price bands and circuit filters: which stocks get which band, how bands change, and evidence on band hits

### Takeaway
There are two band regimes, and circuit detection must model both:
- **Non-F&O stocks** have fixed daily bands of 2/5/10/20 % (none at 40 % as of June 2026). The exchanges review and move these bands as a surveillance tool.
- **F&O stocks** have no fixed band. They get a dynamic ±10 % operating range that flexes in steps. The flexing rules were rewritten in June, August and October 2024.

The Indian evidence on band hits is thin and conflicting. One NSE study finds upper-band hits are followed by continuing abnormal returns and about 5 days of elevated volume. Another finds no volatility spillover. No India-specific magnet-effect study was found.

### Cited Findings
- **Band counts, 5 June 2026 revision:**
  - 2 % band: 42 securities. 5 %: 565. 10 %: 177. 20 %: 2,288. No band: 211. 40 %: 0.
  - Securities with derivatives keep a 10 % daily operating range even when classed as "no band".
  - NSE says it updates a *daily* price-band review on its website.
  - Source: secondary summary of NSE Circular 414/2026, not read in the original — [TeamLease RegTech](https://teamleaseregtech.com/updates/article/56591/nse-revises-price-bands-for-securities-from-june-05-2026/)
- **Default bands and exemptions:** NSE's price-band page lists 5 % and 10 % bands, with 20 % applying to all remaining scrips. Scrips with derivative products have no price band but get a 10 % operating range — [NSE equity price bands](https://www.nseindia.com/static/products-services/equity-market-price-bands) (search snippet; page not fetched)
- **Bands as a surveillance tool:**
  - BSE says the maximum band is 20 %, and exchanges can tighten bands to 10 % or 5 % as a surveillance action — [BSE surveillance actions](https://www.bseindia.com/static/markets/equity/EQReports/sur_Surveillance.html) (search snippet; page returned 403)
  - A 2012 joint NSE–BSE release shows stocks cut to 5 % for surveillance reasons, then restored to 20 % — [NSE press release 27-07-2012](https://nsearchives.nseindia.com/content/press/27072012.htm) (snippet)
  - A 2013 revision moved 216 stocks between bands — [Business Standard, Sept 2013](https://www.business-standard.com/article/markets/nse-revises-price-band-on-over-200-stocks-from-today-113090600134_1.html)
- **Bands inside the surveillance frameworks:** the NSE–NYU GSM paper describes surveillance bands of 2, 5 and 10 % "for securities satisfying a specific criteria". GSM stages carry a band of 5 % or lower — [Aggarwal, Bhatia & Zaveri](https://archives.nseindia.com/research/content/nse_nyu/NidhiAggarwal_Rules_vs_discretion_Impact_of_trading_rules_on_market.pdf); [NSE periodic-review page](https://www.nseindia.com/static/regulations/movement-securities-periodic-review) (snippet)
- **Exit from trade-for-trade:** a security moving out of the trade-for-trade segment goes to a **5 % band** until the next review for upward revision — [NSE periodic-review page](https://www.nseindia.com/static/regulations/movement-securities-periodic-review) (snippet)
- **IPO listing day (sources conflict):** one glossary says new listings have no band on day 1. BSE (citing a 2010 SEBI circular) describes special treatment for new listings, with the first day open. The current NSE rule was not verified — [BSE surveillance page](https://www.bseindia.com/static/markets/equity/EQReports/sur_Surveillance.html) (snippet)
- **F&O dynamic bands, old rule:** start at ±10 %. Flex by 5 % after a 15-minute cooling-off once **25 trades from 5 accounts** print at or above 9.90 % — [Zerodha explainer](https://zerodha.com/z-connect/business-updates/explainer-on-new-price-band-rules-for-stocks-trading-in-the-fo-segment)
- **F&O dynamic bands, 2024 reforms:**
  - From **3 June 2024**: flexing needs **50 trades, 10 accounts and 3 trading members** on each side at or above 9.90 % of base price.
  - From **19 August 2024**: a hit in either the cash stock or the near-month future triggers the flex.
  - From 19 August 2024, flexing is stepped:

    | Instance | Band move | Step | Cooling-off |
    |---|---|---|---|
    | 1st | 10 % → 15 % | 5 % | 15 min (5 min in the last 30 min of trading) |
    | 2nd | 15 % → 20 % | 5 % | 15 min (5 min in the last 30 min) |
    | 3rd | 20 % → 23 % | 3 % | 30 min |
    | 4th | 23 % → 26 % | 3 % | 30 min |
    | 5th | 26 % → 28 % | 2 % | 60 min |
    | Next | 28 % → 30 % | 2 % | 60 min |

  - From **21 October 2024**: "sliding" bands. When one side flexes, the opposite side moves by the same amount, and resting orders outside the new band are cancelled.
  - Sources: [Zerodha explainer](https://zerodha.com/z-connect/business-updates/explainer-on-new-price-band-rules-for-stocks-trading-in-the-fo-segment); [NSE circular FAOP/63405, 14 Aug 2024](https://nsearchives.nseindia.com/content/circulars/FAOP63405.pdf)
- **Market-wide index circuit breakers:** trading halts at 10 %, 15 % and 20 % moves in Nifty or Sensex, introduced by SEBI in 2001 — [Aggarwal, Bhatia & Zaveri](https://archives.nseindia.com/research/content/nse_nyu/NidhiAggarwal_Rules_vs_discretion_Impact_of_trading_rules_on_market.pdf)
- **Band-hit evidence, Chari & Inamdar (2017, Research Bulletin 43(1), NSE data; period not visible):** price limits delay price discovery. CAARs of stocks hitting the upper band "continue to increase after the event day", and volume stays "at much higher level for 5 days after the event day". Abstract only, no magnitudes — [ICMAI Research Bulletin](https://icmai-rnj.in/index.php/rb/article/view/117598)
- **Contradicting evidence, Chaturvedula & Rastogi (2018, Accounting and Finance Research 7(4)):** using the Kim–Rhee method on Indian bands, they find no volatility spillover and no hindrance to price discovery — [IDEAS/RePEc](https://ideas.repec.org/a/jfr/afr111/v7y2018i4p195.html)
- **No India magnet study found.** The nearest emerging-market analogue is Bursa Malaysia (±30 % limit, 2015–17 high-frequency data): a moderate magnet effect, stronger at lower limits — [IIUM repository](https://irep.iium.edu.my/69724/) (non-India, context only)
- **Correction to a common claim:** one broker explainer says trading "stops for the rest of the day" once a band is hit. The NSE/BSE material instead describes bands as price caps. Trading can continue at the band price (one-sided book), so do not treat a band hit as a halt — [IIFL explainer](https://indiainfoline.com/knowledge-center/online-share-trading/what-are-circuit-filters-limits-and-how-are-they-used) (contradicted by the band descriptions above)

### Inferences
- For circuit detection, the band a stock sits in on day *d* is **time-varying data**, not a constant. Non-F&O bands change through surveillance reviews (daily or weekly lists). F&O stocks have no fixed band, so a "limit hit" for them means 10 % then 15 % (and so on) of previous close, with a cooling-off pause.
- In minute bars, a flex shows up as a **flat price at ±10 % (±15 %, …) lasting about 15 minutes, then a jump**. Before June 2024 this needed only 25 trades from 5 accounts, so flexes were easier and more frequent in 2015–2024 than after.
- A test must therefore be split at 2024-06-03 and 2024-08-19.
- For non-F&O stocks, a hit is a run of minutes with close equal to prior close × (1 ± band) and thin volume.
- Without the historical band file, the detector should test all of 2/5/10/20 % and pick the band consistent with the day's extreme. That is ambiguous when, for example, a 5 % band stock moves exactly 5 %.
- Upper-band hits in non-F&O names are the setting where the only Indian evidence (Chari & Inamdar) suggests continuation over the next days. That is plausible for a short-horizon signal, but it rests on a paywalled abstract.

### Gaps
- No primary SEBI or NSE text was found giving the *criteria* for assigning 2/5/10/20 % bands. The bands appear to be surveillance-discretionary.
- Whether NSE publishes a downloadable *history* of daily price-band files (needed for a point-in-time band per stock-day) was not established.
- There is no India magnet-effect or post-hit return study using post-2015 data.
- The current NSE IPO-day rule is unverified.

---

## 2. Surveillance frameworks (ASM, GSM, trade-for-trade, periodic call auction): footprints and return effects

### Takeaway
Entering a surveillance framework predicts **negative abnormal returns and lower liquidity**, and the effect persists after exit. The GSM entry estimate is about −6 to −7 % CAR over a (−4, +5) day window, from 2017–19 data. ASM's short-term trigger (STASM) is itself defined from close-to-close price moves relative to NIFTY 50 and from client concentration. The price part can be rebuilt from daily data; the client-concentration part cannot. Illiquid stocks in periodic call auction trade only in hourly batches, which leaves an unmistakable minute-bar footprint.

### Cited Findings
- **GSM framework design:**
  - Introduced **23 February 2017**, with 7 stages. Stage 0 has no trading consequence beyond investor alerts. Consequences become severe from Stage 3 up.
  - The list is reviewed quarterly and published at least one week before it takes effect.
  - Stage 0 criteria: net worth ≤ ₹10 cr, net fixed assets ≤ ₹25 cr, and P/E > 2× Nifty 500 P/E (or negative).
  - Stage 1 criteria: full market cap < ₹25 cr, plus the P/E or P/B tests.
  - Source: [Aggarwal, Bhatia & Zaveri, NSE–NYU](https://archives.nseindia.com/research/content/nse_nyu/NidhiAggarwal_Rules_vs_discretion_Impact_of_trading_rules_on_market.pdf)
- **GSM evidence (same paper, March 2017 – March 2019; 110 securities, 72 treated matched to 65 controls):**
  - Only **35 %** of firms put under GSM met the joint inclusion criteria (65 % did not). About 88 % met the net-worth and P/E criteria individually.
  - Treatment coefficient on CAR(−4, 5): **−0.068 (s.e. 0.026)**. On CAR(−9, 10): about **−0.06**. Both significant at 5 %.
  - Liquidity: DiD estimates are negative. The fall in number of trades and turnover ratio is significant at 5 %; the fall in traded quantity is not.
  - Source: [Aggarwal, Bhatia & Zaveri](https://archives.nseindia.com/research/content/nse_nyu/NidhiAggarwal_Rules_vs_discretion_Impact_of_trading_rules_on_market.pdf)
- **GSM persistence:** press coverage of Zaveri's work reports a negative effect on returns and liquidity "long after the restrictions" are lifted — [Business Standard, Feb 2021](https://www.business-standard.com/article/markets/how-sebi-s-warning-system-curbs-gamestop-like-gains-in-indian-stock-markets-121021000097_1.html)
- **GSM trading restriction:** Stage III and IV stocks trade only once a week (every Monday, or the first trading day of the week) — [NSE periodic-review page](https://www.nseindia.com/static/regulations/movement-securities-periodic-review) (snippet)
- **Short-term ASM (STASM):**
  - Started **22 November 2018**.
  - Trigger: close-to-close price variation 25 % more than NIFTY 50 over 5 days, either direction, **and** concentration (25 clients > 30 % of volume).
  - Consequence: 40 % overall additional margin, 100 % for the top-10 dominating clients.
  - Source: [Chari & Inamdar, NSE–NYU white paper 2021](https://nsearchives.nseindia.com/s3fs-public/inline-files/Effectiveness%20of%20additional%20surveillance%20measures_WhitePaper.pdf)
- **STASM evidence (same paper; 218 events, 188 firms, 21 Nov 2018 – 28 Feb 2019):**
  - CARs fall after inclusion, and the fall persists after exclusion. Abnormal volume also falls and stays lower.
  - Among stocks with positive pre-inclusion CAR, delivery % is lower. It rises post-inclusion for continuation patterns and falls for reversal patterns.
  - No point estimates appear in the 4-page white paper.
  - Source: [Chari & Inamdar](https://nsearchives.nseindia.com/s3fs-public/inline-files/Effectiveness%20of%20additional%20surveillance%20measures_WhitePaper.pdf)
- **Trade-for-trade (BE/BT series):**
  - No netting is allowed, so every trade must be delivered — [Aggarwal, Bhatia & Zaveri](https://archives.nseindia.com/research/content/nse_nyu/NidhiAggarwal_Rules_vs_discretion_Impact_of_trading_rules_on_market.pdf)
  - Candidates are identified fortnightly, and movement to or from trade-for-trade is quarterly. Entry needs all criteria, including P/E tests.
  - Exit criteria include market cap > ₹500 cr, institutional holding > 20 %, and dividends or bonus in 2 of the last 3 years (page dated March 2025).
  - Source: [NSE periodic-review page](https://www.nseindia.com/static/regulations/movement-securities-periodic-review) (snippet; page timed out)
- **Periodic call auction for illiquid securities:**
  - From the March 2013 NSE circular: one-hour sessions from 09:30 to 15:30, with order entry closing at a random point between the 44th and 45th minute — [NSE circular CMTR23063](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/CMTR23063.pdf) (snippet)
  - The illiquidity criterion was rationalised by SEBI circular CIR/MRD/DP/38/2013 (19 December 2013) to average daily turnover < ₹2 lakh over the previous two quarters, at all exchanges.
  - NSE's January 2025 circular shortlisted **no** securities from 13 January 2025.
  - Source: [NSE periodic call auction page](https://www.nseindia.com/static/products-services/equity-market-periodic-call-auction) (snippet)
- **Manipulated-stock profile used by surveillance:** large price spikes, high volatility, volume spikes, short-term continuation, long-term reversal, low liquidity, and concentration in a few clients — [Chari & Inamdar](https://nsearchives.nseindia.com/s3fs-public/inline-files/Effectiveness%20of%20additional%20surveillance%20measures_WhitePaper.pdf)

### Inferences
- A minute-bar "**ASM-trigger proximity**" feature is possible from daily closes: the 5-day stock-minus-NIFTY return approaching ±25 %. It flags stocks likely to be put under surveillance. The literature implies negative forward abnormal returns once a stock enters, so the most useful job is as an **exclusion or kill gate** for the multibagger and SMALL books, not a long signal.
- A **sudden switch to weekly-only or hourly-batched volume** in minute bars marks GSM Stage III/IV or periodic call auction:
  - volume only on Mondays, or
  - volume only in the minute after each hourly auction (about 10:15, 11:15, … if order entry closes at 44–45 minutes after 09:30).
  This is directly detectable from minute volume and is a strong illiquidity and surveillance flag.
- Because 65 % of GSM inclusions did not meet the stated criteria, inclusion cannot be fully predicted from fundamentals. A price/volume detector may catch some of what the discretion responds to.
- Survivorship: GSM/ASM names delist or suspend more than most. Our survivors-only minute data will understate the negative post-entry returns.

### Gaps
- There is no post-2019 GSM study and no long-term-ASM (LTASM) study. No study used intraday data on surveillance entry.
- The current STASM/LTASM thresholds (they have been revised several times since 2018) were not retrieved.
- Historical lists of ASM, GSM and trade-for-trade entries are needed point-in-time. Whether NSE archives them was not checked.

---

## 3. Closing-price rule, the 2026 closing auction, expiry settlement and "marking the close"

### Takeaway
Until July 2026 every NSE stock's official close was the VWAP of the last 30 minutes, which drew about 10 % of daily turnover. That window is also the derivatives settlement window. Expiry-day volatility in 15:00–15:30 was 34–58 % higher than normal in 2001–09 data.

From **3 August 2026**, F&O stocks move to a Closing Auction Session:
- continuous trading ends at **15:15**;
- the reference price is the VWAP of 15:00–15:15;
- the official close is the auction equilibrium price.

Non-F&O stocks keep the 30-minute VWAP. SEBI has already brought one CAS manipulation case, from August 2026.

### Cited Findings
- **Old rule:** the official close was the VWAP of all trades in the last 30 minutes (in effect until July 2026). Under VWAP, the final window was about **10 % of daily NSE turnover**. Early Bernstein data put the CAS final window at **1.6–2.3 %** — [Finshots, 21 Aug 2026](https://finshots.in/markets/how-traders-allegedly-gamed-cas/)
- **Settlement uses the same window:** in 2001–09, stock and index derivative settlement prices were the weighted average of all trades in the last 30 minutes on expiry day — [Agarwalla & Pandey, IIMA WP 2012-11-03](https://iima.ac.in/sites/default/files/rnpfiles/19191060542012-11-03.pdf) **[pre-2015]**
- **CAS mechanics (F&O stocks, from 3 Aug 2026):**
  - Regular trading 09:15–15:15.
  - Reference price = VWAP 15:00–15:15. Auction band ±3 % of the reference price.
  - 15:15–15:20 transition. 15:20–15:25 market and limit orders can be entered, modified or cancelled.
  - From 15:25, only limit orders can be placed or modified, and market orders are locked.
  - Order entry closes at a random time between 15:28 and 15:30. Matching finishes by 15:35.
  - Equity derivatives trade until 15:40.
  - If no equilibrium price is found, the reference price becomes the close.
  - Source: [Wright Research](https://www.wrightresearch.in/blog/how-does-sebis-closing-auction-session-change-market-close/)
  - Timings are confirmed by [Angel One](https://www.angelone.in/news/market-updates/sebi-closing-auction-session-from-august-3-2026-new-timings-and-rules-for-f-o-stocks), which also gives a post-close session at 15:50–16:00 at the official close.
  - Sources differ on whether the CAS window is "15:15–15:30" or "15:15–15:35" — [search summary of broker pages](https://www.share.market/buzz/circulars/closing-auction-session/)
- **Non-F&O stocks:** trading continues to 15:30, with the close still the 30-minute VWAP. No phase-2 date was found — [Angel One](https://www.angelone.in/news/market-updates/sebi-closing-auction-session-from-august-3-2026-new-timings-and-rules-for-f-o-stocks)
- **Pre-open alignment:** the pre-open auction is aligned with CAS rules from 7 September 2026 — [share.market circular summary](https://www.share.market/buzz/circulars/closing-auction-session/) (secondary)
- **Why SEBI moved:** at index rebalancing and expiry, the VWAP mechanism could cause large price volatility and leave large passive orders unfilled, raising tracking error. An earlier December 2024 draft proposed a 15:30–15:45 session — [Outlook Money](https://www.outlookmoney.com/invest/sebi-proposes-changes-to-closing-auction-session-fo-settlement-rules-key-proposals-explained); [TaxGuru on the 2026 consultation](https://taxguru.in/?p=1079025)
- **2026 consultation (comments due 3 Oct 2026):** proposes an expiry-day settlement price that blends the last 30 minutes of continuous trading with the CAS, weighted by turnover — [Outlook Money](https://www.outlookmoney.com/invest/sebi-proposes-changes-to-closing-auction-session-fo-settlement-rules-key-proposals-explained)
- **First CAS manipulation case (SEBI ex-parte interim order, about 19 Aug 2026, concerning BSE SENSEX expiry 13 Aug 2026):**
  - Copthall Mauritius placed 32 buy orders across all 30 SENSEX stocks, worth about ₹66 cr, in the first 2 seconds of CAS. That was 99.9 % of buy-order value in those seconds and lifted the indicative SENSEX by 362 points. It repeated this twice and cancelled each time.
  - Mansi Share & Stock Broking placed about ₹145 cr of sell orders 1.5–3 % below reference between 15:21 and 15:25, then cancelled within 3 seconds, moving the index about −233 points.
  - Alleged gain: ₹3.68 cr. These are allegations.
  - Source: [Finshots](https://finshots.in/markets/how-traders-allegedly-gamed-cas/)
- **Expiry-day closing volatility (2001–09, 500 stocks, 5-minute data; 153 stocks with 8,132 stock-expiry days):**
  - Volatility of F&O stocks is **34.2 % higher in 15:15–15:30** and **57.7 % higher in 15:00–15:15** on expiry days. Third and fourth market-cap quintiles: 42.9 % / 76.4 % and 37.7 % / 53.3 %.
  - No effect in other intervals.
  - Source: [Agarwalla & Pandey 2012](https://iima.ac.in/sites/default/files/rnpfiles/19191060542012-11-03.pdf) **[pre-2015]**
- **In-house probe:** RELIANCE on 2026-10-09 had official close 1,170.3, 30-minute minute-bar VWAP 1,170.6 and last trade 1,170.9 — [research 0009](/home/ubuntu/alpha-signal-v2/docs/research/0009-intraday-factor-menu.md). This date is after CAS start, so for RELIANCE (an F&O stock) the official close was an auction price, not the VWAP.

### Inferences
- **This changes our data contract.** The note "official close = VWAP of 15:00–15:30" holds for all stocks before 2026-08-03, and only for **non-F&O** stocks after.
- For F&O stocks after 2026-08-03:
  - the 15:15–15:29 minute bars contain no continuous trading;
  - the official close is an auction price;
  - the auction volume probably appears as one print, or is missing from the minute series. This should be probed.
- Any `close_pressure` or `vwap_dev` factor must be **regime-split at 2026-08-03 for F&O names**. For F&O names after that date, it should be redefined as (auction close − 15:00–15:15 reference VWAP).
- About 2.5 months of CAS data is too short to test. For backtests, treat those stock-days as out-of-regime.
- Before CAS, the last 30 minutes carried about 10 % of turnover, with documented expiry-day volatility jumps in exactly the settlement window. This supports **expiry-day closing pressure** (last trade − official VWAP close, on expiry days only) as a distinct, India-specific variant. It can be measured from minute close and volume.

### Gaps
- No peer-reviewed India study of "marking the close" under the VWAP regime was found, nor any SEBI order specific to closing-VWAP manipulation in single stocks.
- No source was found for the SEBI circular number for CAS, or a phase-2 date for non-F&O stocks.
- How Kite minute bars represent the CAS (one bar at 15:30–15:35? none?) is unknown and needs a direct probe of our archive.

---

## 4. Block-deal windows

### Takeaway
Block deals happen only in two fixed windows: 08:45–09:00 (before our first bar) and 14:05–14:20. The afternoon reference price is the VWAP of 13:45–14:00. That puts a mechanical **13:45–14:00 VWAP window** inside our minute data.

### Cited Findings
- **2017 framework:** SEBI circular CIR/MRD/DP/118/2017, effective 1 January 2018. Morning window 08:45–09:00, afternoon window 14:05–14:20, minimum order ₹10 cr — [Business Standard, Oct 2017](https://www.business-standard.com/amp/article/pti-stories/sebi-revises-block-deal-norms-min-order-size-hiked-to-rs10-cr-117102601023_1.html); [NSE circular CMTR36573](https://nsearchives.nseindia.com/content/circulars/CMTR36573.pdf)
- **October 2025 review:** SEBI circular SEBI/HO/MRD/POD-III/CIR/P/2025/134 (8 Oct 2025), effective about 60 days later (about 7 Dec 2025).
  - Same windows. Morning reference = previous close. Afternoon reference = VWAP of cash trades 13:45–14:00, published 14:00–14:05.
  - Price range ±3 % of reference (circular text "+3 %"; earlier ±1 % per secondary sources). Minimum order ₹25 cr.
  - Compulsory delivery, with same-day public disclosure after market hours.
  - Sources: [TaxGuru](https://taxguru.in/sebi/sebi-revises-block-deal-trading-framework.html); [MediaNama](https://www.medianama.com/2025/10/223-sebi-revamps-block-deal-norms-hikes-25-crore/)

### Inferences
- A morning block deal is invisible in our minute bars because it trades before 09:15. Its *price impact* still shows in the open-to-first-bars path. Join it with our block-deal table.
- An afternoon block's reference is the 13:45–14:00 VWAP. A party planning an afternoon block has a motive to push that 15-minute VWAP. A small "13:45–14:00 pressure" feature (VWAP of that window vs the trend on either side, on days with a reported block) is detectable from minute data. It is speculative: no study found.
- Afternoon block trades themselves print in a separate window. Whether Kite minute volume includes block-window volume should be checked against the block-deal table.

### Gaps
- No Indian study of price behaviour around block-deal windows or reference-price manipulation was found.

---

## 5. Derivatives expiry effects on underlying stocks; F&O ban (MWPL); the Jane Street case

### Takeaway
Expiry effects on Indian underlyings are documented mostly with daily data and are modest. The sharpest evidence is intraday: settlement-window volatility (section 3), possible pinning, and SEBI's 2025 Jane Street order. That order alleges a **morning-buy / afternoon-sell pattern in index constituents on expiry days**, a footprint visible in minute bars.

Expiry calendars changed several times:
- weekly index expiries, single-stock monthly;
- one weekly benchmark per exchange from 20 Nov 2024;
- NSE moved to Tuesday expiry in 2025.

The F&O ban (open interest > 95 % of MWPL) blocks new positions. No return study of ban entry was found. The MWPL formula changed in 2025.

### Cited Findings
- **Older stock-futures studies (daily data):**
  - 131 NSE stocks: an overall negative effect of stock-futures expiry on price and volume — [Mehta & Shah 2020, GJRIM](https://publishingindia.com/archive/gjrim/a-study-on-expiration-effects-of-stock-future-on-price-and-volume-of-underlying-stocks-with-reference-to-indian-capital-market)
  - 42 large caps: positive abnormal returns and volume on days before expiry — [Sadath & Kamaiah 2011](https://independent.academia.edu/AnverSadath) **[pre-2015]**
  - Stock options, testing abnormal volume, price, reversal and pinning — [Gupta, Metia & Trivedi 2004](https://ideas.repec.org/p/wpa/wuwpfi/0411035.html) **[pre-2015]**
- **Pinning:** IIM Bangalore work observed pinning toward strikes, with price drifting to the strike near the close for suspect stocks. The authors note intraday underlying data would strengthen the test — [IIMB repository](https://repository.iimb.ac.in/handle/2074/21032?mode=full) (search snippet; page certificate error)
- **Index expiry (2000–2015 data):** spot volatility effects span the whole expiry week, likely stronger for indices than single stocks — [NMIMS Management Review](https://management-review.nmims.edu/?p=279); modest Nifty expiry-day effects — [SAGE 2016](https://journals.sagepub.com/doi/10.1177/0972622516629029)
- **Jane Street interim order (SEBI, 3 July 2025):**
  - Covers 18 expiry days, Jan 2023 – May 2025 (15 Bank Nifty, 3 Nifty). Alleged gains ₹4,843.57 cr.
  - "Patch I" (about 09:15–11:46): aggressive buying of Bank Nifty constituent stocks and futures. On 17 Jan 2024, ₹4,370.03 cr of longs while holding short index options.
  - "Patch II" (afternoon): selling. On the same day, ₹5,372 cr sold.
  - On three days (e.g., 10 Jul 2024), aggressive selling from 14:30 onward to depress the close.
  - Jane Street deposited the amount on 14 Jul 2025 and disputes the findings.
  - Sources: [Moneylife](https://www.moneylife.in/article/jane-street-accused-of-massively-rigging-of-indias-derivatives-market-sebi-orders-ban-escrow-of-rs4843-crore-illegal-gains/77585.html); [Oxford Business Law Blog](https://blogs.law.ox.ac.uk/oblb/blog-post/2025/07/jane-street-and-expiry-day-trap-unpacking-sebis-crackdown-algorithmic); [Legal500](https://www.legal500.com/developments/thought-leadership/sebi-update-interim-order-against-jane-street-group-for-alleged-index-manipulation/); [ECGI blog](https://www.ecgi.global/publications/blog/expiry-day-and-the-governance-of-algorithmic-trading-the-jane-street-episode)
- **Expiry calendar changes:**
  - From **20 Nov 2024**, each exchange keeps weekly expiry on only one benchmark (NSE: Nifty 50; BSE: Sensex). Bank Nifty, FinNifty and others go monthly only.
  - In 2025 NSE weekly expiry moved from Thursday to **Tuesday**. Sources disagree on the date, 15 June vs 1 September 2025. BSE Sensex weekly moved to Thursday.
  - A March 2025 consultation proposed all of an exchange's equity derivatives expire on its chosen day (Tue or Thu).
  - Sources: [5paisa](https://www.5paisa.com/index.php/news/sebi-gives-green-light-for-nses-weekly-fo-expiry-shift-to-tuesday); [share.market](https://www.share.market/buzz/insights/weekly-expiry-days-in-indian-fo-markets/); [Taxmann](https://www.taxmann.com/post/blog/sebi-proposes-to-limit-the-expiries-of-all-equity-derivatives-contracts-of-exchange-to-either-tuesday-or-thursday/)
- **F&O ban rule:**
  - A stock enters the ban when combined open interest exceeds **95 % of MWPL**. Only position reduction is allowed. The ban lifts at ≤ **80 %**.
  - Old MWPL = lower of 30× average daily cash volume (previous month) or 20 % of non-promoter shares. Cash trading is unaffected.
  - Sources: [ICICI Direct](https://www.icicidirect.com/ilearn/stocks/articles/future-and-options-ban-impact-on-stock); [IIFL](https://indiainfoline.com/knowledge-center/derivatives/why-are-stocks-banned-in-f-and-o)
- **2025 MWPL reform:**
  - MWPL = lower of 15 % of free float or **65× average daily delivery value**, with a 10 % floor, recalculated quarterly.
  - Open interest is measured as delta-adjusted future-equivalent (FutEq) instead of notional.
  - Glide path July–December 2025. Intraday MWPL monitoring from 3 Nov 2025.
  - Sources: [Zerodha](https://zerodha.com/z-connect/kite/a-short-brief-on-the-new-sebi-measures-for-the-fo-space); [Business Standard, May 2025](https://www.business-standard.com/amp/markets/news/sebi-fo-revamp-new-oi-metric-position-limits-july-december-rollout-125052901798_1.html); [Kotak Neo](https://www.kotakneo.com/bulletins/sebi-new-f-o-rules-explained-delta-based-oi-new-mwpl-what-it-means-for-your-trading/)
- **No empirical F&O-ban return study** was found; the search returned practitioner explainers only — [ICICI Direct](https://www.icicidirect.com/ilearn/stocks/articles/future-and-options-ban-impact-on-stock)

### Inferences
- An "**expiry-day intraday reversal**" feature fits a minute-bar model:
  - for index-heavy names on expiry days, the sign of the 09:15–11:45 return versus the 11:45–15:30 return (or 14:30–close);
  - a cross-sectional rank of constituents' morning-up / afternoon-down patterns.
  The Jane Street order shows such flows were large enough (₹4,000–5,000 cr a day) to move constituents. The pattern may have weakened after July 2025 enforcement and after the Bank Nifty weekly expiry ended (Nov 2024). Split the sample at 2024-11-20 and 2025-07-03.
- The expiry dates used to tag expiry days must follow the calendar changes:
  - Thursday weekly or monthly until 2025;
  - Tuesday on NSE after the 2025 shift;
  - also the earlier Bank Nifty Wednesday and FinNifty Tuesday weeklies, which are not covered by the sources above.
- **Pinning test:** distance of the official close from the nearest high-open-interest strike on stock-expiry days, compared with non-expiry days. Needs F&O bhavcopy (which we have) plus the minute path into the close.
- **F&O ban:** we can rebuild ban days from F&O bhavcopy open interest (95 % of MWPL), with formula changes in 2020 and 2025. Ban days remove derivatives-led speculation, so delivery % and minute volume patterns should shift. That makes it a clean natural experiment, but with no prior evidence.

### Gaps
- No post-2015 intraday study of single-stock expiry effects.
- No study of the F&O ban effect on returns or volatility.
- Exact effective date of the NSE Tuesday shift conflicts between sources.
- The Jane Street final order's outcome was not found.

---

## 6. Index rebalancing (NIFTY, MSCI, FTSE) and closing flows

### Takeaway
Indian Nifty-inclusion studies find mostly **temporary price pressure**:
- inclusions gain, then reverse within about 60 days;
- exclusions fall over about 10 days;
- volume spikes on the effective day from index funds and ETFs.

MSCI rebalance flows concentrate at the close. Under CAS, auction turnover reached 22 % of cash turnover on the August 2026 MSCI day.

### Cited Findings
- **Chhatwani (Nifty 50, 2000–2016):** positive abnormal returns for additions, reversing within 60 days. Deletions show negative returns only in the first 10 days — [JCAR](https://publishingindia.com/archive/jcar/price-and-volume-effects-of-nifty-50-index-reorganization)
- **Joshipura & Janakiramanan (2015):** no significant positive returns at announcement. A positive effective-day effect that does not last. A volume bump on the effective day attributed to index funds and ETFs. Supports price pressure — [IDEAS](https://ideas.repec.org/a/ids/afasfa/v5y2015i1p21-36.html) **[pre-2015 sample]**
- **Contrary view, Parthasarathy (2010; 1999–2010 additions):** permanent positive abnormal returns and limited volume effects; argues an information explanation — [IDEAS](https://ideas.repec.org/a/mth/ajfa88/v2y2010i2p55-80.html) **[pre-2015]**
- **MSCI August 2026 review (secondary, practitioner-grade source):**
  - Effective 1 Sept 2026, with most passive trades at the 31 Aug close.
  - Estimated passive buying: about $598 m Laurus Labs, $352 m Lenskart. Net passive inflow to India about $1 bn.
  - NSE closing-auction turnover on 31 Aug was ₹39,718 cr, about 22 % of that day's cash turnover.
  - Source: [multibagg.ai](https://www.multibagg.ai/market-pulse/articles/msci-aug31-rebalance-nifty-impact-cmteu3l64000830s569rimiyj) (aggregator; treat as indicative)
- **SEBI's own rationale:** rebalancing and expiry were cited as the occasions where the VWAP close caused volatility and unfilled passive orders — [Outlook Money](https://www.outlookmoney.com/invest/sebi-proposes-changes-to-closing-auction-session-fo-settlement-rules-key-proposals-explained)

### Inferences
- On known rebalance effective days, the last-30-minute volume share and the closing-pressure measure (last trade vs official close) should be extreme for added or deleted names. That is a calibration check for the closing-pressure factor.
- The documented post-inclusion reversal over about 60 days is a slow-horizon effect that can be built from daily data plus index-change dates. Minute data adds only the size of the closing imbalance as a conditioning variable.

### Gaps
- No Indian study used intraday data around rebalancing.
- No MSCI- or FTSE-specific peer-reviewed India study was found.
- The pre-2026 last-30-minute volume share on rebalance days is unquantified.

---

## 7. Regime changes that shift intraday behaviour: T+1, tick size, retail and prop participation, algorithmic trading

### Takeaway
Four regime changes fall inside our 2015–2026 window and should be treated as structural breaks:
- **T+1:** phased from February 2022 (smallest caps first), complete by January 2023.
- **Tick size:** cut from 5 paise to 1 paisa for stocks below ₹250 from 10 June 2024, affecting about 1,300 stocks.
- **Retail surge:** unique investors on NSE went from 4 cr (March 2021) to 13.5 cr (August 2026).
- **Participant mix:** prop traders' share of cash turnover rose to 29.8 % in 2025 while individuals fell to 33.5 %.

### Cited Findings
- **T+1:** the move from T+2 started in February 2022 in batches by market cap, beginning with the smallest — [Business Standard, Jan 2023](https://www.business-standard.com/article/opinion/quick-settlement-123012900898_1.html). SEBI estimated a ₹700 cr a year gain to investors — [Outlook Business](https://www.outlookbusiness.com/amp/story/markets/what-is-t0-settlement-cycle-and-how-will-it-impact-the-stock-market-and-investors). No rigorous liquidity or volatility study found — [Thomas Murray](https://thomasmurray.com/insights/t1-settlement-cycles-lessons-india-and-asia-pacific)
- **Tick size:**
  - Cut to ₹0.01 for stocks below ₹250 in EQ, BE, BZ and similar series from 10 June 2024 (circular 24 May 2024), about 1,300 stocks — [Business Standard](https://www.business-standard.com/amp/markets/news/nse-lowers-tick-size-to-1-paisa-over-1-300-stocks-to-be-impacted-124052700463_1.html)
  - Reviewed monthly on the last close of the month — [Business Today](https://www.businesstoday.in/amp/markets/market-commentary/story/nse-lowers-tick-size-to-one-paisa-what-does-it-mean-to-you-and-markets-431024-2024-05-27)
- **Participant shares:**
  - Individuals were 35.9 % of equity cash turnover in FY24 (as reported; source page not opened) — [Business Standard, Jul 2024](https://www.business-standard.com/amp/finance/personal-finance/20-of-households-are-channeling-savings-into-capital-markets-eco-survey-124072200804_1.html)
  - In 2025, individuals fell to a decade-low 33.5 % and prop traders rose to a 21-year high of 29.8 %. NSE cash ADTV fell 15 % to ₹99,622 cr — [Business Standard, Jan 2026](https://www.business-standard.com/markets/news/amid-retail-pullback-proprietary-firms-gained-as-trading-softened-in-2025-126012600542_1.html)
- **Investor counts:**
  - NSE unique investors: 4 cr (March 2021), 5 cr (December 2022), 10 cr (8 August 2024), 12 cr (23 September 2025) — [5paisa](https://5paisa.com/blog/nse-crosses-5-crore-unique-investors-mark); [HDFC Sky](https://hdfcsky.com/news/nse-crosses-12-crore-unique-investor-mark-growth-accelerates-with-younger-participation)
  - 13.5 cr unique PANs at 31 August 2026 — [NSE Market Pulse, Sept 2026](https://nsearchives.nseindia.com//web/mediaattachment/2026-09/Market_Pulse_September_2026_Final.pdf) (snippet)
  - Unique individual demat holders: 282.2 lakh (March 2019) → 895.8 lakh (March 2024) — [SEBI study, Jul 2025](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2025/1753874458062.pdf) (snippet)
- **Intraday retail traders (SEBI study, FY23):**
  - Over 70 % of individual intraday cash traders lost money; 80 % of those with > 500 trades a year.
  - Individuals in intraday trading rose by over 300 % versus FY19, and 1 in 3 cash-segment individuals trades intraday.
  - Source: [Business Standard, Jul 2024](https://www.business-standard.com/amp/markets/news/7-in-10-intraday-traders-in-equity-cash-suffered-losses-in-fy23-sebi-study-124072400975_1.html)
- **Day-trader share (2002 and 2009):** day traders were 28.1 % of sample volume in 2002 and 42.2 % in 2009 — [Agarwalla & Pandey](https://iima.ac.in/sites/default/files/rnpfiles/19191060542012-11-03.pdf) **[pre-2015]**
- **Volume by trader type (NSE trade-level data, Nifty 500, 2011–2015):**
  - Retail about **50 %** of volume, institutions about 25 %, HFT 7%.
  - In the smallest size group, retail is **69 %**. Institutions plus HFT are about 46 % of large-cap volume.
  - Retail order imbalance is the only group imbalance with a *negative* coefficient for next-day returns; the other groups' are positive.
  - Source: [Nawn & Banerjee, NSE–NYU WP, July 2024](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Trading%20around%20Unscheduled%20announcements_FINALTONYU.pdf)
- **Algorithmic trading:**
  - Algo share rose after co-location (January 2010) to about 60–75 % of volume — [Aggarwal & Thomas, Business Standard](https://www.business-standard.com/amp/article/opinion/nidhi-aggarwal-susan-thomas-making-sense-of-algorithmic-trading-117030201267_1.html)
  - Co-movement in returns, volatility and liquidity *fell* after co-location (150 stocks, two-week windows around January 2010) — [Boehmer & Shankar, NSE–NYU white paper](https://archives.nseindia.com/research/content/nse_nyu/NSE_NYU_12-13WPCh-3.pdf) **[pre-2015]**

### Inferences
- Bid-ask bounce in minute closes of stocks below ₹250 was larger before 10 June 2024, when the tick was 5 paise: a 5-paise tick on a ₹20 stock is 25 bps. Roll- or Abdi–Ranaldo-style spread estimates and realized moments will show a **level break** at that date. Normalise or add a regime dummy.
- The 2020–24 retail surge and the 2025 prop rise change who is on the other side of intraday flow. Intraday-reversal and overnight-sentiment factors should be tested for stability by sub-period: 2015–19, 2020–24, 2025–26.
- The Nawn & Banerjee finding (retail imbalance predicts lower next-day returns) supports a signed-flow factor. Our minute data can only approximate signed flow (bulk-volume classification). Delivery % (which we have daily) is closer to an institutional-versus-intraday split.

### Gaps
- No academic India study of T+1's effect on intraday liquidity or volatility.
- No study of the June 2024 tick-size cut's effect on spreads or depth.
- FPI and DII shares of cash turnover by year were not retrieved.

---

## 8. Operator-driven and pump-and-dump small caps: intraday signatures from SEBI orders

### Takeaway
SEBI orders describe a consistent mechanical signature in illiquid small caps and SMEs:
- many tiny trades at or just above the last traded price (LTP), often self-trades or trades within a connected group;
- synchronised and circular trades that set "new high prices";
- a multi-month price run with rising volume, then distribution into retail demand (sometimes social-media driven);
- then collapse.

The LTP-ladder part is partly visible in minute close+volume. No peer-reviewed India event study of SEBI-sanctioned pump-and-dumps was found.

### Cited Findings
- **LTP manipulation cases:**
  - OCTSL: one individual made 4,062 trades and contributed about ₹85 to net LTP rise through persistent one-share trades — [Business Standard, 2017](https://www.business-standard.com/article/pti-stories/fraudulent-trade-sebi-imposes-rs-7-lakh-fine-on-individual-117072001437_1.html)
  - Gujarat NRE Coke: a large sell order priced above LTP, followed by a one-share self-trade at that price, set a new higher LTP. 5,041 such self-trades — [TaxTMI](https://www.taxtmi.com/tmi_blog_details?id=687509)
  - SAT upheld findings on repeated tiny buy orders placed above LTP while large sell orders sat on the book — [SAT order](https://watchoutinvestors.com/Press_Rel-T/sat/ST4264.pdf)
  - RM Mohite Textiles: five entities traded among themselves to lift LTP; ₹20 lakh fines in 2019 — [Business Standard, 2019](https://www.business-standard.com/amp/article/pti-stories/sebi-imposes-rs-20-lakh-fine-on-5-entities-for-manipulating-r-m-mohite-textiles-scrip-price-119090300912_1.html)
- **Sadhna Broadcast (SEBI interim order, 2 Mar 2023; 31 noticees):**
  - The price went from about ₹2.50 to ₹13.05 between April and mid-July 2022 (over 400 %), with synchronised and structured trades among connected entities.
  - Misleading YouTube videos in July 2022 coincided with small shareholders rising from 2,167 to 55,343.
  - Impounded about ₹41.85–41.90 cr (sources differ). SAT later set aside the order in part.
  - Sources: [The News Minute](https://thenewsminute.com/news/why-sebi-banned-actor-arshad-warsi-maria-goretti-securities-market-174035); [SCC Online](https://www.scconline.com/blog/post/2023/04/03/sat-reverses-sebis-order-in-arshad-warsis-pump-and-dump-case/)
- **Best Agrolife:** ₹2.50 (3 Apr 2018) → ₹1,399.70 (4 Nov 2021), with circular and synchronised trades and artificial volume; 15 entities penalised ₹1.03 cr — [Moneylife](https://moneylife.in/article/stock-manipulation-sebi-slaps-rs103-crore-penalty-on-15-in-best-agrolife-case/73870.html)
- **Retro Green Revolution:** an illiquid stock went from about ₹10 to ₹33.85 and then fell. A group sold about 39.5 % of shares and was more than 20 % of traded volume — [Moneylife](https://www.moneylife.in/article/retro-green-revolution-stock-manipulation-sebi-slaps-280-crore-penalty-on-18-entities-orders-294-crore-refund/79974.html)
- **Typical surveillance profile:** price spike, high volatility, volume spike, short-term continuation, long-term reversal, low liquidity, client concentration — [Chari & Inamdar](https://nsearchives.nseindia.com/s3fs-public/inline-files/Effectiveness%20of%20additional%20surveillance%20measures_WhitePaper.pdf)
- **Unverified 2026 case:** a reported SEBI case on 82 SME stocks (Telegram, WhatsApp and X promotion; 7 barred; ₹20.25 cr impounded) appeared only on low-quality mirror sites. **Not verified; do not rely on it** — [mirror](https://servicios.uta.edu.ec/first-dry/SEBI-Exposes-Social-MediaLinked-PumpandDump-Scheme-Involving-82-SME-Stocks-21-3186)

### Inferences
Features that may be detectable from minute close and volume:
1. **Ratchet share:** share of minutes in which close is a new intraday high on very small volume (a "one-share LTP ladder"). It needs only close and volume, but a 1-minute bar hides how many trades sit inside it.
2. **Smoothness of rise:** low realized variance relative to drift over weeks, with up-minutes dominating. Operator-driven names rise in a staircase.
3. **Persistent upper-band locks:** many days closing at the upper band on a 5 % or 2 % band (sections 1–2).
4. **Distribution phase:** volume spikes several times normal while price stalls, with delivery % falling.

These suit an **exclusion gate**, the mania screen the in-house daily version failed, better than a return factor. Survivors-only data hides the collapses of names that were later suspended.

### Gaps
- There is no systematic Indian dataset or study of SEBI-sanctioned manipulation cases with intraday price and volume paths.
- The SEBI orders (sebi.gov.in) are the primary source for trading-pattern detail and were not read in full here.
- Minute bars do not give trade count, so "one-share trades" cannot be identified directly.

---

## 9. Documented Indian intraday patterns and anomalies (U-shape, open, intraday momentum or reversal, overnight vs intraday, day-of-week, lunchtime, herding)

### Takeaway
The robust Indian intraday facts are about **shape**, not return predictability:
- volatility follows a "reverse-J";
- volume and trade counts are U-shaped;
- peak-to-trough volatility is about 4×, against about 2× in the US and Japan;
- the open takes about 30 minutes to settle, even after the 2010 pre-open call auction.

Return-predictive Indian evidence is thinner:
- intraday overreaction positively predicts next-day returns (Siddiqui & Misra 2025);
- returns reverse within minutes after extreme moves;
- overnight returns act as firm-level sentiment that persists without reversing;
- day-of-week effects are unstable.

No India-specific study of the market-level "first half hour predicts last half hour" effect was found.

### Cited Findings
- **Shape of the day (Agarwalla & Pandey; 500 most-liquid NSE stocks, 2001–2009, 5-minute data):**
  - Reverse-J volatility. U-shaped trade size, volume and number of trades.
  - Peak volatility is about **4×** the intraday low, against about 2× for Nikkei and S&P 500. Average 5-minute absolute returns range from **0.3 % to 1.2 %**, against 0.05–0.11 % for Nikkei and 0.05–0.10 % for S&P.
  - Intraday variation is higher for large caps than small caps.
  - Volatility is higher in the first hour after weekends, the first half hour after holidays and the last hour before weekends. Cross-listed stocks are more volatile in the first 45 minutes.
  - Source: [IIMA WP 2012-11-03](https://iima.ac.in/sites/default/files/rnpfiles/19191060542012-11-03.pdf) **[pre-2015; session was 09:55–15:30]**
- **Opening call auction:**
  - Reintroduced 18 Oct 2010 for Nifty-50 stocks. It did not change the intraday volume or volatility pattern: these still take about 30 minutes to stabilise, and the auction draws very little volume.
  - Negative intraday return correlations suggest excessive price movement at the call auction.
  - Session timings moved from 09:55 to 09:15 in January 2010.
  - Source: [Agarwalla, Jacob & Pandey, IIMA WP 2012-10-03](https://iima.ac.in/sites/default/files/rnpfiles/1017244242012-10-03.pdf) **[pre-2015]**
- **Liquidity shape (20 Nifty stocks, one year of NSE intraday data):** volume and spread measures are U-shaped, with weak commonality in liquidity — [Krishnan & Mishra, via NEP listing](https://nep.repec.org/nep-mst/2012-09-30) **[pre-2015]**
- **Intraday overreaction → next-day returns (Siddiqui & Misra, Journal of Asset Management 26(5), 2025):**
  - Intraday overreaction, measured with a price-adjustment-speed efficiency measure robust to non-trading, is **positively** related to next-day returns.
  - A long-overreaction / short-underreaction factor earns a premium not explained by market, size, value, momentum or illiquidity.
  - Sample period not seen.
  - Source: [IDEAS](https://ideas.repec.org/a/pal/assmgt/v26y2025i5d10.1057_s41260-025-00418-y.html)
- **Minute-scale reversal (Tripathi & Aggarwal, IJFM 2015, intraday data):** returns reverse within a few minutes of extreme rises and falls — [IJFM](https://publishingindia.com/archive/ijfm/prior-return-effect-in-indian-stock-market-an-intra-day-analysis)
- **Overnight return as sentiment (Nair, Raghunandanan & Nair, Vision/SAGE, 2024; 612,066 firm-days):**
  - Overnight returns persist in the short term, more so for hard-to-value or hard-to-arbitrage firms. Persistence was stronger during COVID.
  - Unlike US results, Indian overnight returns **do not reverse** over time.
  - Source: [DOI 10.1177/09722629241281021](https://www.citedrive.com/en/discovery/make-some-noise-tonightovernight-return-as-investor-sentiment-index-indian-evidence)
- **Nifty options (2017–2020):** overnight mean returns are positive and highly significant, while intraday means are negative or insignificant. This concerns option returns, not stocks — [vLex abstract](https://law-journals-books.vlex.com/vid/the-asymmetry-in-day-1115554990)
- **Day-of-week (mixed, unstable):**
  - Positive Monday and Wednesday effects, 1997–2012, GARCH — [MPRA 46805](https://mpra.ub.uni-muenchen.de/46805/1/MPRA_paper_46805.pdf) **[pre-2015]**
  - The Wednesday effect disappeared after the end of weekly settlement, and a Friday effect existed before rolling settlement — [Management Prudence Journal](https://publishingindia.com/archive/mpj/the-calendar-anomalies-in-indian-stock-market-a-special-reference-to-nse)
- **Lunchtime:** no Indian study found. The U-shape implies a midday volume and volatility trough — [Agarwalla & Pandey](https://iima.ac.in/sites/default/files/rnpfiles/19191060542012-11-03.pdf)
- **Herding:**
  - Intraday data on 10 dual-listed stocks shows significant positive and negative herding — [Sinha 2016, IJFM](https://publishingindia.com/archive/ijfm/herd-behaviour-how-decisive-is-the-noise-in-the-nse-and-bse-stock-markets)
  - FII herding measured with high-frequency data, Jan 2003 – Jun 2014 — [Chattopadhyay, Garg & Mitra 2018, J. Behavioral Finance](https://ideas.repec.org/a/taf/hbhfxx/v19y2018i1p73-88.html)
  - Daily, weekly and monthly data for 2000–2013 show no herding — [IIM Calcutta repository](https://ir.iimcal.ac.in:8443/jspui/handle/123456789/3056?mode=full)
- **Intraday momentum context (US only, already on our menu):**
  - The market's first half hour predicts the last half hour, 1993–2013 — [Gao, Han, Li & Zhou via Alpha Architect](https://alphaarchitect.com/2014/08/attention-prop-traders-the-first-half-hour-of-trading-predicts-the-last-half-hour/)
  - In the cross-section, early-day returns *negatively* predict the last half hour — [Notre Dame working paper](https://www3.nd.edu/~zda/EOD.pdf)
  - No NSE replication was found.

### Inferences
- Because the open stays noisy for about 30 minutes, realized moments and VWAP measures should **exclude or down-weight 09:15–09:45**. The first bar also folds in the pre-open auction move, which we cannot see. Use `stock_prices.open` for the overnight leg.
- Midday is the cleanest window for spread or impact estimation.
- The Indian overnight-return result (no reversal, persistent) argues for testing `overnight_ret_1m` with a **positive** sign at 1–4 weeks, not the US-style reversal.
- Siddiqui & Misra give a published India-specific short-horizon factor (overreaction minus underreaction) that can be rebuilt from minute closes. It is the closest Indian analogue to our fast-menu reversal and skew items. Retrieve the full paper to copy the efficiency-measure definition before building it.
- The index-level first-half-hour → last-half-hour test is cheap with a synthetic LARGE-tier minute index. No India evidence either way.

### Gaps
- No post-2015 Indian study of intraday seasonality, which matters given the retail and algo shifts.
- No India test of tug-of-war, intraday-vs-overnight momentum or realized skewness was found in this pass. A separate researcher may cover these.
- The sample period and data source of Siddiqui & Misra were not seen.

---

## 10. Information leakage before announcements

### Takeaway
There is Indian evidence of pre-announcement run-ups:
- ahead of earnings (daily data, several studies);
- ahead of **unscheduled** corporate events.

The strongest study uses NSE trade-level data, 2011–15. It finds that **retail traders' 5-day pre-announcement imbalance predicts post-announcement returns** for unscheduled announcements (Q4−Q1 = 1.1 %), but not for scheduled earnings. The authors attribute this to leakage through social media and bulk SMS. We have timestamped BSE/NSE announcements, so pre-event minute-volume anomalies are testable.

### Cited Findings
- **Nawn & Banerjee (NSE–NYU WP, July 2024; NSE trade-level data identifying HFT, algorithmic institutions, manual institutions and retail; Nifty 500, 2011–2015):**
  - Main effect: across 1,471 unscheduled announcements (acquisitions, divestitures, buybacks, equity offerings, JVs, mergers, spin-offs), stocks retail bought most in T−5 to T−1 beat those they sold most by **1.1 %** (Q4−Q1, significant at 1 %).
  - By size: smaller stocks 1.3 %, larger stocks 1.1 %. Good-news events 1.5 %. When |post-return| > 3 %, 2.9 %.
  - Other groups: traditional institutions show −0.9 %. No retail edge on bad news (−0.3 %).
  - Placebo on 9,733 scheduled earnings events: retail Q4−Q1 is about zero, while traditional institutions and HFT show positive outperformance at 10 %.
  - Source: [NSE–NYU WP](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Trading%20around%20Unscheduled%20announcements_FINALTONYU.pdf)
- **Earnings run-ups (daily data, abstracts only; which figure belongs to which paper was not checked):**
  - Pre-announcement return premiums in 67 large caps (2010–2018).
  - 469 companies (2002–2011) with significant pre-event abnormal returns in 32 of 37 quarters.
  - Sources: [Cogent Economics & Finance 2021](https://www.informahealthcare.com/doi/abs/10.1080/23322039.2021.1898112); [Asian Journal of Accounting Research](https://ideas.repec.org/a/eme/ajarpp/ajar-06-2021-0078.html)

### Inferences
- A "**pre-event abnormal minute volume**" feature fits our data: volume in the T−5…T−1 days (or the last hours before a timestamped unscheduled filing) relative to a 60-day baseline, with an imbalance proxy from minute returns.
- The Indian evidence says leakage concentrates in **unscheduled** events and in **retail-heavy small caps**. Scope it there.
- This works as a short-horizon event signal (it needs the announcement to follow), not a monthly factor. The live use is "unusual pre-filing activity → expect a filing".

### Gaps
- No Indian study used intraday timestamps to locate leakage hours.
- No study was found linking SEBI insider-trading (PIT) orders to minute patterns.

---

## 11. Synthesis: what is detectable from minute close + volume alone

### Takeaway
The India-specific institutional features with the best evidence-to-buildability ratio:

| Feature | Detectability from close + volume | Best use |
|---|---|---|
| Surveillance entry (GSM/ASM) | Partly: ASM's price trigger from daily closes; weekly-only or hourly-batch trading from minute volume | Negative returns after entry → exclusion gate |
| Upper-band locks in non-F&O names | Good | Continuation evidence, weak |
| Expiry-day settlement-window pressure | Good | Closing-pressure variant |
| Morning-up / afternoon-down constituent pattern on expiry days | Good | Jane Street footprint |
| Pre-unscheduled-announcement volume | Good, with announcement timestamps | Short-horizon event signal |
| Intraday overreaction → next-day return | Good | Short-horizon factor (Siddiqui & Misra) |

The data contract must change at **2026-08-03 (CAS for F&O stocks)** and should carry regime dummies at:
- 2018-01-01 (block-deal windows)
- 2022-02 / 2023-01 (T+1)
- 2024-06-03 and 2024-08-19 (band flexing)
- 2024-06-10 (tick size)
- 2024-11-20 (one weekly expiry per exchange)
- 2025 (NSE Tuesday expiry; MWPL reform)

### Cited Findings
- See sections 1–10. Key anchors:
  - GSM CAR coefficient −0.068 — [Aggarwal, Bhatia & Zaveri](https://archives.nseindia.com/research/content/nse_nyu/NidhiAggarwal_Rules_vs_discretion_Impact_of_trading_rules_on_market.pdf)
  - STASM trigger 25 % vs NIFTY over 5 days — [Chari & Inamdar](https://nsearchives.nseindia.com/s3fs-public/inline-files/Effectiveness%20of%20additional%20surveillance%20measures_WhitePaper.pdf)
  - Expiry-window volatility +34–58 % — [Agarwalla & Pandey](https://iima.ac.in/sites/default/files/rnpfiles/19191060542012-11-03.pdf)
  - CAS from 3 Aug 2026 — [Wright Research](https://www.wrightresearch.in/blog/how-does-sebis-closing-auction-session-change-market-close/)
  - Retail-leakage Q4−Q1 1.1 % — [Nawn & Banerjee](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/Trading%20around%20Unscheduled%20announcements_FINALTONYU.pdf)
  - Overreaction premium — [Siddiqui & Misra](https://ideas.repec.org/a/pal/assmgt/v26y2025i5d10.1057_s41260-025-00418-y.html)
  - Jane Street patches — [Moneylife](https://www.moneylife.in/article/jane-street-accused-of-massively-rigging-of-indias-derivatives-market-sebi-orders-ban-escrow-of-rs4843-crore-illegal-gains/77585.html)

### Inferences
Candidate additions to the menu (not already listed in research 0009):
1. **`asm_trigger_gap_5d`:** (5-day stock return − 5-day NIFTY 50 return) relative to the ±25 % STASM line. Negative sign or exclusion gate. Daily data, from 2018-11.
2. **`batch_trading_flag`:** share of a stock's daily volume in the minute after each hourly call-auction close, or volume on a single weekday only. Flags periodic call auction or GSM III/IV. Gate.
3. **`expiry_close_pressure`:** closing pressure restricted to the stock's or its index's expiry days. Sign to be tested. Split at 2024-11-20, 2025 and 2026-08-03.
4. **`expiry_am_pm_reversal`:** for index constituents on expiry days, the 09:15–11:45 return minus the 11:45–close return, averaged over the last N expiries. Exploratory.
5. **`intraday_overreaction_1d`:** Siddiqui & Misra-style speed-of-adjustment measure from minute closes. Positive sign for the next day.
6. **`prefiling_volume_z`:** abnormal minute volume in the 1–5 days before an unscheduled BSE/NSE filing. Event-driven, SMALL tier.
7. **`ltp_ladder_share`:** share of minutes setting a new intraday high on bottom-decile minute volume, over 20 days. Mania or operator gate.
8. **`block_ref_window_pressure`:** the 13:45–14:00 VWAP move on days with a reported afternoon block deal. Exploratory, low prior.

Circuit-detector requirements from section 1:
- F&O stocks: bands of 10 / 15 / 20 / 23 / 26 / 28 / 30 % with cooling-off pauses (pre-2024-08-19: 10 % then 5 % steps).
- Non-F&O stocks: 2 / 5 / 10 / 20 % taken from the daily band list, which should be harvested; fall back to inference.
- Trade-for-trade exits go to 5 %.
- GSM stages ≤ 5 %.

Survivorship bias is worst for exactly the surveillance and manipulation names. Every gate test must say so.

### Gaps
- Primary SEBI/NSE circular texts for band assignment, the current ASM thresholds and the CAS circular number were not retrieved (several NSE pages timed out or returned 403).
- An empirical check is needed of how our Kite minute archive represents CAS (from 2026-08-03), block-deal windows and periodic-call-auction stocks before any of the features above is built.
