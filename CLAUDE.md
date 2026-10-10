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
- v1 has no active cron, but v2 runs on its venv — never touch `~/alpha-signal/`. All v2 work in `~/alpha-signal-v2/`
- Credentials live in `~/.config/alpha-signal/secrets.env` (mode 600, outside git; moved out of v1's `run_pipeline.sh` 2026-10-10) — never in code. Loaded once, in `run.sh`. Don't duplicate secrets anywhere; a new key is one `export` line in that file.
- Every v2 cron line is `/home/ubuntu/alpha-signal-v2/run.sh <job> >> <log> 2>&1` (plan 0015): `run.sh` owns the `cd`, venv, credential import and harvest lock. Never add an inline cron one-liner — add a `case` to `run.sh` (the monthly snapshot cron once silently no-op'd for lack of a `cd`).

**Architecture & Code**
- No frameworks, no base classes, no YAML. Plain functions, Python config dict, SQLite. See `docs/decisions/0004-no-base-classes-no-yaml.md`
- ETFs excluded — universe is 2,448 stocks, not 2,500
- Tiers are data (`config.TIERS`: rank rule, `pickable`, picks, costs). `scoring/segment.py` re-tiers LARGE/MID/SMALL monthly (±10% hysteresis) before the screener; `tools/classify_micro_tier.py` carves MICRO. Never hard-code a tier list — iterate `config.TIERS` / `PICKABLE_TIERS`
- Never rank across tiers — always within-segment
- A wired factor with no value for a stock scores as the middle of its tier (`config.MISSING_FACTOR_SCORE`); never re-spread its weight over the other factors (ADR 0064). A result print is `factors.RESULT_FILING_SQL`, not `category='Result'` alone
- A source column is named for what it holds, and its meaning is checked against a second source: a statement column a factor reads goes in `tools/reconcile.FUND_FIELDS` (Tickertape's "interest" was operating expenses and "depreciation" was dividends for months; ADR 0062). A weight sits on the column its evidence was measured on
- Price and share count on one basis: market cap is `signals._fundamentals.market_caps` (live tiers, backtest tiers, MICRO carve-out, `stocks.market_cap_cr` in ₹ crore), per-share values come from `shares_and_book`, returns from adjusted prices (`pit.forward_returns` is the one label); never divide a vendor share count by a raw close. Live tiering uses `pit.tier_inputs`, the backtest's own inputs (ADR 0065)
- Financial sector stocks rank through the MAIN screener (generic weights), NOT a separate sub-model — with `accruals`+`piotroski` marked INELIGIBLE for Financials in `eligibility/registry.py` (structurally N/A for banks) so `eligible_coverage` renormalizes over the signals that DO apply. `financial_signal_scores` is dossier/display-only, evidence-benched from ranking (within-financials IC t=0.73, fails the bar). See [ADR 0048](docs/decisions/0048-financials-rank-generic-not-submodel.md). (Was mis-documented as "route through the sub-model"; the mis-wired eligibility silently dropped all MID Financials from `daily_picks` post-ADR-0045 until fixed 2026-07-05.)
- Tickertape SIDs ≠ NSE tickers (e.g. `REDY` not `DRRD`). Always use universe SIDs
- Cockpit static files: every `<script>`/stylesheet from `/static` carries `?v={{ asset_version(...) }}` (`tests/test_static_cache.py`; an untagged `cockpit.js` left charts blank in Amit's cached browser), and a template class must have a CSS rule (`tests/test_cockpit_css.py`; a "cleanup" once deleted the industry dossier's styles). Verify UI with Playwright at 1440 and 375, including a stale-cache browser

**Data Operations**
- Never run two harvester scripts simultaneously — doubles request rate, risks IP block
- Never run two multi-hour DB writers at once (panel rebuild, `datamodel.sync`, backfills): on 2026-10-08 the WAL reached 32.5 GB and filled the disk. Message the other session first
- In a git worktree `config.DB_PATH` points inside the worktree: set `ALPHA_DB=/home/ubuntu/alpha-signal-v2/data/alpha_signal.db`, or sqlite silently creates an empty DB there
- Every external call goes through the host door (`sources/_http` + `hosts.HOSTS`: gap ≥2 s, headers, retries, budgets). Never `requests.get`/`sleep` for pacing in a module — declare the host
- Smoke test with 3 stocks before any full run
- `INSERT OR IGNORE` for append-only tables (insider_trades, bulk_deals, news_articles); column-level `db.upsert_df` for snapshot/state tables — never `INSERT OR REPLACE` there (it NULLs columns another producer owns, e.g. analyst_consensus)
- Read `docs/reference/data-playbook.md` before fetching from any new source
- Every data stream is a `feeds.FEEDS` entry (family, routes, canary; tier is derived) — `tests/test_feeds.py` blocks unregistered modules/steps/RAW tables, unscheduled production feeds and T1 feeds without fallback/serve-stale + canary. New source: candidate entry + canary on 3 items first (`python -m tools.canary --feed X`). Fix loop: [feed-runbook](docs/reference/feed-runbook.md). Failures must be visible in `run_events` (runlog.py): use `_http.run_harvester` + the door, or `runlog.item_error/item_failed` in a custom loop — a failure that is only `print`ed is a silent failure. Debug with `python -m runlog bundle <feed>`. Raw tables on the T1 path declare a write `contract` in `tables.TABLES` (enforced before write in `db.insert_df/upsert_df`) — never loosen one to make a harvest pass; after a canary `--accept`, refresh replay fixtures (`python -m tools.canary --save-fixtures`)

**Health & observability**
- Daily health email at 04:00 UTC + URGENT push on CRITICAL. Driven by `tools/health_report.py` — one source of truth for terminal/email/push/MCP/ops page. `/catchup` runs it first; never skip its output.
- Every check answers ONE of the five questions in `checks.THEMES` and declares `theme` / `message` / `why` / `fix` in plain words, on the check itself (`checks/custom.py`, or `checks/system.SYSTEM_CHECKS` for a system check; a system area is one `(facts, verdicts)` pair in `checks/system.AREAS`). `checks/report.gather()` builds the ONE state; a surface renders it and never decides severity or derives its own. `python -m tools.health_report --catalog` lists every check. See [health-checks](docs/reference/health-checks.md), ADR 0059.
- A daily check must be able to fail today because the world changed, and prove it: every check has a fire drill in `tests/test_check_drills.py` (the suite fails without one). A rule that only breaks when code or a registry changes is a test, not a check. Factor checks read what the ranking used (`checks/model.py`, scope from `factors.SIGNAL_WEIGHTS`) — never hand-list factors in a check. Catalog capped at 30. The picks email runs the `picks` checks before sending and carries a banner when one fails. ADR 0060.
- The per-pick number is `eligible_coverage`, worded only by `views.pick_data` ("Data 84% · Partial"); thresholds in `config.PICK_GATE`. UHS and gates 3–7 are retired (ADR 0061) — don't bring back a composite trust score. A stored analyst target is judged by ONE check (`ANALYST_TARGET_IMPLAUSIBLE`, rules in `validators/plausibility.py`: `PT_CLOSE_RATIO` and the average inside its own low–high), at both writers and in the check; Yahoo owns `analyst_consensus.price_target` (the broker aggregate fills only stocks Yahoo does not cover — two writers on one column produced 178 impossible averages, 2026-10-10).
- Silent failures are the enemy. Producers MUST raise on missing env or 0 output (not write placeholders). `freshness_watchdog` covers DB tables AND file outputs via `config.FILE_OUTPUTS`.
- Push: ntfy.sh — set `NTFY_TOPIC` in `~/.config/alpha-signal/secrets.env` to enable phone push. Without it, URGENT email still fires on CRITICAL.

**The org (plan 0019)**
- Every agent seat is ONE `org.ROLES` entry. A desk seat = a charter in `.claude/routines/roles/` + a role-owned task kind in `alpha_mcp/org_kinds.py` (brief, schema, ingest); a builder seat = `.claude/agents/<id>.md`. `tests/test_org.py` enforces it. Desk seats write ONLY through `alpha-work.submit` into `documents` (`source='org'`): never give one a shell, a table write, or a path to weights / config / cron. Memo numbers must come from the brief (validator-enforced); doer and grader are different seats. Amit tunes a seat (schedule, model, directive, prompt) from the ops cockpit `/org` → read the effective seat with `org.seat(role)`, never `ROLES[role]` directly, and expect the charter / agent files to carry his uncommitted edits (don't revert them). Fixes he agrees with a seat in chat arrive as numbered work orders: run one with `/work-order N` (only if approved; `python -m org work N` shows it with the chat it came from). Runbook: [org.md](docs/reference/org.md)

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
