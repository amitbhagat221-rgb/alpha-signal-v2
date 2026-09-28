# Alpha Signal v2 — AI Context

**AI-Native Daily Stock Intelligence for Indian Retail Investors**
Owner: Amit Bhagat | Bengaluru | Oracle Cloud Ubuntu VM | Started April 2026

This file is short on purpose. Rules only. Reference lives in `docs/reference/`.

---

## The system (rule of 3 at every level)

**3 files in head:** `README.md` · `CLAUDE.md` · `HANDOFF.md`
**3 folders in head:** `docs/plans/` · `docs/decisions/` · `docs/reference/`
**3 sections in HANDOFF:** Left off · Pick up here · Watch out
**3 steps per session:** `/catchup` → work → `/handoff`

Everything else (memory, `_archive/`, slash commands, settings) — Claude handles.

---

## Critical Rules

**Environment**
- Activate venv first: `source ~/alpha-signal/venv/bin/activate` (shared with v1)
- v1 has no active cron, but v2 runs on its venv and reads its credentials — never touch `~/alpha-signal/`. All v2 work in `~/alpha-signal-v2/`
- Credentials live in v1's `run_pipeline.sh` exports — never in code. v2 imports them at runtime via `eval "$(grep '^export ' /home/ubuntu/alpha-signal/run_pipeline.sh)"` (read-only, no execution of v1 body) — done once, in `run.sh`. Don't duplicate secrets anywhere.
- Every v2 cron line is `/home/ubuntu/alpha-signal-v2/run.sh <job> >> <log> 2>&1` (plan 0015): `run.sh` owns the `cd`, venv, credential import and harvest lock. Never add an inline cron one-liner — add a `case` to `run.sh` (the monthly snapshot cron once silently no-op'd for lack of a `cd`).

**Architecture & Code**
- No frameworks, no base classes, no YAML. Plain functions, Python config dict, SQLite. See `docs/decisions/0004-no-base-classes-no-yaml.md`
- ETFs excluded — universe is 2,448 stocks, not 2,500
- Tiers are data (`config.TIERS`: rank rule, `pickable`, picks, costs). `scoring/segment.py` re-tiers LARGE/MID/SMALL monthly (±10% hysteresis) before the screener; `tools/classify_micro_tier.py` carves MICRO. Never hard-code a tier list — iterate `config.TIERS` / `PICKABLE_TIERS`
- Never rank across tiers — always within-segment
- Financial sector stocks rank through the MAIN screener (generic weights), NOT a separate sub-model — with `accruals`+`piotroski` marked INELIGIBLE for Financials in `eligibility/registry.py` (structurally N/A for banks) so `eligible_coverage` renormalizes over the signals that DO apply. `financial_signal_scores` is dossier/display-only, evidence-benched from ranking (within-financials IC t=0.73, fails the bar). See [ADR 0048](docs/decisions/0048-financials-rank-generic-not-submodel.md). (Was mis-documented as "route through the sub-model"; the mis-wired eligibility silently dropped all MID Financials from `daily_picks` post-ADR-0045 until fixed 2026-07-05.)
- Tickertape SIDs ≠ NSE tickers (e.g. `REDY` not `DRRD`). Always use universe SIDs

**Data Operations**
- Never run two harvester scripts simultaneously — doubles request rate, risks IP block
- Every external call goes through the host door (`sources/_http` + `hosts.HOSTS`: gap ≥2 s, headers, retries, budgets). Never `requests.get`/`sleep` for pacing in a module — declare the host
- Smoke test with 3 stocks before any full run
- `INSERT OR IGNORE` for append-only tables (insider_trades, bulk_deals, news_articles); column-level `db.upsert_df` for snapshot/state tables — never `INSERT OR REPLACE` there (it NULLs columns another producer owns, e.g. analyst_consensus)
- Read `docs/reference/data-playbook.md` before fetching from any new source
- Every data stream is a `feeds.FEEDS` entry (family, routes, canary; tier is derived) — `tests/test_feeds.py` blocks unregistered modules/steps/RAW tables, unscheduled production feeds and T1 feeds without fallback/serve-stale + canary. New source: candidate entry + canary on 3 items first (`python -m tools.canary --feed X`). Fix loop: [feed-runbook](docs/reference/feed-runbook.md). Failures must be visible in `run_events` (runlog.py): use `_http.run_harvester` + the door, or `runlog.item_error/item_failed` in a custom loop — a failure that is only `print`ed is a silent failure. Debug with `python -m runlog bundle <feed>`

**Health & observability**
- Daily health email at 04:00 UTC + URGENT push on CRITICAL. Driven by `tools/health_report.py` — one source of truth for terminal/email/push. `/catchup` runs it first; never skip its output.
- Silent failures are the enemy. Producers MUST raise on missing env or 0 output (not write placeholders). `freshness_watchdog` covers DB tables AND file outputs via `config.FILE_OUTPUTS`.
- Push: ntfy.sh — set `NTFY_TOPIC` env var in `~/alpha-signal/run_pipeline.sh` to enable phone push. Without it, URGENT email still fires on CRITICAL.

**LLM output hygiene**
- Narrative LLM fields (dossier thesis/bull/bear/catalysts/risks) MUST NOT contain raw numbers — they hallucinate plausibly. Numbers live ONLY in structured fields (`target_price`, `stop_loss`, etc.). `output/dossier.py` validates this; cockpit `get_dossier()` returns `{}` for invalid dossiers. See HALC 2026-05-22 ("16.5% downside at ₹1038" — 950/1038 = -8.5%).
- Calendar tokens (Q1, FY25, H1) are allowed. Specific decimals / percentages / rupee amounts / multiples / score ratios are not.

**Data-cadence rule (per HANDOFF 2026-05-22)**
- Analyst price targets are EPISODIC, not continuous. Sell-side analysts revise quarterly at best — most days the underlying PT is unchanged. Daily PT history is phantom precision and lets `lastPrice` masquerade as PT. The 2026-05-22 HALC bug lived in this gap.
- Three tables, three rhythms — keep them straight:
  - `analyst_consensus` (PK=sid, daily-refreshed): cockpit "current PT" view. Daily yfinance refresh updates `price_target` + `total_analysts` only; leaves Tickertape-sourced `forward_eps` / growth fields intact.
  - `analyst_consensus_snapshots` (PK=sid+date+source, MONTHLY): backtest + revision signals. Cron: 1st of month 04:30 UTC. NEVER write a daily row to this table.
  - `forecast_history` (Tickertape year-end eps/revenue snapshots). The `price` metric is NOT ingested — it was the realized year-ahead close, not a PT (ADR 0045). The only honest PT history is `analyst_consensus_snapshots`.
- When adding any new "PT-like" producer: ask first "is this episodic?". If yes, snapshot table at the natural cadence (monthly or quarterly), not daily.

**Backtest hygiene**
- A factor is ONE compute function called by both live and PIT: the screener takes every factor from `pit.features_at(today)` — the same code the backtest panel stores. Input hygiene (consolidated filter, Financials exclusion) lives INSIDE the compute function, never in a live-only loader
- Register every factor ONCE in `factors.FACTORS` (compute producer, range, cadence, eligibility, bench, and — if wired — `weights: {tier: w}`). `BACKTEST_SIGNALS`, `FACTOR_LIBRARY`, `PIT_COLUMNS`, `SIGNAL_WEIGHTS`, lineage table reads etc. are derived — never hand-edit a list; `tests/test_factor_registry.py` enforces it. See ADRs 0017, 0052
- New table → `schema.sql` AND `tables.TABLES` (`tests/test_tables.py` enforces it)
- Don't give a factor `weights` until t-stat ≥ 1.5 on at least one cap tier, and never mechanically — see `docs/reference/signal-weights.md`
- `reconstruct_pit.py` writes only the columns the requested signals produced — `--signal X` is safe on existing dates by construction. If you ever pad missing PIT_COLUMNS with NaN before the write, you'll wipe every untouched column on UPDATE — don't.

**Git**
- Never `git commit --amend`, `git add .`, `git add -A`
- Never `pkill -f "uvicorn cockpit.app"` — pattern matches prod systemd service

**Graph-first lookup**
- Before any cross-file grep/read sweep, query the graphify MCP first (`mcp__graphify__*`). The graph indexes 1,792 nodes / 2,801 edges at 90% extraction confidence — use it for navigation and recall, then read only the specific files it points to.
- Do NOT query the graph for files you're about to edit — read them directly. Graph is for finding things, not for the working file.
- Do NOT run `graphify --update` yet. Graph is frozen on the 2026-05-23 snapshot until Amit rebuilds without image extraction — it predates the 2026-09-26 cleanup (factors.py, tables.py, archived modules), so verify any path it returns before trusting it.

---

## Session Protocol

**Start:** `/catchup` reads HANDOFF.md + `docs/plans/0000-checklist.md` + the active plan. Names the specific checklist item(s) this session will work on — if the goal isn't already a bullet, add it before starting.
**End:** `/handoff` overwrites HANDOFF.md, updates the checklist (step 1.5), files any ADRs, updates plan status, commits.

Skipping `/handoff` is the single biggest source of context loss. Working on something that isn't on the checklist is the second.

---

## When to write a doc

| Trigger | Where it goes |
|---|---|
| Non-obvious technical choice | New ADR in `docs/decisions/` (write-once; decision in the first 10 lines, ≤60 total; mark the ADR it supersedes) |
| Detail diverges from active plan | Append to that plan's "Implementation notes" |
| New recurring landmine | One-line rule in this file's Critical Rules |
| Plan reaches "Done when" | Status → implemented; reflect in `docs/reference/`; archive in 30 days |
| Plan checkbox ticked or scope changed | Tick the same item in `docs/plans/0000-checklist.md` |

If unsure where a doc goes: would I open this file again in 3 months? If no, skip.

---

## Where everything lives

| You need | Read |
|---|---|
| Where I am right now | `HANDOFF.md` |
| What I'm building | active plan in `docs/plans/` |
| Why we chose X | `docs/decisions/` |
| How X works / schema / signals / data sources | `docs/reference/` |
| What changed recently | `git log` |
| The doc map itself | `docs/README.md` |
