# Research 0003 — Special-Situations / Event Sleeve (Engine 3)

**Deep-research dive #3 of 4** · Plan [0011 WS4.0](../plans/0011-roadmap-to-90.md) · Decision [D7 (ADR 0051)](../decisions/0051-roadmap-to-90-decisions-d1-d12.md) — greenlit, 15% paper share, ≥6mo paper first.
**Written:** 2026-07-11 · **Status:** research complete → gates WS4.1 (`event_calendar`), WS4.2 (`tools/event_study.py`), WS4.3 (backtests).
**Author stance:** skeptical event-driven quant. The Greenblatt *You Can Be a Stock Market Genius* paradigm — episodic, capacity-limited, uncorrelated with the factor book, a solo-operator edge **precisely because it doesn't scale for institutions**.

> **Reuse-first note:** built from memory `bse_announcements_event_stream`, `survivorship_universe_via_bhavcopy`, `nselib_apis`, `bse_event_factors_governance`, plus live DB inspection (read-only) and public/academic sources. No harvesters run (parallel agents active — IP-block risk). Anything needing a fetch is flagged **NEEDS LIVE PROBE**.

---

## 0. What's in-house (the shared substrate for all six)

Verified 2026-07-11 against `data/alpha_signal.db`:

| Asset | Coverage | Notes for the sleeve |
|---|---|---|
| `bse_announcements` | 2.51M rows, **2018-01-01 → live**, survivorship-complete (delisted scrip codes persist) | The event firehose. `dt_tm` = look-ahead-safe event time. **sid mapped on only ~53%** (1.34M/2.51M rows; 2,202 distinct sids) — scrip_master↔sid map incomplete → **roughly halves usable n**. |
| `corporate_actions` | 18,923 rows, **2018-03 → live**, has `ex_date` | Record/ex dates for BUYBACK (256), RIGHTS (244), SPLIT/BONUS. Demerger buried under `ind='OTHER'`. This is the **PIT-safe record-date** source that the announcement stream lacks. |
| `stock_prices` | 2.33M rows, **2020-01-01 → live**, 2,447 sids | ⚠️ **CURRENT-NAMES-ONLY** (0 orphan sids). Pre-2020 events have no CAR window; delisted/acquired names vanish from the panel. |
| `macro_history` (`nifty50`) | daily **2015 → live** (2,719 rows) | Event-time CAR benchmark (already the `announcement_car` benchmark). |
| `nse_index_history` (`NIFTY SMALLCAP 250`) | daily **2016 → live** | Better tier-matched benchmark for small/mid event names. |
| `shareholding` | quarterly `promoter_pct`, `pledge_pct` | Promoter-participation signal for rights; **no cross-holding map** (holdco NAV needs this — absent). |

**Two structural constraints that bound every situation type below:**

1. **Price panel starts 2020-01 and is survivorship-biased.** The BSE event stream reaches 2018 and is survivorship-complete, but our *prices* are neither. Event studies are honestly backtestable **2020+ only**, and any event whose resolution *removes the name from the panel* (delisting completion, acquisition-driven open-offer success) cannot be measured post-event in-house. The bhavcopy reconstruction (memory `survivorship_universe_via_bhavcopy`) only reaches **2023-04**, not 2018 — so it does **not** rescue 2018–2022 delisted-name prices. This is the single biggest feasibility risk for the sleeve.
2. **The event-time framework is the right instrument.** `announcement_car` (ADR 0050) already proved event-time CAR works here where the monthly cross-sectional PIT panel failed for PEAD. `tools/event_study.py` (WS4.2) should generalize its `_car_one` / NIFTY-adjustment pattern: day0 = first trading day ≥ event date, market-adjusted CAR over a per-event window, benchmark asof-joined. It should reproduce `announcement_car` as the `[-1,+1]`-window special case (WS4.2 acceptance test).

---

## 1. Demergers / Spinoffs  ★ SHOVEL-READY #1

**(a) MECHANICS.** Board approves a Scheme of Arrangement → files with BSE/NSE + NCLT → SEBI/exchange no-objection → NCLT sanction → **record date** for entitlement → the demerged undertaking lists as a **new entity** (parent continues trading; shareholders receive shares of the spun-off co in a fixed ratio). Key PIT-safe dates and where they live:
- **Announcement:** `bse_announcements` `subcategory='Scheme of Arrangement'` (`dt_tm`) + `subcategory='Amalgamation / Merger / Demerger'`; the clean filter is a headline scan `lower(headline|news_sub) LIKE '%demerg%' OR '%spin%off%'`. **In-house ✓.**
- **Record date:** `corporate_actions` (`ind='OTHER'`, subject `'Demerger'`/`'Scheme Of Arrangement'`, `ex_date`) — partial; **NCLT-sanction and record dates are cleanest from the announcement PDF** → parse layer (NEEDS LIVE PROBE for completeness, but the announce date alone anchors the drift study).
- **Spinoff listing date:** `bse_announcements` `category='New Listing'` (57–291/yr).

**(b) EDGE + EVIDENCE.** The strongest-documented post-event drift in the literature, and it **replicates natively in India**:
- 221 BSE spin-offs 2003–2020: parent abnormal return peaks **+1.35% on day +1**, CAAR **+2.64% over (+1,+5)** — positive and significant ([Cogent Economics 2022](https://www.tandfonline.com/doi/full/10.1080/23322039.2022.2109277)); a separate 2012–2014 India demerger event-study (n=51) reaches the same sign ([Impact of Demerger Announcement on Shareholder Value, India](https://www.academia.edu/66155837/Impact_of_Demerger_Announcement_on_Shareholder_Value_Evidences_from_India)).
- **Economic story (structural, persists):** the US spinoff premium (Cusatis-Miles-Woolridge 1993, Greenblatt's flagship trade) is driven by *forced/indifferent selling* — index funds and institutions dump the small spun-off stub they didn't choose to own, and analyst coverage lags the separation. India adds retail inattention and thin coverage of the newly-listed stub. This is a genuine India-native result, **not a US transfer** — transfer risk LOW.
- **Expected edge:** parent +2–3% CAAR in the announcement window (documented); the larger prize historically is the **spun-off stub's** first 6–12 months, which our data can only see once it lists (New Listing date) — measurable but with a short in-panel history.
- **Capacity: HIGH.** Parents are mid/large liquid names; a solo book can size to the name's ADTV (₹ crores/name). ~40–80 demergers/yr universe-wide; after a liquidity filter, **~20–40 tradeable/yr**.

**(c) FEASIBILITY.** In-house, price-era (2020+), sid-mapped: **507 demerger filings / 178 distinct sids**; broad Scheme-of-Arrangement 531 sids. Pooled n≈178 clears the n≥30 bar comfortably (though per-tier splits may be thin → pool tiers or report pooled). **Backtestable ✓** — the parent stays in the price panel (no survivorship hole, unlike delistings). Window: announcement `[-2,+5]` for the immediate reaction + a `[+1,+60]` drift leg; benchmark NIFTY SMALLCAP 250 (tier-matched) or nifty50. Cleanest of the six because the tradeable leg (parent) survives the event.

---

## 2. Buyback Tender-Offer Arbitrage  ★ SHOVEL-READY #2

**(a) MECHANICS.** Board approves buyback → **Public Announcement** → Letter of Offer → **record date** (fixes entitlement) → tendering window (~5 days) → acceptance → extinguishment → **Post-Buyback PA**. Two routes, and **only the TENDER route is arb-relevant** (open-market route buys on-exchange, no proportionate acceptance, no edge). Dates:
- **PA / record / close:** `bse_announcements` `subcategory='Public Announcement-Buyback of Shares'` (329), `'Closure of Buy Back'` (189), `'Post Buyback Public Announcement'` (261) + `corporate_actions` `ind='BUYBACK'` `ex_date` = **record date, in-house ✓** (120 sids, price-era).
- **Tender-vs-open-market flag + buyback price + size:** buried in the PDF/board resolution — a headline `LIKE '%tender%'` catches only **60 of 4,813** buyback filings. **NEEDS a parse layer** (or Chittorgarh/exchange LoF scrape) for the route flag, buyback price `B`, and reserved-quantity.

**(b) EDGE + EVIDENCE.** The canonical Greenblatt structural edge, and India *legislates* it: **SEBI reserves 15% of every tender buyback for "small shareholders"** (holding ≤ ₹2,00,000 market value on record date). Because small holders under-tender, the **small-shareholder acceptance ratio runs far above the entitlement ratio** — frequently 60–100% ([Chittorgarh](https://www.chittorgarh.com/article/buyback-price-and-maximum-share-in-retail-category/548/), [Upstox — Bajaj Auto](https://upstox.com/news/market-news/stocks/bajaj-auto-buyback-know-about-acceptance-ratio-return-and-retail-quota-ahead-of-june-24-record-date/article-195782/)).
- **Story (structural — the purest in the queue):** the edge exists *because* it's capped at ₹2 lakh/name — an institution literally cannot deploy size into the reserved category, so the reserved acceptance stays rich. This is the textbook "doesn't scale for institutions, perfect for a solo operator" trade.
- **Expected edge:** deterministic per-event (see worked example) — typically **+5 to +15% on the ₹2 lakh** over a ~1–2 month hold, when acceptance is high and the post-record price decline is < the accepted premium.
- **Capacity: STRUCTURALLY CAPPED — this is the honest reality.** The retail-reserved arb only accepts ~₹2 lakh/name. ~30–40 tender buybacks/yr → **max ~₹60–80 lakh/yr of pure retail-reserved arb**, recycling capital across non-overlapping windows. Real, uncorrelated, but **small absolute rupees** — a return *enhancer*, not a book-mover.

**(c) FEASIBILITY.** In-house: 128 buyback-PA sids + 120 BUYBACK record-dates (price-era). But **this is not a drift/CAR study — it's a deterministic acceptance-ratio P&L.** "Backtest" = reconstruct, per historical tender buyback: entry at pre-record market `M`, buyback price `B`, realized acceptance ratio `a`, post-record price `M'`, and compute the return formula below. n≈120 events is ample; the binding gap is **acceptance-ratio history + route flag + `B`**, which need the parse/scrape layer (NEEDS LIVE PROBE). Until then the mechanics are proven but the historical `a` distribution is unmeasured.

**(d) WORKED EXAMPLE.** Buy `N` shares at market `M` just before record; buyback price `B` (premium `p = B/M − 1`); acceptance ratio `a`; post-record market price `M'`.
```
Return ≈ a·(B−M)/M  +  (1−a)·(M'−M)/M   =   a·p  +  (1−a)·(M'/M − 1)
```
Concrete: hold the ₹2 lakh cap → `N = 200` shares at `M = ₹1,000`; `B = ₹1,200` (p = 20%). Tender all 200.
- Acceptance `a = 0.75`, stock flat post-record (`M' = M`): return = 0.75×20% + 0.25×0 = **+15%**.
- Acceptance `a = 0.60`, stock drops 10% post-record (`M' = ₹900`): return = 0.60×20% + 0.40×(−10%) = 12% − 4% = **+8%**.
- The accepted premium `a·p` is the buffer; the trade turns negative only if `(1−a)·(post-record decline) > a·p` — i.e. a low acceptance AND a sharp drop. Risk management = weight toward high-reservation, high-premium, liquid names.

---

## 3. Open Offers (SAST-triggered)  ○ MIDDLE (n huge, edge thin)

**(a) MECHANICS.** Acquirer crosses **25% voting rights** or acquires control → mandatory **Public Announcement** (Reg 3(1)/4) → Detailed PA → Letter of Offer → offer for **≥26%** of remaining shares at the **Reg-8 price** (60-day VWAP / negotiated, whichever higher) → tendering window → proportionate acceptance ([IBA](https://www.ibanet.org/competing-offers-under-the-Indian-takeover-regime), [SEBI SAST FAQ](https://www.sebi.gov.in/sebi_data/faqfiles/mar-2022/1648620806406.pdf)). Dates:
- **PA:** `bse_announcements` `subcategory IN ('Open Offer','Public Announcement-Open Offer','Open Offer - Updates')` — **huge, in-house ✓** (922 events / 183 sids price-era; 2,811 total). SAST disclosures also under `category='Insider Trading / SAST'`.
- **Offer price `O` + offer size + close date:** in the PA/LoF PDF → **parse layer** (NEEDS LIVE PROBE).

**(b) EDGE + EVIDENCE.** Merger-arb spread: market price `M` trades below offer price `O` reflecting deal risk + time value + proportionate-acceptance dilution. Story is structural (deal-completion risk premium + retail can't-be-bothered), but the Indian mandatory-offer spread is **thin and crowded** — dedicated arb desks watch it. No clean India drift-anomaly study found (US merger-arb literature is the reference class → **transfer risk MEDIUM-HIGH**, and the spread is a *risk premium*, not a free lunch). **Survivorship bites hardest here:** offers that succeed and lead to delisting remove the target from our price panel → in-house sample is biased toward *failed/partial* offers.
- **Capacity: MEDIUM-LOW after filtering.** ~300/yr PAs but most spreads are tiny or negative; the tradeable subset (positive net-of-cost spread, liquid, low deal-risk) is small.

**(c) FEASIBILITY.** Dates in-house and abundant, but the study needs `O` (PDF) + completion outcome, and the survivorship hole corrupts the post-event leg. **Partial** — backtestable only as an announce-window CAR on the *acquirer/target-that-survives*; the true arb P&L needs offer-price + acceptance data we don't hold.

**(d) WORKED EXAMPLE.** Offer `O = ₹500`, buy at `M = ₹470` (spread `s = 6.4%`); tender all; proportionate acceptance `a = 0.55`; post-offer price `P`.
```
Return = a·(O−M)/M + (1−a)·(P−M)/M
```
- `P = M` (flat): 0.55×6.4% + 0.45×0 = **+3.5%** over ~2–3 months.
- `P = ₹450` (−4.3% post-offer fade): 3.5% + 0.45×(−4.3%) = 3.5% − 1.9% = **+1.6%** — and negative if the stock cracks. Thin, path-dependent, deal-risk-laden → ranks below buyback/demerger.

---

## 4. Delistings (reverse book building)  ✗ SKIP / DEFER

**(a) MECHANICS.** Promoter proposes voluntary delisting → board + special resolution → **Public Announcement** → **Reverse Book Building (RBB):** public shareholders bid; the **discovered price** = price at which promoter reaches 90% → promoter *accepts or rejects* it. SEBI 2024 added a **fixed-price alternative** (≥15% premium to floor) ([IndiaCorpLaw 2024](https://indiacorplaw.in/2024/07/22/striking-a-balance-sebis-fixed-price-method-in-voluntary-delisting/), [Chambers](https://chambers.com/articles/voluntary-delisting-in-india)). Dates in `bse_announcements` `subcategory LIKE '%Delisting%'` (`'Public Announcement-Delisting'` 208, `'Delisting'` 216, `'Voluntary Delisting'` only 6).

**(b) EDGE + EVIDENCE.** The RBB premium is real (US going-private literature) but Indian RBB is **speculative and binary**: shareholder groups bid up the discovered price, and **the promoter can walk away** if the premium is "exorbitant" — so the payoff has a fat left tail (offer fails → stock falls back to floor). This is a *lottery/event-risk* trade, not a drift anomaly. Transfer risk HIGH; the mechanism SEBI is actively reforming (2024) breaks any long backtest's stationarity.

**(c) FEASIBILITY — POOR, hence SKIP.** (i) The arb-relevant **voluntary** subset is thin: most of the ~30–86/yr "Delisting" rows are compliance/suspension notices; genuine voluntary RBB delistings are **~10–20/yr** → n barely reaches the bar even pooled to 2018. (ii) **Survivorship kills the post-event leg** — a *successful* delisting removes the name from `stock_prices`, and bhavcopy reconstruction only reaches 2023-04, so completed pre-2023 delistings have no exit price in-house. (iii) The 2024 regime change fragments the sample. **Verdict: SKIP for the paper sleeve.** Revisit only if a delisted-name price backfill + PDF floor/discovered-price parse gets built for another reason.

---

## 5. Rights Issues (promoter-participation signal)  ✗ SKIP as standalone

**(a) MECHANICS.** Board approves rights issue → **record date** (`corporate_actions` `ind='RIGHTS'`, `ex_date` — in-house ✓, 125 sids price-era; `bse_announcements` `subcategory='Bonds / Right issue'`) → offer at a discount to market → renounceable entitlements trade → promoter subscribes (or renounces). Promoter subscription intent appears in the LoF (PDF) and post-issue `shareholding.promoter_pct` delta.

**(b) EDGE + EVIDENCE — WEAK/NEGATIVE.** The hypothesis is "promoter full-subscription = confidence." But the Indian evidence on the *plain* event is discouraging: market reaction to rights issues is **generally neutral, and significantly NEGATIVE for business-group firms**, with **worse long-run abnormal returns** than non-issuers ([Price reaction to rights issues in the Indian capital market, ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0927538X0700056X); [QIP vs Rights, Banerjee-Deb 2015](https://doi.org/10.1177/0972150915601260)). A rights issue often signals the promoter *couldn't* raise cheaper QIP/debt. The promoter-participation *conditioning* might salvage a signal, but even then business-group rights are negative, and it needs LoF-parse for subscription intent.

**(c) FEASIBILITY.** Dates in-house, but the base-rate drift is the wrong sign for a long trade. **Verdict: SKIP as a standalone event trade.** Keep `promoter_pct`-change-around-rights as a *candidate feature* for the factor book (WS2.4 SHP-delta family), not an event sleeve.

---

## 6. Holding-Company NAV Discount  ✗ SKIP for this sleeve (wrong instrument + data absent)

**(a) MECHANICS.** A holdco owns stakes in listed (and unlisted) subsidiaries; it trades at a persistent discount to look-through NAV = Σ(stake% × subsidiary market cap) + unlisted-at-book. Not an event — a **standing valuation state**.

**(b) EDGE + EVIDENCE.** India's holdco discounts are unusually deep — **50–80% vs a ~40–60% global norm** ([EquitiesIndia](https://equitiesindia.com/glossary/holding-company-discount), [Incwert 2024 study](https://incwert.com/wp-content/uploads/2025/05/Study-on-Holdco-discount-2024.pdf)). Causes are structural (dividend double-taxation, holdco overheads, illiquidity of unlisted stakes, no monetization path). The discount **mean-reverts on a catalyst** — monetization/buyback, demerger, or activist pressure. Story is sound and India-specific.

**(c) FEASIBILITY — SKIP here.** (i) It is **not episodic and not event-time** — it's a slow value/carry trade → the event-study framework (WS4.2) is the wrong instrument. (ii) **The data is absent:** no cross-holding map in-house (`shareholding` gives promoter %, not *which listed stocks the holdco owns and how much*). Building look-through NAV needs a holdco→holdings registry + daily MTM of each subsidiary — a bespoke data build. (iii) The discount can stay wide for years (value-trap risk) without the catalyst. **Verdict: SKIP for Engine 3; re-home the idea as a NAV-discount value factor in the compounder sleeve (Engine 2) or a standalone catalyst-gated position, where the multi-year hold and the data build fit.**

---

## RANKED BUILD ORDER

| Rank | Situation | Dates in-house? | Edge quality | Backtestable 2020+ | Capacity | Build call |
|---|---|---|---|---|---|---|
| **1** | **Demergers / spinoffs** | ✓ (announce; record partial) | **Strong, India-native** (+2.6% CAAR) | ✓ parent survives | **HIGH** (₹cr/name, 20–40/yr) | **BUILD FIRST** |
| **2** | **Buyback tender arb** | ✓ (record dates) + parse for route/price | **Structural, deterministic** | ✓ (as P&L, not CAR) | **LOW-capped** (~₹2 lakh/name) | **BUILD SECOND** |
| 3 | Open offers (SAST) | ✓ (abundant) + parse for `O` | Thin, crowded, deal-risk | Partial (survivorship-biased) | MEDIUM-LOW | Defer to phase 2 |
| — | Delistings (RBB) | ✓ dates, thin voluntary subset | Binary/speculative, regime-shifting | ✗ survivorship + n too thin | LOW | **SKIP** |
| — | Rights issues | ✓ (record dates) | **Neutral-to-negative drift** | ✓ but wrong sign | n/a | **SKIP** (feature, not sleeve) |
| — | Holdco NAV discount | ✗ (no cross-holding map) | Sound but not event-time | ✗ needs bespoke NAV build | MEDIUM | **SKIP here** → Engine 2 |

**Top-2 shovel-ready:** Demergers (dates in-house, cleanest edge, parent survives the event) and Buyback tender arb (record dates in-house, deterministic acceptance-ratio math, the purest solo-operator structural edge).

**Sequencing for WS4.2/4.3:**
1. Build `tools/event_study.py` generalizing `announcement_car._car_one` (WS4.2), acceptance test = reproduce `announcement_car`.
2. **Demerger drift** first — pure CAR study on the survivorship-clean parent leg; n≈178, benchmark NIFTY SMALLCAP 250, windows `[-2,+5]` and `[+1,+60]`.
3. **Buyback tender** second — not a CAR regression but a deterministic P&L reconstruction; needs the acceptance-ratio/route/price parse layer (the one net-new data build the sleeve requires).
4. Open offers only after a PDF offer-price parser exists and the survivorship hole is quantified.

**Net-new data the sleeve needs (one build):** a tender-buyback **acceptance-ratio + route + buyback-price** parser (Chittorgarh/exchange LoF — NEEDS LIVE PROBE, don't concurrent-harvest). Everything for the demerger study is already in-house.

---

## Feasibility risks (do not soften)

1. **Survivorship + 2020 price floor** is the master constraint. Events resolve by *removing names from the panel* (delisting, acquisition) exactly where the edge is largest — and our prices start 2020 and drop dead names; bhavcopy backfill stops at 2023-04. Any open-offer/delisting number will be optimistically biased toward survivors. Demergers dodge this (parent survives).
2. **sid-mapping at ~53%** halves every raw event count; the scrip_master↔sid map is the gating infra for `event_calendar` (WS4.1).
3. **Buyback capacity is genuinely small** (~₹2 lakh/name reserved) — this is the honest ceiling of the purest edge; it enhances returns on a small sleeve, it does not move the book.
4. **PDF-locked fields** (tender-vs-open-market flag, buyback price, open-offer price, RBB floor/discovered price) sit behind a parse layer — the same PDF-extraction dependency that deferred credit-rating direction (memory `bse_event_factors_governance`). Budget for it or the arb legs stay un-backtestable.
