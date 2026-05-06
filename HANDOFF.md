# HANDOFF

> Overwritten at the end of each session per CLAUDE.md session protocol. If you're starting a new session: read this, then CLAUDE.md, then any plan or ADR linked below.

**Last updated:** 2026-05-06 (Amit Bhagat + Claude Code)
**Current branch:** `master` (4 commits ahead of origin/master — push blocked by harness policy, see "Open questions" #7)
**HEAD:** `25f71a2` fix: split parser at 100% + smart-beta indices at 13 (was 9) — *working tree clean*

---

## Where I am

Multi-day session that crossed PIT reconstruction, paid-data evaluation, the cleanup of all 10 PARTIAL factors, and the introduction of a third project track. Started "what data sources have we missed?" → discovered nselib unlocks ~5 historical APIs v1 thought were blocked → ingested 4 streams (bulk deals, corp actions, short selling, FII positioning, MF NAV, smart-beta indices) → wrote three new plans → audited factor count (42 vs ~100 at small quant shops) → drafted plan 0005 to scale to 100 factors + factor model → cleaned up partials so 40/42 are now READY → consolidated the F-track into the mother plan as the project blueprint. **All changes are unstaged.**

## What works

- **Smart-beta index history live — 13 indices.** All NSE smart-beta + benchmark indices populated in `nse_index_history`. The 9 from prior session (~720 rows each, 2023-06 → 2026-04) plus 4 backfilled today: NIFTY100 LOW VOLATILITY 30, NIFTY ALPHA LOW-VOLATILITY 30, NIFTY200 QUALITY 30, NIFTY100 EQUAL WEIGHT — 743 rows each, 2023-05-08 → 2026-05-06 (more current than the older 9). Old 9 will refresh on next cron tick. Validation: `value_composite` top-30 LARGE+MID portfolio tracks NIFTY200 VALUE 30 at **Pearson 0.984** with 5/5 sign-matches.
- **nselib ingest pipelines live.** [sources/nselib_pull.py](sources/nselib_pull.py) — single CLI `--source {bulk,corp,short,fii_pos,fii_cash,mf_nav,indices,surveillance,daily_forward,all}`. Ingested: bulk deals (13,652 rows, 12mo), corp actions (4,516 rows, 24mo), short selling (30,692 rows, 24mo), FII positioning (220 rows, ~3mo), MF NAV (38,830 NAVs across 12 schemes).
- **Forward-only daily cron wired.** `0 14 * * *` runs [run_daily_forward.sh](run_daily_forward.sh) (7:30 PM IST, after NSE EOD). Captures FII/DII cash flow + F&O positioning + ASM list — sources with no historical archive that must accumulate forward. ASM working (146 rows); GSM + F&O ban parsers have known bugs (deferred).
- **Split adjustment now full coverage.** [tools/compute_splits.py](tools/compute_splits.py) regex extended to handle the canonical NSE "Face Value Split (Sub-Division) - From Rs X/- Per Share To Rs/Re Y/- Per Share" format (was only catching the legacy "Stock Split From Rs.X to Rs.Y" form). Parse rate **104/207 → 207/207 (100%)**. [tools/apply_splits.py](tools/apply_splits.py) reapplied: `stock_prices.adj_close` now adjusted across **102,315 (sid, date) rows on 188 stocks** (was 58,263 / 101). Apples-to-apples diagnostic across 12 v1 snapshot dates: raw-close mom_12m vs v1 = 0.74 mean Pearson; adj-close mom_12m vs v1 = **0.86 mean Pearson** — split adjustment delivers **+0.12 Pearson lift** unambiguously. The earlier 0.67→0.78 figure used a different methodology (different lookback window). Remaining gap to v1 = dividend adjustment (deferred).
- **PIT reconstruction harness mature.** [tools/reconstruct_pit.py](tools/reconstruct_pit.py) computes 22+ signals across 7 monthly snapshot dates (2025-11 → 2026-05) for 2,448 stocks. New functions added today: `pit_earnings_beat_rate`, `pit_news_volume`. Validation guardrails + checkpoint log + `--skip-existing` flag in place. Latest full run: 17,136 rows, all 7 dates ✅.
- **Backtest harness validates v1 archive exactly.** [tools/backtest_pit.py](tools/backtest_pit.py) reproduces every C13b headline t-stat from v1 within rounding: promoter t=3.20 SMALL ✅, earnings_yield t=3.13 SMALL ✅, piotroski t=2.81 SMALL ✅, book_to_price t=2.54 SMALL ✅, avg_delivery t=2.49 SMALL ✅, cf_accruals t=3.20 MID ✅. New v2 signals show provisional t-stats (n=5, diagnostic only).
- **Factor registry: 40/42 READY.** [db.py BACKTEST_SIGNALS](db.py) flipped 8 PARTIAL → READY this session: m_score, z_score, fii_dii_cash_net, fii_dii_fno_positioning (status flip — data was always there); earnings_beat_rate, news_volume (built v2 compute functions); mom_6m_adj, mom_12m_adj (applied splits); promoter_qoq (diagnostic showed 97.4% sign-match when both non-zero); short_selling_signal (PROPOSED → READY, was already wired).
- **Three reference docs in repo.** [docs/reference/data-playbook.md](docs/reference/data-playbook.md) (43KB, 6 reconstruction patterns), [docs/reference/api-endpoints.md](docs/reference/api-endpoints.md) (per-endpoint catalog with NSE quirks), [docs/reference/paid-data-sources.md](docs/reference/paid-data-sources.md) (₹5K/mo budget playbook + Sensibull skip rationale). Extracted from Claude private memory (which user couldn't see) into checked-in repo.
- **Three plans alive.** [0003-mother-plan.md](docs/plans/0003-mother-plan.md) is now the **project blueprint** — three tracks (Engineering ✅ / Intelligence D-phases / Factor-depth F-phases). [0004-pit-reconstruction.md](docs/plans/0004-pit-reconstruction.md) most phases complete this session. [0005-100-factors-and-model.md](docs/plans/0005-100-factors-and-model.md) draft of F1/F2/F3 (data → 50 new factors → factor model upgrade).

## What's broken or half-built

- ~~upsert_df fix~~ **Resolved 2026-05-05.** Fix shipped in `88a2fa9`; regression test `test_upsert_df_preserves_untouched_columns` added to [tests/test_smoke.py](tests/test_smoke.py) (uses in-memory SQLite, no real-DB pollution). Audited every upsert_df target table — all 15 (`daily_snapshots_pit`, `daily_picks`, `forensic_scores`, `daily_snapshots`, `piotroski_scores`, `sentiment_scores`, `vix_history`, `macro_indicators`, `smart_money_scores`, `macro_sector_signals`, `insider_signals`, `analyst_consensus`, `stocks`, `regime_state`, `nse_index_history`) resolve real PKs; zero hit the legacy `INSERT OR REPLACE` fallback. Partial reconstructions (`--signal X`) are now safe.
- **Surveillance parser bugs.** [sources/nselib_pull.py](sources/nselib_pull.py) `pull_surveillance_today()` has `'list' object has no attribute 'get'` for GSM and F&O ban list. ASM works (146 rows). Cron is firing the broken paths nightly; harmless except for noise in `output/daily_forward.log`.
- ~~3 smart-beta indices missing~~ **Resolved 2026-05-06.** SMART_BETA_INDICES list updated with the correct NSE names (`NIFTY100 LOW VOLATILITY 30`, `NIFTY ALPHA LOW-VOLATILITY 30`); also added `NIFTY200 QUALITY 30` and `NIFTY100 EQUAL WEIGHT` (bonus). All 4 backfilled with 743 rows each via monthly chunks (the wide-range query truncates at ~70 rows — important gotcha). The discarded names from the original list (`NIFTY100 LOWVOL30`, `NIFTY ALPHALOWVOL`, `NIFTY LOW VOL 50`) all returned empty against NSE's API.
- ~~Split adjustment is partial~~ **Resolved 2026-05-06.** Parse rate now 207/207 (100%). See "Split adjustment now full coverage" above.
- **Dividend adjustment missing entirely.** v1's yfinance Adj Close adjusts both splits and dividends. v2's adj_close only adjusts splits. Largest remaining contributor to the v1↔v2 momentum gap. Needs a second adjustment pass over `corporate_actions` for DIVIDEND events.
- **2 signals legitimately not READY.** `sentiment_7d` PARTIAL (no FinBERT classifier in repo — needs F1.4); `screener_final_composite` PROPOSED (by-design end-state, waits on F3 orthogonalization). Both have explicit owners in plan 0005; not bugs.
- **No CHANGELOG entry yet** for today's work — proposed below.
- **README.md still stale** — same staleness flagged in 2026-05-02 HANDOFF; not addressed.

## Next 3 actions (in order, concrete)

1. **Push 4 commits to origin/master.** Direct push to master is currently blocked by harness policy (`Bash: git push origin master` denied in this session). Either grant the permission via `claude config`, or cherry-pick to a `release/2026-05-06` branch and PR. Commits queued: `88a2fa9` PIT/factor cleanup, `6c91691` cockpit DAG, `c08929a` upsert_df regression test, *new* splits-regex + smart-beta indices.
2. **Add dividend adjustment pass.** Largest remaining v1↔v2 momentum gap (~5-10 pp Pearson). Extend [tools/compute_splits.py](tools/compute_splits.py) to parse DIVIDEND events from `corporate_actions` (or write a sibling `tools/compute_dividends.py`), then update [tools/apply_splits.py](tools/apply_splits.py) (or rename to `apply_corporate_adjustments.py`) to factor dividends in. Use total-return convention `(close - dividend) / close` cumulative. ~3 hours.
3. **Subscribe to Screener Premium (₹420/mo) and ship F1.1.** Highest-leverage paid-data move per [paid-data-sources.md](docs/reference/paid-data-sources.md). Build [sources/screener_pull.py](sources/screener_pull.py) with the cookie-jar + Excel-export pattern. ~2 dev-days. Unblocks 15 Tier-1 factors (CCC, FCF yield, ROIC, ROIIC, gross margin trend, Sloan accruals, NWC factors).

## Don't do

- ~~Don't run `python -m tools.reconstruct_pit --signal X`~~ **Cleared 2026-05-05.** Partial reconstructions are now safe (regression test in [tests/test_smoke.py](tests/test_smoke.py) verifies the upsert_df contract).
- **Don't subscribe to Sensibull or Trendlyne yet.** Sensibull has no retail API ([paid-data-sources.md](docs/reference/paid-data-sources.md)). Trendlyne lost ~70% of its marginal value when nselib unlocked the historical APIs. Screener Premium is the only paid sub with non-overlapping data; everything else is convenience.
- **Don't run all 5 nselib backfills concurrently** ([sources/nselib_pull.py](sources/nselib_pull.py) `--source all`). The 2-second rate-limit floor adds up; `all` takes ~45 min sequential, and concurrent calls risk cookie-session issues. Prefer staggered single-source runs.
- **Don't apply additional splits via [tools/compute_splits.py](tools/compute_splits.py) without re-running [tools/apply_splits.py](tools/apply_splits.py) afterward.** The latter rebuilds `adj_close` from scratch — it's idempotent but fragile if you forget. Sequence: compute → apply → reconstruct.
- **Don't query nselib `cm.index_data` with date ranges wider than ~3 months.** The endpoint silently caps responses at ~70 trading days and returns the most-recent slice. Always paginate via `_months_back(N)` (monthly chunks). The 4 newly-added indices were initially backfilled with 12-month chunks and only got 210 rows each before re-running.
- **Don't mark `sentiment_7d` or `screener_final_composite` as READY.** Both are scoped in plan 0005 (F1.4 NLP setup; F3 factor model). Reclassifying them prematurely defeats the purpose of the status taxonomy.
- **Don't add factors past ~100 before F3 ships.** Plan 0005 has explicit gate: 60th+ factors add noise without orthogonalization. The 100→200 expansion is deferred until F3's marginal-IC gate is in production.
- **Don't `git add .` or `git add -A`** — it'll pull in `tools/__pycache__/`, possibly `output/daily_forward.log`, and any stray `.playwright-mcp/` artifacts. Stage explicit files.

## Open questions for me (decisions you need to make)

1. **ADR for the F-track parallel architecture?** The mother plan now describes three concurrent tracks with explicit non-blocking integration points (D17↔F3.3, D18↔F3.2). My take: **yes, propose ADR 0009** — it's a structural decision a future contributor needs context for, and it's load-bearing on resource-allocation calls. Draft below.
2. **Single commit or split today's work?** Diff is large but tightly coupled (the docs reference the tools, the plans reference the docs, registry status flips reference the new tools). My take: one commit. The pieces don't make sense in isolation.
3. ~~Fix upsert_df bug now or after F1.1 ships?~~ **Resolved 2026-05-04.** SQL fix shipped in `88a2fa9`. Regression test still owed — see action #1.
4. **Should the registry ship a `pit_column_v2` audit?** A few signals had `pit_column_v2: None` while their reconstruction function exists (fixed inline this session for `news_volume`, `short_selling_signal`, `earnings_beat_rate`). Worth a one-shot diagnostic that diffs PIT_COLUMNS in [tools/reconstruct_pit.py](tools/reconstruct_pit.py) against the registry's `pit_column_v2` values? My take: **yes, 5-line `python -m tests.audit_registry`** — catch drift early.
5. **Plan 0004 status — Implemented or close it?** Today's session executed phases 2 (coverage gaps), 3 (methodology fixes for momentum + promoter_qoq), and 6 (operational — apply_splits, full reconstruction). Phases 4 (depth — extend PIT past 2023) and 5 (backtest harness) are partially done. My take: leave Status: active, add an "Implementation notes" section documenting today's progress, archive when full PIT depth ships.
6. ~~Should `output/daily_forward.log` be added to .gitignore?~~ **Resolved 2026-05-06.** `.gitignore` already contains `output/*.log` (and `__pycache__/`, `.playwright-mcp/`). Verified during this session.
7. **Push permission to master.** Direct push to `master` is denied by the harness ("Pushing directly to master (default branch) bypasses PR review"). Solo-repo so the policy's effectively self-imposed. Two options: (a) add a Bash permission rule via `claude config` for `git push origin master` (simplest), (b) switch to a feature-branch + PR flow (introduces overhead for a one-person project). My take: **(a) for now**, revisit when collaborators arrive.

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
- **upsert_df bug fixed.** [db.py:178-222](db.py#L178-L222) switched from `INSERT OR REPLACE` (DELETE+INSERT, nulls every column not in df) to `INSERT ... ON CONFLICT(pk) DO UPDATE SET col=excluded.col` (update in place, only touches columns present in df). Added `_table_pk()` helper that reads PK columns via `PRAGMA table_info` and caches them. Edge cases: df with only PK cols → `INSERT OR IGNORE`; tables with no declared PK → fallback to `INSERT OR REPLACE` (legacy, should be rare). Regression test still owed.

### Plan status changes

- **[0004-pit-reconstruction.md](docs/plans/0004-pit-reconstruction.md):** add `## Implementation notes — 2026-05-04` section noting Phase 2 (coverage gaps), Phase 3 (methodology corrections — splits + promoter_qoq diagnostic), Phase 6 (operational — apply_splits, full reconstruction harness) shipped this session. Status remains `active` until Phase 4 (PIT depth past 2023) is addressed.
- **[0005-100-factors-and-model.md](docs/plans/0005-100-factors-and-model.md):** Status `draft` → `active`. The plan was reviewed and absorbed into the mother plan as the F-track. Owner has committed to Screener Premium subscription as the F1.1 trigger.
- **[0003-mother-plan.md](docs/plans/0003-mother-plan.md):** Already updated to project-blueprint state with F-track absorbed. Status remains `active`.

### Files to add to .gitignore (proposed)

- `output/*.log` (covers daily_forward.log, rerun.log, future ones)
- `tools/__pycache__/`
- `.playwright-mcp/` (verification screenshots from prior sessions)
