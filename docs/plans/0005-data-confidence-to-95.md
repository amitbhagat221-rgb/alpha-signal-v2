# Plan 0005 — Data confidence 75 → 95 (institutional-grade)

**Status**: proposed · 2026-05-24
**Goal**: take the system from "trust it for my own picks if I verify outliers manually" → "trust it blind for institutional capital deployment".
**Baseline today**: 75/100 (see HANDOFF 2026-05-24 confidence breakdown).
**Total estimated effort**: ~10-14 sessions across 6 phases. Each phase ships independently and moves the needle.

---

## Why this plan

Today's gaps that prevent blind trust:
- 14% of universe (339 SIDs) silently absent from `stock_prices`, 22% from `fundamentals_screener`, 59% from analyst attribution. The cockpit *surfaces* these as WARNs but doesn't *act* on them — a partial-data stock can still rank.
- No per-stock integrity validator. The HALC bug ("16.5% downside" while price was -8.5%) lived for 20 days. Class of bug: LLM narrative says one thing, structured field says another, no cross-check.
- Backtest is 36 months. Weekly-cadence factors have n≤4 for some tiers. Statistical claims are thin.
- News + regulatory feed dark 44 days. A whole sentiment stream is intermittently absent.
- No PIT replay — we cannot prove the system would have produced its claimed picks on a historical date.

Each phase below targets one or two of these directly. Confidence-delta is my honest estimate, not marketing.

---

## Phase A — Source-eligibility transparency (75 → 80)
**Effort**: 1-2 sessions. **Highest leverage / unit work.**

Today the cockpit shows "339 stocks missing from stock_prices" as a WARN. But these stocks are STILL in `daily_picks` and STILL ranked — they just rank on incomplete data. The right behaviour: **a stock the system cannot fully evaluate should be deliberately excluded with a reason, not silently downgraded.**

### Deliverables
1. New table `universe_eligibility` — PK (sid, signal) → status {ELIGIBLE, INELIGIBLE, COVERAGE_GAP, DATA_FORTHCOMING}.
2. New file `eligibility/registry.py` — each signal declares an `eligible_universe_sql` (mirror what we built for `cockpit_endpoint_audit`).
3. `tools/refresh_eligibility.py` — runs nightly, populates the table.
4. [scoring/screener.py] picks gate extended: a SID must be ELIGIBLE for ≥60% of the model's signals OR explicitly classified DATA_FORTHCOMING (don't penalise new IPOs).
5. Cockpit: new Health Center sub-section "Universe coverage" showing per-signal eligible/covered/gap counts.

### Done when
- Every signal has an `eligible_universe_sql`.
- `daily_picks` no longer ranks any SID that the system can't fully evaluate (or explicitly tags them as "limited-data review").
- The Live Issues Inbox shows the COVERAGE_GAP set as a discrete actionable item (count + drilldown to SID list), not a vague %.

---

## Phase B — Per-stock integrity validator (80 → 85)
**Effort**: 2 sessions. **Closes the HALC class of bug.**

For every stock in `daily_picks` top-N, run a battery of cross-source consistency assertions. Block promotion of any pick that fails.

### Deliverables
1. New file `validators/per_stock_integrity.py` with a suite of assertions:
   - `market_cap = shares_outstanding × close_price` (within 5%)
   - `consensus_signal IS NOT NULL` implies (`total_analysts > 0` OR `price_target IS NOT NULL`)
   - `pt_upside_pct` between (`(price_target - close) / close - 0.5%`, `+0.5%`) — catches HALC arithmetic
   - `forward_pe = close_price / forward_eps` (within 5%)
   - `dossier.narrative` does not contain any decimal that contradicts a structured field (extension of existing [output/dossier.py] validator to also cross-check structured fields, not just suppress numbers)
   - `f_score` between 0 and 9; `m_score < 0` for non-fraud; `z_score` consistent with debt ratios
2. Validator output: per-SID `integrity_status` {PASS, WARN, FAIL} + list of failed assertions.
3. [scoring/screener.py] top-N pick gate: FAIL → demoted to "review" bucket with reason; WARN → flagged in dossier.
4. Cockpit: new column `integrity` in daily_picks table; full per-SID failure list visible in stock_detail page.
5. Cockpit: new Health Center sub-section "Integrity violations" — flagged picks of the day with the specific assertions failed.

### Done when
- Every top-300 daily_pick has an `integrity_status`.
- A reproducible HALC-class injection (deliberately corrupt one EPS) is caught and reported.
- No FAIL-status SID appears in `morning_brief` or `action_queue` outputs.

---

## Phase C — Coverage gap closure (85 → 88)
**Effort**: 2-3 sessions (**~80% done as of 2026-05-24**). **Mechanical but high-impact.**

Phase A *surfaced* the gaps; Phase C *fills the closable ones and explicitly accepts the structural ones*.

### Deliverables
1. **Price coverage fallback** ✅ — shipped 2026-05-24 as `sources/yfinance_prices.py` (NOT a BSE bhavcopy scraper as originally planned — yfinance was 10× cheaper with comparable hit rate). Tries `.NS` then `.BO` for any SID missing from stock_prices in last 30d. Wired into `PIPELINE_STEPS` as `fetch_prices_fallback`. Manual backfill landed 330/333 SIDs (327 via `.BO`), 9,296 price rows. Universe coverage **86% → 99.9%**. The 2 truly-dark SIDs (`DHENUBUILD`, `ISCITRUST`) have no yfinance data on either suffix — accept.
2. **Analyst attribution — handled, not lifted.** Originally scoped as "lift from 41% → 60% via yfinance ticker audit". Investigation showed this is impossible: probed 10 well-known SMALL caps (Tata Investment, Gillette, Astrazeneca, Wockhardt, etc) on both `.NS` and `.BO` — *zero* have yfinance analyst data. The 41% IS the yfinance ceiling for Indian stocks (broker coverage outside NIFTY 200 is structurally thin). Critically, by tier the picture is **LARGE 100%, MID 96%, SMALL 33%** — and SMALL doesn't use `consensus` in `SIGNAL_WEIGHTS` anyway. The correct fix is the eligibility tagging from Phase A (`eligibility/registry.py` marks 1,472 SMALL caps as INELIGIBLE for `consensus`); the screener's `eligible_coverage` correctly ignores these for the gate. **No production impact from the 41% headline number.**
3. **Regulatory feed recovery** ✅ — shipped 2026-05-24. Root cause: `fetch_regulatory` step called `harvest_all` (a 3-year historical backfill — 180 Google + 870 RBI + 110K PIB IDs) which timed out daily. Built `harvest_incremental(days=30)` — daily-cron-safe ~5min runtime. Manual backfill landed 1,904 new events; raw `regulatory_events` went from latest 2023-05 → 2026-05. Classifier separately re-run 2026-05-24 ($3.41 Anthropic spend) to clear pending backlog.
4. **News feed continuity** — `news_articles` cutoff 2024-04. Status unchanged. Decision needed: fix RSS harvester OR accept gap and remove `sentiment_7d` factor from active production until backfilled. Deferred.
5. **Sanity check on each fix** ✅ — `ELIGIBILITY_REGRESSION` in `tools/data_sanity.py` compares each signal's eligible count today vs prior snapshot in `universe_eligibility`; WARN at 5% drop, CRITICAL at 10%. Catches "harvester silently shrinking universe overnight". Manually seeded 2026-05-23 snapshot so check is armed today (returns 0 — all signals stable).

### Done when
- ✅ `stock_prices` coverage ≥ 95% of universe (now **99.9%**).
- ✅ Analyst attribution **handled correctly** via per-tier eligibility tagging — NOT lifted to 60% (proven structurally infeasible) but the structural gap no longer penalises production scoring.
- ⏳ `regulatory_events` freshness < 14d sustained for 30 days — alive today (May 2026 latest), sustainability gated on cron stability over the next 30 days.
- ✅ Each filled gap has a regression sanity check.

### Remaining for next session
- News feed: fix or accept-and-remove.
- Verify `regulatory_events` freshness stays < 14d for 7+ consecutive cron runs.

---

## Phase D — Backtest depth (88 → 90)
**Effort**: 2 sessions. **Slow burn, high statistical payoff.**

Today's PIT is 36 months for fundamentals, ~52 weekly Fridays for behavioural. Claims like "sentiment_7d LARGE t=-3.88" sit on n=4 — preliminary at best.

### Deliverables
1. **Extend fundamental PIT to 60 months** using v1 archive (`/home/ubuntu/alpha-signal/data/`) where the source has data.
2. **Add 2024-2025 historical backfill** for behavioural signals from the new `sources/historical_backfill.py` outputs (bulk, short, FII F&O).
3. **Re-run all factor backtests** at both monthly and weekly cadence with the deeper window.
4. **Reject any KEEP verdict with n < 12** — gate in `db.BACKTEST_SIGNALS` registry.
5. **Bootstrap confidence intervals** on each t-stat — surface in Factor Health table (replace single t-stat with `t̂ ± CI95`).

### Done when
- All 60 PIT-shipped factors have ≥ 60 months OR explicit `BACKTEST_INSUFFICIENT` flag.
- No KEEP verdict in `BACKTEST_SIGNALS` with n < 12.
- Factor Health table shows confidence intervals, not point estimates.

---

## Phase E — End-to-end PIT replay validator (90 → 93)
**Effort**: 2-3 sessions. **The "prove it works" guarantee.**

Today we can't *prove* that on (say) 2025-09-01 the system would have produced exactly the picks it now claims it would have. Maybe a producer was rewritten and the PIT helper drifted. Maybe `daily_snapshots_pit` was hand-edited. The HALC bug would've passed all current checks because no historical replay exists.

### Deliverables
1. **Frozen historical snapshot suite** — pick 6 dates across 2024-2025, persist the exact picks + factor scores that should have been produced at each.
2. **`tools/pit_replay.py`** — given a date, reconstructs picks from scratch using ONLY data available at that date, compares vs frozen snapshot.
3. **Allowed-drift policy** — what counts as a legitimate change (new factor added) vs a regression (existing factor output differs).
4. **CI on every model/data-pipeline commit** — runs replay against 1 sample date; full 6-date run nightly.
5. **Cockpit Health Center**: new tile "PIT replay" with last-pass status + drift indicators.

### Done when
- 6 historical dates frozen with their claimed picks + scores.
- Replay tool reproduces each within allowed-drift tolerance.
- Every git push to model/scoring/signals/sources is gated by 1-date replay (~30s).

---

## Phase F — Risk decomposition + sub-models (93 → 95)
**Effort**: 3-4 sessions. **Already partly on the roadmap.**

The last 2 points require treating the model as a real portfolio not just a ranker.

### Deliverables
1. **Ship financial sub-model** — Track 2.2 (`sources/banking_metrics.py` + `signals/financial_signal.py`). Until shipped, financial-sector picks have weaker grounding.
2. **Barra-style risk decomp** — Track 3.3d. Surface in cockpit Portfolio tab: "your top-30 has +1.4σ Value tilt, -0.8σ Growth, sector concentration HHI = X".
3. **Per-stock data lineage** — for each scored stock, record which source-table-row produced each factor input. Enables "explain why this rank changed today" forensics.
4. **Cross-source PT reconciliation** — daily sanity: where the same SID has PT from multiple sources (yfinance + Tickertape + future Moneycontrol), assert they're within 10% of each other or flag.

### Done when
- Financial sub-model live for ≥ 30 days with non-degenerate Bank Nifty backtest performance.
- Risk decomp visible in cockpit and matches a manual reconciliation.
- Lineage table queryable: `SELECT lineage WHERE sid='X' AND date='Y'` returns every row that contributed.
- Cross-source PT mismatches surfaced in Live Issues Inbox.

---

## Sequencing rationale

Phases are ordered by **confidence-delta per unit of work**, with a soft dependency chain:

- **A first** because it unblocks the rest (B's gate depends on knowing eligibility; C's "did we fill the gap" needs A's measurement; E's replay needs to know which SIDs are eligible per date).
- **B second** because per-stock integrity is the single biggest blast-radius bug class (HALC, ANO, ABSM all lived here).
- **C third** because it's the mechanical "fill the source holes" work — slower to do, real impact on coverage.
- **D fourth** because longer backtest is "slow burn" — value comes from time accumulating, not from work done.
- **E fifth** because PIT replay requires A and B in place to be meaningful.
- **F last** because it's the institutional polish that only matters once A-E are solid.

If forced to ship only one: do Phase B alone. It moves the daily-confidence number the most for the actual question "should I trust today's top 10 picks blind?".

---

## What this plan deliberately does NOT include

- **More factors** — we have 63 registered. Adding more without first proving the existing ones are correct (Phases B + E) is moving in the wrong direction.
- **More portfolio modes** — single-stock rank quality is the bottleneck, not portfolio construction sophistication.
- **More LLM features** — the LLM is a presentation layer. Hardening data underneath it has higher leverage than richer narratives.

---

## Open questions

1. Phase E: which dates to freeze? Suggest one per quarter across 2024-2025, choosing dates without known data anomalies.
2. Phase C: if `news_articles` source is permanently dark, do we drop sentiment factors or accept stale signal? (Affects 5 of 26 DROP-verdict factors.)
3. Phase D: confidence intervals via bootstrap or analytic Newey-West-corrected? (ADR 0022 already uses NW.)
4. Phase F: lineage table will be large. Cap at top-300 SIDs per date? Or full universe with aggressive pruning?
