# Plan 0020 — Factor audit: calculations, input data, parity, evidence

**Status:** approved 2026-10-03 with a wider scope (Amit: "a comprehensive audit … any bug or code issue needs to be corrected … also audit backtest, cadence and suggest further improvements … fundamentally rethink features and factors … ensure the factor codebase and calculations are elegant, no redundancy"). The factor **model** (weights, combination) is out of scope until this is done.
**Why now:** the health rebuild (ADR 0059–0061) checks that today's factor *inputs arrived* (`FACTOR_INPUT`) and that weights *keep their edge* (`FACTOR_DECAY`). Nothing checks that a factor is **calculated correctly**, that its **inputs are right**, or that its **stored evidence is reproducible**. Every factor bug so far was found by accident: `pt_upside` look-ahead, the `fwd_return_20d` anchor landmine, `market_cap_cr` in rupees, MID Financials dropped by a mis-wired eligibility.

**State on 2026-10-03 (measured, not assumed):**
- 105 factors in `factors.FACTORS`: 10 wired (16 tier × factor weights), 4 variant, 26 proposed, 63 library, 1 blocked, 1 control. 68 producers.
- Panel `daily_snapshots_pit`: 202 anchors, 2019-12-02 → 2026-09-25, 109 columns. Frozen screener inputs: 137 days.
- Evidence `pit_ic_by_tier_v2`: 349 rows, 100 signals, computed between 2026-05-03 and 2026-10-02.
- Suspects already visible:
  - **MID `accruals`**: weight +0.22, long-run IC −0.050 (37 anchors). Sign audit already approved, not run.
  - **`consensus`** (LARGE 0.28, SMALL 0.16): reads `forecast_history` EPS with no filing lag (checklist D7 ①).
  - **`market_cap_cr`** holds rupees (work order 1). Any factor reading it is suspect.
  - **`pit_ic_by_tier_v2`**: `t_stat_ci_lo` down to −93, `t_stat_ci_hi` up to 310, max `t_stat` 19.42; `v1_archive` rows from May sit beside re-baselined ones.
  - **`pt_revision_yoy`, `insider_score`**: 0% coverage at the latest anchor.
  - 3 decayed weights: `book_to_price` MID + SMALL, `delivery_anomaly_z` SMALL.
  - Multibagger ranks the text `promoter_trend` alphabetically (D7 ④).

## 1. The idea

One audit sheet per factor, built by one read-only tool, answering six questions. All 105 factors are audited; the 10 wired ones first because they move picks. Bugs are fixed as they are found (§3).

| # | Question | How it is answered |
|---|---|---|
| A | Is it **calculated right**? | Independent recompute from raw rows for 3 stocks per tier, against the written definition, not the code |
| B | Are its **inputs right**? | Freshness, coverage against eligibility, discards, distribution, second source |
| C | Is **live the same as PIT**, with no look-ahead? | Live vs panel diff; re-reconstruct old anchors; filing-lag review of every producer |
| D | Is the **evidence true**? | Re-run the backtest and diff against the stored row; a second, independent IC computation |
| E | Is the **backtest and its cadence** right? | Audit of the IC engine, the label, anchors, historical tiers and universe, and of each factor's cadence against how often its information arrives |
| F | Is the **code elegant**? | One compute per quantity, shared primitives, no per-factor boilerplate, no dead names; every refactor proven by "panel values identical before and after" |

## 2. Phases

**P0 — Audit sheet (`tools/factor_audit.py`, read-only).** One row per factor × tier, everything derived from `factors.FACTORS`, no hand list:
- registry: status, producer, input tables, cadence, range, weight
- inputs: age of each input table against the factor's cadence
- coverage: stocks with a value ÷ stocks the `eligible_sql` says should have one, latest anchor and 12-anchor trend
- values: share discarded by `pit_range`, share at the range edge, distinct values, top repeated value, skew, largest day-on-day jump in the frozen inputs
- evidence: t-stat, anchors, age of the evidence row, sign against the weight, decay flag
- Output: `docs/studies/factor-audit-2026-10.md` and an ops cockpit table, in the same session.

**P1 — Calculation audit, wired factors first** (`announcement_car`, `consensus`, `sector_tilt`, `book_to_price`, `iv_skew_25d`, `accruals`, `piotroski`, `governance_resignation`, `delivery_anomaly_z`, `pledge_quality`). For each:
1. Write the definition in one line (formula, units, sign that should predict returns, filing lag).
2. Recompute by hand for 3 stocks per wired tier from raw tables; compare with `pit.features_at(today)` and the frozen screener input. Tolerance 1e-6, or explain the difference.
3. Check units (crore vs rupees, percent vs fraction), consolidated vs standalone, Financials handling, share-count and corporate-action adjustment.
4. Check the path to the score: percentile within tier, negative weight inverts, per-factor contributions sum to `final_score`.
5. Verdict per factor: correct / wrong (issue filed) / correct but definition unclear (doc fix).
Then the 26 proposed factors at steps 1–3 with one stock per tier. Library factors only when P0 flags them.

**P2 — Input data quality.** Work the P0 flags, worst first:
- coverage below eligibility by more than 10 points, per tier
- an input older than the factor's cadence allows
- discard rate above 2%, or values piled on a range edge
- constant or near-constant columns; the two 0%-coverage columns
- second source where one exists: `tools/reconcile.py` (Tickertape vs Screener) extended to the inputs of the wired fundamentals factors (equity, shares, EPS, cash flow). MMTC and GOCL outliers are already open.

**P3 — Live = PIT, and look-ahead.**
- Parity: `features_at(D)` live against the stored panel row for the same D, every factor, latest anchor.
- Reproducibility: re-reconstruct 3 old anchors (2021, 2023, 2025) into a scratch DB copy and diff against the stored panel. Drift means restated inputs or a changed formula; each needs a reason.
- Look-ahead review: for every producer, the date column it filters on and the lag it applies. Known open: `forecast_history`, insider `available_at`, today's tiers used in the backtest (D7 ①–③).

**P4 — Evidence.**
- Re-run `tools/backtest_pit.py` for all factors; diff t-stat and anchors against `pit_ic_by_tier_v2`. A row that does not reproduce is replaced, with a note.
- Second method for the 16 wired pairs: an independent IC computation (different code path, bootstrap CI). The layer-2 guardrail logged on 2026-07-05 and never built.
- Repair or remove the broken CI columns and the stale `v1_archive` rows.
- Re-run `tools/multiple_testing.py` and `tools/factor_decay.py` on the corrected evidence.

**P4b — Backtest engine and cadence.**
- Engine: IC, t-stat, Newey-West lag against the overlap of returns, bootstrap CI, verdict thresholds; one IC function for every tool.
- Label: entry and exit dates, corporate actions inside the window, same-close entry; more than one horizon.
- Panel: anchors, stocks per anchor over time, today's tiers and universe used historically, liquidity.
- Cadence: per factor, how often its information arrives against the cadence it is tested at, the horizon it is judged on, and the daily re-rank.
- Output: fixes for what is wrong, and a ranked list of improvements with benefit and effort.

**P4c — Code: one compute per quantity.**
- Redundancy map across `pit.py`, `signals/` and `factors.py`: duplicated formulas, near-copy modules, dead modules, surplus names per factor.
- Target layout within the project rules (plain functions, dict registry): declared inputs → one pure function → one registry entry, on shared primitives.
- Refactor in steps; each step must leave the panel and today's frozen screener inputs identical (`tools/pit_replay.py`, panel diff).

**P4d — Rethink of the feature set.** From the audit sheet and corrected evidence: which factors are duplicates of each other, which are definitions worth fixing, which are dead data, which families are missing. A proposal for Amit, not a build.

**P5 — Verdicts, and make it permanent.**
- One table: factor, verdict (sound / fix / review), evidence link. It goes to the promotion review already pending (3 decayed weights, LARGE re-weight, MID accruals sign).
- Each fix is a separate, evidence-gated change. A fix that changes a wired factor's values is measured before and after (rank correlation, top-30 overlap).
- What can fail on a normal day becomes a health check with a fire drill (catalog at 23 of 30): coverage against eligibility, discard rate, live-vs-panel parity. What only breaks when code changes becomes a test: one golden recompute per wired factor in `tests/`.
- ADR for anything non-obvious; `docs/reference/signal-weights.md` updated with corrected evidence.

## 3. Rules for this plan

- Audit first, then fix. A bug fix ships with its before/after measurement (values changed, rank correlation, top-30 overlap per tier) and a test. No harvester runs. Re-reconstruction is tried on a scratch DB (`ALPHA_DB`) before the live panel is rewritten.
- A fix that changes a wired factor's values changes picks: it is listed for Amit with its measured impact before it goes live.
- No weight changes. The audit produces evidence; the promotion review decides.
- Scope always comes from the registry (`factors.FACTORS`, `SIGNAL_WEIGHTS`, `config.TIERS`), never a typed list.
- Plan 0017 is renaming tables: read through `db` and the registry views, not raw table names.

## 4. Sessions

| Session | Work | Visible result |
|---|---|---|
| 1 | P0 + P2 triage | Audit sheet for 105 factors, on the ops cockpit and as a study |
| 2 | P1 wired factors | 10 recompute verdicts; accruals sign and `market_cap_cr` resolved |
| 3 | P3 + P4 | Parity and reproducibility diff; evidence table corrected |
| 4 | P1 proposed factors + P5 | Verdict table, new checks and tests, promotion review pack |

## 5. Done when

- Every wired factor has a hand-recompute verdict and a golden test.
- Every factor has an audit-sheet row with no unexplained flag.
- Every stored evidence row reproduces from the current panel, or is replaced.
- Live and panel values agree for every factor at the latest anchor, or the difference is explained.
- Every producer has a stated date column and lag; open look-aheads are fixed or carry a measured impact.
- The promotion review has run on the corrected evidence.

## 6. Decisions (Amit, 2026-10-03)

1. Depth: comprehensive, all 105 factors.
2. Bugs and code issues are corrected inside this plan.
3. Backtest, cadence, code elegance and a rethink of the feature set are in scope; the factor model comes after.

## 7. Proposal: dead and never-listed names in the panel (owed since 2026-10-03, not built)

**What exists:** `stock_prices_unlisted` holds every traded symbol outside `stocks` since 2020 (2,212 symbols; 538 delisted or merged). The survivorship study recomputes five price factors on them in memory.

**What blocks putting them in the panel:**
1. `daily_snapshots_pit.sid` references `stocks`; a dead name has no sid.
2. A dead name has no market cap before NSE's daily MCAP file starts (present in 2026, absent in 2020 and 2022), so it has no tier.
3. Fundamentals do not exist for dead names: only price, delivery and event factors can be computed.

**Proposal, in order:**
1. Identity: give every unlisted symbol an entity in plan 0017's `entities` (kind `security`, status `unlisted`), keyed by symbol with `symbol_changes` as its alias history. No row in `stocks`: the live universe stays 2,448.
2. Size: find the first date NSE's PR archive carries `mcap*.csv` (one probe per quarter back from 2026) and harvest it for the 204 anchors from that date. Before it, estimate market cap from 90-day traded value by quantile-mapping against the stocks that have one, and mark the tier as estimated.
3. Panel: a second panel table with the same columns for unlisted entities (no foreign key to `stocks`), written by the same `reconstruct_one_date` for the price, delivery and event producers only. `tools/backtest_pit.py` unions the two for those factors.
4. Evidence: every price factor then carries two t-stats, universe and full market. A weight on a price factor needs both.

**Size:** about three sessions. **Why not now:** it changes the panel's key and depends on `entities`, which another session is migrating this week.

## Implementation notes

**2026-10-03, session 1.** Full write-up: [factor-audit-2026-10.md](../studies/factor-audit-2026-10.md).
- Built `tools/factor_audit.py` (P0) and ran four read-only auditors (P1, P3, P4, P4b, P4c).
- Fixed, none of it changing today's ranking: label on adjusted prices, NCRPS bonus parser (adjustments table recomputed), filing lag on the consensus input, minimum 12 anchors for a verdict or interval, block bootstrap, `computed_at` + orphan rows, one `evidence()` reader, decay monitor on the backtest's anchors and the ranked column (3 flags → 0), promotion-gate net t, `bulk_deal_signal` sign. Tests in `tests/test_backtest_engine.py`.
- Not done: the panel rebuild for the new label / consensus / bulk-deal columns and the evidence re-run (writing `daily_snapshots_pit` was not permitted in the session). Commands in the study §7.
- Staged for one measured model change, each needing the rebuild and re-test: R1–R11 and P1–P10 in the study. Decisions needed from Amit: accruals column (R5), Financials treatment (R9), deleting phantom holiday price rows (P2).
**2026-10-03, session 1, second pass (Amit: "fix all and institute the new checks").** [ADR 0062](../decisions/0062-factor-audit-fixes-one-model-change.md); study §7.
- Data: two columns renamed in the DB, schema, source map and readers; 44 copied holiday price days deleted and the harvester guarded; adjustment parser fixed.
- Factors: book-to-price share basis + owners' equity, Piotroski, forensic, accruals (column and inputs), consensus formula, sector tilt macro leg, option staleness, earnings window, governance dedupe, eligibility for every wired factor.
- Guards: reconcile over every statement column factors read; two new health checks with drills (catalog 25 of 30); tests in `tests/test_backtest_engine.py`, `tests/test_factor_registry.py`, `tests/test_sector_tilt.py`. 399 tests green.
- Ranking effect measured (study §7). Cockpit services restarted. Full panel rebuild + evidence re-run started 11:55 UTC (`output/factor_audit_rebuild.log`).
- Next session: read the corrected evidence → promotion review (LARGE consensus, LARGE book-to-price, MID accruals) → R9 / R11 / P3 / P6 → backtest redesign and code refactor (study §5).
**2026-10-03, session 1, third pass (Amit: "agree with all go ahead", "do the backfill also").** Study §8, §9.
- Backtest: point-in-time tiers (`pit.tiers_at`), next-session label entry, full rebuild of 202 anchors, evidence re-run (`output/factor_audit_evidence.log`).
- Survivorship: `stock_prices_unlisted` backfilled 2020-01 → today and kept daily; `symbol_changes` + `link_renames`; `tools/survivorship_study.py`.
- Result: 8 of 16 wired weights are below the 1.5 bar on the corrected panel; LARGE has one factor with evidence (`announcement_car`). Several unwired momentum, option and delivery factors clear 2.5 in MID and SMALL.
- A last pass of the price producers (renamed stocks' history) + evidence was started 15:58 UTC: `output/factor_audit_price_pass.log`.
- Owed: promotion review on §8 (Amit decides weights) · proposal for dead names in the panel · R9, R11, P3 · cadence fields and the code refactor (study §5).
**2026-10-03, session 1, fourth pass (Amit: "yes build it but check should be weekly").** Weekly data-quality audit: `tools/dq_probes.py` (probes + planted-fault drill), desk seat `dq-auditor` with kind `org_dq_audit` (trap findings in the brief, server re-run of every query, score on the memo and the scorecard), `tests/test_dq_audit.py`, [org.md](../reference/org.md). First scheduled run: Sunday 2026-10-04 06:30 UTC.
**2026-10-04, close-out.** First run on the new weights read (email banner: reshuffle expected; LARGE 96 ranked tripped the flat-100 check). Fixed same day, [ADR 0064](../decisions/0064-missing-factor-is-neutral.md): result filings found under board-meeting outcomes, a missing factor counts as neutral (closes R9), demergers adjusted (closes P3), thin-tier check relative to tier size, third mislabelled column renamed (`tax_and_minority`), CHAV and ORIA splits recorded, step reads declared. A pass of the price and result producers on all anchors + evidence was started 06:21 UTC (`output/factor_audit_pass4.log`). Still open: R11 (statements arriving after the modelled lag), the dead-names panel (§7), the feature-layer refactor and the rest of the backtest redesign (study §5).
- The plan's opening claim that MID accruals has the wrong sign was a naming artefact: the sign is right, the evidence is on a different column (R5).
