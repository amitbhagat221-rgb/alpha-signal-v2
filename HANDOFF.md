# HANDOFF

> Overwritten at the end of each session per CLAUDE.md session protocol. If you're starting a new session: read this, then CLAUDE.md, then any plan or ADR linked below.

**Last updated:** 2026-05-06 (Amit Bhagat + Claude Code)
**Current branch:** `master` — 3 commits ahead of `origin/master` after `a26674e` (push manually; harness BLOCKs default-branch pushes)
**HEAD:** *to be set by next commit* — pending PIT-strict adjustment commit

---

## Where I am

Started the day closing two partial items (splits regex 100%, smart-beta indices 9→13) and pushed those. After a deep gut-check on whether to chase v1's leaky-but-validated forward-adjustment via yfinance vs. build PIT-strict ourselves, committed to PIT-strict. **PIT-strict price adjustment for splits + bonuses + dividends is now live.** Architecture symmetric with the existing `knowable_quarterly`/`knowable_annual`/`knowable_shareholding` discipline for fundamentals — no more half-honest middle ground.

## What works

- **PIT-strict corporate-action adjustment (NEW today, late session).** [tools/compute_corporate_adjustments.py](tools/compute_corporate_adjustments.py) parses SPLIT + BONUS + DIVIDEND events from `corporate_actions` into a unified `corporate_adjustments` table (PK `(sid, ex_date)`, columns `factor`, `n_events`, `inds`, `subjects`). 3,036 rows landed: 92 SPLIT-only + 90 BONUS-only + 2,840 DIVIDEND-only + 17 multi-event days. Same-day events (e.g. SPLIT+DIVIDEND on 2025-06-16) are pre-multiplied into a single combined factor — solves the same-day PK collision the old `split_adjustments` had.
- **Snapshot-aware adjustment helper.** [tools/reconstruct_pit.py:283-324](tools/reconstruct_pit.py#L283-L324) `apply_pit_adjustments(prices_pit, adjustments, eval_date)` composes only events with `ex_date <= eval_date`. Vectorized per sid via reverse-cumprod + `np.searchsorted` — full reconstruction goes from 14.6s (momentum-only) to 216s (all 23 signals), same as prior baseline. Three signals switched from raw close to `adj_close`: `pit_momentum`, `pit_position_52w`, `pit_macd_bullish`. `pit_fwd_return_20d` deliberately left on raw close (it's a backtest-realized-return metric, not a signal input).
- **Diagnostic confirms structural correctness, not numerical magic.** 12-date apples-to-apples Pearson lift: raw close 0.745 → PIT-adj 0.862 (+0.117). Earlier today's forward-adjusted-splits-only path showed +0.119. So adding dividends + PIT-strictness barely moved the lift number — but the architecture is now correct (no future-event leakage), symmetric with how fundamentals are already PIT'd, and ready for the F-track factor expansion.
- **Deprecated/removed.** [tools/compute_splits.py] and [tools/apply_splits.py] deleted (`git rm`). `stock_prices.adj_close` column left in place (1.3M rows of dead weight; safe to drop in a future migration). `split_adjustments` table left in place (orphaned but inert).
- **From earlier today (already pushed in `25f71a2`).** Splits regex extended from 104/207 → 207/207 (later superseded by `compute_corporate_adjustments.py`). Smart-beta indices 9→13 — added `NIFTY100 LOW VOLATILITY 30`, `NIFTY ALPHA LOW-VOLATILITY 30`, `NIFTY200 QUALITY 30`, `NIFTY100 EQUAL WEIGHT`. Discovered nselib `cm.index_data` silently caps wide queries at ~70 rows (always use monthly chunks).
- **upsert_df regression test in place** ([tests/test_smoke.py:82](tests/test_smoke.py#L82)). All 7 smoke tests pass. Partial reconstructions (`reconstruct_pit --signal X`) safe.
- **Everything from prior sessions still works.** PIT reconstruction harness, nselib unified ingest, forward-only daily cron, factor registry at 40/42 READY, three reference docs, three live plans.

## What's broken or half-built

- **README.md stale.** Flagged in 2026-05-02, 2026-05-05, and again here. Not addressed.
- **Surveillance parser bugs.** [sources/nselib_pull.py](sources/nselib_pull.py) `pull_surveillance_today()` raises `'list' object has no attribute 'get'` for GSM and F&O ban list. ASM works. Cron fires the broken paths nightly; harmless except for log noise.
- **Old 9 indices stale at 2026-04-30.** Today's index backfill only touched the 4 new ones. Daily cron will catch them up.
- **2 signals legitimately not READY.** `sentiment_7d` PARTIAL (no FinBERT, F1.4 in plan 0005); `screener_final_composite` PROPOSED (F3 deliverable). Not bugs.
- **`stock_prices.adj_close` column is now dead weight.** Nothing reads it (`reconstruct_pit.py` uses the in-memory `apply_pit_adjustments` output instead). Safe to drop via `ALTER TABLE stock_prices DROP COLUMN adj_close` (SQLite ≥3.35); not worth a session of its own.
- **`split_adjustments` table orphaned.** Same situation — was populated by the deleted `tools/apply_splits.py`. Drop in a future cleanup.

## Next 3 actions (in order, concrete)

1. **Drop dead schema** — `ALTER TABLE stock_prices DROP COLUMN adj_close` and `DROP TABLE split_adjustments`. ~5 min. Removes a permanent source of "is this stale?" confusion for future readers. Single commit.
2. **Subscribe to Screener Premium (₹420/mo) and ship F1.1.** Highest-leverage paid-data move per [paid-data-sources.md](docs/reference/paid-data-sources.md). Build [sources/screener_pull.py](sources/screener_pull.py) with the cookie-jar + Excel-export pattern. ~2 dev-days. Unblocks 15 Tier-1 factors (CCC, FCF yield, ROIC, ROIIC, gross margin trend, Sloan accruals, NWC factors). **This is the actual returns-leverage step** — today's PIT-strict work was correctness/credibility; F1.1 is alpha.
3. **Refresh README.md.** ~30 min. It's been stale across three sessions; future-you (or a collaborator) reads it first. Flip "alpha-signal-v2" from "we just started v1.5" framing into "production v2 with 42 factors and PIT-strict reconstruction."

## Don't do

- **Don't query nselib `cm.index_data` with date ranges wider than ~3 months.** Endpoint silently caps at ~70 trading days. Always paginate via `_months_back(N)`. [sources/nselib_pull.py:454](sources/nselib_pull.py#L454) already does this — don't bypass.
- **Don't reintroduce `tools/apply_splits.py` or `stock_prices.adj_close` writes.** PIT correctness depends on adjustments being composed AT signal-compute time, not pre-baked at ingest time. Pre-baked adjustment is leaky-by-construction (same problem yfinance has).
- **Don't `git push origin master` directly via Bash.** Harness BLOCKs default-branch pushes regardless of user authorization. Push manually from your terminal, or grant `Bash(git push origin master)` permission via `/config`. See "Open questions" #1.
- **Don't subscribe to Sensibull or Trendlyne.** Sensibull has no retail API. Trendlyne lost ~70% of its marginal value when nselib unlocked the historical APIs. Screener Premium is the only paid sub with non-overlapping data.
- **Don't run all 5 nselib backfills concurrently** (`--source all`). 2-second rate-limit floor + concurrent calls risk cookie-session issues. Stagger.
- **Don't mark `sentiment_7d` or `screener_final_composite` as READY.** Both scoped in plan 0005.
- **Don't add factors past ~100 before F3 ships.** Plan 0005 explicit gate.
- **Don't `git commit --amend`.** I broke this rule once today; recovered with a separate commit. Always new commits.
- **Don't `git add .` or `git add -A`.** Stage explicit files.
- **Don't switch `pit_fwd_return_20d` to `adj_close` without thinking it through.** It's a backtest-realized-return metric — a trader on `eval_date+20` realizes the actual cash return including dividends received and post-event prices. Forward-adjusting it is a separate decision; what's there now is fine for IC measurement.

## Open questions for me (decisions you need to make)

1. **Push policy for master.** Direct push BLOCKed by harness. Options: (a) `/config` add `Bash(git push origin master)` to allow list — friction-free, OK for solo; (b) feature-branch + PR flow — closer to industry practice. **My take: (a) for now**, revisit if collaborators join.
2. **Drop `stock_prices.adj_close` and `split_adjustments` now or never?** They're inert. **My take: now** — 5-minute commit, removes a permanent confusion vector.
3. **Refresh README — actually do it or stop nagging?** Three sessions running. **My take: do it, 30 min.**
4. **ADR for the PIT-strict adjustment architecture?** It's a real architectural decision (price adjustment composes at signal-compute time, not at ingest). Not invasive but durable — future contributors should understand why `apply_splits.py` was deleted. **My take: yes — propose ADR 0010 — *PIT-strict corporate-action adjustment composes at signal-compute time, not at ingest*.** Draft below.
5. **Plan status changes today?** Plan 0004 (PIT reconstruction) gets a meaningful step closer — Phase 3 (methodology corrections — momentum + promoter_qoq) now genuinely complete with PIT-clean adjustment. Still leave `Status: active` until Phase 4 (PIT depth past 2023) lands.

---

## Proposed for this session, awaiting approval

### ADR 0010 — *PIT-strict corporate-action adjustment composes at signal-compute time*

**Status:** Proposed (Draft)
**Date:** 2026-05-06
**Decided by:** Amit (with Claude Code)

**Context.** v1 used yfinance `Adj Close` which forward-adjusts the entire price history every time a new event lands. This embeds future events into past prices — leaky for backtesting at any historical snapshot. v2 had been quietly mirroring this with `tools/apply_splits.py` writing a static `adj_close` column. After explicit gut-check, we decided fundamentals are already PIT-disciplined (`knowable_quarterly`, `knowable_annual`, `knowable_shareholding`) and prices should be symmetric.

**Decision.** Corporate adjustments live in a `corporate_adjustments` table (PK `(sid, ex_date)`, factor multiplier per event). At signal-compute time, `apply_pit_adjustments(prices, adjustments, eval_date)` composes only events with `ex_date <= eval_date` into per-(sid, date) cumulative factors. No static `adj_close` column. No pre-baked forward-adjusted prices.

**Alternatives considered.** (a) Use yfinance Adj Close directly (rejected — leaky, asymmetric with PIT fundamentals discipline). (b) Pre-bake static `adj_close` and accept the leak (rejected — half-honest middle ground, was today's pre-PR state). (c) Per-snapshot materialized adjusted prices (rejected — explosive storage, modest performance benefit).

**Reversal cost.** Low. The helper is one self-contained function (~40 LOC). The `corporate_adjustments` table can be ignored or dropped without affecting raw prices.

**Implications.** All future price-based factors (F2 expansion: 50 new factors, several price-based) inherit PIT correctness for free by reading `prices_pit['adj_close']` after `apply_pit_adjustments` has been called in `reconstruct_one_date`.

---

## Today's commits (already pushed)

| SHA | Subject |
|---|---|
| `c08929a` | test: regression test for upsert_df partial-write preservation |
| `25f71a2` | fix: split parser at 100% + smart-beta indices at 13 (was 9) |
| `a26674e` | docs: refresh HANDOFF HEAD reference |

## Today's commits (pending — about to commit, push manually after)

| Subject |
|---|
| feat: PIT-strict corporate-action adjustment (splits + bonuses + dividends) |
