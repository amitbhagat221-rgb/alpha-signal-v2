# HANDOFF

> Overwritten at the end of each session per CLAUDE.md session protocol. If you're starting a new session: read this, then CLAUDE.md, then any plan or ADR linked below.

**Last updated:** 2026-05-02 (Amit Bhagat + Claude Code)
**Current branch:** `master` (clean tree as of session start; today's work uncommitted)
**HEAD:** `6249984` Initial commit — *no follow-up commits yet; today's UI work is unstaged*

---

## Where I am

v2 took over from v1 yesterday (2026-05-01). Today was a single-thread session about the cockpit's `/flow` page: started as a "should we add Dagster?" conversation, ended as a hand-rolled mini-DAG visualization with in-UI step rerun. **All changes are unstaged.** The pipeline itself was not touched; signals, scoring, schema, cron — all untouched.

## What works

- `/flow` page now shows a **mini-DAG visualization** above the existing detail cards: 4 phase columns side-by-side (Sources → Signals → Scoring → Output), color-coded step pills, fat `→` arrows, critical-fail steps get a thick red border. Hand-rolled CSS grid; no graph library. See [cockpit/templates/flow.html](cockpit/templates/flow.html).
- **In-UI step rerun**: every step pill (mini-DAG) and every detail card has a `↻` button. Clicking POSTs to `/api/pipeline/rerun/{step_name}`, which spawns `python pipeline.py --step <name>` as a detached subprocess and returns immediately. Backed by `rerun_step()` in [cockpit/api.py](cockpit/api.py) and the new POST route in [cockpit/app.py](cockpit/app.py).
- **Duplicate protection**: rerun refuses with HTTP 409 if a `pipeline_log` row for that step is in `RUNNING` state and younger than 5 min. Verified end-to-end with a fake RUNNING row injection.
- **Auto-refresh**: `/flow` reloads every 60s with a visible countdown; rerun shortens countdown to 8s so you see state flip soon after triggering.
- **Failure banner**: any FAILED or ABORTED step in the latest run pops a top-of-page banner with anchor links to each failed card, including a 60-char excerpt of `error_message`.
- **Smoke tests pass** ([tests/test_smoke.py](tests/test_smoke.py)) — added two tests (`test_flow_overview_returns_layers_and_failures`, `test_rerun_step_rejects_unknown_step`); all 6 green via `python -m tests.test_smoke`.
- **Live verification done**: cockpit restarted, page rendered cleanly at http://localhost:3000/flow, real `regime_update` rerun produced fresh RUNNING + SUCCESS rows in `pipeline_log` within 4 seconds.

## What's broken or half-built

- **Nothing is committed yet.** `git status` will show: modified [cockpit/api.py](cockpit/api.py), [cockpit/app.py](cockpit/app.py), [cockpit/templates/flow.html](cockpit/templates/flow.html), [tests/test_smoke.py](tests/test_smoke.py); empty [HANDOFF.md](HANDOFF.md) being filled now; new files `output/rerun.log` and two `.playwright-mcp/` screenshots (verification artifacts — do not commit).
- **No CHANGELOG entry yet** for today — proposed below in this HANDOFF, not written.
- **No ADR yet** for the architectural shift "cockpit can mutate state via subprocess spawning" — proposed below as ADR 0008, not written.
- **README.md is stale** — reads "Phase 7 of 9 complete" and lists Phase D/8/9 as not started; reality is v2 is in production and smoke tests exist. [README.md:5,77-80](README.md).
- **architecture.md is stale** — "What's not built yet" lists "Parallel run" (done 2026-05-01); also says Tickertape is manual when crontab actually runs `run_tickertape_monthly.sh` on the 1st of each month. [docs/architecture.md:173-178](docs/architecture.md).
- **v1 weekend-refresh cron is still firing** every Saturday 5am: `/home/ubuntu/alpha-signal/run_weekend_refresh.sh`. Either port to v2 or kill — needs a deliberate decision.

## Next 3 actions (in order, concrete)

1. **Commit today's `/flow` work** as one commit. Includes ADR 0008 + CHANGELOG entry + the four code/template changes + `cockpit/pipeline_dag.py` deletion + this HANDOFF. Add `output/rerun.log` and `.playwright-mcp/` to `.gitignore`. Commit message draft in "Open questions" below.
2. **Refresh README.md and architecture.md** to match reality (Phase D/8/9 done, Tickertape on cron, no "what's not built" parallel-run item). 10-min cleanup; safe to do same-day.
3. **Resume regulatory harvester**: paused on 2026-04-10 after hitting Anthropic budget; CHANGELOG slated resumption for "May 1" which was yesterday. Verify budget reset, re-enable in [config.py](config.py) (or wherever the pause toggle lives), monitor first run.

## Don't do

- **Do not add Dagster, Airflow, Prefect, or any DAG/asset framework.** Today's conversation explicitly re-litigated and re-rejected this — see [docs/decisions/0002-no-prefect.md](docs/decisions/0002-no-prefect.md). The `/flow` page now does the visualization job at zero framework cost.
- **Do not add `depends_on` to PIPELINE_STEPS.** Pipeline is linear today; the mini-DAG infers phases by `module` prefix. Adding the field with no consumer is premature.
- **Do not vendor Mermaid or any graph library.** The hand-rolled CSS-grid mini-DAG is the answer; Mermaid was tried today and abandoned because its auto-layout collapsed 26 nodes into an unreadable horizontal stripe (this is why `cockpit/pipeline_dag.py` is deleted).
- **Do not amend or force-push commits.** No commits since `6249984` Initial commit anyway.
- **Do not run `python pipeline.py` (full run) without checking `pipeline_log` first** — the daily cron run already happened at 03:30 UTC; a manual full run would mostly INSERT-OR-IGNORE / INSERT-OR-REPLACE its way through, but is wasteful and logs noise.
- **Do not modify v1 (`~/alpha-signal/`)** — its weekend cron is still firing; touching v1 is out of scope until the decommission decision is made.

## Open questions for me (decisions you need to make)

1. **ADR 0008 scope** — proposed below covers "cockpit may spawn subprocesses to rerun pipeline steps." Should it broaden to "the cockpit is a write-side surface, with these guardrails," anticipating future write-side endpoints (trigger backfill, kick harvester, edit a flag)? My take: yes, broaden — but keep the *current* scope strictly to step rerun until each new mutation is added behind its own review.
2. **Commit message + split** — draft: `feat(cockpit): pipeline DAG viz + in-UI step rerun on /flow`. Keep as one commit, or split into (a) DAG-viz, (b) rerun feature, (c) ADR/CHANGELOG/HANDOFF? My take: one commit. The pieces are coupled (the rerun button lives on the DAG pills) and the diff is small.
3. **Decommission v1 weekend refresh?** — `0 5 * * 6 /home/ubuntu/alpha-signal/run_weekend_refresh.sh` still fires. What does it actually do that v2 doesn't? Worth a 10-minute audit before killing.
4. **Should rerun support a `?force=1` override** for the 5-min RUNNING-row guard? Use case: a step crashed silently and the RUNNING row never got finalized. The cockpit's existing `get_pipeline_status` already marks >5-min RUNNING as ABORTED visually; the rerun endpoint uses the stricter check.
5. **`output/rerun.log`** — currently appends forever, no rotation. Add to `.gitignore` for now. Long-term: rotate weekly, or just truncate on cockpit restart?

---

## Proposed for this session, awaiting approval

**ADR 0008** — *Cockpit as a write-side surface (step rerun)*. Captures: cockpit may now spawn `pipeline.py` subprocesses; guardrails (step-name allowlist from `PIPELINE_STEPS`, RUNNING-row dedup, `start_new_session=True` so subprocess survives the HTTP request); scope (only rerun for now, not config edits or DB writes); reversal cost (low — single endpoint + one helper function).

**CHANGELOG.md entry** — under `## 2026-05-02`:
- `/flow` page rebuilt: hand-rolled mini-DAG (4 phase columns, color-coded step pills, critical-fail border) replaces the previous card-only view. Rejected Mermaid earlier in the session — its auto-layout collapsed 26 nodes into an unreadable stripe.
- In-UI step rerun: `↻` button on every step (mini-DAG + detail card) → POST `/api/pipeline/rerun/{step_name}` → spawns `python pipeline.py --step <name>` as detached subprocess. Duplicate-protected (refuses if RUNNING row younger than 5 min, returns 409). Logs to `output/rerun.log`.
- Auto-refresh on `/flow` every 60s with visible countdown; shortens to 8s after a rerun trigger so status flip is visible without manual reload.
- Smoke tests: dropped intermediate Mermaid-renderer tests; added `test_flow_overview_returns_layers_and_failures` and `test_rerun_step_rejects_unknown_step`. All 6 pass via `python -m tests.test_smoke`.
- Originally framed as "should we add Dagster?" — explicitly re-rejected per [docs/decisions/0002-no-prefect.md](docs/decisions/0002-no-prefect.md); ADR 0008 records the narrower decision (cockpit-as-write-surface) that did get accepted.

**No plan-status changes.** [docs/plans/0001-regulatory-signal.md](docs/plans/0001-regulatory-signal.md) and [docs/plans/0002-macro-data.md](docs/plans/0002-macro-data.md) remain "Implemented — distillation pending" — today's work didn't touch either area.
