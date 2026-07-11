# Research 0001 — India-structural event/microstructure factors (six-factor deep dive)

**Status:** research complete · **Written:** 2026-07-11 · **Type:** deep-research dive #1 of the roadmap-to-90 queue
**Gates:** Plan 0011 WS2.5 · Decision D12 (ADR 0051) · **Guardrail:** every card obeys the ADR-0043 lens (|t|≥2.5 necessary-not-sufficient, BY-FDR context, sign matches prior, n≥20) and the ≤10-hypotheses/month budget (guardrail 3). A card is a licence to *test*, not to wire.
**Companion format:** [return-prediction-2026-07-05-report.md](../return-prediction-2026-07-05-report.md) Task-3 house card.
**Reuse-first assets consulted (per D12):** memory `bse_announcements_event_stream`, `bse_event_factors_governance`, `nselib_apis`, `historical_data_sources`, `survivorship_universe_via_bhavcopy`; `docs/reference/data-playbook.md`; live read-only DB inspection of `surveillance_flags`, `fno_bhav`, `nse_index_history`, `corporate_actions`, `bse_announcements`, `stock_prices`, `shareholding`.

> **Method note.** READ-ONLY + web-search only. No harvester was run, no endpoint probed, no code/DB touched. Where a recipe needs a live endpoint probe it is flagged **NEEDS LIVE PROBE (single-threaded)** as a follow-up — never run concurrent with another BSE/NSE harvester (documented IP-block rule).

---

## In-house status at a glance (verified against the live DB, read-only)

| # | Factor | Raw data in-house? | Where | Depth / cadence | Harvester exists? |
|---|---|---|---|---|---|
| 1 | ASM/GSM surveillance additions | **PARTIAL** (forward-only, ~2mo) | `surveillance_flags` (ASM_LT 5,684 / ASM_ST 3,763 / GSM 222 rows; 146/265/6 sids) | daily snapshot, 69 distinct dates, **2026-05-03 → today only** | ✅ `sources/nselib_pull.py::pull_surveillance_today()` |
| 2 | F&O ban-list entries | **PARTIAL** (2 ways) | `surveillance_flags` FNO_BAN (23 rows/2 sids, 2026-06-03+) **+** derivable from `fno_bhav` OI (5.8M rows, **2025-05-26 → today**, 279 days) | ban-flag forward-only; OI ~14mo | ✅ ban flag; ⚠️ OI-derived ban needs MWPL denominators |
| 3 | Index inclusion/exclusion | **ABSENT** (levels only, not membership) | `nse_index_history` has index **OHLC** (NIFTY 50/500/Midcap150/Smallcap250 + smart-beta, 2016/2023+) — **no constituent list** | n/a for membership | ❌ constituents not captured |
| 4 | IPO / anchor lock-up expiry | **ABSENT** | no IPO table; `corporate_actions` = splits/bonus/div/rights only | n/a | ❌ |
| 5 | Circuit-hit frequency | **PARTIAL** (derivable-with-noise) | `stock_prices` (OHLC + delivery, 3yr) → approx circuit pin; exact band needs NSE price-band file | prices daily 3yr | ⚠️ approximate from prices; exact band file not captured |
| 6 | SEBI SCORES complaint counts | **ABSENT** | — | n/a | ❌ |

**Headline:** the six split cleanly into two disjoint groups — *(a) strong-story + clean-PIT but data-absent* (index, lock-up), each a small harvester away; and *(b) data-in-house but weak-or-overlapping story* (ASM/GSM is only 2 months deep and left-censored; circuit-hit ≈ the not-yet-built MAX card; F&O-ban sign is ambiguous). The `surveillance_flags` table looks like a gift but is **forward-accumulate, not backtest-now**. See ranked shortlist §7.

---

## 1 — ASM / GSM surveillance-list additions

### (a) Data recipe
- **Source (free):** NSE JSON `nseindia.com/api/reportASM` (ASM long-term + short-term) and `/api/reportGSM` (cookie-warm required). Already wired: `sources/nselib_pull.py::pull_surveillance_today()` → `surveillance_flags(sid, symbol, flag_type∈{ASM_LT,ASM_ST,GSM,FNO_BAN}, flag_date, stage, reason)`.
- **History depth:** the endpoints return **only the *current* list** (who is under surveillance *today*), not an event log. Our archive therefore starts at first harvest, **2026-05-03 → present (~69 daily snapshots)**. NSE does **not** publish a clean historical ASM/GSM add/remove log; third-party mirrors (marketsmith, chittorgarh, 5paisa) also show current-only. **Historical depth is genuinely unavailable for free** — this is a Pattern-2 (forward-accumulate) source, not a Pattern-1 (slice raw history) one.
- **Update cadence:** daily (NSE revises the ASM/GSM lists each evening).
- **Survivorship/delisted:** forward snapshots cover whatever is listed on each date; delisted names simply stop appearing. No look-back reconstruction of pre-2026-05 additions is possible from free data.
- **PIT-safety of the key date:** *derived, not native.* The snapshot is a state, not an event. An **addition date** = the first snapshot a sid appears in; a **removal date** = the first snapshot it disappears from. Both are PIT-safe **going forward** (we learn them same-day) but **left-censored** for our start — a sid already under ASM on 2026-05-03 has an unknown true add-date. Do not treat "appears on 2026-05-03" as an event.
- **In-house status:** **PARTIAL** — harvester live, table populated, but only ~2 months and left-censored.
- **Harvester build effort:** **~zero** (already running). The work is *time* (accumulate 12+ months for an IC test) — not code.

### (b) Build-candidate card
- **Evidence class:** **EMPIRICAL** (India-specific, liquidity/volatility-side). Inamdar & Chari (2023), *Liquidity Impact of Novel Market Surveillance Measures — Evidence from India* (Sage; also NYU-Stern working paper), event-study on 245 ASM inclusion/exclusion events (Nov-2018→Feb-2019): **post-inclusion, prices stabilise and volatility falls, and there is an overall fall in liquidity.** The paper's headline is *liquidity/volatility*, **not** a clean cross-sectional return premium — so the *return-drift* claim below is my structural hypothesis, only partially supported by the cited study. Marked EMPIRICAL, not BOTH.
- **Economic story (structural):** ASM/GSM inclusion raises margins (up to 100% in higher GSM stages), caps or freezes price bands, and forces leveraged/speculative longs to deleverage into a shrinking-liquidity tape. The names selected are, by construction, over-extended (abnormal price+volume run-ups). Structural forced-deleveraging + the removal of the marginal leveraged buyer ⇒ **expected negative forward drift** in the weeks after inclusion.
- **Persistence argument:** the mechanism is *regulatory and mechanical* (margin hikes are exogenous to fundamentals), and the affected clientele is retail/leveraged momentum-chasers who cannot arbitrage their own forced exit. No US or global fund trades the NSE ASM list — it is a purely local, disclosure-gated microstructure event. Persistence is plausible **but** the effect may be partly *already in* delivery_anomaly_z (see orthogonality).
- **Expected sign:** **negative** (inclusion → lower forward returns; long-only capture is *exclusion-shaped* — avoid/underweight ASM names, like governance_resignation's negative weight).
- **Expected net-of-cost alpha:** **+0.2–0.6pp** book-level, SMALL/MID-concentrated, honest single-digit. ASM names are illiquid by selection — trading cost eats a chunk, which is why the honest capture is *avoidance* not shorting.
- **Orthogonality:** medium. Overlaps conceptually with `delivery_anomaly_z` (both microstructure-stress) and `iv_skew` (vol) — **must check ρ before sizing.** Distinct in that ASM is a *discrete exchange-forced state*, not a continuous z-score. Orthogonal to consensus/book_to_price/piotroski/announcement_car.
- **Build effort:** **LOW code / HIGH calendar** — the code is a Pattern-2 accumulation feature on an existing table; the binding constraint is 12+ months of forward history before an honest IC test (guardrail 4).

---

## 2 — F&O ban-list entries

### (a) Data recipe
- **Source (free), two independent paths:**
  1. **Native ban flag** — `nselib.derivatives.fno_security_in_ban_period(trade_date)` (bare symbol list), already harvested to `surveillance_flags` FNO_BAN. Forward-only; **23 rows/2 sids since 2026-06-03** (thin because few names are in ban on any given day).
  2. **Derive from OI (in-house)** — a stock enters ban when market-wide OI ≥ **95% of MWPL**; exits when it falls below 80%. We hold per-symbol `fno_bhav.oi` / `chg_oi` back to **2025-05-26 (279 trading days)**. The ban list is *reconstructable* from OI **if** the per-stock MWPL denominator is known (MWPL = 20% of free-float shares, revised monthly; NSE publishes the combined OI% file). So OI gives ~14 months of *proxy* ban history for free.
- **History depth:** native flag ~1 month; OI-derived proxy ~14 months (limited by `fno_bhav` start).
- **Update cadence:** intraday for the live ban; EOD for OI.
- **Survivorship/delisted:** F&O universe is ~180–220 large/liquid names — survivorship is a non-issue at this cap (delisting of an F&O name is rare and pre-announced).
- **PIT-safety:** the ban is announced *before* the next session (it restricts *fresh* positions next day) — the ban date is PIT-safe. The OI-derived entry is EOD-knowable, also PIT-safe.
- **In-house status:** **PARTIAL** — native flag thin/forward-only; OI-derived proxy buildable from in-house `fno_bhav` for ~14 months.
- **Harvester build effort:** **LOW** — flag already captured; OI-derived ban needs a MWPL denominator table (one monthly NSE file). **NEEDS LIVE PROBE (single-threaded)** to confirm the MWPL file endpoint/format.

### (b) Build-candidate card
- **Evidence class:** **EMPIRICAL / thin.** No clean India academic *return* study located (searched; the literature is practitioner-side on liquidity/volatility). Practitioner consensus: ban → reduced derivative liquidity, elevated cash-market volatility, often marks a *local sentiment extreme*.
- **Economic story (structural):** ban = OI hit 95% MWPL = extreme speculative positioning. Fresh positions blocked ⇒ forced unwinding of existing positions into a thin tape. **But the sign depends on whether the crowd is long or short** — a long-crowded ban unwinds *down*, a short-crowded ban can squeeze *up*. Without decomposing OI direction (which `fno_bhav` chg_oi + price lets us approximate), the sign is ambiguous.
- **Persistence argument:** weak-to-medium. The clientele (retail F&O speculators) is famously loss-making and under-arbitraged (SEBI's own studies show ~90% retail F&O loss rates), so an over-positioning fade *could* persist — but the effect is short-horizon (ban lasts ~1 day typically) and sits squarely in the F&O-positioning family we already tried and benched.
- **Expected sign:** **ambiguous** — must be conditioned on OI-direction (long-buildup ⇒ negative; short-buildup ⇒ positive/squeeze). A signed factor is `ban × sign(net_OI_buildup)`.
- **Expected net-of-cost alpha:** **+0.1–0.4pp** at best, short-horizon, capacity-limited to the F&O universe (already the most-arbitraged, most-liquid tier).
- **Orthogonality:** **low** — overlaps the existing F&O-positioning library set (OI/PCR/max-pain, never cleared t=1.5) and `iv_skew`. Likely redundant.
- **Build effort:** **LOW–MED** (OI-derive + MWPL file), but low expected value.

---

## 3 — Index inclusion / exclusion (NSE semi-annual reconstitution)

### (a) Data recipe
- **Source (free):** `niftyindices.com` publishes (i) **current constituent CSVs** per index and (ii) **reconstitution press releases / circulars** (semi-annual: changes announced ~4 weeks ahead, effective end-Mar & end-Sep for Nifty 50/Next50/100/500; Midcap/Smallcap similar). NSE also archives the change circulars. To build membership *history* you snapshot the constituent CSV each rebalance (forward) **and** parse past reconstitution circulars for the add/drop list (backfillable several years from the circular archive).
- **History depth:** constituent CSVs are current-only (forward-accumulate), but the **reconstitution circulars are archived** — the add/drop *events* are recoverable back ~10+ years from niftyindices/NSE circular archives (India literature below reconstructs 2000-2018).
- **Update cadence:** **semi-annual** (announce ≈ 4 weeks before effective date). Two clean dates per event: **announce date** (information/front-run window opens) and **effective date** (mechanical index-fund flow).
- **Survivorship/delisted:** the circular archive names exclusions (often distressed/delisted names) → survivorship-complete by construction if sourced from circulars.
- **PIT-safety:** **excellent — this is the cleanest of the six.** The announce date is unambiguous and public; the effective date is known the moment the announcement drops. A pre-effective-date position is fully PIT-safe.
- **In-house status:** **ABSENT for membership** (we hold index *levels* in `nse_index_history`, not constituents). Corporate-actions and prices are in-house.
- **Harvester build effort:** **LOW–MED** — one scraper for niftyindices constituent CSVs (forward) + a circular-archive parser for history. No PDF-locking (change lists are in the circular body/CSV).

### (b) Build-candidate card
- **Evidence class:** **BOTH** (strong). India event studies: inclusion → significant **positive** abnormal returns that **partially reverse within ~60 days**; exclusion → **negative** for ~10 days then a **+4–7% reversal over 60–240 days**; the index effect was significant 2000-2018 but has **diminished post-2010** (Kumar/Gupta and others; ScienceDirect *Institutional ownership, investor recognition and stock performance around index rebalancing: Evidence from the Indian market*). Global anchor: Shleifer (1986) downward-sloping demand curves; Chen-Noronha-Singal.
- **Economic story (structural / flow):** index funds and ETFs **must** buy additions and sell deletions at/around the effective date regardless of price → a mechanical, price-inelastic demand shock. The tradable edge is *anticipating* the rebalance flow between announce and effective date, then fading the post-effective reversal.
- **Persistence argument:** **the honest weak point.** Passive AUM in India is growing fast, which *strengthens* the flow but also *attracts more front-runners* → the announce→effective alpha is visibly **decaying** (the literature's "diminished post-2010" finding). Persistence is better in the **smaller indices** (Midcap 150, Smallcap 250, sectoral) where arb capital is thinner and the flow-to-float ratio is larger.
- **Expected sign:** **positive** on additions (long the add, announce→effective), **negative** on deletions; plus a **reversal** leg (fade the inclusion pop after ~1–2 weeks).
- **Expected net-of-cost alpha:** **+0.3–0.8pp** blended, event-episodic (a handful of events per rebalance × 2/yr) — small in book terms but **fully orthogonal** and capacity-real in smallcap indices. Best implemented in the WS4 special-situations sleeve (event-time CAR), not the monthly cross-sectional panel.
- **Orthogonality:** **high** — nothing flow-shaped is wired. Orthogonal to delivery/consensus/governance/momentum/value. This is its main attraction.
- **Build effort:** **MED** — data harvester (low-med) + event-time backtest (belongs in `tools/event_study.py`, WS4.2). Not a monthly-panel factor.

---

## 4 — IPO / anchor-investor lock-up expiry calendar

### (a) Data recipe
- **Source (free):** **chittorgarh.com** `/report/anchor-investor-lock-in-end-dates/156/all/?year=YYYY` — per-IPO table of the **30-day (50% of anchor shares)** and **90-day (remaining 50%)** anchor lock-in expiry dates, plus listing dates, mainboard + SME, years 2022→2026 archived. Secondary: SEBI mandates the 30d/90d split (rule, not estimate), so expiry dates are *deterministic* from the allotment/listing date. BSE/NSE listing announcements (in `bse_announcements`, category "Listing"/"New Listing") corroborate listing dates.
- **History depth:** chittorgarh archives ≥2022; the rule-based derivation works for any IPO whose listing date is known.
- **Update cadence:** event-driven (per IPO); the calendar is fixed at listing.
- **Survivorship/delisted:** covers all mainboard (and SME) IPOs of the period; newly-listed names are exactly the population — no survivorship issue.
- **PIT-safety:** **best-in-class.** The expiry dates are **known on the listing day** — a genuine *scheduled known-date supply shock*. Zero look-ahead risk. This is the textbook "predictable supply increase" event.
- **In-house status:** **ABSENT** (no IPO/lock-up table; `corporate_actions` doesn't carry listings or lock-ups).
- **Harvester build effort:** **LOW** — one chittorgarh scraper (HTML table) → an `ipo_lockup_calendar(sid, listing_date, expiry_30d, expiry_90d, anchor_pct)` table. **NEEDS LIVE PROBE (single-threaded)** to confirm chittorgarh table structure + sid mapping (IPO names → universe sid).

### (b) Build-candidate card
- **Evidence class:** **BOTH.** US lit is strong and directional: Field & Hanley, Bradley et al., Ofek-Richardson — **abnormal negative returns of ~1–3% and a permanent liquidity/volume jump around lock-up expiry**, larger where VC/insider overhang is big. India: Bubna & Prabhala (ISB) on anchor IPOs (anchor-backed IPOs larger/better quality, greater short-run underpricing, less-negative long-run returns) establishes the anchor institution; the *expiry-drift* magnitude is a US import — **flag transfer risk**.
- **Economic story (structural / supply):** at the 30d/90d marks, a large, previously-locked block becomes sellable. Anchors that are sitting on gains (most, given IPO underpricing) have an incentive to book — a predictable, price-inelastic *supply* increase into a still-thin post-IPO float. Downward price pressure clusters in the days around expiry.
- **Persistence argument:** the event is *public and predictable*, so the large-IPO version is partly arbitraged (informed traders pre-position) — **but** the edge persists in **SME and smaller mainboard IPOs** where (i) arb capital is thin, (ii) the anchor block is a huge fraction of free float, and (iii) retail dominates the register. This is exactly the under-arbitraged, disclosure-gated, local segment the fund's edge lives in.
- **Expected sign:** **negative** around the 30d and 90d expiry windows (short/avoid; long-only capture = *don't hold* a name into its anchor unlock).
- **Expected net-of-cost alpha:** **+0.2–0.6pp**, episodic, SME/smallcap-concentrated; capacity-limited (few IPOs/month) but genuinely uncorrelated.
- **Orthogonality:** **high** — nothing supply/float-shaped is wired; orthogonal to announcement_car (earnings CAR), delivery, consensus, governance.
- **Build effort:** **LOW–MED** — scraper (low) + event-time study (WS4). Belongs in the special-situations sleeve.

---

## 5 — Circuit-hit frequency (price-band rules → lottery/attention proxy)

### (a) Data recipe
- **Source (free):** two paths. (i) **Derive from in-house `stock_prices`** — a circuit hit ≈ a day where the security pins the band (open=high=low=close, or high/low equals the ±band and no further movement). We have 3yr OHLC. This is **approximate** (we don't store the per-stock band, which is 2/5/10/20% and revised daily-down/bimonthly-up). (ii) **Exact** — NSE "Daily review of Price Bands" report (`nseindia.com/regulations/daily-price-bands-reports`) gives each stock's band per day; combined with OHLC it yields exact circuit hits. Path (ii) is forward-only (no clean archive).
- **History depth:** derived-approx → full 3yr (in-house prices); exact → forward-only from first band-file harvest.
- **Update cadence:** daily.
- **Survivorship/delisted:** inherits `stock_prices` (current-names-only) — for a lottery/attention factor over 6–12mo windows the survivorship bias is noise (per data-playbook: material only for 3yr+).
- **PIT-safety:** the circuit hit is an EOD-observable fact (price pinned that day) — PIT-safe. The *frequency* is a trailing rolling count (Pattern-4 window), fully PIT.
- **In-house status:** **PARTIAL** — derivable-with-noise from in-house prices today; exact needs the band file (forward-only).
- **Harvester build effort:** **LOW** — the derived version is a pure `reconstruct_pit` computation on existing `stock_prices` (no new harvest). Exact band file is a later refinement.

### (b) Build-candidate card
- **Evidence class:** **BOTH.** Bali-Cakici-Whitelaw (2011) MAX; **India-specific:** *Lottery factor and stock returns: Evidence from India* (ScienceDirect S2214845024000267, Dec-2001→Mar-2021) — constructs a lottery factor from MAX/skew/tail-risk/idio-vol and finds it priced in India; and *The MAX effect: lottery stocks with price limits and limits to arbitrage* (S1386418118300247) — **upper price-limit hits attract attention, high-MAX names are overpriced and subsequently underperform.** Circuit-hit frequency is a direct India-flavoured operationalisation of exactly this mechanism.
- **Economic story (behavioral):** frequent upper-circuit hits are the most *attention-grabbing, lottery-like* events available to Indian retail (a stock "hitting upper circuit" is a cultural signal). Retail lottery preference overprices these names; the overpricing subsequently reverses. India's smallcap/retail options boom is the ideal habitat.
- **Persistence argument:** **strong on the clientele** (retail lottery-buyers don't optimise; SEBI data shows the segment is persistently loss-making) — **but weak on independence** (see orthogonality). The premium persists because the marginal buyer is a probability-mis-weighing retail speculator, under-arbitraged in the smallcap tail.
- **Expected sign:** **negative** (high circuit-hit frequency → underperformance; exclusion-shaped, SMALL-concentrated).
- **Expected net-of-cost alpha:** **+0.3–0.7pp** SMALL-concentrated — *but see the double-counting caveat*.
- **Orthogonality:** **the problem.** This heavily overlaps the **MAX/lottery card (#4 in the 2026-07-05 report, ABSENT/not-yet-built)** — circuit-hit frequency and MAX are two constructions of the *same* lottery/attention premium. It also touches `delivery_anomaly_z` (attention/microstructure). Building both MAX and circuit-hit would spend two hypotheses on one economic effect (guardrail-3 waste).
- **Build effort:** **LOW** — but should be built as a **variant test *inside* the MAX card**, not as an independent factor. Recommendation: build MAX first (it's the cleaner, better-pedigreed construction); test circuit-hit-frequency only as an alternative operationalisation and keep whichever has the higher clean t — never both.

---

## 6 — SEBI SCORES investor-complaint counts

### (a) Data recipe
- **Source (free):** **not the SCORES portal directly** (no company-wise bulk download / clean API). The usable data is the **LODR Reg 13(3) quarterly Investor-Grievance filing**, published company-wise by the exchanges: NSE `nseindia.com/companies-listing/corporate-filings-investor-complaints` (XBRL) and the BSE equivalent — each listed company files complaints **received / resolved / pending** per quarter. SEBI's SCORES monthly bulletin gives aggregate (not clean per-company) counts.
- **History depth:** XBRL Reg-13(3) filings run from ~2016 (regime start); NSE/BSE archive them. Backfillable several years.
- **Update cadence:** **quarterly** (within 21 days of quarter-end, LODR).
- **Survivorship/delisted:** listed-company filings only; delisted names drop out. For a slow governance signal this is acceptable.
- **PIT-safety:** the filing date (≤21d post-quarter) is PIT-safe; treat with the shareholding-style 21-day lag.
- **In-house status:** **ABSENT.**
- **Harvester build effort:** **MED** — XBRL parsing of the exchange investor-complaint filings. **NEEDS LIVE PROBE (single-threaded)** to confirm the XBRL schema + bulk-list endpoint.

### (b) Build-candidate card
- **Evidence class:** **UNVERIFIED for returns.** No study linking SCORES/complaint counts to cross-sectional stock returns was found (searched). The platform literature is operational only. The return hypothesis below is **untested prior**, not evidence.
- **Economic story (governance micro-signal):** a rising complaint count could proxy operational/governance stress (delayed transfers, dividend/refund failures, disclosure lapses) ahead of harder red flags. Sits in the governance family that produced `governance_resignation`.
- **Persistence argument:** **weak.** Counts are (i) **quarterly and low-variance**, (ii) **near-zero for the large/mid names** that dominate the book (complaints cluster in a handful of distressed micro-caps), (iii) heavily **confounded by size** (more shareholders → more complaints mechanically). The signal is sparse, noisy, and size-contaminated.
- **Expected sign:** negative (more complaints → worse governance → lower returns), *if it exists at all*.
- **Expected net-of-cost alpha:** **~0, likely unmeasurable** — too sparse and low-variance to clear the ADR-0043 bar; a null would be inconclusive (like the credit-rating headline case).
- **Orthogonality:** **low** — same governance family as `governance_resignation` (already wired MID −0.14) and forensic penalties; likely redundant with the stronger resignation signal.
- **Build effort:** **MED** (XBRL) for **~zero expected value** — the worst effort/reward ratio of the six.

---

## 7 — Ranked shortlist

Ranked by honest expected value = (evidence strength × PIT-cleanliness × orthogonality × persistence) ÷ effort, with the guardrail-3 hypothesis budget in mind.

| Rank | Factor | Verdict | Why |
|---|---|---|---|
| **1** | **Index inclusion/exclusion** | **BUILD** (WS4 event-study) | Strongest India lit + cleanest announce/effective PIT dates + **fully orthogonal flow factor** (nothing flow-shaped wired). Data absent but harvester is LOW-MED. Alpha decaying → concentrate on Midcap/Smallcap indices. |
| **2** | **IPO / anchor lock-up expiry** | **BUILD** (WS4 event-study) | **Best PIT purity of all six** — a scheduled known-date supply shock, expiry dates fixed at listing. Orthogonal (supply/float). LOW-effort chittorgarh scrape. Edge concentrated in SME/smallcap where arb is thin (the fund's habitat). |
| **3** | **ASM/GSM surveillance additions** | **BUILD / ACCUMULATE** | Data *already flowing* (surveillance_flags) + structural forced-deleveraging story + India empirical support (Inamdar-Chari). Constraint is calendar: forward-accumulate 12mo, left-censored today. Check ρ vs delivery_anomaly_z before sizing. |
| **4** | **Circuit-hit frequency** | **BUILD ONLY AS A VARIANT OF MAX** | Strong lit + derivable in-house, **but ≈ the MAX/lottery card** — same economic effect. Build MAX (report card #4) first; test circuit-hit as an alternative operationalisation and keep the higher-t one. Never spend two hypotheses on one premium. |
| **5** | **F&O ban-list entries** | **PARK** | Ambiguous sign (needs OI-direction conditioning), thin evidence, overlaps the already-benched F&O-positioning family. Low expected value; capacity-limited to the most-arbitraged tier. |
| **6** | **SEBI SCORES complaints** | **DO NOT BUILD** | No return evidence anywhere; quarterly, low-variance, size-confounded, near-zero for the book's mid/large names, redundant with `governance_resignation`. MED effort for ~zero expected value — worst effort/reward of the six. Revisit only if the WS5 LLM-extraction factory makes XBRL parsing free as a by-product. |

### Top-2 flagged shovel-ready
The mission asks for the two "data-in-house + strong story" builds. **Honest caveat first:** the *strongest-story* pair (index #1, lock-up #2) have **absent data** (each a low-effort harvester away), while the *data-in-house* pair have weaker or overlapping stories. There is **no clean intersection** of "data fully in-house AND strong independent story" among the six — that is the finding, not an oversight.

Given the constraint as written, the two genuinely *buildable-now on in-house data* are:
- **⭐ ASM/GSM surveillance additions (#3)** — data already in `surveillance_flags`, structural story, India empirical support. Shovel-ready to *start accumulating and coding the Pattern-2 feature today*; honest IC test is 12 months out.
- **⭐ Circuit-hit frequency (#5-data / #4-rank)** — fully derivable from in-house `stock_prices` with zero new harvest, strongest pedigree of the in-house pair — **but gated behind the MAX card** to avoid double-counting.

**The higher expected-value builds (index, lock-up) are the actual recommendation** and are only a small single-threaded scrape away from shovel-ready; do not let "data in-house" alone decide priority.

### Explicitly do NOT build
- **SCORES complaints (#6)** — for the reasons above; a MED-effort XBRL parse for a signal that cannot clear the bar and duplicates a wired governance factor.
- **F&O ban as a standalone factor (#5)** — park until/unless an OI-direction-conditioned version is motivated by a real story; the unconditioned version has an ambiguous sign and lives in the benched F&O family.
- **Circuit-hit *and* MAX together** — pick one operationalisation; building both burns two hypotheses on one premium (guardrail-3 violation).

---

## What I could not verify

- **ASM/GSM return drift (sign & magnitude).** The cited India study (Inamdar-Chari 2023) documents *liquidity down, volatility down, prices stabilise* — it does **not** publish a clean post-inclusion cross-sectional return premium. My "expected negative drift" is a **structural hypothesis, only partially supported** — the return-factor claim is unverified until we run it on our own panel. Do not present it as established.
- **F&O-ban return sign.** No India academic return study located; the sign is genuinely ambiguous without OI-direction decomposition. Unverified.
- **Lock-up expiry magnitude in India.** The ~1–3% negative-drift number is a **US import** (Field-Hanley, Ofek-Richardson) — *transfer risk*. Bubna-Prabhala establishes the anchor institution in India but not the expiry-drift magnitude. Unverified for India.
- **Index-effect decay rate.** The literature says "diminished post-2010" but I did not obtain a current (2020+) magnitude — the alpha may be smaller than the 2000-2018 studies imply. Assume decayed; verify on recent events.
- **SCORES company-wise data mechanics.** I confirmed the LODR Reg-13(3) exchange filings *exist* (NSE corporate-filings-investor-complaints page) but did **not** probe the XBRL schema, bulk-download availability, or history depth. **NEEDS LIVE PROBE (single-threaded).**
- **Circuit-band exactness.** The derived circuit-hit from `stock_prices` is approximate (we don't store the per-stock daily band); the exact NSE "Daily review of Price Bands" file was not probed for archive depth. **NEEDS LIVE PROBE (single-threaded).**
- **F&O-ban MWPL denominators** and **niftyindices constituent/circular endpoints** and **chittorgarh table structure** — all documented from public description + memory, none probed. **NEEDS LIVE PROBE (single-threaded)** before any harvester build.
- **Left-censoring of surveillance_flags** — I verified the table starts 2026-05-03 but did not attempt to establish true add-dates for names already flagged on day one; those are unknowable from free data.

**Sources (web):** Inamdar & Chari 2023, *Liquidity Impact of Novel Market Surveillance Measures* (journals.sagepub.com/doi/abs/10.1177/23197145231153923; stern.nyu.edu working paper); NSE ASM/GSM report pages; *Lottery factor and stock returns: Evidence from India* (sciencedirect.com/science/article/pii/S2214845024000267); *The MAX effect: lottery stocks with price limits* (sciencedirect.com/science/article/abs/pii/S1386418118300247); Nifty index-reorganization event studies (researchgate 397750550; sciencedirect S1042444X20300049); Bubna & Prabhala, *Anchor Investors in IPOs* (w4.stern.nyu.edu); chittorgarh anchor lock-in end-dates report; NSE daily price-bands report + corporate-filings investor-complaints pages; SEBI SCORES portal.
