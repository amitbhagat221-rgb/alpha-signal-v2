# HANDOFF

> Overwritten at the end of each session per CLAUDE.md session protocol. If you're starting a new session: read this, then CLAUDE.md, then any plan or ADR linked below.

**Last updated:** 2026-05-10 (Amit Bhagat + Claude Code) — F-track Phase A landed end-to-end + Phase B began
**Current branch:** `master` — clean, in sync with `origin/master` (9 commits today)
**HEAD:** `4b98084` — docs: ADR 0011 + plan-0005 status + 2026-05-10 changelog

---

## Where I am

F-track went from "thin slice on RELI" to "production-ready data layer" today. F1.1 (xlsx scraper) covers 86.6% of the universe — 681,256 rows of fundamentals across 2,119 stocks. F1.2 (schedules JSON scraper) module is shipped; universe scrape is **still running in the background** (PID 74316, started 2026-05-10 12:17 UTC, at stock ~83 of 2,448 when last checked, likely finishing around 17:30–18:00 UTC). Two F-track factors live — `signal_roic` and `signal_fcf_yield` — both in `pipeline.py` but neither in scoring weights (no validated t-stat). Big landmine surfaced and fixed: financial-sector exclusion was silently disabled across 5 modules since v2 began; 248 financials had been quietly entering main-screener scoring.

## What works

- **F1.1 — Screener Premium xlsx scraper, universe-complete.** [sources/screener_pull.py](sources/screener_pull.py) (commits `1757abf`, `bb6df46`). 2,119 / 2,448 stocks pulled; 100% LARGE, 100% MID, 85% SMALL. 681,256 rows in `fundamentals_screener`. 329 fetch failures (concentrated in SMALL — delisted, newly-listed, non-standard Excel templates). Final log line: `total rows: 681256 | failures: 329/2448`. Idempotent: PK `(sid, period_end, period_type, line_item)`, INSERT OR REPLACE.
- **F1.2 — Screener schedules JSON scraper, module shipped.** [sources/screener_schedules.py](sources/screener_schedules.py) (commit `6bd5a38`). Hits the undocumented endpoint `GET /api/company/{cid}/schedules/?parent=<row>&section=<section>&consolidated` to expand "+"-marked rows the xlsx rolls up. Discovered via reading `https://cdn-static.screener.in/js/company.customisation.js` for `Company.showSchedule` then `utils.js` for `urls.schedules`. RELI smoke test wrote 276 rows / 23 new line items including `Trade Payables` (12 fiscal years), `Long term Borrowings`, `Short term Borrowings`, `Lease Liabilities`, `Plant Machinery`, `Land`, `Buildings`, `Trade receivables`, `Inventories`, `Loans n Advances`. Long format absorbs new line_items without DDL — see [ADR 0011](docs/decisions/0011-long-format-for-new-fundamentals-tables.md).
- **F1.2 universe scrape, in flight.** Running detached via `nohup` since 2026-05-10 12:17 UTC (PID 74316). Output to [logs/schedules_universe_20260510_1217.log](logs/schedules_universe_20260510_1217.log). Rate ~10s/stock observed (slower than F1.1's 7s — 4 schedule calls per stock plus the inter-step delays). ETA finish around 17:30 UTC. **It is not in claude's foreground task tracker — claude won't notify when it finishes.** Check with `ps -ef | grep screener_schedules` or tail the log.
- **ROIC factor — 1,501 stocks scored, in pipeline.** [signals/roic.py](signals/roic.py) (commits `9dce5d1`, `bbdf5ce`, `1a94c22`). NOPAT = (PBT + Interest) × (1 − Tax/PBT); IC = Equity + Reserves + Borrowings; 3-year median across calendar years with IC ≥ ₹50 cr floor. Top-5 LARGE: NESTLE 65%, TCS 47%, HZNC 46%, BRITANNIA 41%, MARICO 38% — textbook quality compounders. Median ROIC LARGE 17%, MID 16%, SMALL 12% (consistent with capital-light premium). Wired into `pipeline.py` as `signal_roic`; runs in 0.4s.
- **FCF Yield factor — 1,195 stocks scored, in pipeline.** [signals/fcf_yield.py](signals/fcf_yield.py) (commit `f43e065`). FCF = OCF − Capex (Capex ≈ Δ(Net Block + CWIP) + Depreciation), 3-year median FCF / current market cap. Sanity: INFY 5.0%, TCS 4.4%, BRITANNIA 1.6%, RELI 0.4%. Wired as `signal_fcf_yield`; runs in 0.3s.
- **Financial-sector exclusion fixed — was a silent no-op for the entire history of v2.** [config.py:183](config.py#L183) (commit `af94835`). `SCREEN["financial_sectors"] = ["Financial Services"]` but `stocks.sector` actually has `"Financials"` (no "Services"). Fix is the one-character change. Affected 5 modules: `signals/{roic,accruals,piotroski,forensic}.py`, `tools/reconstruct_pit.py`. After fix: piotroski_scores rows 2,448 → 2,200 (financials correctly excluded); ROIC universe 94 → 72 LARGE (with banks at 3-5% ROIC dropped from the bottom).
- **`accruals.py` partial-composite-for-financials fixed.** [signals/accruals.py:283-285](signals/accruals.py#L283-L285) (commit `3321827`). Even after the exclusion was repaired, 244 of 248 financials were still getting a non-null `accruals_signal` because EPS-CV + beat-rate alone produced a partial composite when the accrual ratios came through as NaN. Now explicitly None-d for financial sids.
- **Surveillance parser fixed.** [sources/nselib_pull.py:549-595](sources/nselib_pull.py#L549-L595) (commit `bb6df46`). NSE GSM API returns a bare list (`gsmStage`, `survDesc` fields) not `{"data": [...]}`; F&O ban via nselib returns a bare list (today empty) instead of a DataFrame. Both crashed silently in the nightly cron. After fix: ASM/GSM/F&O all write cleanly.
- **PIT archive refreshed with financials-fix; v2_recompute t-stats now reflect corrected logic.** Ran `tools/reconstruct_pit.py` (215s, 7 dates × 26 signals × 2,448 stocks → 17,136 rows in `daily_snapshots_pit`) followed by `tools/backtest_pit.py` (132 rows in `pit_ic_by_tier_v2`). Notable post-fix shifts: `cf_accruals_ratio` MID t=−2.89 → −1.93, `bs_accruals_ratio` SMALL t=−2.49 → −2.25 (financials had been amplifying these signals; cleaner sample is honestly weaker). piotroski / z_score / quality_composite barely moved. v1_archive rows stay frozen as historical reference per [ADR 0012](docs/decisions/0012-pit-archive-refresh-on-signal-fix.md).
- **ADRs 0011 and 0012 filed.** [docs/decisions/0011-long-format-for-new-fundamentals-tables.md](docs/decisions/0011-long-format-for-new-fundamentals-tables.md) — long for F-track and onward; legacy wide tables stay wide. [docs/decisions/0012-pit-archive-refresh-on-signal-fix.md](docs/decisions/0012-pit-archive-refresh-on-signal-fix.md) — refresh v2 PIT archive whenever signal logic changes; v1 archive is frozen reference; v1-match validates port correctness only, not financial truth.
- **plan-0005 status updated and CHANGELOG entry for 2026-05-10.** Both in commit `4b98084`.
- **Cockpit Command Centre shipped.** New `/command` route with 8 collapsible sections: mission control, factor library (with `[MODEL]` vs `[LIBRARY]` badges), data layer, plans (parsed from `docs/plans/*.md` frontmatter), pending actions (parsed from HANDOFF), open questions, ADRs, recent commits. Updates whenever HANDOFF / plans / git change — no live polling, just re-renders on page load. Reachable from sidebar (compass icon) on desktop, "More" sheet on mobile. [cockpit/app.py:198-205](cockpit/app.py#L198-L205), [cockpit/templates/command.html](cockpit/templates/command.html).
- **Everything from prior sessions still works.** PIT-strict corporate-action adjustment, PIT reconstruction harness, nselib unified ingest, factor registry at 40/42 READY, four reference docs, four other live plans (0001 regulatory, 0002 macro, 0003 mother plan, 0004 PIT).

## What's broken or half-built

- **Schedules universe scrape still in flight.** Started 2026-05-10 12:17 UTC, observed ~83/2,448 stocks done within 10 minutes, ETA finish around 17:30 UTC. Until it finishes, only ~80 stocks have Trade Payables / ST/LT Borrowings / asset-composition data. CCC and other working-capital factors are gated on this completion. Process is detached — claude won't get a notification.
- **ROIC and FCF Yield are not backtest-able yet — no PIT helpers.** They compute today's value (`signals/roic.py`, `signals/fcf_yield.py`) and persist via pipeline. But neither has a `pit_roic(sid, eval_date)` / `pit_fcf_yield(sid, eval_date)` in `tools/reconstruct_pit.py`, so the historical 36-period archive doesn't include them — meaning `tools/backtest_pit.py` can't compute their t-stats. Until the PIT helpers ship, both factors are "live but invisible to validation". The retrofit is in next-action #2.
- **No factor is in the production scoring composite from F-track yet — by design.** ROIC, FCF Yield (and every future F-track factor) sit in their own snapshot tables. Promotion to `SCREEN.weight_tiers` is gated on backtest t-stat ≥ 1.5 in any tier. (Listed for visibility, not as a fix-it item.)
- **F1 / F1.2 not in cron / pipeline.** Both `sources.screener_pull` and `sources.screener_schedules` are manual-run only. There's no daily incremental, no weekly full-universe schedule, no cookie-health probe. HANDOFF question 1 from yesterday is still open.
- **`stocks.market_cap_cr` is misnamed.** Values are stored in raw rupees, not crores (RELI shows 1.83×10^13). Fixed locally in [signals/fcf_yield.py:39-46](signals/fcf_yield.py#L39-L46) with a `1e7` divisor and a comment. Other consumers (cockpit/api.py, output/email_sender.py) treat the value as-is and could be displaying wrong units. Worth checking before relying on those outputs.
- **F1.1 had 329 fetch failures, all in SMALL tier.** Logged in `screener_pull_errors`. Mostly delisted / newly-listed / non-standard Excel templates. Could be retried later but not a blocker.
- **Cockpit `/command` page (Command Centre) — new, may need polish.** [cockpit/templates/command.html](cockpit/templates/command.html) + [cockpit/api.py:get_command_centre()](cockpit/api.py). Renders 8 collapsible sections: mission control / factor library / data layer / plans / pending actions / open questions / ADRs / recent commits. Server-rendered with `<details>` collapsibles, no JS dependency beyond what base.html already loads. Tested via `curl /command` — HTTP 200, 54 KB. May want visual iteration once you see it in the browser; flow-chart-style visualization (vs the current cards-and-tables) is a possible v0.2.
- **2 signals legitimately not READY.** `sentiment_7d` PARTIAL (no FinBERT, F1.4 in plan 0005); `screener_final_composite` PROPOSED (F3 deliverable). Not bugs.

## Next 3 actions (in order, concrete)

> **Goal architecture (clarified 2026-05-10):** ~100 factor modules, all backtested historically, **two-tier**: validated factors (e.g. t ≥ 1.5 in some tier) drive `scoring/screener.py` daily picks; non-validated factors sit in a personal factor library — explorable, not voting. Module-write throughput, PIT-helper coverage, and the library surface are the three workstreams. See [memory: factor library vs production model](file:///home/ubuntu/.claude/projects/-home-ubuntu-alpha-signal-v2/memory/feedback_factor_count_vs_weighting.md).

1. **Wait for F1.2 universe scrape to finish, then verify coverage.** Expected ~17:30 UTC. Check: `ps -ef | grep screener_schedules`, `tail -10 logs/schedules_universe_*.log`, `sqlite3 data/alpha_signal.db "SELECT COUNT(DISTINCT sid) FROM fundamentals_screener WHERE line_item='Trade Payables';"` (should be ~1,800–2,000 if successful). If stuck or rate-limited (HTTP 429), it'll have stopped mid-run. Errors in `screener_pull_errors`.
2. **Batch-build factors + PIT helpers in pairs.** Module-write throughput is the bottleneck. Each new factor ships with two functions: `signals/<x>.py:compute()` (today's value, runs in pipeline) AND a `pit_<x>(sid, eval_date)` helper added to `tools/reconstruct_pit.py` (so the historical 36-period archive can be re-reconstructed and the factor backtested). Annual fundamentals: knowable only when `period_end + 90 days <= eval_date` — that's the PIT discipline. Without the PIT helper the factor can't be backtested, only computed today. Concrete next 8 (data either landed or arriving with the in-flight scrape):
   - `cash_conversion_cycle` (CCC = DSO + DIO − DPO; Trade receivables, Inventories, Trade Payables from F1.2 + Sales, Raw Material Cost from F1.1)
   - `gross_margin_trend` (Sales − RM − Power − Employee; Y0 vs Y-3)
   - `roiic` (Δ NOPAT / Δ Invested Capital — marginal capital efficiency)
   - `working_capital_intensity` ((Trade Recv + Inv − Trade Pay) / Sales)
   - `debt_structure` (Short-term Borrowings / Total Borrowings — funding fragility)
   - `asset_tangibility` ((Land + Buildings + Plant Machinery) / Net Block — hard-asset composition)
   - PIT-helper retrofit for `roic` and `fcf_yield` (currently only have today's value, not history)
3. **Run end-to-end backtest of the first batch.** Once 6+ new factors + PIT helpers exist: extend `tools/reconstruct_pit.py`'s function list → re-run the 36-period reconstruction → extend `SIGNAL_COLUMN_MAP` in `tools/backtest_pit.py` → re-run backtest. Output: t-stats per (factor, cap_tier). Validation threshold (proposed): `t ≥ 1.5` in any tier promotes to "model"; below stays in "library". Don't change `SCREEN.weight_tiers` mechanically — review the t-stats first, then promote in batches.

**Then in subsequent sessions:** keep batching (~6 modules + PIT helpers per session, ~30–45 min each), re-reconstruct + re-backtest. Build the library surface (cockpit page `/factors` or `notebooks/factor_library.ipynb`) once factor count is high enough that browsing matters (~30+).

**Operational debt to close after a few factor batches:** wire `sources.screener_pull` + `sources.screener_schedules` into a weekly cron (Sun 02:00 IST, clear of the daily 03:30 UTC pipeline) + cookie-health probe surfaced in cockpit `/data`. Fundamentals refresh quarterly so weekly is sufficient. Use `earnings_calendar` for the ~200 stocks expected to file in the week for daily incremental pulls. Not blocking factor work but should land before mid-June so we don't ride a stale cookie.

## Don't do

- **Don't edit `SCREEN.weight_tiers` mechanically when shipping a factor.** Module ships, PIT helper ships, factor goes through reconstruction + backtest, **then** promotion is a deliberate review step against the threshold (proposed: t ≥ 1.5 in any tier). Below threshold → factor stays in the library, accessible but not voting. The recurring mistake to avoid: conflating "shipped" with "in production scoring".
- **Don't ship a factor module without a PIT helper alongside.** A `signals/<x>.py` without a corresponding `pit_<x>(sid, eval_date)` in `tools/reconstruct_pit.py` is a factor that *can't be backtested*. It computes daily and accumulates forward-paired data, but you can't ask "what was its IC over the last 36 months?" until the PIT version exists. The pair is the unit of work, not the module alone.
- **DO re-run `tools/reconstruct_pit.py` after any signal-side fix.** Per [ADR 0012](docs/decisions/0012-pit-archive-refresh-on-signal-fix.md) — `v1_archive` t-stats validate port correctness, not financial truth. v2's archive (`daily_snapshots_pit`) should reflect v2's actual current logic. Cost is ~215 sec for the full 7-date × 26-signal run; benefit is correct numbers in `v2_recompute`. After today's financials-fix reconstruction: `cf_accruals_ratio` MID t-stat moved from −2.89 → −1.93, `bs_accruals` SMALL moved −2.49 → −2.25. This is the actual signal quality and what future weight assignments should use.
- **Don't migrate the legacy wide tables to long format.** Per [ADR 0011](docs/decisions/0011-long-format-for-new-fundamentals-tables.md) the boundary is at the F-track edge. Migrating the legacy wide tables would risk breaking the four signals (Piotroski, Forensic, Accruals, Consensus) that reproduce C13b t-stats exactly.
- **Don't run `screener_pull` and `screener_schedules` concurrently.** Same cookie, doubled request rate, easy way to trip Screener's bot detection. The schedules scrape is alive right now (PID 74316) — don't fire anything else against screener.in until it ends.
- **Don't `source ~/alpha-signal/run_pipeline.sh` from inside claude or any non-interactive context.** It runs the v1 pipeline at the bottom, not just exports. Use `eval "$(grep '^export SCREENER' ~/alpha-signal/run_pipeline.sh)"` to load only the SCREENER vars.
- **Don't share or paste the Screener cookie file.** Single-user, chmod 600. The `sessionid` value gives full account access.
- **Don't auto-`--login` from cron without testing first.** Repeated login POSTs from the same IP can look like credential stuffing. Trust the cached cookie first; only re-login on observed 401/302-to-login.
- **Don't switch `fundamentals_screener` to wide format.** Per ADR 0011 the long format is intentional and will keep absorbing new line items as Screener adds them.
- **Don't reintroduce `tools/apply_splits.py` or `stock_prices.adj_close`.** Per ADR 0010, PIT correctness depends on adjustments composing at signal-compute time.
- **Don't rename `stocks.market_cap_cr` globally without an ADR.** It's misnamed (actually rupees, not crores) but the rename touches `cockpit/api.py`, `output/email_sender.py`, every signal that filters by it. Worth a deliberate decision; do not silently rename in passing.
- **Don't query nselib `cm.index_data` with date ranges wider than ~3 months.** Endpoint silently caps at ~70 trading days. Carried-forward guardrail.
- **Don't run all 5 nselib backfills concurrently.** 2-second floor + concurrent calls risk cookie-session issues. Stagger.
- **Don't mark `sentiment_7d` or `screener_final_composite` as READY.** Both scoped in plan 0005.
- **Don't add factors past ~100 before F3 ships.** Plan 0005 explicit gate.
- **Don't `git commit --amend` / `git add .` / `git add -A`.** Carried-forward rules.

## Open questions for me (decisions you need to make)

1. **Validation threshold for "model vs library"?** Proposing t ≥ 1.5 in any cap-tier as the cutoff for promotion to scoring weights. v1's C13b rubric uses |t| ≥ 2.5 → 1.0× / 1.5–2.5 → 0.5× / 0.5–1.5 → 0.2×; the 0.2× tier is essentially "library, but lightly voting". Two clean choices: (a) hard cut at 1.5 — anything below stays purely library; (b) keep the C13b 4-tier rubric with the 0.5–1.5 band as 0.2×-weighted (effectively a "weak library member" that still nudges scoring). **My take:** (a). The point of the library is exploration, not nudging. Either you've earned a real weight (≥1.5) or you're research only.
2. **Should we file an ADR documenting "PIT archives are immutable; bug fixes are forward-only"?** Today we explicitly chose not to re-run `tools/reconstruct_pit.py` to "fix" historical t-stats after the financials-fix. The reasoning isn't obvious — future-me might wonder why we accepted contaminated historical archives. ~10 min ADR. **My take:** yes, ADR 0012 — it's a recurring pattern (any signal-side fix has the same forward-only property) and worth recording once.
3. **F1.x cadence — weekly or daily incremental?** HANDOFF question 1 from yesterday, still open. Annual fundamentals refresh quarterly; daily is wasteful. Daily incremental for stocks expected to file this week (via `earnings_calendar`) + weekly full universe seems right. Run from cockpit cron at Sunday 02:00 IST. **My take:** weekly full + daily incremental, exactly as I proposed yesterday.
4. **`stocks.market_cap_cr` rename — when?** Pure tech debt. Doesn't block any factor work. ~30 min to grep, rename to `market_cap_inr`, fix consumers, retest. **My take:** defer until a slow session — too many real factors to ship.
5. **Library surface — when?** Cockpit page `/factors` (live, server-rendered) or `notebooks/factor_library.ipynb` (researcher-facing, lighter to build). **My take:** notebook first (~1–2 hour build, low cost, quick to iterate). Add a cockpit page once factor count is past ~30 and we want it visible without spinning up a Jupyter kernel. Until then, a notebook is plenty for browsing IC distributions, top/bottom names, "in model? yes/no" badges.

---

## Today's commits (all pushed to origin)

| SHA | Subject |
|---|---|
| `bb6df46` | fix: surveillance parser — GSM bare-list + F&O ban empty-list |
| `9dce5d1` | feat(F-track): ROIC factor — first signal from fundamentals_screener |
| `af94835` | fix: financial-sector exclusion was silently disabled |
| `bbdf5ce` | fix(F-track): ROIC robustness — 3-year smoothing + invested-capital floor |
| `3321827` | fix: accruals — drop partial composite for financials |
| `6bd5a38` | feat(F1.2): Screener schedules scraper — Trade Payables + 22 other line items |
| `1a94c22` | feat: wire ROIC into pipeline as signal_roic step |
| `f43e065` | feat(F-track): FCF Yield factor — second signal from fundamentals_screener |
| `4b98084` | docs: ADR 0011 + plan-0005 status + 2026-05-10 changelog |

## Today's local-only state (not in git)

| What | Where |
|---|---|
| F1.1 universe-pull data | `fundamentals_screener` table — 681,256 rows × 2,119 stocks (LARGE 100, MID 150, SMALL 1,869). Idempotent re-pull is fine. |
| F1.2 RELI smoke-test data | `fundamentals_screener` table — 276 additional rows for RELI (23 new line items). Will be overwritten as the universe scrape progresses. |
| F1.2 universe scrape | Running detached via `nohup`, PID 74316, log at [logs/schedules_universe_20260510_1217.log](logs/schedules_universe_20260510_1217.log). |
| ROIC scores | `roic_scores` table — 1,501 rows, snapshot_date=2026-05-10. Will refresh next pipeline run. |
| FCF Yield scores | `fcf_yield_scores` table — 1,195 rows, snapshot_date=2026-05-10. |
| Re-run signal snapshots after fix | piotroski_scores 2,200 rows (from 2,448; 248 financials correctly excluded), accruals_scores 2,448 rows (financials present but accruals_signal=NULL), forensic_scores 2,448 rows (same shape). |
| pit_ic_by_tier_v2 | 132 rows from today's backtest re-validation. |
