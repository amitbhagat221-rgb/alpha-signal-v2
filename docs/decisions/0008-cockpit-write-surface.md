# 0008 — Cockpit as a write-side surface (starting with step rerun)
**2026-05-02 · Accepted**

**Decision.** Cockpit gains write endpoints, scoped narrowly. First: `POST /api/pipeline/rerun/{step_name}` — rerun a failed pipeline step from the `/flow` page via a `↻` button. Helper: `cockpit.api.rerun_step()`.

**Why.** When triaging a failed step, the user is already on `/flow`. A separate CLI helper splits the workflow. This is the first time the cockpit causes state change rather than just displaying it — worth recording so the next "let me kick X" request inherits a deliberate scope, not scope drift.

**Guardrails (apply to every write endpoint going forward).**
1. **Allowlist** any user-supplied identifier (step name validated against `{s["name"] for s in PIPELINE_STEPS}`)
2. **Dedup** — refuse if a `RUNNING` row younger than 5 min exists (HTTP 409). Stale = treated as crashed.
3. **Subprocess detachment** — `start_new_session=True`, stdout/err to file (`output/rerun.log`)
4. **No shell** — explicit arg list, never `shell=True`, never f-string interpolation
5. **UI confirm()** before firing

**Out of scope.** Editing config values, direct SQL writes, destructive ops, multi-user auth. Cockpit is single-user, localhost-only on a single VM.

**Risks.** Cron + manual click could race on same `(run_date, step_name)` — SQLite WAL handles row-level, dedup catches common case. Public exposure would require auth before any write endpoint stays.

**References.** [cockpit/app.py](../../cockpit/app.py) · [cockpit/api.py](../../cockpit/api.py) · [tests/test_smoke.py](../../tests/test_smoke.py) `test_rerun_step_rejects_unknown_step`
