# HANDOFF

> Overwritten at the end of each session per CLAUDE.md session protocol. If you're starting a new session: read this, then CLAUDE.md, then any plan or ADR linked below.

**Last updated:** 2026-05-04 (Amit Bhagat + Claude Code)
**Current branch:** `master`
**HEAD:** `6c91691` feat(cockpit): pipeline DAG viz + in-UI step rerun on /flow — *today's data + plan + factor work is unstaged*

---

## Where I am

Multi-day session that crossed PIT reconstruction, paid-data evaluation, the cleanup of all 10 PARTIAL factors, and the introduction of a third project track. Started "what data sources have we missed?" → discovered nselib unlocks ~5 historical APIs v1 thought were blocked → ingested 4 streams (bulk deals, corp actions, short selling, FII positioning, MF NAV, smart-beta indices) → wrote three new plans → audited factor count (42 vs ~100 at small quant shops) → drafted plan 0005 to scale to 100 factors + factor model → cleaned up partials so 40/42 are now READY → consolidated the F-track into the mother plan as the project blueprint. **All changes are unstaged.**

## What works

- **Smart-beta index history live.** 9 of 12 NSE indices populated in `nse_index_history` — NIFTY 50/500/MIDCAP 150/SMALLCAP 250/ALPHA 50/100 ALPHA 30/200 ALPHA 30/50 VALUE 20/200 VALUE 30, ~720 rows each from 2023-06 to 2026-04. Validation: our `value_composite` top-30 LARGE+MID portfolio tracks NIFTY200 VALUE 30 at **Pearson 0.984** with 5/5 sign-matches (~125 bps/mo drag, likely from missing quality overlay).
- **nselib ingest pipelines live.** [sources/nselib_pull.py](sources/nselib_pull.py) — single CLI `--source {bulk,corp,short,fii_pos,fii_cash,mf_nav,indices,surveillance,daily_forward,all}`. Ingested: bulk deals (13,652 rows, 12mo), corp actions (4,516 rows, 24mo), short selling (30,692 rows, 24mo), FII positioning (220 rows, ~3mo), MF NAV (38,830 NAVs across 12 schemes).
- **Forward-only daily cron wired.** `0 14 * * *` runs [run_daily_forward.sh](run_daily_forward.sh) (7:30 PM IST, after NSE EOD). Captures FII/DII cash flow + F&O positioning + ASM list — sources with no historical archive that must accumulate forward. ASM working (146 rows); GSM + F&O ban parsers have known bugs (deferred).
- **Split adjustment shipped.** [tools/apply_splits.py](tools/apply_splits.py) populates `stock_prices.adj_close` from the 104 parsed corporate-action events. Adjusted 58,263 (sid, date) rows across 101 stocks. v1↔v2 momentum correlation improved 0.67→0.78 on mom_12m, 0.70→0.72 on mom_6m. Remaining gap = dividend adjustment (v1 yfinance Adj Close adjusts both; v2 only splits).
- **PIT reconstruction harness mature.** [tools/reconstruct_pit.py](tools/reconstruct_pit.py) computes 22+ signals across 7 monthly snapshot dates (2025-11 → 2026-05) for 2,448 stocks. New functions added today: `pit_earnings_beat_rate`, `pit_news_volume`. Validation guardrails + checkpoint log + `--skip-existing` flag in place. Latest full run: 17,136 rows, all 7 dates ✅.
- **Backtest harness validates v1 archive exactly.** [tools/backtest_pit.py](tools/backtest_pit.py) reproduces every C13b headline t-stat from v1 within rounding: promoter t=3.20 SMALL ✅, earnings_yield t=3.13 SMALL ✅, piotroski t=2.81 SMALL ✅, book_to_price t=2.54 SMALL ✅, avg_delivery t=2.49 SMALL ✅, cf_accruals t=3.20 MID ✅. New v2 signals show provisional t-stats (n=5, diagnostic only).
- **Factor registry: 40/42 READY.** [db.py BACKTEST_SIGNALS](db.py) flipped 8 PARTIAL → READY this session: m_score, z_score, fii_dii_cash_net, fii_dii_fno_positioning (status flip — data was always there); earnings_beat_rate, news_volume (built v2 compute functions); mom_6m_adj, mom_12m_adj (applied splits); promoter_qoq (diagnostic showed 97.4% sign-match when both non-zero); short_selling_signal (PROPOSED → READY, was already wired).
- **Three reference docs in repo.** [docs/reference/data-playbook.md](docs/reference/data-playbook.md) (43KB, 6 reconstruction patterns), [docs/reference/api-endpoints.md](docs/reference/api-endpoints.md) (per-endpoint catalog with NSE quirks), [docs/reference/paid-data-sources.md](docs/reference/paid-data-sources.md) (₹5K/mo budget playbook + Sensibull skip rationale). Extracted from Claude private memory (which user couldn't see) into checked-in repo.
- **Three plans alive.** [0003-mother-plan.md](docs/plans/0003-mother-plan.md) is now the **project blueprint** — three tracks (Engineering ✅ / Intelligence D-phases / Factor-depth F-phases). [0004-pit-reconstruction.md](docs/plans/0004-pit-reconstruction.md) most phases complete this session. [0005-100-factors-and-model.md](docs/plans/0005-100-factors-and-model.md) draft of F1/F2/F3 (data → 50 new factors → factor model upgrade).

## What's broken or half-built

- **Nothing committed yet.** `git status` shows: M [CLAUDE.md](CLAUDE.md), [cockpit/api.py](cockpit/api.py), [cockpit/templates/_icons.html](cockpit/templates/_icons.html), [cockpit/templates/model.html](cockpit/templates/model.html), [db.py](db.py), [docs/plans/README.md](docs/plans/README.md), [docs/reference/README.md](docs/reference/README.md). New files: 3 plans, 3 reference docs, [sources/nselib_pull.py](sources/nselib_pull.py), entire `tools/` directory (apply_splits, backtest_pit, compute_splits, import_v1_pit, reconstruct_pit). Diff is **+1025 lines** in db.py alone.
- **`INSERT OR REPLACE` bug in upsert_df.** Running `python -m tools.reconstruct_pit --signal X` only nulls every other column for that snapshot. Workaround: always run full reconstruction. Long-term fix: switch to `INSERT ... ON CONFLICT UPDATE` ([db.py:181](db.py#L181)). **Caused real data loss mid-session** when I ran `--signal earnings_beat_rate` then `--signal momentum` — both wiped prior columns. Recovered via final full reconstruction.
- **Surveillance parser bugs.** [sources/nselib_pull.py](sources/nselib_pull.py) `pull_surveillance_today()` has `'list' object has no attribute 'get'` for GSM and F&O ban list. ASM works (146 rows). Cron is firing the broken paths nightly; harmless except for noise in `output/daily_forward.log`.
- **3 of 12 smart-beta indices failed silently.** `nse_index_history` has 9 indices populated; the missing ones (NIFTY100 LOW VOL 30, NIFTY200 QUALITY 30, NIFTY100 ALPHA LOW VOL 30) returned empty — likely symbol-name mismatch with NSE's index master. Worth a 10-min retry with verified symbol strings.
- **Split adjustment is partial.** [tools/compute_splits.py](tools/compute_splits.py) parsed 104 of 207 corporate-action events (50%). The other 103 had ambiguous "Subject" strings the regex didn't catch. Improving the parser is a lever — likely closes another 15-20% of the v1↔v2 momentum gap.
- **Dividend adjustment missing entirely.** v1's yfinance Adj Close adjusts both splits and dividends. v2's adj_close only adjusts splits. This is the largest remaining contributor to the 0.66-0.78 momentum correlation gap. Needs a second adjustment pass over `corporate_actions` for DIVIDEND events.
- **2 signals legitimately not READY.** `sentiment_7d` PARTIAL (no FinBERT classifier in repo — needs F1.4); `screener_final_composite` PROPOSED (by-design end-state, waits on F3 orthogonalization). Both have explicit owners in plan 0005; not bugs.
- **No CHANGELOG entry yet** for today's work — proposed below.
- **README.md still stale** — same staleness flagged in 2026-05-02 HANDOFF; not addressed.

## Next 3 actions (in order, concrete)

1. **Commit today's work as ONE feat commit.** Message draft: `feat: PIT reconstruction + factor cleanup (40/42 READY) + F-track project blueprint`. Includes: 3 plans, 3 reference docs, [tools/](tools/) directory, [sources/nselib_pull.py](sources/nselib_pull.py), db.py registry updates, CLAUDE.md edits, plan/reference README index updates. Skip the `tools/__pycache__/` directory. Add CHANGELOG entry (drafted below) in the same commit.
2. **Fix the upsert_df bug** ([db.py:181](db.py#L181)) before any future partial reconstruction work. Change `INSERT OR REPLACE` → `INSERT ... ON CONFLICT(<pk>) DO UPDATE SET <only-cols-in-df>`. Add a regression test in [tests/test_smoke.py](tests/test_smoke.py) that runs `--signal X` and verifies other columns survive. ~1 hour.
3. **Subscribe to Screener Premium (₹420/mo) and ship F1.1.** This is the highest-leverage paid-data move per [paid-data-sources.md](docs/reference/paid-data-sources.md). Build [sources/screener_pull.py](sources/screener_pull.py) with the cookie-jar + Excel-export pattern. ~2 dev-days. Unblocks 15 Tier-1 factors (CCC, FCF yield, ROIC, ROIIC, gross margin trend, Sloan accruals, NWC factors).

## Don't do

- **Don't run `python -m tools.reconstruct_pit --signal X`** until the upsert_df bug is fixed. It will null every other column for the affected snapshot dates. If you must run partial signals, use `--dry-run` to inspect.
- **Don't subscribe to Sensibull or Trendlyne yet.** Sensibull has no retail API ([paid-data-sources.md](docs/reference/paid-data-sources.md)). Trendlyne lost ~70% of its marginal value when nselib unlocked the historical APIs. Screener Premium is the only paid sub with non-overlapping data; everything else is convenience.
- **Don't run all 5 nselib backfills concurrently** ([sources/nselib_pull.py](sources/nselib_pull.py) `--source all`). The 2-second rate-limit floor adds up; `all` takes ~45 min sequential, and concurrent calls risk cookie-session issues. Prefer staggered single-source runs.
- **Don't apply additional splits via [tools/compute_splits.py](tools/compute_splits.py) without re-running [tools/apply_splits.py](tools/apply_splits.py) afterward.** The latter rebuilds `adj_close` from scratch — it's idempotent but fragile if you forget. Sequence: compute → apply → reconstruct.
- **Don't mark `sentiment_7d` or `screener_final_composite` as READY.** Both are scoped in plan 0005 (F1.4 NLP setup; F3 factor model). Reclassifying them prematurely defeats the purpose of the status taxonomy.
- **Don't add factors past ~100 before F3 ships.** Plan 0005 has explicit gate: 60th+ factors add noise without orthogonalization. The 100→200 expansion is deferred until F3's marginal-IC gate is in production.
- **Don't `git add .` or `git add -A`** — it'll pull in `tools/__pycache__/`, possibly `output/daily_forward.log`, and any stray `.playwright-mcp/` artifacts. Stage explicit files.

## Open questions for me (decisions you need to make)

1. **ADR for the F-track parallel architecture?** The mother plan now describes three concurrent tracks with explicit non-blocking integration points (D17↔F3.3, D18↔F3.2). My take: **yes, propose ADR 0009** — it's a structural decision a future contributor needs context for, and it's load-bearing on resource-allocation calls. Draft below.
2. **Single commit or split today's work?** Diff is large but tightly coupled (the docs reference the tools, the plans reference the docs, registry status flips reference the new tools). My take: one commit. The pieces don't make sense in isolation.
3. **Fix upsert_df bug now or after F1.1 ships?** Bug is real but only fires when running partial reconstructions; daily cron does full runs. My take: **fix now**, before the next partial run causes silent data loss. ~1 hour with a smoke test.
4. **Should the registry ship a `pit_column_v2` audit?** A few signals had `pit_column_v2: None` while their reconstruction function exists (fixed inline this session for `news_volume`, `short_selling_signal`, `earnings_beat_rate`). Worth a one-shot diagnostic that diffs PIT_COLUMNS in [tools/reconstruct_pit.py](tools/reconstruct_pit.py) against the registry's `pit_column_v2` values? My take: **yes, 5-line `python -m tests.audit_registry`** — catch drift early.
5. **Plan 0004 status — Implemented or close it?** Today's session executed phases 2 (coverage gaps), 3 (methodology fixes for momentum + promoter_qoq), and 6 (operational — apply_splits, full reconstruction). Phases 4 (depth — extend PIT past 2023) and 5 (backtest harness) are partially done. My take: leave Status: active, add an "Implementation notes" section documenting today's progress, archive when full PIT depth ships.
6. **Should `output/daily_forward.log` be added to .gitignore?** Currently it appends every cron run forever. Same question as 2026-05-02's `output/rerun.log`. My take: yes, ship a single .gitignore line for `output/*.log`.

---

## Proposed for this session, awaiting approval

### ADR 0009 — *F-track runs parallel to D-track (no blocking)*

**Status:** Proposed (Draft)
**Date:** 2026-05-04
**Decided by:** Amit (with Claude Code)

**Context.** v2 had two tracks (Engineering ✅ + Intelligence D-phases ⏳) per the original master plan. Today's audit revealed factor count + factor model are also load-bearing — a third track. There are two ways to add it: (a) sequentially after D18 (which is data-blocked until 2027), (b) in parallel with explicit integration points.

**Decision.** F-track runs in parallel to D-track, with documented integration points: F3.3 (mean-variance portfolio construction) replaces D17's equal-weight portfolio if it ships first; F3.2 (orthogonalization) feeds D18's XGBoost training set.

**Alternatives considered.** Sequential (rejected — loses 12+ months waiting for D18); informal parallel (rejected — no explicit handoff means race conditions when D17 and F3.3 both try to write portfolio_holdings); single combined track (rejected — D-phases are about deployment of validated signals, F-phases are about deepening the model itself; conflating them muddles the per-phase definition-of-done).

**Reversal cost.** Low. If F-track loses traction, the D-track is fully self-sufficient (D17 ships portfolio at equal-weight; D18 trains on existing factors). No code change needed to roll back; just stop work on plan 0005.

### CHANGELOG entry — under `## 2026-05-04`:

- **PIT reconstruction full-featured.** [tools/reconstruct_pit.py](tools/reconstruct_pit.py) now computes 22 signals across 7 monthly snapshots for 2,448 stocks; new functions `pit_earnings_beat_rate` (proxy via QoQ-positive rate, 8-quarter window) and `pit_news_volume` (article count from news_articles ⟕ news_article_stocks, 7-day rolling). Validation ranges + checkpoint log + `--skip-existing` working.
- **Split adjustment live.** [tools/apply_splits.py](tools/apply_splits.py) populates `stock_prices.adj_close` from 104 parsed corporate-action events. v1↔v2 momentum correlation improved 0.67→0.78 mom_12m, 0.70→0.72 mom_6m. Remaining gap = dividend adjustment (deferred). Schema: `stock_prices.adj_close REAL` added.
- **Factor registry: 40 of 42 READY** (was 30/42). 8 PARTIAL → READY: m_score, z_score, fii_dii_cash_net, fii_dii_fno_positioning, earnings_beat_rate, news_volume, mom_6m_adj, mom_12m_adj, promoter_qoq, short_selling_signal. Remaining non-READY: sentiment_7d (PARTIAL — needs FinBERT, scoped in plan 0005 F1.4), screener_final_composite (PROPOSED — F3 deliverable). status_reason text rewritten with hard data (n_periods, sign-match rates, correlation values).
- **promoter_qoq diagnostic.** Raw v1↔v2 corr 0.42-0.63 was misleading — median |diff|=0.000 across 1,896 stocks; on the subset where both >0.05 absolute (n=303), **sign-match=97.4%**. Reclassified READY.
- **nselib unified ingest.** [sources/nselib_pull.py](sources/nselib_pull.py) single CLI `--source {bulk,corp,short,fii_pos,fii_cash,mf_nav,indices,surveillance,daily_forward,all}`. Backfilled: 13,652 bulk deals, 4,516 corp actions, 30,692 short-selling rows, 220 FII positioning rows, 38,830 MF NAVs, 6,243 smart-beta index rows.
- **Smart-beta indices populated.** `nse_index_history` now has 9 of 12 NSE smart-beta indices, ~720 rows each (2023-06 → 2026-04). Validation: our `value_composite` tracks NIFTY200 VALUE 30 at Pearson 0.984 with 5/5 sign-matches.
- **Forward-only cron wired.** `0 14 * * * /home/ubuntu/alpha-signal-v2/run_daily_forward.sh` runs at 7:30 PM IST (after NSE EOD), captures FII/DII cash flow + F&O positioning + ASM list. ASM works (146 rows); GSM and F&O ban parsers have known bugs (deferred).
- **Three new reference docs.** [docs/reference/data-playbook.md](docs/reference/data-playbook.md) (43KB strategy + 6 reconstruction patterns), [docs/reference/api-endpoints.md](docs/reference/api-endpoints.md) (per-endpoint catalog), [docs/reference/paid-data-sources.md](docs/reference/paid-data-sources.md) (₹5K/mo budget allocation, Sensibull skip rationale).
- **Three plans alive.** [0003-mother-plan.md](docs/plans/0003-mother-plan.md) is now the **project blueprint** — three concurrent tracks (Engineering ✅ / Intelligence D-phases / Factor-depth F-phases). [0004-pit-reconstruction.md](docs/plans/0004-pit-reconstruction.md) phases 2/3/6 implemented. [0005-100-factors-and-model.md](docs/plans/0005-100-factors-and-model.md) draft — F1 (data: Screener+F&O+Kite+NLP) → F2 (50 new factors → ~100 total) → F3 (IC weighting + orthogonalization + MVO + Barra-style risk).
- **Backtest harness validates v1 archive.** [tools/backtest_pit.py](tools/backtest_pit.py) reproduces every C13b headline t-stat (promoter 3.20 SMALL, EY 3.13 SMALL, piotroski 2.81 SMALL, B/P 2.54 SMALL, avg_delivery 2.49 SMALL, cf_accruals 3.20 MID — all within rounding). v1 archive remains canonical reference; v2 is canonical going forward.
- **Bug found, not fixed.** [db.py:181](db.py#L181) `upsert_df` uses `INSERT OR REPLACE` which nulls non-updated columns. Caused mid-session data loss; recovered with full reconstruction. Fix proposed: switch to `INSERT ... ON CONFLICT UPDATE`. Tracked in next-actions.

### Plan status changes

- **[0004-pit-reconstruction.md](docs/plans/0004-pit-reconstruction.md):** add `## Implementation notes — 2026-05-04` section noting Phase 2 (coverage gaps), Phase 3 (methodology corrections — splits + promoter_qoq diagnostic), Phase 6 (operational — apply_splits, full reconstruction harness) shipped this session. Status remains `active` until Phase 4 (PIT depth past 2023) is addressed.
- **[0005-100-factors-and-model.md](docs/plans/0005-100-factors-and-model.md):** Status `draft` → `active`. The plan was reviewed and absorbed into the mother plan as the F-track. Owner has committed to Screener Premium subscription as the F1.1 trigger.
- **[0003-mother-plan.md](docs/plans/0003-mother-plan.md):** Already updated to project-blueprint state with F-track absorbed. Status remains `active`.

### Files to add to .gitignore (proposed)

- `output/*.log` (covers daily_forward.log, rerun.log, future ones)
- `tools/__pycache__/`
- `.playwright-mcp/` (verification screenshots from prior sessions)
