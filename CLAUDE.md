# Alpha Signal v2 — AI Context

**AI-Native Daily Stock Intelligence for Indian Retail Investors**
Owner: Amit Bhagat | Bengaluru | Oracle Cloud Ubuntu VM | Started April 2026

Rules only; reference lives in `docs/reference/`. This file holds the rules every session needs and is capped (see "Keeping this file small"). Area rules live in `.claude/rules/` and load only when you touch matching files.

---

## The system (rule of 3 at every level)

**3 files in head:** `README.md` · `CLAUDE.md` · `HANDOFF.md`
**3 folders in head:** `docs/plans/` · `docs/decisions/` · `docs/reference/`
**3 sections in HANDOFF:** Left off · Pick up here · Watch out (+ the active-plan line)
**3 steps per session:** catchup (automatic) → work → `/handoff`

Everything else (memory, `_archive/`, slash commands, settings) — Claude handles.

---

## Critical Rules (every session)

**Environment**
- Activate venv first: `source ~/alpha-signal/venv/bin/activate` (shared with v1). Never touch `~/alpha-signal/`; all v2 work in `~/alpha-signal-v2/`
- Credentials live only in `~/.config/alpha-signal/secrets.env` (mode 600, outside git), loaded once by `run.sh` — never in code; a new key is one `export` line there
- Every cron line is `/home/ubuntu/alpha-signal-v2/run.sh <job> >> <log> 2>&1` (plan 0015): `run.sh` owns the `cd`, venv, credentials and harvest lock. A new job is a `case` in `run.sh`, never an inline cron one-liner

**Model invariants**
- No frameworks, no base classes, no YAML: plain functions, Python config dict, SQLite (ADR 0004)
- Universe is 2,448 stocks, ETFs excluded. Tickertape SIDs ≠ NSE tickers (`REDY` not `DRRD`) — always use universe SIDs
- Tiers are data (`config.TIERS`): never hard-code a tier list, iterate `config.TIERS` / `PICKABLE_TIERS`. Never rank across tiers — always within-segment
- A factor is ONE compute function shared by live and backtest (`pit.features_at`), registered ONCE in `factors.FACTORS`; derived lists are never hand-edited
- Never give a factor `weights` mechanically, nor below t ≥ 1.5 on a cap tier (`docs/reference/signal-weights.md`)
- LLM narrative fields (dossier thesis/bull/bear/catalysts/risks) carry no raw numbers — they hallucinate plausibly. Numbers live only in structured fields; `output/dossier.py` validates. Calendar tokens (Q1, FY25, H1) are fine

**Data safety**
- One harvest per source at a time (`run.sh harvest_lock <source…>`; different sources may run in parallel), and never two multi-hour DB writers at once (a 32.5 GB WAL filled the disk 2026-10-08) — message the other session first
- Never copy the 22 GB DB: read it with `sqlite3 -readonly` / `file:...?mode=ro`. In a git worktree set `ALPHA_DB=/home/ubuntu/alpha-signal-v2/data/alpha_signal.db`, or sqlite silently creates an empty DB there
- Every external call goes through the host door (`sources/_http` + `hosts.HOSTS`); never `requests.get` or `sleep` pacing in a module
- Smoke test with 3 stocks before any full run
- `INSERT OR IGNORE` for append-only tables; column-level `db.upsert_df` for snapshot tables — never `INSERT OR REPLACE` (it NULLs columns another producer owns)
- New table → `schema.sql` AND `tables.TABLES` (`tests/test_tables.py`)
- Silent failures are the enemy: producers raise on missing env or 0 output, never write placeholders. A failure that is only `print`ed is silent — it must reach `run_events`

**Health**
- `python -m tools.health_report` is the one source of truth for terminal, email, push, MCP and the ops page; never skip its output at session start
- Every check must be able to fail today and has a fire drill (ADR 0060). Don't bring back a composite trust score (ADR 0061)

**Git & processes**
- Never `git commit --amend`, `git add .`, `git add -A`
- Concurrent sessions share this tree: commit only your own files and hunks (`/handoff` steps 0, 4–5). Never stage, revert, stash, reset or checkout another session's uncommitted edits
- Never `pkill -f "uvicorn cockpit.app"` — the pattern matches the prod systemd service
- Approval tiers (ADR 0086): Tier A paths (live options, weights/config, `run.sh`/crontab, schema drops, data deletes) wait for Amit; everything else commits when the pre-push suite passes, Tier B work orders approve themselves after 48 h, and every plan decision carries its default and effect date

**Graph-first lookup**
- Before a cross-file grep/read sweep, query the graphify MCP (`mcp__graphify__*`) and read only the files it points to. Don't query it for a file you're about to edit
- The graph is frozen on the 2026-05-23 snapshot (predates the 2026-09-26 cleanup): verify any path it returns. Don't run `graphify --update` until Amit rebuilds it without image extraction

---

## Area rules (load on demand)

| `.claude/rules/` file | Loads when you touch |
|---|---|
| `data-feeds.md` | `sources/`, `datamodel/`, `feeds.py`, `hosts.py`, `tables.py`, `db.py`, `schema.sql`, `run.sh`, `pipeline.py` — incl. analyst-target cadence |
| `factors-backtest.md` | `factors.py`, `pit.py`, `config.py`, `signals/`, `scoring/`, `eligibility/`, backtest + study tools |
| `health-checks.md` | `checks/`, `validators/`, `views.py`, `tools/health_report.py` |
| `cockpit.md` | `cockpit/`, `cockpit_ops/` |
| `org.md` | `org.py`, `alpha_mcp/`, `.claude/routines/`, `.claude/agents/` |

---

## Keeping this file small

- Budget, enforced by `tests/test_claude_md.py`: this file ≤ 1,800 words and ≤ 60 words per bullet; each area file ≤ 800 words, with `paths:` that match real files
- A rule stays here only if any session could break it. Otherwise it goes in the area file whose paths fit (new area → new file + a row above)
- The story behind a rule ("on 2026-10-08 …", evidence, numbers) goes in its ADR; the rule keeps one clause and the ADR number. A rule a test enforces shrinks to "X — `tests/test_Y.py`"
- `/handoff` runs the budget test. Over budget: demote the least general rule to its area file, or merge two — never just delete one

---

## Session Protocol

**Start (automatic):** the SessionStart hook (`.claude/hooks/session_start.py`) injects the health report, HANDOFF.md and git state, and the first reply opens with the catchup report (`/catchup` does it by hand). Name the checklist item(s) this session works on — if the goal isn't a bullet in `docs/plans/0000-checklist.md`, add it before starting.
**End:** `/handoff` overwrites HANDOFF.md, updates the checklist (step 1.5), prunes rules to budget, files any ADRs, updates plan status, commits.

Skipping `/handoff` is the single biggest source of context loss. Working on something that isn't on the checklist is the second.

---

## When to write a doc

| Trigger | Where it goes |
|---|---|
| Non-obvious technical choice | New ADR in `docs/decisions/` (write-once; decision in the first 10 lines, ≤60 total; mark the ADR it supersedes) |
| Detail diverges from active plan | Append to that plan's "Implementation notes" |
| New recurring landmine | One-line rule — here if any session could hit it, else the matching `.claude/rules/` file |
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
