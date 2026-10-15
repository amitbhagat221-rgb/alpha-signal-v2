---
paths:
  - "sources/**"
  - "datamodel/**"
  - "ops/**"
  - "feeds.py"
  - "hosts.py"
  - "tables.py"
  - "db.py"
  - "schema.sql"
  - "run.sh"
  - "runlog.py"
  - "pipeline.py"
  - "tools/canary.py"
  - "tools/reconcile.py"
  - "tools/freshness_watchdog.py"
---
# Data feeds, tables and harvesting

**Sources and feeds**
- Read `docs/reference/data-playbook.md` before fetching from any new source.
- Every data stream is a `feeds.FEEDS` entry (family, routes, canary; tier is derived). `tests/test_feeds.py` blocks unregistered modules/steps/RAW tables, unscheduled production feeds, and T1 feeds without fallback/serve-stale + canary.
- New source: candidate entry + canary on 3 items first (`python -m tools.canary --feed X`). Fix loop: [feed-runbook](../../docs/reference/feed-runbook.md). Debug with `python -m runlog bundle <feed>`.
- Failures must reach `run_events` (`runlog.py`): use `_http.run_harvester` + the door, or `runlog.item_error/item_failed` in a custom loop.
- Raw tables on the T1 path declare a write `contract` in `tables.TABLES` (enforced in `db.insert_df/upsert_df`). Never loosen one to make a harvest pass. After a canary `--accept`, refresh replay fixtures (`python -m tools.canary --save-fixtures`).
- The host door (`sources/_http` + `hosts.HOSTS`) owns gap ≥ 2 s, headers, retries and budgets — declare the host, never pace by hand.

**Columns mean what they say**
- A source column is named for what it holds, and its meaning is checked against a second source: a statement column a factor reads goes in `tools/reconcile.FUND_FIELDS` (ADR 0062 — Tickertape's "interest" was operating expenses for months).
- Append-only tables (insider_trades, bulk_deals, news_articles): `INSERT OR IGNORE`. Snapshot/state tables: column-level `db.upsert_df`, so one producer never NULLs another's columns (e.g. `analyst_consensus`).

**Analyst targets are episodic (HALC bug 2026-05-22)**
- Sell-side revises quarterly at best; daily PT history is phantom precision and lets `lastPrice` masquerade as a PT. Three tables, three rhythms:
  - `analyst_consensus` (PK sid, daily): the cockpit's current PT. The daily refresh updates `price_target` + `total_analysts` only. Yahoo owns `price_target`; the broker aggregate fills only stocks Yahoo does not cover (two writers produced 178 impossible averages, 2026-10-10).
  - `analyst_consensus_snapshots` (PK sid+date+source, MONTHLY, cron 1st 04:30 UTC): backtest + revision signals. Never write a daily row.
  - `forecast_history`: Tickertape year-end eps/revenue. Its `price` metric is the realized year-ahead close, not a PT — never ingest it (ADR 0045).
- New PT-like producer: ask "is this episodic?" — if yes, a snapshot table at its natural cadence.

**Harvest lock: one harvest per source (Amit 2026-10-15)**
- A harvest job in `run.sh` names its sources: `harvest_lock nse bse`. Jobs on different sources run in parallel; two on one source queue (wait `LOCK_WAIT_S`, then a logged skip).
- `harvest_lock` with no sources = every source, exclusive: the morning pipeline, the canary, `management`. The watchdog heal runner and the ops cockpit rerun take the same global file exclusively.
- A new source-specific job adds its sources; a job hitting more than three sources takes every source.

**Disk and long writers**
- `run.sh sweep` clears week-old scratchpads; `DISK_LOW` pages. A DB copy you truly need goes in a worktree and is deleted the same session.
- Long writers include panel rebuilds, `datamodel.sync` and backfills — one at a time.
