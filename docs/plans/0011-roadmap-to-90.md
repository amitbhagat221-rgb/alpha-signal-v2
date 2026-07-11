# Plan 0011 — Roadmap to a 90/100 Shop

**Status:** active · **Written:** 2026-07-06 (from the 2026-07-05/06 honest-return audit + holistic strategy session)
**Source evidence:** [return-prediction-2026-07-05-report.md](../return-prediction-2026-07-05-report.md) · [audit-2026-07-04-report.md](../audit-2026-07-04-report.md) · ADRs 0043/0045/0047/0049/0050
**Companion tool:** [tools/expected_return.py](../../tools/expected_return.py) (prediction log = the plan's own scoreboard)

## Why this plan exists

The 2026-07-05 audit rated the shop ~60/100: research process 82, portfolio execution 45,
return-engine breadth 35. The gap between process and product is unrealized inventory — the fund
has ONE return engine (monthly cross-sectional factor rank) running at the wrong cadence, with
capital allocated against its own evidence. This plan closes the gap on three fronts:
**fix execution** (worth more than all current alpha combined), **widen the alpha base**
(India-structural factors nobody imports), and **build the two missing engines**
(compounder/owner-operator sleeve; special-situations sleeve).

**Target: 90/100 by 2027-04, verified by re-running the audit prompt quarterly.**

| Dimension | Now | 2026-10 | 2027-01 | 2027-04 target |
|---|---|---|---|---|
| Research process & discipline | 82 | 85 | 88 | 90 |
| Data moat | 75 | 78 | 82 | 85 |
| Infrastructure & observability | 70 | 78 | 82 | 85 |
| Validated alpha | 55 | 58 | 64 | 70 |
| Portfolio construction & execution | 45 | 70 | 80 | 85 |
| Return-engine breadth | 35 | 45 | 62 | 75 |
| Operating model | 65 | 72 | 82 | 88 |
| **Overall (weighted)** | **60** | **~72** | **~82** | **~90** |

## DECIDED 2026-07-11 (ADR 0051 — do not re-litigate)

Amit pre-authorized all twelve strategic decisions (D1–D12) to remove the sequential human-gate
bottlenecks. Full record + acceptance bars: **[ADR 0051](../decisions/0051-roadmap-to-90-decisions-d1-d12.md)**.
Net effect on this plan: every workstream is now **evidence-gated, not decision-gated** — when a
task's pre-committed bar is met, execution proceeds without a second approval round-trip.
- WS1.1 cadence: auto-adopt the sweep winner meeting the ≤1.5%/day + net-within-4pp + corr≥0.90 bar (D1).
- WS1.2 tier budgets: **SMALL 45 / MID 30 / LARGE 25, LARGE passive ballast** — adopt on replay confirmation (D2).
- WS1.4 conviction sizing: adopt iff study A1 localization t≥1.5 (D3).
- WS2.1 wirings pre-authorized with guards (D4); rebaseline review closed with a `factor_decay` sign-flip kill rule (D5).
- WS3/WS4 engines greenlit — 25%/15% paper shares at launch, ≥6mo paper first (D6/D7).
- WS6 agents, WS7.2 regime (bar: −10pp DD for ≤2pp CAGR), WS7.3 options — all greenlit on research completion (D8/D9/D10).
- The 4 deep-research dives run back-to-back starting 2026-07-11 (D12); guardrails reaffirmed (D11).

## Non-negotiable guardrails (carry over; violating any is an automatic plan failure)

1. **Never reverse-engineer to a target return.** 25% is an aspiration, not a model input.
   Every return claim decomposes into beta/alpha/cost (use `tools/expected_return.py`).
2. **ADR-0043 lens on every promotion**: |t|≥2.5 necessary-not-sufficient, BY-FDR headline,
   sign must match economic prior, n≥20, dead ends stay dead (SUE-PEAD, NLP-lexicon,
   credit_beta, forecast_history PT).
3. **Hypothesis budget: ≤10 new backtested (signal,tier) hypotheses per month**, each with a
   build-candidate card (evidence class + causal story) BEFORE testing. Protects the
   multiple-testing budget that makes our t-stats mean anything.
4. **Every sleeve stays ADVISORY/paper until it has ≥6 months of tracked, net-of-cost,
   net-of-tax paper history.**
5. Data ops rules unchanged (one harvester at a time, 2s delays, smoke-test-3, PIT helpers
   ship with factors).

---

## WS1 — Execution layer (Q3 2026, first ~3 weeks) → Portfolio 45→70, E[1Y] −10%→+11%

The measured facts: banded book churns 6.2%/day one-way = −24.5%/yr cost drag vs +2.6%/yr
gross alpha. Nothing else in this plan matters until this is fixed.

- [ ] **1.1 Cadence fix** — EMA-smooth `final_score` (screener-touching, flagged in HANDOFF) +
  widen exit/drift bands until one-way turnover ≤1.5%/day (~ monthly effective).
  **Test (done when):** `tools/rebalance_sim.py` shows ≤1.5%/day AND net_ann within 4pp of
  gross_ann AND daily-return corr vs unsmoothed book ≥0.90 (we didn't smooth away the signal).
  PREREQ: none — parameters exist, this is tuning + one screener change.
- [ ] **1.2 Evidence-weighted tier budgets + LARGE passive ballast** — capital ∝ validated edge.
  LARGE becomes a near-static liquid basket (zero factor churn on ~1/3 of the book); active
  risk concentrates in SMALL (walk-forward-validated) and MID. Straw-man: 45/30/25 S/M/L.
  **Test:** replay tier-budget variants through `rebalance_sim`/`portfolio_nav`; adopt the one
  maximizing net return at ≤1.2× current book vol. File an ADR (supersedes HRP tier output).
  PREREQ: decision only — evidence already in the audit (Portfolio-F4).
- [x] **1.3 Tax model** — add STCG(20%)/LTCG(12.5%)/STT to the cost layer, per-sleeve holding-
  period aware; surface in `expected_return.py` and `rebalance_sim`. India-reality: monthly
  churn pays ~8pp more tax on gains than 1yr+ holds — this differential is a standing argument
  for Engines 2/3. **Test:** expected_return decomposition gains a tax line; sim reports
  net-net. PREREQ: none (rates are statutory).
  **Done 2026-07-11 (plan 0012 B1)** — `expected_return.py` tax line shipped. Finding: neither
  operating mode reaches LTCG under current turnover assumptions — see implementation notes.
  `rebalance_sim` net-net (with tax) NOT added — out of B1's scope as specified.
- [ ] **1.4 Conviction sizing within tier** — replace flat 5-per-tier with score-proportional
  weights (caps: name ≤12%, echoing existing caps).
  PREREQ: 🔬 **mini-study first** — does rank IC localize in the top ranks? (decile-1 vs
  decile-2 spread from `pick_outcomes`/PIT panel). If no localization, skip — flat weights are
  honest.
- [x] **1.5 Prediction discipline** — monthly cron: `python -m tools.expected_return` (logs to
  `data/expected_return_predictions.jsonl`); quarterly: score past predictions vs realized
  `portfolio_nav`. **Done when:** first scored quarter exists.
  **Cron shipped 2026-07-11 (plan 0012 B3)** — first prediction logged by hand-run to verify.
  "First scored quarter" test criterion still pending (needs ~3 months of cron history, next
  natural check ~2026-10).

## WS2 — Factor book: widen the validated base (Q3–Q4 2026) → Alpha 55→64

- [ ] **2.1 Scope-B wiring** (already validated, needs producers in `_load_signals`):
  `eps_revision_yoy` (SMALL t=2.78) + `value_composite` (SMALL t=3.32; **test swap-vs-stack**
  against book_to_price per ADR-0049 rule 4 before sizing). PREREQ: none — ADR-0050 pattern.
- [ ] **2.2 Weekly-cadence backtest panel** — one infra build unlocks the dormant fast-factor
  family (st_reversal_21d retest, F&O positioning set, delivery-fast variants). **Test:** panel
  reproduces monthly t-stats at monthly anchors before trusting weekly ones.
  PREREQ: 🔬 **design decision** — weekly PIT anchor storage vs on-the-fly (storage cost vs
  reproducibility; write ADR).
- [ ] **2.3 `mf_holdings` accumulation factor** — MF quarter-over-quarter position deltas per
  sid (281K rows in-house, 90% sid-mapped, zero consumers — audit's "unused gem").
  **Test:** standard `backtest_pit` + card. PREREQ: none.
- [ ] **2.4 Shareholding-pattern (SHP) delta family** — FII Δ, DII Δ, promoter Δ, and ⭐
  retail shareholder-count growth (India uniquely discloses counts; crowding = contrarian
  prior). PREREQ: 🔬 **data-recipe research** — quarterly SHP source (BSE/NSE endpoint, format,
  history depth, delisted coverage) → add to data-playbook before harvester build.
- [ ] **2.5 India-structural event factors** (the family that produced delivery_anomaly_z):
  ⭐ ASM/GSM surveillance-list additions · F&O ban-list entries · index add/delete ·
  IPO/anchor lock-up expiries · circuit-hit frequency · SCORES complaint counts.
  PREREQ: 🔬 **one deep-research pass covering all six** — data recipes (free endpoints,
  history depth, PIT-safety of each date) + what literature exists on each in India. Output:
  build-candidate cards; only carded ones get built (guardrail 3).
- [x] **2.6 Residual momentum 12-1** + **2.7 MAX/lottery-avoidance** — cards already written in
  the 2026-07-05 report. PREREQ: none (prices in-house).
  **Done 2026-07-11 (plan 0012 C3/C4)** — both built, backtested (66/77 monthly anchors), NOT
  wired. `max_lottery_21d` SMALL t=-3.47 is the best result of the plan 0012 batch (promotion-
  review candidate); `residual_momentum_12_1` SMALL t=+2.84 correct sign, less robust. See
  implementation notes + docs/studies/new-factors-2026-07.md.
- [ ] **2.8 Survivorship fix in the backtest panel** (audit Data-F1) — intersect
  `historical_universe` into `reconstruct_pit` eval frames; report per-factor dead-name
  exposure. **This gates trust in every other WS2 number** — schedule early.
  **Test:** re-run wired-factor backtests; document t deltas like rebaseline-2026-07-05.

## WS3 — Engine 2: Compounder / owner-operator sleeve (Q4 2026) → Breadth 35→55

The Buffett/Pabrai engine: concentrated (5–8 names), multi-year holds, tax-advantaged,
quality + capital-allocation + cloning driven. Absorbs/supersedes the multibagger HOLDING
sleeve (ADR 0040) — explicit merge decision required.

- [ ] **3.0 Sleeve charter** — PREREQ: 🔬 **deep research FIRST, gates everything below**:
  (a) what Buffett/Pabrai/Greenblatt criteria are *measurable* from our data; (b) India
  replication evidence for quality/owner-operator premia (note: our own panel shows
  gross_profitability NEGATIVE — the charter must explain why compounder-quality ≠
  cross-sectional-quality-factor, i.e. holding-screen vs rank-factor, per ADR-0040's lesson);
  (c) entry discipline (valuation gate — "wonderful company, fair price" needs a number).
- [ ] **3.1 Capital-allocation score** — Buffett's $1-retained test (5y market-value-added per
  retained rupee), incremental ROIC (`roiic` — in FACTOR_LIBRARY, never tested), payout
  discipline, acquisition track record. Data in-house. **Test:** point-in-time screen on the
  survivorship-free universe (WS2.8 prereq!), cohort forward returns vs BSE500 TR.
- [ ] **3.2 Owner-operator score** — promoter holding level+trend, pledge=0 hard gate,
  related-party-transaction intensity + promoter remuneration ratio (needs WS5 extraction),
  royalty leakage. Extends our validated ownership/disclosure family.
- [ ] **3.3 Moat metrics** — ROIC persistence vs sector fade (Mauboussin), gross-margin
  stability through input cycles, **market-share momentum = revive plan 0003** (already
  specced, never built).
- [ ] **3.4 Cloning tracker** — superinvestor registry + quarterly >1% holder parsing + bulk/
  block-deal cross-reference. PREREQ: 🔬 **data-recipe research** — where >1% holder names
  live (SHP annexures), which investors to track, look-ahead safety of disclosure dates.
- [ ] **3.5 Sleeve construction + paper launch** — 5–8 names, quarterly review cadence,
  event-triggered entries only (valuation gate from 3.0), kill criteria per name, LTCG-aware
  exits. **Done when:** paper sleeve live with charter ADR + 6-month tracking begun
  (guardrail 4). **Success test at +12mo:** sleeve TWR vs BSE500 TR, net-of-tax.

## WS4 — Engine 3: Special-situations / event sleeve (Q4 2026 → Q1 2027) → Breadth 55→70

Greenblatt engine: episodic, capacity-limited, uncorrelated — the classic solo-operator edge.
Raw material already flows through `bse_announcements` + `corporate_actions`.

- [ ] **4.0** PREREQ: 🔬 **deep research FIRST** — India event-study evidence + mechanics for
  each situation type: demergers/spinoffs (strongest documented drift), buyback tender arb
  (acceptance-ratio math), open offers, delistings, rights issues (promoter participation
  signal), holdco NAV discounts. Output: one card per situation type with expected edge,
  capacity, and the *specific* PIT-safe date fields.
- [x] **4.1 Event calendar infra** — normalize the six situation types from the BSE stream
  into an `event_calendar` table (announce/record/ex dates). `INSERT OR IGNORE` append-only.
  **Done 2026-07-11 (plan 0013 A3), demerger+buyback subset only** — see implementation notes.
- [x] **4.2 `tools/event_study.py`** — event-time CAR framework (the monthly cross-sectional
  panel is the WRONG instrument for episodic trades; announcement_car proved the event-time
  approach works here). **Test:** reproduces announcement_car's result as a special case.
  **Done 2026-07-11 (plan 0013 A1)**, 20/20 exact reproduction of `compute_announcement_car()`.
- [ ] **4.3 Per-situation backtests** on 2018+ event history (survivorship-complete stream).
  Promotion bar: same ADR-0043 discipline, adapted to event counts (n≥30 events/type).
- [ ] **4.4 Paper sleeve** — 6 months tracked before any capital share (guardrail 4).

## WS5 — LLM-native research factory (parallel, Q3 2026 →) → Data moat 75→85

Our structural advantage as an AI-native shop; currently LLMs only write narrative.

- [ ] **5.1 Extraction factory pilot** — annual report + concall PDFs → structured PIT fields
  (guidance direction Δ, order-book mentions, RPT intensity, contingent-liability growth,
  auditor identity, promoter remuneration). Batch API, content-dedup, **cost ledger** (closes
  audit gap "no LLM spend ledger").
  PREREQ: 🔬 **accuracy pilot gates scale-up** — 50 companies, hand-label validation,
  acceptance ≥90% field-level accuracy; below that, fix prompts/schema before spending on 2,400.
  LLM-hygiene rule applies: extracted NUMBERS go only to structured fields, never narrative.
- [ ] **5.2 PDF-locked seams** — credit-rating rationale text (recovers the buried downgrade
  half — upgrade-skew 805:88 made headlines useless) + SAST pledge detail. The soil that grew
  delivery_anomaly_z. PREREQ: 5.1 pilot passes.
- [ ] **5.3 Ideation loop** — monthly LLM factor-ideation against FACTOR_LIBRARY + literature,
  forced through the card format, capped by guardrail 3's hypothesis budget.
  **Test of the loop itself:** track ideation-sourced vs human-sourced hypothesis hit-rates.

## WS6 — Agentic operating model (Q4 2026) → Operating model 65→85

Institutionalize the weekly rhythm so nothing goes 6-anchors-stale again. All agents are
read-only reporters; **weight/wiring changes stay human decisions** (ADR-0043 stance).

- [ ] **6.0** PREREQ: **agent charters ADR** — scope, tools, read-only boundaries, escalation
  format, human-approval gates. One page, written before any cron.
- [ ] **6.1 CRO agent (weekly cron)** — factor decay (`factor_decay`), exposure drift, regime
  state, realized turnover vs budget, alarm review, "what would falsify the robust core."
  Output: one email section in the existing health-report pattern.
- [ ] **6.2 CIO agent (monthly)** — promotion review: anchors accrued, bar crossings both ways,
  weight-change PROPOSALS with evidence (human approves). Kills registry staleness.
- [ ] **6.3 PM agent (weekly)** — book vs model divergence, pick post-mortems from
  `pick_outcomes`, cost/tax tracking vs plan.
- [ ] **6.4 Research-analyst agent** — one build-candidate card per week through the pipeline.
  **Done when:** all four running ≥4 weeks with zero silent failures (watchdog-covered).

## WS7 — Foundations & risk (ongoing) → Infra 70→85, Process 82→90

- [ ] **7.1 Registry hygiene** — resolve the 38 limbo signals (wire/library/retire each);
  scheduled monthly `backtest_pit` refresh (currently hand-run, 6 anchors behind at audit).
- [ ] **7.2 Regime overlay** — exposure scaling (not stock selection): trend + breadth + credit
  ensemble → invested fraction {1.0, 0.8, 0.6}. The only honest lever on bear-year outcomes.
  PREREQ: 🔬 **deep research** — regime-signal evidence for Indian equities, walk-forward
  design that avoids the multibagger-funnel regime trap (ADR 0039).
  **Test:** walk-forward on survivorship-free index history; acceptance = max-DD reduction
  ≥10pp with CAGR give-up ≤2pp. If it fails, publish the negative result and drop.
- [ ] **7.3 Options overlay on the LARGE ballast** — covered calls (+2-4pp carry target) once
  1.2 makes LARGE near-static; F&O/IV infra exists (ADR 0035).
  PREREQ: 🔬 **design research** — strike/tenor policy, assignment handling, margin; and
  1.2 shipped.
- [ ] **7.4 Quarterly re-audit** — re-run the audit prompt (fresh eyes each time) + re-score
  this plan's dimension table. The score trajectory IS the plan's test.

## 🔬 Deep-research queue (every PREREQ flag above, in one place)

No 🔬-flagged step gets built before its research output exists (a card, ADR, or pilot result).

**REUSE FIRST — standing rule:** substantial research is ALREADY DONE and banked in memory notes
+ `docs/reference/`. Every dive below MUST start by reading its mapped prior assets and only
research the *delta*; re-probing a confirmed dead end (forecast_history PT, Finnhub/Tijori/
MoneyControl PT sources, SUE-PEAD, NLP-lexicon factors, credit_beta un-bench) is a plan
violation. General-purpose assets that apply to nearly every dive:
[data-playbook.md](../reference/data-playbook.md) ·
[historical_data_sources](memory: master map of all confirmed-working free sources) ·
[paid-data-sources.md](../reference/paid-data-sources.md) (₹5K budget, if a recipe needs paid) ·
[oss-quant-toolbox.md](../reference/oss-quant-toolbox.md) (libs mapped to gaps) ·
[pit-data-sources-research.md](../reference/pit-data-sources-research.md).

Per-dive prior-asset map:

| # | Research item | START from these existing assets |
|---|---|---|
| 1 | Event-factor recipes (WS2.5) | memory `bse_announcements_event_stream` (endpoint recipe + 3 gotchas, 2018 depth), `bse_event_factors_governance` (which subcategories yield factors + full registration touchpoint list), `nselib_apis` (bulk deals, short selling, corporate actions) |
| 2 | Compounder charter (WS3.0) | [multibagger-research.md](../reference/multibagger-research.md), [Quantifying Indian Multibagger Stocks.md](../reference/Quantifying%20Indian%20Multibagger%20Stocks.md), [multibagger-data-requirements.md](../reference/multibagger-data-requirements.md), ADR 0039/0040 (regime + holding-vs-selection lessons), [sector_deep_research.md](../reference/sector_deep_research.md), DLM managerial-ability lens (2026-06-09) |
| 3 | Special-situations studies (WS4.0) | memory `bse_announcements_event_stream` + `survivorship_universe_via_bhavcopy` (corporate_actions backfilled to 2022-05, delisted coverage), `nselib_apis` |
| 4 | Regime overlay (WS7.2) | ADR 0039 (the regime-dominance finding IS the motivating evidence), ADR 0041 (macro ensemble already built for sector_tilt), regime_state/macro_score tables |
| 5 | SHP recipe (WS2.4) | memory `historical_data_sources` + data-playbook FIRST — check if SHP already mapped before probing |
| 6 | Cloning recipe (WS3.4) | `nselib_apis` (bulk/block deals date-range access), existing `bulk_deals` table + BSE scrip→sid crosswalk (2026-06-09) |
| 7 | LLM extraction pilot (WS5.1) | memory `nlp_transcript_factors_dont_validate` (the look-ahead-safe `available_date` transcript infra survives and is the pilot's backbone; 15.5K-doc corpus exists), classify_regulatory cost lessons (audit Eff-F2: dedup + Batch API) |
| 8 | Rank-IC localization (WS1.4) | in-house: `pick_outcomes`, `validate_rank_skill` (non-overlap correction), PIT panel |
| 9 | Weekly panel design (WS2.2) | `reconstruct_pit.py` architecture + memory `backtest_v1_validates` (the archive-reuse pattern that makes 10s re-tests possible) |
| 10 | Options overlay (WS7.3) | memory `iv_greeks_derivable_from_bhav` (full IV surface from stored settles), [kite-setup.md](../reference/kite-setup.md), oss-toolbox broker-API section |

Priority order:

| # | Research item | Gates | Type | Target |
|---|---|---|---|---|
| 1 | India-structural event-factor recipes (ASM/GSM, F&O ban, index add/delete, lockups, circuit hits, SCORES) — endpoints, history depth, PIT-safety, India literature | WS2.5 | deep research (one pass, 6 cards) | 2026-07 |
| 2 | Compounder sleeve charter — measurable Buffett/Pabrai criteria, India quality-premium evidence, valuation entry gate, holding-screen vs rank-factor distinction | WS3.0 → all of WS3 | deep research | 2026-08 |
| 3 | Special-situations event studies — demergers, buyback tender arb, open offers, delistings, rights, holdco discounts: India evidence + mechanics + PIT-safe dates | WS4.0 → all of WS4 | deep research (6 cards) | 2026-09 |
| 4 | Regime overlay — regime-signal evidence for Indian equities, walk-forward design avoiding the ADR-0039 regime trap | WS7.2 | deep research | 2026-09 |
| 5 | SHP data recipe — quarterly shareholding-pattern source, format, depth, delisted coverage | WS2.4 | data-recipe research | 2026-08 |
| 6 | Cloning data recipe — >1% holder disclosures, superinvestor registry, disclosure-date look-ahead safety | WS3.4 | data-recipe research | 2026-09 |
| 7 | LLM extraction accuracy pilot — 50 companies, hand-labeled, ≥90% field accuracy | WS5.1 scale-up, WS5.2, WS3.2 inputs | pilot | 2026-08 |
| 8 | Rank-IC localization mini-study — does edge concentrate in decile-1? | WS1.4 | mini-study (in-house data) | 2026-07 |
| 9 | Weekly PIT panel design — anchor storage vs on-the-fly | WS2.2 | design ADR | 2026-08 |
| 10 | Options overlay design — strike/tenor policy, assignment, margin | WS7.3 | design research | 2026-10 |

## Sequencing summary

- **Now → 2026-08 (Q3):** WS1 complete · WS2.1/2.3/2.8 · WS5.1 pilot · deep-research queue:
  WS2.5 events, WS2.4 SHP recipe.
- **2026-09 → 12 (Q4):** WS2 remainder · WS3 charter→paper launch · WS4 research+infra ·
  WS6 agents live · WS7.2 regime research.
- **2027-01 → 04 (Q1):** WS4 paper sleeve · WS7.3 options · engines accumulate track record ·
  two quarterly re-audits → 90 verdict.

## Done when

1. Quarterly audit re-run scores ≥88 weighted, two consecutive quarters.
2. Three engines live: factor book at ≤1.5%/day turnover; compounder + special-situations
   sleeves each with ≥6 months tracked paper history, net-of-cost, net-of-tax.
3. `expected_return_predictions.jsonl` holds ≥9 monthly predictions with the first
   prediction-vs-realized quarterly scoring done — the fund's stated E[1Y] is a *tracked
   model output*, not a hope.
4. Honest expected profile published in the cockpit: base-year ~market+3-5pp net; bull-year
   25%+ via beta+regime; bear-year protected by regime overlay — with the decomposition shown.

## Implementation notes

**2026-07-11 — Plan 0013 (Sonnet tranche 2) event-infra + demerger/buyback studies DONE, 6/6
tasks, 0 BLOCKED:**
- **A1 `tools/event_study.py`** — generalized `event_car`/`car_summary`/`drift_curve` over
  `signals/announcement_car.py`'s wired [-1,+1] CAR machinery. VERIFY: 20/20 exact
  reproduction of `compute_announcement_car()` at window (1,1).
- **A2 `tools/sid_crosswalk.py`** — built the scrip_cd→sid helper (`scrip_master` primary,
  `bse_announcements`-own-pairs fallback). **Finding: coverage lift is negligible** (2,203 vs
  2,202 raw-mapped sids) — `sources/scrip_master.py` already backfills
  `bse_announcements.sid` from the same map on every run, so the research-0003-cited ~53%
  mapping ceiling is NOT a freshness gap this helper can close; the binding constraint is
  scrip_cd's absent from BSE/`scrip_master` entirely.
- **A3 `event_calendar` table** — populated demerger (112 rows / 70 sids, 2018-02→2026-07;
  NOT "2020+" as the plan text assumed) + buyback (242 rows / 151 sids, 2018-03→2026-07)
  from in-house `bse_announcements`/`corporate_actions` only. Both well above the n≥30 bar.
  Landmine found + worked around: the DECIDED PK `(sid, event_type, announce_date)` can't
  dedupe buyback rows via SQLite alone (every buyback row has `announce_date=NULL`, and
  SQL treats NULL≠NULL in a UNIQUE index) — `tools/build_event_calendar.py` pre-filters
  against existing rows in Python before `INSERT OR IGNORE` so re-runs are still idempotent
  in practice (verified: 2nd run → 0/0 new rows).
- **B1 demerger parent-drift — NULL result.** No window clears mean>0 & t≥1.5 ([0,+5] t=1.21
  directionally positive; [0,+20]/[0,+60] flip negative). Does not reproduce research 0003's
  cited +2.64% parent CAAR — most likely explanation: day0 = announcement date, not the
  scheme's actual effective/listing date (NCLT approval is typically months-to-years later).
  [Study](../studies/demerger-drift-2026-07.md).
- **B2 buyback record-date price-move — NULL result, opposite-signed.** Every window
  negative; [-1,+1] is large AND highly significant (mean -3.58%, t=-12.2, hit-rate 14%) —
  a real, high-confidence finding, just not the hypothesized "run-up into record date."
  Reading: the record-date tender entitlement appears priced in ahead of time and stripped
  out at/after the record date itself, not paid out afterward. Arb-leg (retail
  reservation/acceptance-ratio economics) remains genuinely unmeasured — needs the PDF/LoF
  layer (§OUT). [Study](../studies/buyback-move-2026-07.md).
- **Net: WS4.1/4.2 infra now reusable for future event factors (index-rebalance, lock-up,
  open-offers, …) without rebuilding the CAR machinery.** WS4.3's demerger/buyback subset is
  answered — both null per G2, no capital, no sleeve (D7 human gate untouched). §OUT items
  (WS2.8 survivorship rewrite, index/lock-up scrapes, buyback PDF/LoF layer) remain
  supervised-session-only, unattempted.

**2026-07-11 — D12 deep-research dives ALL COMPLETE** (4 parallel agents; docs/research/0001-0004):
- **0001 events (WS2.5):** no clean "in-house data + strong story" intersection. BUILD = index
  rebalance + IPO/lock-up expiry (both need small scrapes, cleanest PIT dates, orthogonal).
  Circuit-hit ≈ the queued MAX factor (don't double-build). SCORES = DO NOT BUILD (no evidence).
  F&O-ban = park. `surveillance_flags` is forward-accumulate/left-censored — can't backtest now.
- **0002 compounder (WS3.0):** thesis DEFENSIBLE-but-UNPROVEN — quality as a left-tail GATE not a
  cross-sectional bet reconciles our negative quality-factor sign. Entry rule = PEG≤1 AND EY≥7%
  AND reverse-DCF growth≤ROIC×reinvest. ABSORB the multibagger sleeve. **Validation BLOCKED by
  WS2.8** (cohort study needs the survivorship fix).
- **0003 special-situations (WS4.0):** BUILD = demergers (India-native +2.64% parent CAAR, dates
  in-house, parent survives → NO survivorship hole) + buyback tender arb (structural retail edge,
  but capacity-capped ~₹2L/name → return-enhancer not book-mover). SKIP delistings/rights(wrong
  sign)/holdco(→Engine 2). Needs `tools/event_study.py` + a PDF/LoF parse layer + sid-mapping fix.
- **0004 regime (WS7.2):** honest prior LEANS FAIL the D9 bar (~30-40% pass) — whipsaw × STCG-20%
  on V-recoveries + thin bear sample. Zero-parameter ensemble (Nifty vs 12m-SMA + VIX + smallcap
  breadth); extend Nifty to 1999 for bear regimes. Build the sim, let the number decide — a clean
  cited negative closes "should we time the market?".

**Critical-path findings (fold into sequencing):**
1. **WS2.8 survivorship fix is now a HARD BLOCKER for Engine 2** (confirmed by both 0002 cohort
   validation and 0003 name-removing-event bias). Elevate from "schedule early" to "critical path."
2. **`tools/event_study.py` is the highest-leverage single build** — generalizing
   `announcement_car._car_one` unlocks demergers + buyback + index-rebalance + lock-up ALL at once
   (four top candidates share the event-time-CAR instrument). Build once, add each event thin.
3. **sid-mapping ~53% halves usable event n** — a shared infra fix that multiplies the whole
   event/special-situation program.
4. **Tax (B1) is load-bearing across the roadmap** — makes the compounder engine attractive
   (LTCG), most likely sinks the regime overlay (STCG whipsaw), shapes special-situation exits.

**2026-07-11 — Plan 0012 (Sonnet tranche) executed, 10/10 tasks, 0 BLOCKED:**
- **A1 rank-IC localization** — LOCALIZES in LARGE (pick_outcomes lens, bucket 1-5 vs 6-10
  t=1.78 ≥1.5); MID shows the OPPOSITE (t=-3.40 — bucket 1-5 underperforms 6-10, not just
  flat); SMALL flat. Per the plan's own verdict rule ("localizes iff t≥1.5 in ≥1 tier") this
  is evidence FOR prototyping WS1.4, not CLOSED-NO — but MID's negative result argues any
  conviction-sizing design should be tier-specific, not applied uniformly.
  [study](../studies/rank-localization-2026-07.md)
- **A2 registry limbo** — the audit's "38 limbo signals" figure is stale; only **2** remain
  today (`mom_12m_adj`/`mom_6m_adj`, both clean-panel DROP, orphaned when ADR 0049 dropped
  momentum from `SIGNAL_WEIGHTS` without a `FACTOR_LIBRARY` add). Recommend both →
  `FACTOR_LIBRARY`. [study](../studies/registry-limbo-2026-07.md)
- **A3 survivorship exposure — WORSE than WS2.8 assumed.** Dead-name count by symbol (sid
  doesn't exist for delisted names — verified 0 dead sids vs 1,381 dead symbols) = 1,381. But
  `historical_universe` itself has only **9 sparse (~annual) snapshot dates total, 2018-2026**
  — even the "true universe" reconstruction lacks the temporal density to backtest delisted
  names at the live panel's monthly/20d-forward cadence. **This changes WS2.8's shape**:
  fixing it needs a full daily-price backfill project for ~1,381 delisted symbols, not just
  pointing `reconstruct_pit.py` at `historical_universe` as the plan text assumes.
  [study](../studies/survivorship-exposure-2026-07.md)
- **B2 cadence sweep** — no cell in the 36-cell {exit-rank 8/10/12}x{drift-pp 2/3/4}x{EMA
  halflife None/3/5/10} grid clears the WS1.1 bar (≤1.5%/day, gap≤4pp, corr≥0.90 vs today's
  config). Best miss: rank_exit=12/EMA halflife=10 at ~4.5%/day (3x the target) — but net_ann
  +19-21% vs production's +2.0% (net Sharpe ~1.0-1.1 vs 0.11). EMA-smoothing the ranking score
  materially improves economics even where it misses the strict bar — worth a follow-up sweep
  with a wider/EMA-focused grid. [study](../studies/cadence-sweep-2026-07.md)
- **C1/C2 Scope-B wiring** — `eps_revision_yoy`/`value_composite` producers wired into
  `_load_signals` as computed/zero-weight (the infra half of WS2.1 is done). `value_composite`
  swap-vs-stack evidence delivered: SMALL ρ(composite, book_to_price)=0.71, clean t=3.32 vs
  b2p's 1.88. Neither factor's evidence is BY-FDR robust (p_BY 1.00 / 0.36) — the weight-
  wiring decision (WS2.1's actual point) remains open. [report](../studies/new-factors-2026-07.md)
- **C3/C4 momentum/lottery retest** — both built + backtested (66/77 monthly anchors,
  2020-02→2026-07). `max_lottery_21d` SMALL t=-3.47 (p_BY=0.22, correct NEGATIVE sign) is the
  strongest result and best promotion-review candidate of the WHOLE plan 0012 batch;
  `residual_momentum_12_1` SMALL t=+2.84 (p_BY=0.88, correct sign, all 3 tiers) is much
  further from robust. Neither wired; both in `FACTOR_LIBRARY`.
- **B1 tax model** — STCG/LTCG line added to `expected_return.py`. **Finding that revises
  point 4 above:** under the CURRENTLY-SHIPPED turnover assumptions, NEITHER operating mode
  (as-operated OR monthly-cadence) reaches the 1yr LTCG threshold — both classify STCG today.
  This holds even at WS1.1's own aspirational ≤1.5%/day target (~0.26yr implied hold). The
  "tax favors slower cadence" argument is directionally correct (STCG 20% > LTCG 12.5%, same
  gross base) but the FACTOR BOOK itself doesn't currently reach the LTCG regime at any
  turnover level explored here — the LTCG argument applies cleanly to the compounder engine
  (WS3, genuinely multi-year holds), not yet to WS1/WS2's active factor book.
- **B3 cron** — monthly `expected_return` snapshot installed (1st of month 05:00 UTC);
  first log line verified by hand (exit 0, JSONL 1→2 lines).

**2026-07-11 — BOARD REASSESSMENT after plans 0012+0013 (Fable, opus session).** Every lever
came back weaker than the roadmap's targets assumed — the fund's own discipline (multiple-testing
haircut, honest sims, null-reporting) is what surfaced it. Recalibration:

- **Cadence (WS1.1) — the ≤1.5%/day target is STRUCTURALLY UNREACHABLE.** All 36 sweep cells floor
  at ~4.47%/day (the signal turns over faster than that). The robust, bankable win is EMA-smoothing
  cuts turnover ~15-30% at corr≥0.95 (signal preserved). The large net_ann jumps (+2%→+20%) are
  NOT trustworthy — gross also jumps 30%→47%, which smoothing cannot cause → n=61 in-sample luck.
  → Adopt a moderate config (EMA halflife=10, rank_exit=10-12) for the COST benefit only, on paper,
  validate OOS before believing any return improvement. D1 auto-adopt does NOT fire (bar not met).
- **Factor-book widening (WS2, Alpha 55→64) — MUCH weaker than hoped.** All FOUR new/validated
  candidates FAIL BY-FDR: eps_revision_yoy p_BY=1.00 (likely false discovery), residual_momentum
  p_BY=0.88, max_lottery_21d p_BY=0.22 (best of batch, correct sign, academic — but still fails),
  value_composite p_BY=0.36. Per ADR-0043 a new factor must clear the haircut to wire → NONE do.
  Only defensible move: SWAP value_composite→book_to_price in SMALL (quality upgrade of an existing
  slot, t=3.32 vs 1.88, ρ=0.71 — not new weight). This empirically CONFIRMS the return-report's
  "signal-gen ceiling ~70-75 for free-data long-only" — four more failed candidates.
- **Engine 3 (WS4) — parked** (0013 nulls). **Engine 2 (WS3) — gated on WS2.8, which A3 revealed
  is a full PRICE-BACKFILL PROJECT** (historical_universe has only 9 sparse snapshots), not a
  table-swap. Both missing engines got materially harder.
- **WS1.4 conviction sizing — NO-GO for now** (A1: localizes only in LARGE t=1.78, the least-
  validated tier; MID opposite-signed). Revisit if localization appears in SMALL.

**Recalibrated read of the path to 90:** the evidence just proved 90 is NOT reachable by "wire more
free-data factors" — that ceiling is now empirically confirmed (~Validated-Alpha 60-65, not 70).
The three levers that remain real: (1) execution/cost (bankable, modest), (2) the WS2.8 price
backfill (fixes survivorship across ALL backtests — foundational correctness, and the gate on any
honest Engine-2 validation), (3) Engine 2 compounder (only remaining breadth lever with a story,
but unproven and backfill-gated). Honest near-term trajectory is ~63-66 by Oct (not 72). Reaching
the high 80s likely requires EITHER the engines working (unproven) OR paid data to break the
free-data alpha ceiling — a genuine strategic fork for Amit, not a sequencing detail.

_(append as work proceeds)_
