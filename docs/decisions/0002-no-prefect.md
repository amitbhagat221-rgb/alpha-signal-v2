# 0002 — No Prefect, plain Python orchestrator
**2026-04-09 · Accepted**

**Decision.** Hand-rolled `pipeline.py` (~100 lines) reads steps from `config.PIPELINE_STEPS`, runs each as a subprocess, logs to `pipeline_log` table. Flags: `--dry-run`, `--step <name>`, `--status`. Cron at 03:30 IST.

**Why.** Single VM, single user, 24 sequential daily tasks. Visibility need is "did it run? did anything fail?" — answered by `SELECT * FROM pipeline_log WHERE status='FAILED'`. A framework's mental-model tax exceeds its value at this scale.

**Trade-offs.**
- Zero deps beyond Python; new steps = append to a dict
- No built-in retries (most failures are deterministic; retry won't help)
- Revisit if pipeline grows past ~50 steps with real DAG dependencies

**Not chosen.** Prefect Cloud (overkill). Airflow/Dagster (server). Make (poor logging surface).

**References.** `pipeline.py` · `config.PIPELINE_STEPS`
