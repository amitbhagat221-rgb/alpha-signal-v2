# HANDOFF

> Overwritten at the end of each session per CLAUDE.md session protocol. If you're starting a new session: read this, then CLAUDE.md, then any plan or ADR linked below.

**Last updated:** 2026-05-09 (Amit Bhagat + Claude Code) — second handoff of the day; supersedes the earlier hygiene-only one
**Current branch:** `master` — clean, in sync with `origin/master`
**HEAD:** `1757abf` — feat(F1.1): Screener Premium ingest — thin slice end-to-end

---

## Where I am

Big session. Two distinct phases: (a) hygiene cleanup — ADR 0010 filed, README refreshed, dead schema dropped, three commits pushed; (b) F1.1 thin slice — `sources/screener_pull.py` end-to-end working for a single stock with auth, fetch, parse, and idempotent write. Five commits today, all on `origin/master`. The F-track (factor depth) has its first real data stream landed; next session is about scaling F1.1 to the universe and writing the first factor that consumes it.

## What works

- **F1.1 — Screener Premium ingest, end-to-end on one stock.** [sources/screener_pull.py](sources/screener_pull.py) (commit `1757abf`). Single-stock RELIANCE pull verified: 419 rows landed in `fundamentals_screener` (10 annual fiscal years × 36 line items + 10 quarters × 9 line items). Idempotent — second run kept 419 rows, only `fetched_at` advanced.
- **F1.1 auth path.** Password-login via env vars (`SCREENER_USERNAME`, `SCREENER_PASSWORD` exported in `~/alpha-signal/run_pipeline.sh`) → POST to `/login/` → cookie cached at `~/.cache/screener_cookie.json` (chmod 600). Re-run `python -m sources.screener_pull --login` anytime to refresh. Manual browser-cookie fallback documented in module docstring for OAuth-only accounts.
- **F1.1 fetcher logic.** [sources/screener_pull.py:131-203](sources/screener_pull.py#L131-L203) `fetch_export()` — GET `/company/{ticker}/consolidated/`, scrape per-stock export ID from button's HTML5 `formaction=` attribute (NOT the `<form action=>` — that was the initial bug), POST to `/user/company/export/<id>/` with `csrfmiddlewaretoken` from cookies. Falls back to standalone if consolidated 404s. Returns `(xlsx_bytes, view)`.
- **F1.1 parser.** [sources/screener_pull.py:222-307](sources/screener_pull.py#L222-L307) `parse_export()` walks the "Data Sheet" tab section-by-section (PROFIT & LOSS / Quarters / BALANCE SHEET / CASH FLOW: / DERIVED:), uses each section's "Report Date" row to define period_end columns, and emits long-format rows. The other tabs (Profit & Loss, Quarters, etc.) duplicate the same data with broken column headers and are intentionally ignored.
- **F1.1 bot-detection mitigations.** Randomized 2.5–4.0s inter-stock delay, 0.5–1.2s inter-step delay (page→export POST), HTTP 429 stops the run rather than blindly retries (so we surface rate-limit problems instead of compounding them). Honors `Retry-After` header if present.
- **Schema additions.** [schema.sql:GROUP 8](schema.sql) — `fundamentals_screener` (PK `(sid, period_end, period_type, line_item)`, long format), `screener_pull_errors` (audit trail, indexed by sid + attempted_at). Both created via `init_db()` 2026-05-09. Indexes on sid + line_item.
- **Dependency added.** `openpyxl` 3.1.5 + `et-xmlfile` 2.0.0 installed into shared venv (`~/alpha-signal/venv`). Required for `pd.read_excel` on Screener's xlsx.
- **From earlier today (already committed).** ADR 0010 (`5102eaa`), README refresh (`8c80240`), `stock_prices.adj_close` column + `split_adjustments` table dropped (manual via user, backup at `data/alpha_signal.db.bak-20260509-204353`), HANDOFF + plan-0004 cleanup (`e8b0797`).
- **Auto-mode push allowlist.** [.claude/settings.local.json:4](.claude/settings.local.json) now includes `Bash(git push origin master)`. Verified working — five push operations today, no friction.
- **Everything from prior sessions still works.** PIT-strict corporate-action adjustment, PIT reconstruction harness, nselib unified ingest, forward-only daily cron, factor registry at 40/42 READY, four reference docs, four live plans (0001 regulatory, 0002 macro, 0004 PIT, 0005 F-track).

## What's broken or half-built

- **F1.1 has only one stock in the DB.** Only RELI exercised. The 2,448-stock universe pull has never been run; we don't actually know if (a) Screener rate-limits us at scale, (b) other tickers have weird Excel formats, (c) delisted/F&O-only stocks 404 cleanly, (d) the form `formaction=` regex matches across all company-page templates.
- **F1.1 not in pipeline.py / cron.** It's a standalone module; nothing schedules it. No daily refresh, no `pipeline_log` row, no cockpit visibility.
- **F1.1 cookie health probe not running.** If the cookie expires (~2 weeks of inactivity per Django default) we'll find out from a failed pull, not a proactive check. Should be a daily `--check-cookie` somewhere.
- **No factor consumes `fundamentals_screener` yet.** The data is sitting in the table; no `signals/*.py` reads it. The whole point of F1.1 was to unlock B1 factors (CCC, FCF yield, ROIC, gross-margin trend, Sloan accruals). None of those exist yet.
- **Surveillance parser bugs — STILL not fixed; mid-investigation when F1.1 took priority.** [sources/nselib_pull.py](sources/nselib_pull.py) `pull_surveillance_today()`. Diagnosis confirmed today: **GSM** API returns a bare list (52 items, fields like `gsmStage` and `companyName`), not a `{"data": [...]}` dict — the `d.get("data", [])` fails. **F&O ban** via nselib `dv.fno_security_in_ban_period()` returns a bare `list` (empty today since no securities in ban), not a DataFrame — the `df.empty` check raises `AttributeError`. Both are 5-line fixes. Cron fires the broken paths nightly; harmless except for log noise.
- **2 signals legitimately not READY.** `sentiment_7d` PARTIAL (no FinBERT, F1.4 in plan 0005); `screener_final_composite` PROPOSED (F3 deliverable). Not bugs.
- **Old 9 indices stale at 2026-04-30.** Daily cron should have caught up by now — verify before relying on index data past 2026-04-30.

## Next 3 actions (in order, concrete)

1. **F1.1 scale-up — first to LARGE tier, then full universe.** `python -m sources.screener_pull --tier LARGE` (~250 stocks × ~3s = 12 min). Watch for: HTTP 404s (delisted stocks), HTTP 429 (rate-limited), parse failures (companies with non-standard Excel templates — common for banks/insurance). All go to `screener_pull_errors`. If clean, `--universe` (~3 hrs). Run from your terminal with sourced env, not from claude (claude can't `source run_pipeline.sh` without triggering the pipeline). Don't run during the 03:30 UTC daily cron window.
2. **Wire F1.1 into pipeline.py + cron.** Add `screener_pull` as a step (after the existing `tickertape` step, since it's the same fundamentals neighborhood). Schedule weekly full-universe + daily incremental for new filings. Surface in cockpit `/data` health page so cookie expiry shows up immediately.
3. **First F-track factor that consumes `fundamentals_screener`.** Either `cash_conversion_cycle` (DSO + DIO − DPO from Receivables, Inventory, Payables — but Payables not in Data Sheet, so we'd need to derive from Other Liabilities or fetch standalone xlsx tabs) **or** simpler `roic` (NOPAT / invested capital using Net Profit + Tax + Interest, Total Equity + Borrowings — all line items we already have). Recommend `roic` first; CCC needs a Payables source decision.

## Don't do

- **Don't `source ~/alpha-signal/run_pipeline.sh` from inside claude or any non-interactive context.** It runs the pipeline at the bottom, not just exports. Use `eval "$(grep '^export SCREENER' ~/alpha-signal/run_pipeline.sh)"` to load only the SCREENER vars. Discovered today the hard way.
- **Don't share or paste the Screener cookie file.** Single-user, chmod 600. The `sessionid` value gives full account access.
- **Don't run two `screener_pull` invocations concurrently.** Same cookie, compounded request rate, easy way to trip Screener's bot detection.
- **Don't pull `screener_pull --universe` during 02:30–04:30 UTC.** Cron runs the daily pipeline at 03:30 UTC; overlap risks resource contention and (more importantly) confused diagnostics if both are writing.
- **Don't auto-`--login` from cron without testing first.** Repeated login POSTs from the same IP can look like credential stuffing. Trust the cached cookie first; only re-login on observed 401/302-to-login.
- **Don't switch `fundamentals_screener` to wide format.** Long format is intentional — Screener has 36+ line items and growing; columns would mean a schema migration every time a new line item appears. Long format absorbs new line items for free. Already documented in plan 0005 spec.
- **Don't reintroduce `tools/apply_splits.py` or `stock_prices.adj_close`.** Per ADR 0010, PIT correctness depends on adjustments composing at signal-compute time.
- **Don't query nselib `cm.index_data` with date ranges wider than ~3 months.** Endpoint silently caps at ~70 trading days. Carried-forward guardrail.
- **Don't run all 5 nselib backfills concurrently.** 2-second floor + concurrent calls risk cookie-session issues. Stagger.
- **Don't mark `sentiment_7d` or `screener_final_composite` as READY.** Both scoped in plan 0005.
- **Don't add factors past ~100 before F3 ships.** Plan 0005 explicit gate.
- **Don't `git commit --amend` / `git add .` / `git add -A`.** Carried-forward rules.
- **Don't switch `pit_fwd_return_20d` to `adj_close` without a separate decision.** Per ADR 0010.

## Open questions for me (decisions you need to make)

1. **F1.1 universe-pull cadence — daily, weekly, or hybrid?** Full pull = ~3 hrs. Annual fundamentals only update quarterly (~once every 90 days per stock); quarterly fundamentals update at most quarterly (~once every 90 days per stock). Daily is wasteful. **My take:** weekly full universe (Sun 02:00 IST), daily incremental for the ~200 stocks expected to have a filing this week (use `earnings_calendar` as the trigger).
2. **Payables source for `cash_conversion_cycle`?** Not in Data Sheet, but might be in the standalone xlsx's "Profit & Loss" or "Balance Sheet" tabs (which we currently skip). Three options: (a) re-parse standalone tabs to find Payables — adds parser complexity; (b) skip CCC for now, ship FCF yield + ROIC + ROIIC first; (c) derive Payables ≈ Other Liabilities − provisions, accept the noise. **My take:** (b) — ROIC alone gives us a real B1 factor in 1 dev-day vs. 3 days of parser work for one factor.
3. **Surveillance bug fix — slot it where?** 5-min fix, no cookie / auth required, fully unblocked. Could go in any 30-min slot: (a) before next session's main work, (b) after F1.1 universe pull, (c) batch with other small fixes when there's a critical mass. **My take:** (a) — clear it on session start to free mental space.
4. **ADR for the long-format fundamentals decision?** Plan 0005 specifies long format, but the architectural choice (long for new fundamentals tables; existing wide tables stay wide) deserves an ADR — future contributors will ask why we have two formats. ~10 min to write. **My take:** yes, ADR 0011 — *Long-format for new fundamentals tables; wide-format legacy tables stay wide*. Not blocking but nice hygiene.
5. **Plan 0005 phase tracking?** Frontmatter now says "A1 thin slice landed; universe scale-up pending. A2/A3/A4: not started." Granular enough? Or do we want a Phase A status block inside the plan body to track A1.1 / A1.2 / A1.3 milestones? **My take:** the frontmatter sentence is sufficient until A2 starts; revisit then.

---

## Today's commits (all pushed to origin)

| SHA | Subject |
|---|---|
| `5102eaa` | docs: file ADR 0010 (PIT-strict corporate-action adjustment) |
| `8c80240` | docs: refresh README to reflect PIT-strict v2 production state |
| `e8b0797` | docs: refresh HANDOFF + plan 0004 (post-PIT-strict cleanup) |
| `1757abf` | feat(F1.1): Screener Premium ingest — thin slice end-to-end |
| `4e6cef1` | feat: PIT-strict corporate-action adjustment — *committed 2026-05-06, pushed today* |

## Today's local-only changes (no commit; not in git)

| Change | Where |
|---|---|
| `Bash(git push origin master)` and `Bash(git push)` allow rules | [.claude/settings.local.json](.claude/settings.local.json) |
| `stock_prices.adj_close` column dropped + `split_adjustments` table dropped | `data/alpha_signal.db` (DDL, not in git); backup at `data/alpha_signal.db.bak-20260509-204353` |
| `fundamentals_screener` table created (419 rows for RELI) + `screener_pull_errors` (2 rows from earlier debugging) | `data/alpha_signal.db` (created by `init_db()` from committed `schema.sql`) |
| Screener cookie cached | `~/.cache/screener_cookie.json` (chmod 600; sessionid + csrftoken) |
| `openpyxl` 3.1.5 + `et-xmlfile` 2.0.0 installed | `~/alpha-signal/venv/` (shared with v1) |
| `SCREENER_USERNAME`, `SCREENER_PASSWORD` exports added to `~/alpha-signal/run_pipeline.sh` | v1 script (always was the secrets location per CLAUDE.md) |
