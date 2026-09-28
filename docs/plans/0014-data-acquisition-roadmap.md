# Plan 0014 — Data-Acquisition Roadmap (free-first, paid fork costed separately)

**Status:** active · **Written:** 2026-07-11 (from the "what data are we missing?" board reassessment)
**Parent:** [Plan 0011](0011-roadmap-to-90.md) — this is the DATA-LAYER view cutting across its
consumer workstreams (WS2 factors, WS3 compounder, WS5 LLM extraction). **Evidence:** the
2026-07-11 reassessment (plan 0011 impl. notes) confirmed the free-data factor ceiling
empirically — 4 new candidates all failed BY-FDR. The lever is no longer "more free factors";
it's **new data**. This plan ranks what to acquire.

## The core finding this plan acts on

Grounded DB inventory (2026-07-11): `stock_prices` starts **2020-01**, current-names only;
`historical_universe` = 1,921 sids across **9 snapshots** (membership, no prices for dead names);
`analyst_consensus_snapshots` = **3 dates since 2026-05**; no shareholding-pattern table;
`mf_holdings` = 3 months. Fundamentals are deep (`quarterly_income` 2012+, `annual_balance_sheet`
2015+) and the BSE event stream is deep (2018+, 2.5M rows) — those are NOT the gaps. **The gaps
are: survivorship-free history (partly permanent), PIT estimates (permanent-free / paid), and
ownership-flow + PDF-locked text we already sit on but haven't harvested.**

## Ranked acquisition queue — score = (value × confidence) ÷ effort

| # | Data | Unlocks | Free? | Effort | Confidence | Prereq |
|---|---|---|---|---|---|---|
| 1 | **Shareholding-pattern flow** (FII/DII/MF/retail split + retail shareholder counts, quarterly) | ownership-flow family + cloning (Engine 2); our PROVEN disclosure territory | FREE | Med | High | 🔬 recipe |
| 2 | **PDF text extraction** (credit-rating rationale, SAST pledge detail, RPT, promoter remuneration) | governance/forensic factors + Engine-2 owner-operator gates; data already in-house | FREE | Med-High | Med | 🔬 accuracy pilot |
| 3 | **Survivorship price backfill** (bhavcopy → delisted names, to ~2023 floor) | honest t-stats across ALL backtests; gate on Engine-2 cohort validation | FREE | High | High-but-capped | scoping |
| 4 | **Real-activity nowcasts** (GST e-way bills, power, rail freight, VAHAN regs) | orthogonal macro/demand factors; plans 0003/0004 | FREE | Med | Med (India replication?) | 🔬 recipe |
| 5 | **mf_holdings depth** (accumulate + one-time historical scrape if available) | MF-accumulation factor (audit gem) | FREE | Low | Med | none (or 🔬 scrape probe) |
| 6 | **PIT analyst estimates** (consensus EPS, revisions, dispersion — history) | the entire estimates/revisions/surprise family — currently CLOSED | **PAID** | Med | High-value | 🔬 vendor/cost research |
| 7 | Intraday / tick / order-book; stock-level FII flow; borrow/short-interest | deepen microstructure (best family); short-side | **PAID** | High | Med | deferred |

---

## FREE-FIRST TRACK (no money; the honest near-term work)

### D1 — Shareholding-pattern flow harvester (queue #1; the best free unlock)

**OBJECTIVE:** Capture quarterly FII/DII/MF/promoter/public + **retail shareholder counts** per
sid as a survivorship-complete time series (new table `shareholding_pattern`).

**WHY it's #1:** it's the same ownership/disclosure family that produced `delivery_anomaly_z`
and the pledge factors (our only BY-FDR-grade edges) — not a US import. Retail shareholder-count
growth is a uniquely-Indian crowding/contrarian signal. Feeds Engine-2 cloning (superinvestor/FII
accumulation) too. Free from BSE/NSE quarterly filings, back to ~2001 in principle.

**PREREQ 🔬 (plan 0011 WS2.4):** data-recipe research — exact BSE/NSE endpoint/file, format,
history depth, delisted coverage, PIT-safety of the filing date. **REUSE FIRST:** memory
`historical_data_sources`, `nselib_apis` (FII positioning), `bse_announcements_event_stream`
(SHP annexures ride the same disclosure stream), `docs/reference/data-playbook.md`.

**TEST (done when):** `shareholding_pattern` table populated for ≥1,500 sids × ≥8 quarters;
a smoke factor (`fii_holding_qoq_delta`) reconstructs a PIT column and backtests via
`backtest_pit` (verdict recorded, NOT auto-wired — ADR-0043 lens).

### D2 — PDF text-extraction factory (queue #2; WS5, LLM-native)

**OBJECTIVE:** Extract structured PIT fields from documents ALREADY in-house — credit-rating
rationale (recover the buried downgrade half; headline is upgrade-skewed 805:88), SAST pledge
detail, related-party-transaction intensity, promoter remuneration ratio, auditor identity.

**WHY:** no new source — just parsing text we have. Feeds forensic/governance factors AND the
Engine-2 owner-operator gates (charter 0002 flagged RPT + remuneration as "needs extraction").

**PREREQ 🔬 (plan 0011 WS5.1):** accuracy pilot — 50 companies, hand-labeled, **≥90% field-level
accuracy** before any scale-up; a **cost ledger** (closes the audit's "no LLM spend" gap); Batch
API + content-dedup (audit Eff-F2). **REUSE FIRST:** memory `nlp_transcript_factors_dont_validate`
(the look-ahead-safe `available_date` transcript infra + 15.5K-doc corpus is the backbone — the
lexicon factors failed, the infra survived), `bse_event_factors_governance`. **HYGIENE RULE:**
extracted NUMBERS go ONLY to structured fields, never to narrative (CLAUDE.md LLM rule).

**TEST:** pilot hits ≥90% on the hand-labeled set → then one extracted field (e.g. RPT intensity)
reconstructs a PIT column + backtests. Below 90%: fix prompts/schema, do NOT scale.

### D3 — Survivorship price backfill (queue #3; = plan 0011 WS2.8, SUPERVISED)

**OBJECTIVE:** Backfill prices for delisted/dead names into the panel so backtests stop being
survivors-only. **Honest scope caveat:** bhavcopy reaches ~**2023-04** for stock-level; pre-2023
delisted prices are largely GONE from free sources → the honest deep panel floors ~2023. Do NOT
promise pre-2023 survivorship correction.

**WHY:** foundational — it de-biases EVERY t-stat (worst-affected: distress-loading factors) and
is the gate on Engine-2's cohort validation (charter 0002 §5). Not a table-swap (A3 finding:
`historical_universe` is 9 membership snapshots, no prices).

**SUPERVISED — NOT for unsupervised Sonnet** (it rewrites `daily_snapshots_pit`, the panel every
backtest reads; a half-rewritten panel corrupts concurrent work). Sequence as a coordinated
re-baseline like ADR 0047, verified vs pre-snapshot CSVs. **REUSE FIRST:** memory
`survivorship_universe_via_bhavcopy` (bhavcopy_with_delivery recipe, delisted = set-diff), the
ADR-0047 re-baseline machinery.

**TEST:** re-run wired-factor backtests on the intersected panel; document per-factor t deltas +
dead-name exposure (like rebaseline-2026-07-05). Report which factors move most (the honest ones).

### D4 — Real-activity nowcasts (queue #4; plans 0003/0004)

**OBJECTIVE:** Sector-mapped monthly demand/activity series: GST e-way bills, POSOCO power demand,
rail freight, VAHAN vehicle registrations. Orthogonal to price/fundamental factors.

**PREREQ 🔬:** recipe research per source (free endpoint, cadence, sector mapping, PIT-safety) —
revives **plan 0003 (market-share momentum)** + **plan 0004 (consumer-demand pulse)**, both
specced never built. **REUSE FIRST:** those two plan docs, `historical_data_sources`.
**TEST:** ≥2 series harvested + sector-mapped; a nowcast factor backtests (verdict recorded).

### D5 — mf_holdings depth (queue #5; low effort)

**OBJECTIVE:** Let `mf_holdings` accumulate (currently 3 months) and probe for a one-time
historical scrape; when ≥6-8 quarters exist, build the MF-accumulation delta factor.
**PREREQ:** 🔬 scrape-availability probe (single-threaded). **TEST:** factor backtests once depth allows.

---

## PAID FORK (the money decision — costed separately, Amit's call)

**STANDING RULE for every paid item below — free route first:** before costing any vendor, run
the **STEP-0 OSS/GitHub survey** (detailed in P1) — a community library on a free/unofficial public
endpoint may already supply it, as it does for most of our current stack. Two guardrails apply
every time: (a) **PIT integrity** — live-only scrapers don't backfill history, so they're the
"collect-forward" path, not a shortcut; (b) **ToS line** — public/unofficial JSON endpoints are
fine (what we already use); circumventing auth, using a paid login we don't hold, or redistributing
someone's paid credentials is not — if that's the only way, buy the legit feed instead.

### P1 — PIT analyst estimates (queue #6; the single highest ceiling-break potential)

**THE STRATEGIC POINT:** this is the one missing data *type* most likely to open a durable NEW
alpha family, because the entire analyst-estimates literature (revisions, surprise, dispersion)
is currently CLOSED to this fund — `analyst_consensus_snapshots` has 3 dates. Free sources don't
provide PIT estimate history in India; the only paths are **buy it** or **collect forward from
2026-05** (usable ~2028).

**PREREQ 🔬 — STEP 0, do this FIRST (free route before paid):** survey the open-source / GitHub
ecosystem for libraries that pull the same estimates data via **free public or unofficial
endpoints** — the fund already runs on exactly this class of tool (nselib, jugaad-data, mfapi,
the Screener-Premium scrape pattern). **REUSE FIRST:** memory `oss_quant_toolbox` (curated GitHub
libs mapped to gaps) + `paid_data_sources` (Screener scrape recipe) + `historical_data_sources`.
Check specifically: nsepython / jugaad-data / bharat-sm-data / tickerdata-style repos, Screener.in
consensus fields, Trendlyne/MoneyControl estimate endpoints, Tijori.
**Two hard caveats that usually make the free route insufficient here — state the verdict against both:**
1. **PIT integrity is the whole game.** A scraper that returns *today's* estimates does NOT solve
   the gap — the missing thing is **historical point-in-time** estimates (what consensus WAS on
   date T). Live-only scrapers give you a forward-collectable feed (same as our own 2026-05 snapshot
   start), not backfillable history. If a repo only serves current values → it's the "collect
   forward, usable ~2028" path, not a shortcut. (This is exactly the `forecast_history` trap —
   a live value masquerading as history; see `forecast_history_price_contaminated`.)
2. **ToS / legality — stay on the right side of the line the fund already respects:** public and
   unofficial endpoints that return openly-served JSON (what nselib/jugaad already use) are in;
   anything requiring circumventing authentication, a paid login we don't hold, or redistributing
   someone else's paid API key/credentials is OUT — do not go there. If a free repo only works by
   crossing that line, treat the data as PAID (buy the legit feed) rather than use it.

**THEN, only if STEP 0 can't supply honest PIT history:** vendor/cost research — who sells PIT
Indian consensus-estimate history (Refinitiv/LSEG, Bloomberg, FactSet, local: Ace Equity,
Capitaline), depth, PIT-integrity, and price vs the ₹5K/mo `paid_data_sources` budget.
**Frame the decision honestly:** does the expected new-family
alpha (single-digit, uncertain, India-replication-risky) justify the cost — or is "keep collecting
forward, revisit 2028" the disciplined answer? Do NOT buy on hope; this plan's job is to cost it,
not to pre-commit. **REUSE FIRST:** memory `paid_data_sources`, `pt_source_landscape_2026_05_23`
(confirmed-dead free PT sources — don't re-probe).

### P2 — Intraday / alt-data (queue #7) — DEFERRED

Intraday/tick/order-book (deepens the microstructure family), stock-level FII flow, borrow/short
interest, alt-data (web/app/jobs/card-spend). Higher cost, lower confidence. Revisit only after
the free track lands and P1 is decided.

---

## Confirmed-PERMANENT gaps — do NOT chase (bank the knowledge, don't spend on it)

- **Pre-2023 delisted prices** — gone from free sources; the survivorship fix floors ~2023.
- **Pre-2026 PIT estimates** — uncollectable retroactively; only forward or paid.
- Confirmed-dead free PT sources (Finnhub/Tijori/MoneyControl/forecast_history) — memory
  `pt_source_landscape_2026_05_23` + `forecast_history_price_contaminated`. Do not re-probe.

## Sequencing

- **Now → Aug:** 🔬 recipe research for D1 (SHP) + D4 nowcasts; D2 accuracy pilot; scope D3.
  Cost-research P1 in parallel (research only, no purchase).
- **Sep → Nov:** build D1 harvester + first flow factor; D2 scale-up if pilot passes; D3
  supervised backfill; D4 first nowcast factor. **P1 decision made** (buy / wait, with numbers).
- **Dec+:** D5 when depth allows; P2 only if the free track + P1 justify it.

## Done when

1. `shareholding_pattern` live + ≥1 flow factor backtested (verdict recorded).
2. LLM-extraction pilot passed (≥90%) + ≥1 extracted-text factor backtested; cost ledger exists.
3. Survivorship-intersected panel live (to the ~2023 floor) + wired factors re-baselined honestly.
4. The P1 paid-estimates decision is MADE with real cost numbers — buy or documented-wait, not drift.

## Implementation notes

_(append as work proceeds)_

- **2026-09-28 — source-gap sweep ([research 0005](../research/0005-source-gap-sweep.md)).** Corrections to this plan:
  - **D3's "~2023 floor" and the "Pre-2023 delisted prices — gone" permanent gap are WRONG.** The legacy NSE CM bhavcopy (`…/content/historical/EQUITIES/{YYYY}/{MMM}/cm…bhav.csv.zip`) carries every traded symbol, delisted ones included, back to the 1990s. Verified: `tools/build_historical_universe.py::_old_bhav` already reads it, and its 2018-04-02 snapshot has 651 non-universe symbols (FRETAIL, RELCAPITAL…). Adjustment factor = `PREVCLOSE(t)/CLOSE(t-1)`; renames via `symbolchange.csv`.
  - D1: retail shareholder counts, named holders and FPI names come from the exchange shareholding XBRL (BSE `Corp_Shareholding_ng`, NSE `corporate-share-holdings-master`), PIT via broadcast time.
  - P1 stays a real fork: free PIT revision history before 2026 = no. Yahoo `earningsTrend` (90-day lookback per snapshot) shortens forward collection to about a quarter.
  - Intraday (P2 / plan 0002 §3.1c) is no longer paid-only: Fyers 1-min from 2017-07 on a free account; Kite reportedly ₹500/mo with history.
