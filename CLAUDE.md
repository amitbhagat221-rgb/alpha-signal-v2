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
- v1 is LIVE on cron — never touch `~/alpha-signal/`. All v2 work in `~/alpha-signal-v2/`
- Credentials live in v1's `run_pipeline.sh` exports — never in code

**Architecture & Code**
- No frameworks, no base classes, no YAML. Plain functions, Python config dict, SQLite. See `docs/decisions/0004-no-base-classes-no-yaml.md`
- ETFs excluded — universe is 2,448 stocks, not 2,500
- `cap_tier` must be assigned before any ranking — never rank without segment
- Never rank across tiers — always within-segment
- Financial sector stocks route through the financial sub-model, not the main screener
- Tickertape SIDs ≠ NSE tickers (e.g. `REDY` not `DRRD`). Always use universe SIDs

**Data Operations**
- Never run two harvester scripts simultaneously — doubles request rate, risks IP block
- 2-second delay minimum between external API calls
- Smoke test with 3 stocks before any full run
- `INSERT OR IGNORE` for append-only tables (insider_trades, bulk_deals, news_articles)
- `INSERT OR REPLACE` for snapshot tables (analyst_consensus, regime_state, signal tables)
- Read `docs/reference/data-playbook.md` before fetching from any new source

**Backtest hygiene**
- Ship a factor module and its PIT helper as one unit — never separately
- Don't add to `BACKTEST_SIGNALS` until t-stat ≥ 1.5 on at least one cap tier
- Don't edit `SCREEN.weight_tiers` mechanically — see `docs/reference/signal-weights.md`

**Git**
- Never `git commit --amend`, `git add .`, `git add -A`
- Never `pkill -f "uvicorn cockpit.app"` — pattern matches prod systemd service

---

## Session Protocol

**Start:** `/catchup` reads HANDOFF.md + `docs/plans/0000-checklist.md` + the active plan. Names the specific checklist item(s) this session will work on — if the goal isn't already a bullet, add it before starting.
**End:** `/handoff` overwrites HANDOFF.md, updates the checklist (step 1.5), files any ADRs, updates plan status, commits.

Skipping `/handoff` is the single biggest source of context loss. Working on something that isn't on the checklist is the second.

---

## When to write a doc

| Trigger | Where it goes |
|---|---|
| Non-obvious technical choice | New ADR in `docs/decisions/` (write-once, ≤30 lines) |
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
