# 0008 — Cockpit as a write-side surface (starting with step rerun)

**Status:** Accepted
**Date:** 2026-05-02
**Decided by:** Amit (with Claude Code)

## Context

The cockpit ([cockpit/app.py](../../cockpit/app.py)) has been read-only since it shipped: every route reads SQLite via `db.read_sql`, renders Jinja templates, returns HTML or JSON. The pipeline is mutated only by `cron` at 03:30 UTC or by the user invoking `python pipeline.py` from the shell.

Today (2026-05-02) the user asked for the ability to rerun a failed pipeline step from the `/flow` page itself — without dropping into a terminal. The natural place for that capability is the cockpit, which already shows step status and which the user already has open when triaging a failure. The alternative (a separate CLI helper, or a chat command) would split the workflow.

This is the first time the cockpit has been allowed to *cause* state change rather than just *display* it. That shift deserves a recorded decision because the next request — "let me kick the regulatory harvester," "let me toggle a feature flag," "let me edit a weight" — will land in the same place, and we want a deliberate scope each time rather than scope drift.

## Decision

The cockpit is now a **write-side surface**, but with a strict scope and concrete guardrails.

**Scope today (2026-05-02):**
- One write endpoint: `POST /api/pipeline/rerun/{step_name}` ([cockpit/app.py](../../cockpit/app.py)).
- One helper: `cockpit.api.rerun_step()` ([cockpit/api.py](../../cockpit/api.py)).
- Triggered from a `↻` button on each step pill in the mini-DAG and on each detail card in [cockpit/templates/flow.html](../../cockpit/templates/flow.html).

**Guardrails (apply to *every* write endpoint added going forward):**
1. **Allowlist.** Any user-supplied identifier (step name, source name, etc.) must be validated against a server-side enumeration before being passed to a subprocess or SQL query. The rerun endpoint validates `step_name` against `{s["name"] for s in PIPELINE_STEPS}` and returns `{"ok": false, "error": "unknown step: ..."}` on miss.
2. **Dedup / idempotency.** A write must refuse if it would duplicate a still-active operation. Rerun checks `pipeline_log` for a `RUNNING` row younger than 5 minutes and returns HTTP 409 if found. Stale RUNNING (older than 5 min) is treated as crashed and the rerun proceeds.
3. **Subprocess detachment.** Any spawned process must use `start_new_session=True` so it survives the HTTP request, and its stdout/stderr must be redirected to a file, not held in a Python pipe. Rerun writes to `output/rerun.log`.
4. **No shell.** `subprocess.Popen` is called with an explicit arg list, never `shell=True` and never with f-string interpolation of user input.
5. **Confirmation in the UI.** Every write button must show a `confirm()` dialog before firing. Rerun does this in the JS at the bottom of [cockpit/templates/flow.html](../../cockpit/templates/flow.html).

**Out of scope today** (revisit each separately):
- Editing config values (weights, thresholds, the pipeline step list)
- Direct SQL writes from the UI (the read-only `/sql` console stays read-only)
- Triggering destructive operations (DROP, DELETE, file removal)
- Multi-user auth / RBAC (cockpit is single-user, internal-only on a single VM with no public exposure)

## Alternatives considered

- **CLI helper script** (`./rerun.sh fetch_bhavcopy`). Rejected: splits the workflow. The user is already on `/flow` looking at the failure; making them switch to a terminal adds friction for no benefit.
- **Slack-style chat command.** Rejected: adds a new surface (Slack app, webhook, message parsing) that doesn't exist yet. Premature.
- **Add a separate "ops" page in the cockpit instead of mutating `/flow`.** Rejected: the rerun button belongs *next to the status it's reacting to*. Splitting the view from the action would be worse UX, not better.
- **Use a job queue (Celery, RQ, dramatiq).** Rejected: overkill for "spawn one subprocess and walk away." `subprocess.Popen` with `start_new_session=True` is the right size.
- **Block the HTTP request until the step finishes.** Rejected: most steps take seconds, but `fetch_bhavcopy` and the dossier step take minutes; a blocking request would time out and the user wouldn't know whether the step actually ran.

## Consequences

**Easier:**
- Single-click recovery for a failed step from the page where the failure is visible.
- The cockpit is now a coherent ops console, not just a read view.
- Adding the next write endpoint (e.g. "kick the regulatory harvester") follows a known pattern with known guardrails.

**Harder:**
- Two writers can race for the same SQLite file: cron at 03:30 UTC and a user click. SQLite WAL handles this safely at the row level, but a manually triggered rerun overlapping the cron run could write rows for the same `(run_date, step_name)` pair. The dedup check (5-min RUNNING window) catches the common case; the residual risk is "rerun fired between cron's row write and the next status write," which is small.
- Subprocess spawned by uvicorn inherits its environment. If `run_pipeline.sh` exports credentials that `pipeline.py` relies on, calling `pipeline.py` directly from the cockpit may miss them. Today's verified rerun (`regime_update`, no external API calls) doesn't exercise this — the first user who reruns a credential-dependent step will find out. Mitigation if it bites: the rerun helper should source `run_pipeline.sh`'s env, or `cockpit.api.rerun_step` should explicitly export the credentials the pipeline expects.
- `output/rerun.log` grows without rotation. Trivial to add later.

**Will bite us if:**
- We start adding write endpoints without re-checking the five guardrails above. The discipline is what keeps this safe; the framework can't enforce it.
- The cockpit ever gets exposed beyond `localhost`/internal network. Today the systemd unit binds to `0.0.0.0:3000` on a single Oracle Cloud VM with no public ingress, so this is fine. Public exposure would require auth before any write endpoint stays.

## References

- Endpoint: `POST /api/pipeline/rerun/{step_name}` in [cockpit/app.py](../../cockpit/app.py)
- Helper: `rerun_step()` in [cockpit/api.py](../../cockpit/api.py)
- UI: rerun buttons + JS handler in [cockpit/templates/flow.html](../../cockpit/templates/flow.html)
- Smoke test: `test_rerun_step_rejects_unknown_step` in [tests/test_smoke.py](../../tests/test_smoke.py)
- Related: [0002-no-prefect.md](0002-no-prefect.md) — why we don't use a job queue
