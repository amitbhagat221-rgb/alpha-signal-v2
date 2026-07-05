# Plan 0010 — Audit Remediation Roadmap (Sonnet-executable)

**Status:** done (2026-07-05) · **Source:** [docs/audit-2026-07-04-report.md](../audit-2026-07-04-report.md) · **Written:** 2026-07-04 by Opus for a Sonnet executor.

**Execution summary (2026-07-05):** all 32 tasks across 6 phases completed, 0 BLOCKED. Three tasks
(3.2 purge, 3.3 evidence re-run, 4.4 paper backfill) were DB-mutation-only with no repo file diff,
so they carry no dedicated commit — see `git log` for the 25 code/doc commits and this plan's own
task-level VERIFY output (re-run at each step) for evidence. `git log --oneline` from
`374a67d`..`7b737d4` covers Phases 1-6.

This plan is deliberately over-specified. Every decision a weaker model might agonize over is
**pre-answered** in a `DECIDED:` line. Do not re-litigate DECIDED items. Do not invent scope.
If a task hits a `STOP-IF` condition, write `BLOCKED: <reason>` under that task in THIS file,
commit what's done, and move to the next task. Never guess.

---

## GLOBAL RULES (read twice, they override your instincts)

1. `source ~/alpha-signal/venv/bin/activate` before ANY python. Every time. New shell = re-activate.
2. All work in `~/alpha-signal-v2/`. NEVER touch `~/alpha-signal/` (v1 is LIVE on cron).
3. Line numbers in this plan are **hints from the audit** — locate code by the quoted content,
   not the number. If the quoted content doesn't exist, STOP-IF applies.
4. One commit per task, using the exact commit message given. NEVER `git add .`, `git add -A`,
   or `git commit --amend`. Add files by explicit path only.
5. NEVER run two harvester/fetch scripts at once. NEVER run the full pipeline
   (`python -m pipeline`). Tasks below name the ONLY commands you may run.
6. Any DB-mutating step: first `cp data/alpha_signal.db /tmp/claude-backup-$(date +%s).db` is
   **wrong** (7 GB, don't copy). Instead: the nightly rclone backup exists; your safety net is
   that every mutation below is either (a) an UPDATE with an exact WHERE you were given, or
   (b) a producer re-run that upserts by PK. Never write ad-hoc SQL not given in this plan.
7. After each task run its VERIFY block. If VERIFY fails twice → BLOCKED, move on.
8. Timezone: server is UTC. "today" in SQL = `date('now')`.
9. Do not restart, kill, or reload the cockpit service or any systemd unit. Never `pkill -f uvicorn`.
10. Finish the session with `/handoff` (updates HANDOFF.md + checklist + commits).

**Execution order is the phase order below.** Within a phase, task order. Skip nothing silently.

---

## PHASE 0 — Preflight (commit the existing working tree)

The repo has uncommitted changes that predate you. Commit them FIRST so your diffs are clean.

**Task 0.1 — commit pre-existing work-in-progress.**
- `git status` — expected modified: `HANDOFF.md`, `db.py`, `docs/plans/0000-checklist.md`,
  `sources/nse_insider.py`, `tools/freshness_watchdog.py`, `tools/health_report.py`;
  untracked: `tools/risk_decomp.py`, `docs/audit-prompt.md`, `docs/audit-2026-07-04-report.md`,
  `amit_personal_docs/`.
- DECIDED: NEVER add `amit_personal_docs/` (personal, stays untracked). Add everything else
  listed above by explicit path (two commits):
  - Commit A: `git add sources/nse_insider.py tools/freshness_watchdog.py tools/health_report.py db.py tools/risk_decomp.py HANDOFF.md docs/plans/0000-checklist.md` →
    `git commit -m "wip: pre-audit working tree (insider future-date guard, watchdog/health tweaks, risk_decomp step 1)"`
  - Commit B: `git add docs/audit-prompt.md docs/audit-2026-07-04-report.md docs/plans/0010-audit-remediation.md` →
    `git commit -m "docs(audit): 2026-07-04 full-system audit — prompt, report (58/100), remediation plan 0010"`
- VERIFY: `git status` shows only `amit_personal_docs/` untracked, nothing modified.

---

## PHASE 1 — Mechanical bug fixes & alarm holes (low risk, do first)

**Task 1.1 — Register `fundamentals_screener` for freshness (closes audit Data-F2).**
- File: `config.py`. Find the `RAW_TABLES` dict (~lines 881-924, contains entries like
  `quarterly_income`). Add an entry for `fundamentals_screener` mirroring the style of the
  existing entries.
- DECIDED: anchor on `fetched_at`, threshold **21 days** (the manual screener pull is roughly
  fortnightly; 21d gives one missed cycle before alarm). If entries use a `frequency` string
  instead of day-counts, use whatever existing value maps closest to ~21d; if only
  daily/weekly/monthly exist, use `weekly` with a staleness override of 21d — copy the exact
  mechanism `quarterly_income` uses for its 120d override.
- Note in the entry's comment: `# manual pull; auth broken 2026-07-01 — alarm is the point`.
- DECIDED: do NOT attempt to fix the Screener.in auth itself. That needs Amit's credentials —
  it is listed in "HUMAN TASKS" at the bottom.
- VERIFY: `python -c "from db import data_health; import json; h=data_health(); rows=[r for r in h if 'fundamentals_screener' in str(r)]; print(rows)"` —
  adapt to `data_health()`'s real return shape (read the function first); the table must now
  appear with a real staleness status (expected: STALE/OUTDATED, since it IS 55d stale — that
  alarm firing is SUCCESS for this task).
- Commit: `fix(health): register fundamentals_screener freshness — 55d-stale source was alarm-invisible (audit Data-F2)`

**Task 1.2 — Freshness date-column blind spots (audit Data-F4).**
- File: `db.py`, find `DATE_COLS` (~line 1047, a list starting `snapshot_date, date, end_date...`).
- Add: `as_of_date`, `brief_date`, `change_date` (exact strings; `as_of_date` has underscores).
- Then in the freshness/data_health code path (same file, near `_table_date_range`): add a WARN
  when a table has a registered frequency but `latest_date is None`. DECIDED: new status string
  `"NO_DATE_ANCHOR"`, treated at WARN severity (not CRITICAL) — find where statuses like
  STALE/OUTDATED are assigned and mirror.
- File: `tools/health_report.py` — find where STALE/OUTDATED are surfaced (~lines 238-245) and
  include `NO_DATE_ANCHOR` in the surfaced set.
- VERIFY: run `python -m tools.health_report` (it is read-only + prints; safe). `mf_metrics`,
  `mf_holdings`, `news_briefs`, `daily_changes` must now show real dates (not N/A);
  `news_article_stocks` (genuinely no date column) should show `NO_DATE_ANCHOR` WARN.
- Commit: `fix(health): add as_of_date/brief_date/change_date to DATE_COLS + NO_DATE_ANCHOR warn (audit Data-F4)`

**Task 1.3 — MF `sharpe_1y`/`sortino_1y` fabrication bug (audit MF-F4).**
- File: `signals/mf_metrics.py` ~line 163: `sharpe_1y = ((ret_1y or 0)/100 - RISK_FREE_RATE) / (std_1y/100)`
  and the same `or 0` pattern for `sortino_1y` ~line 173.
- Fix: mirror the 3Y branch's guard exactly (it checks `ret_3y is not None`); when `ret_1y is
  None`, sharpe_1y/sortino_1y must be `None`.
- Then recompute the latest snapshot: read `signals/mf_metrics.py`'s entry point (how
  PIPELINE_STEPS calls it — check `config.py` PIPELINE_STEPS for the mf_metrics step's
  module/function) and run exactly that function once via
  `python -c "from signals.mf_metrics import <fn>; <fn>()"`. It upserts by PK
  (scheme_code, as_of_date) — DECIDED: overwriting today's/latest snapshot in place is correct
  and intended. This touches no external API (reads mf_nav_history only) — confirm by reading
  the function before running; if it fetches anything external, STOP-IF → run nothing, commit
  the code fix only, note "recompute deferred to next monthly cron".
- VERIFY: `sqlite3 data/alpha_signal.db "SELECT COUNT(*) FROM mf_metrics WHERE as_of_date=(SELECT MAX(as_of_date) FROM mf_metrics) AND ret_1y IS NULL AND sharpe_1y IS NOT NULL;"` → **0** (was 467).
- Commit: `fix(mf): sharpe_1y/sortino_1y fabricated 0%-return for NULL ret_1y — guard like 3Y branch (audit MF-F4)`

**Task 1.4 — email_sender must raise on failure (audit Data-F6).**
- File: `output/email_sender.py`. ~lines 578-580: missing-GMAIL-creds path returns 0 with a
  print; ~595-597: a bare `except` swallows send exceptions and returns 0.
- DECIDED: in non-dry-run mode, BOTH paths must `raise RuntimeError("email send failed: <reason>")`.
  Keep any existing dry-run flag behavior unchanged (if a dry-run flag exists, it may still
  return without sending, silently). The local HTML file write stays as-is.
- STOP-IF: you cannot find a clear dry-run flag AND the function is called from more than one
  production site with different expectations — then only fix the missing-creds path (raise)
  and leave the send-exception path, noting BLOCKED for the rest.
- VERIFY: `python -c "import os; os.environ.pop('GMAIL_APP_PASSWORD', None); ..."` — construct
  a 3-line snippet that calls the send function with a dummy payload and asserts it raises.
  Read the function signature first. Do NOT actually send an email (missing creds guarantee
  the raise happens before SMTP).
- Commit: `fix(email): raise on missing creds / send failure instead of silent return (audit Data-F6, producers-must-raise rule)`

**Task 1.5 — Silence the month-old `uhs_calibration_log` CRITICAL correctly (audit Data-F5).**
- Two edits:
  a) `tools/health_report.py` ~line 75: DELETE `uhs_calibration_log` from
     `EXPECTED_EMPTY_TABLES` (it has 11,718 rows; the entry is stale).
  b) Find the staleness-override mechanism (grep `STALENESS_OVERRIDE` in db.py/config.py —
     `pick_outcomes` has a 35d override). Add `uhs_calibration_log: 45` (days).
     Rationale, pre-answered: calibration rows mature on a 20d forward window, so the newest
     `date` value is structurally ~1 month old. 45d = alarm only on true death.
- VERIFY: `python -m tools.health_report` → `uhs_calibration_log` no longer CRITICAL (OK or WARN
  acceptable). No other table's status changed vs before your edit (diff the two outputs).
- Commit: `fix(health): uhs_calibration_log 45d staleness override + drop stale EXPECTED_EMPTY entry — ends month of false CRITICALs (audit Data-F5)`

**Task 1.6 — Generic future-date guard on ingestion (audit Data-F9).**
- File: `db.py`, in `insert_df` and `upsert_df`: before writing, if the DataFrame has any
  column in DATE_COLS, drop rows where that column parses to a date **> today + 2 days**, and
  `print(f"[future-date guard] {table}: dropped {n} rows")` when n>0.
- DECIDED: +2 days (not +7) — accommodates weekend/T+1 NAV publishing; the +7 tolerance in
  `_table_date_range` (db.py:1068) stays as-is for reads. Drop-and-log, do NOT raise.
- DECIDED: also clean the existing bad rows:
  `sqlite3 data/alpha_signal.db "DELETE FROM mf_nav_history WHERE nav_date > date('now', '+2 day');"`
  (audit found 90 rows at +1 day — those are within the new tolerance and will survive; only
  genuinely future rows are deleted. If the DELETE reports 0, that is fine.)
- VERIFY: write a 5-line python test in the scratchpad (NOT the repo): build a 2-row DataFrame
  for a fake date column with today and today+10d, call the guard logic (import the helper),
  assert 1 row survives. Do not insert into a real table.
- Commit: `fix(db): reject rows dated > today+2d in insert_df/upsert_df — future-dated NAV rows were breaking freshness math (audit Data-F9)`

**Task 1.7 — Register the DuckDB replica in FILE_OUTPUTS (audit Data-F10).**
- File: `config.py`, find `FILE_OUTPUTS` (~lines 934-944, has `_file_dossiers`). Add an entry
  for the `.duckdb` replica file (find its exact path in `db.py` ~line 395 `read_sql_fast`).
  DECIDED: mtime anchor, threshold 2 days, WARN not CRITICAL.
- VERIFY: `python -m tools.freshness_watchdog --help` first to find a report-only/dry mode; if
  none exists, `python -m tools.health_report` and confirm the file appears and is FRESH.
- Commit: `fix(health): track duckdb replica in FILE_OUTPUTS — failed rebuilds were silent-stale (audit Data-F10)`

**Task 1.8 — flock: one harvester at a time (audit Data-F8).**
- Files: `run_pipeline.sh`, `run_daily_forward.sh`, and the watchdog heal invocation path.
- DECIDED: simplest correct mechanism — wrap each script body:
  `exec 200>/tmp/alpha_signal_harvest.lock; flock -n 200 || { echo "another harvester holds the lock, exiting"; exit 0; }`
  near the top of both .sh files (after the shebang/env setup, before any python). For the
  watchdog heal (python), add the same via `flock` file-lock in python (`fcntl.flock`,
  non-blocking, skip-heal-with-log on contention) inside `tools/freshness_watchdog.py`'s heal
  runner (~line 190).
- STOP-IF: run_pipeline.sh structure makes the `exec 200>` placement ambiguous (e.g. it
  re-execs itself) — then lock only the watchdog heal + run_daily_forward.sh and note BLOCKED
  for run_pipeline.sh.
- VERIFY: in two shells (sandbox-safe): `bash -c 'exec 200>/tmp/alpha_signal_harvest.lock; flock -n 200 && sleep 2' & sleep 0.3; bash run_daily_forward.sh --help 2>&1 | head -3` —
  if the script has no `--help`, instead verify by reading: the lock lines are before any
  python invocation. Do NOT actually run the harvest.
- Commit: `fix(ops): flock across run_pipeline/run_daily_forward/watchdog-heal — no-two-harvesters rule now enforced in code (audit Data-F8)`

---

## PHASE 2 — Efficiency (wasted compute, doubled scrapes)

**Task 2.1 — Kill the duplicate monthly Tickertape scrape (audit Eff-F1).**
- File: `config.py` ~lines 525-529: two PIPELINE_STEPS entries, `fetch_analyst` and
  `fetch_forecast`, BOTH calling `sources.tickertape_analyst.compute`. The comment claims the
  runner dedupes — it does not (`pipeline.py:143-155` proven double-run in pipeline_log).
- DECIDED: delete the `fetch_forecast` step entry entirely. Before deleting, check what the
  entry declares as its output table(s) (likely `forecast_history`): move that table name onto
  the `fetch_analyst` entry's table list so freshness tracking is preserved (read how other
  steps declare multiple tables; if the schema is one-table-per-step, instead add
  `forecast_history` to RAW_TABLES with a monthly threshold — same outcome).
  Fix the misleading comment.
- VERIFY: `python -c "import config; steps=[s for s in config.PIPELINE_STEPS if 'tickertape_analyst' in str(s)]; print(len(steps), steps)"` → exactly 1 step.
  And `python -m tools.health_report` still shows `forecast_history` freshness-tracked.
- Commit: `fix(pipeline): remove duplicate fetch_forecast step — same function ran twice monthly, ~1.9h + doubled Tickertape load (audit Eff-F1)`

**Task 2.2 — Coverage-aware yfinance fetch (audit Eff-F3).**
- File: `sources/yfinance_analyst.py` (~lines 231-244, the universe loop).
- DECIDED: skip logic = "if the sid's `analyst_consensus` row has `price_target IS NULL AND
  total_analysts IS NULL` (i.e. Yahoo has no coverage), only re-attempt it on Mondays"
  (`datetime.utcnow().weekday() == 0`). Everything with coverage keeps daily cadence.
  Implement by reading the no-coverage sid set from the DB at function start (one SELECT).
- DECIDED: do NOT touch the monthly `--snapshot` cron or its double-fetch on the 1st — that
  duplication is 12×/year and entangled with the snapshot table; noted for Amit instead.
- VERIFY: smoke test, 3 stocks, exactly as the module supports it (read its `__main__`/CLI for
  a limit flag; the project rule is smoke-test-3-before-full-run). Confirm: a no-coverage sid
  is skipped on a non-Monday (today 2026-07-04 is Saturday — weekday 5 — so skips happen);
  runtime prints the skip count. Do NOT run the full universe.
- Commit: `perf(yfinance): weekly retry for ~1,400 no-coverage sids, daily for covered — cuts fetch_yf_analyst ~50%+ (audit Eff-F3)`

**Task 2.3 — Annual-data signals: daily → weekly (audit Eff-F4).**
- File: `config.py` PIPELINE_STEPS (~562-654). Every step with `"data_freq": "annual"` or
  `"data_freq": "quarterly"` AND `"frequency": "daily"` → change `"frequency"` to `"weekly"`.
- DECIDED: weekly (not monthly) — the 4 tables `signals/multibagger.py` reads weekly
  (roic/roiic/gross_profitability/operating_margin_trend) stay comfortably fresh, and the
  freshness thresholds derived from `frequency` keep working. Do NOT delete any step or table.
- STOP-IF: the freshness threshold is derived such that weekly frequency would false-alarm a
  table (read how `frequency` maps to staleness); if so, adjust only the mapping-safe subset.
- VERIFY: `python -c "import config; bad=[s['name'] for s in config.PIPELINE_STEPS if s.get('data_freq') in ('annual','quarterly') and s.get('frequency')=='daily']; print(bad)"`
  (adapt key names to the real schema after reading it) → `[]`.
- Commit: `perf(pipeline): annual/quarterly-data signal steps daily→weekly — ~35k redundant rows/day, zero daily consumers (audit Eff-F4)`

**Task 2.4 — Regulatory classifier: content dedup before LLM (audit Eff-F2, dedup only).**
- File: `sources/regulatory_classifier.py` (~105-129 the per-item loop, ~353-373).
- DECIDED scope: ONLY title-dedup. Before classifying an event, normalize its headline
  (lowercase, strip whitespace/punctuation), hash it; if an identical hash was already
  classified (check the output table for a stored hash, or classify-in-memory within the run
  AND store the hash column), reuse the earlier verdict. If adding a column, use
  `ALTER TABLE ... ADD COLUMN title_hash TEXT` guarded by a try/except-already-exists, matching
  however this codebase does column adds (grep `ADD COLUMN` for the house pattern).
- DECIDED: Batch API migration and the 500/day cap question are OUT of scope (parked for Amit).
- VERIFY: unit-style check in scratchpad: feed the dedup function two case-different copies of
  the same headline → one hash. Then run the classifier with its smallest supported limit
  (read the CLI; if it supports `--limit 5` or similar, use it) and confirm the log prints a
  dedup-skip counter. STOP-IF: no small-limit mode exists → verify by code-read only, note it.
- Commit: `perf(regulatory): title-hash dedup before LLM classification — same story was classified up to 3x (audit Eff-F2)`

**Task 2.5 — Stop double-writing the pipeline log (audit Eff-F6).**
- File: `pipeline.py` ~34-37: a FileHandler writes to `config.LOG_PATH` while cron already
  redirects stdout to the same file. DECIDED: remove the FileHandler, keep the
  StreamHandler/stdout path (cron redirect keeps working; interactive runs still print).
- VERIFY: `python -c "import pipeline"` imports clean; grep confirms no FileHandler remains.
- Commit: `fix(logging): drop FileHandler double-writing pipeline.log alongside cron redirect (audit Eff-F6)`

**Task 2.6 — Monthly scheduled backtest refresh (audit Eff-F5).**
- DECIDED: add ONE cron line (do not touch existing lines). Pattern MUST mirror the existing
  watchdog/health lines exactly (cd first, venv, env import, log redirect):
  `15 5 2 * * cd /home/ubuntu/alpha-signal-v2 && <same env-source prefix as the watchdog line> python -m tools.backtest_pit >> output/backtest_refresh.log 2>&1`
  Read `crontab -l` first and copy the exact prefix idiom from the watchdog line (05:15 UTC on
  the 2nd, after the monthly snapshot cron on the 1st).
- STOP-IF: `python -m tools.backtest_pit` with NO arguments does anything other than
  recompute/write `pit_ic_by_tier_v2` for all registered signals (read its `__main__` and
  argparse defaults FIRST). If the no-arg default is unclear or interactive → BLOCKED, do not
  install the cron.
- Install via: `crontab -l > /tmp/claude-1001/cron.bak && (crontab -l; echo "<line>") | crontab -`
- VERIFY: `crontab -l | tail -3` shows exactly one new line; `diff <(crontab -l | head -n -1) /tmp/claude-1001/cron.bak` empty.
- Commit (config-only if no repo file changes; else commit the docs note):
  `ops(backtest): monthly pit_ic refresh cron (2nd, 05:15 UTC) — registry was 6 anchors stale, hand-refreshed only (audit Eff-F5)`

**Task 2.7 — Dead-weight sweep (audit Eff-F9, safe subset only).**
- DECIDED: delete ONLY these (verified zero-byte / stray by the audit): root-level `alpha.db`,
  `alpha_signal.db`, `signals.db`, `data/v2.db`, `data/alpha.db` — CONFIRM each is 0 bytes
  first (`ls -la`); if ANY is >0 bytes, leave it and note it. Move root-level `*.png` into
  `docs/_archive/screenshots/` (create dir). Delete the never-called `_load_pit()` in
  `tools/backtest_pit.py` (~330-343) after `grep -rn "_load_pit" --include="*.py"` returns only
  its definition.
- DECIDED: do NOT drop any DB table, do NOT touch quarantine tables, paper_* tables, or
  `uhs_calibration_log` (deliberate accumulators).
- VERIFY: `python -m tools.backtest_pit --dry-run --signal pt_upside` still runs (proves the
  dead-code removal broke nothing; --dry-run is verified read-only by the audit).
- Commit: `chore: remove zero-byte db strays + dead _load_pit + archive root screenshots (audit Eff-F9)`

---

## PHASE 3 — CRITICAL: pt_upside look-ahead remediation

Read the audit report's headline section first. Facts you must accept, pre-verified:
`forecast_history` metric='price' rows dated Dec-Y contain the realized close of Dec-Y+1.
Every `daily_snapshots_pit.pt_upside` value at anchors before 2026-05 was built from them.
The factor's real edge on clean data is ~0 (IC 0.0009 on the one clean anchor).

**Task 3.1 — Stop the contamination at the source.**
- File: `tools/reconstruct_pit.py`, function `pit_pt_upside` (~line 1062, source-priority logic
  ~1086-1093). Change: the PT source list must NEVER include `forecast_history` metric='price'.
  Allowed sources: `analyst_consensus_snapshots` (primary; exists from 2026-05), and nothing
  else for historical anchors. For anchors with no snapshot ≤ eval_date, emit NULL (the
  emit-filter/PIT_COLUMNS behavior handles NULLs; per CLAUDE.md the writer only writes produced
  columns — do NOT pad NaN).
- Check `pit_pt_revision`/`pit_consensus` (~line 954 already drops pt_revision per the earlier
  cleanup) and grep the whole file for `forecast_history` — every remaining consumer of
  metric='price' rows gets the same removal. List each site you changed in the commit body.
- Commit: `fix(pit): pt_upside PIT must never consume forecast_history price rows — they embed the YEAR-AHEAD realized close (audit Factor-F1, CRITICAL)`

**Task 3.2 — Purge the contaminated PIT column.**
- DECIDED, exact SQL (run once):
  `sqlite3 data/alpha_signal.db "UPDATE daily_snapshots_pit SET pt_upside = NULL WHERE snapshot_date < '2026-05-01';"`
  Then rebuild the clean tail: `python -m tools.reconstruct_pit --signal pt_upside --skip-existing`
  is WRONG (skip-existing would skip). Read the tool's flags; run the form that recomputes
  pt_upside for anchors ≥ 2026-05-01 only (e.g. `--signal pt_upside --date <anchor>` per
  anchor, or `--months 3 --signal pt_upside`). The `--signal X` path writes only pt_upside's
  column — safe on existing dates by construction (CLAUDE.md).
- VERIFY: `sqlite3 data/alpha_signal.db "SELECT snapshot_date, COUNT(pt_upside) FROM daily_snapshots_pit GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 6;"` —
  non-zero counts ONLY on 2026-05+ anchors; zero on earlier.
- Commit: `fix(pit): null pre-2026-05 pt_upside (look-ahead artifact) + rebuild clean anchors from analyst_consensus_snapshots`

**Task 3.3 — Re-run the evidence chain.**
- `python -m tools.backtest_pit --signal pt_upside` (the writing form — updates
  `pit_ic_by_tier_v2`). Expected outcome: n≈2-3 anchors → INSUFFICIENT/DROP-grade. That is the
  CORRECT result; do not "fix" it.
- `python -m tools.multiple_testing` (verified read-only by the audit) — capture the new
  survivor list into the commit message body.
- Commit: `chore(backtest): re-run pt_upside + multiple-testing post-purge — pt_upside now honestly INSUFFICIENT (n<4 clean anchors)`

**Task 3.4 — Pull pt_upside from production weights.**
- File: `config.py` `SIGNAL_WEIGHTS` (pt_upside: LARGE 0.25, MID 0.24, SMALL 0.15).
- DECIDED (do not redesign): set pt_upside to 0 / remove it, and renormalize the REMAINING
  weights in each tier proportionally so Σ|w| = 1.0 per tier (negative weights keep their
  sign; use |w| for the normalization denominator). Example: if LARGE remaining |w| sums to
  0.75, multiply each remaining LARGE weight by 1/0.75. Round to 2dp and fix the largest
  weight by the rounding residual so the sum is exactly 1.00.
- DECIDED: also unwire `smart_money` (SMALL 0.05) in the SAME change — best-ever t=1.06 on n=6
  violates the documented ≥1.5 bar (audit Factor-F3). Same proportional renormalization.
- DECIDED: touch NOTHING else in weights. consensus MID stays (documented v1-held decision,
  Amit's call). `SIGNAL_WEIGHTS_RETURN`/`_SHARPE` variants: pt_upside entries there → set to 0
  too, no renormalization needed if they're non-production (confirm via config comment).
- Update `docs/reference/signal-weights.md`: new weights table + a dated paragraph explaining
  the pull (cite the audit report path).
- Run: `python -m scoring.screener` ONLY IF reading it confirms it is safe to run standalone
  (it reads signal tables, writes `daily_picks` — it is a daily pipeline step, idempotent for
  a given day per INSERT OR REPLACE semantics; confirm the write pattern first). Smoke check
  output: `sqlite3 data/alpha_signal.db "SELECT cap_tier, COUNT(*) FROM daily_picks WHERE pick_date=(SELECT MAX(pick_date) FROM daily_picks) GROUP BY cap_tier;"` — all three tiers present.
- Write ADR: `docs/decisions/0045-pull-pt-upside-lookahead.md` (≤30 lines): what was found,
  what was pulled, the renormalized weights, re-entry condition (≥12 clean monthly snapshots
  AND |t|≥1.5 → revisit ~2027-05).
- VERIFY: `python -c "import config; print({t: round(sum(abs(w) for w in ws.values()),4) for t,ws in config.SIGNAL_WEIGHTS.items()})"`
  (adapt to the real structure) → 1.0 per tier; pt_upside and smart_money absent.
- Commit: `fix(model)!: pull pt_upside (look-ahead artifact) + smart_money (n=6, sub-bar) from SIGNAL_WEIGHTS; proportional renorm; ADR 0045`

**Task 3.5 — Mark the trail.**
- `docs/plans/0000-checklist.md`: item "#2 pt_upside artifact re-verify (due ~2026-08)" →
  mark ✅ RESOLVED NEGATIVELY 2026-07-04 with one line + link to ADR 0045.
- Memory-file note is Amit's; skip.
- Commit: `docs: checklist — pt_upside re-verify resolved negatively via audit`

---

## PHASE 4 — Portfolio guards (no strategy redesign — guards only)

**Task 4.1 — Cap-violation guard before storing books (audit Port-F5).**
- File: `portfolio_construction.py`. `build()` computes `diag["stock_cap_ok"]/["sector_cap_ok"]`;
  `run()`/`backfill()` store regardless (audit found stored books at 12.63%/36.84%).
- DECIDED: in the store path, if either flag is False: clamp — rerun `apply_caps` (~210-232)
  with its iteration budget doubled; if still violating after that, hard-clip weights to the
  caps and renormalize the UNCAPPED names only (standard waterfall); log
  `print(f"[cap-guard] {asof}: clamped, max_stock={...:.4f}, max_sector={...:.4f}")` and store
  the clamped book. Never raise (a missing daily book is worse than a clamped one) and never
  store a violating book.
- VERIFY: scratchpad script: import the module, construct a fake 3-name weight vector violating
  a 12% cap, run your clamp helper, assert all ≤ cap + 1e-9 and sum ≈ 1.
- Commit: `fix(portfolio): never store cap-violating books — clamp waterfall + log (audit Port-F5)`

**Task 4.2 — Staleness cutoff on "latest snapshot per sid" (audit Port-F6).**
- File: `scoring/screener.py` (~89-115, the `(sid, MAX(snapshot_date))` subquery pattern).
- DECIDED: add `config.SCREEN["max_signal_age_days"] = 45` and apply
  `AND snapshot_date >= date('now', '-45 day')` inside every latest-snapshot subquery in the
  screener. 45d covers the new weekly cadence (Task 2.3) with 6× headroom; signals older than
  that are treated as missing → `weight_coverage` renormalization already handles absent
  signals (that mechanism exists; confirm by reading how coverage is computed).
- Expected consequence, pre-answered: sids whose producers froze (e.g. piotroski for
  Financials, frozen 2026-05-09) lose that signal — coverage drops, ranks shift. That is the
  POINT. If today's `daily_picks` top-5 changes after a screener re-run, that is acceptable
  and expected; note the before/after top-5 per tier in the commit body.
- VERIFY: re-run screener (same safety check as Task 3.4); then
  `sqlite3 ... "SELECT COUNT(*) FROM daily_picks WHERE pick_date=(SELECT MAX(pick_date) FROM daily_picks);"` > 1000 (universe still ranks).
- Commit: `fix(screener): 45d staleness floor on signal snapshots — frozen producers no longer feed ranks forever (audit Port-F6)`

**Task 4.3 — Turnover + cost columns in the NAV report (audit Port-F1, measurement half).**
- File: `tools/portfolio_nav.py` (read-only reporting tool — stays read-only).
- Add per-day one-way turnover `T_t = 0.5 * Σ_i |w_target,i,t − w_drifted,i,t|` where
  `w_drifted` = yesterday's weights drifted by realized returns (the tool already computes
  daily-rebalanced NAV so both series exist in its loop), and a cost-adjusted NAV series:
  cost per rebalance day = `Σ_i |Δw_i| × tier_cost_i` using `config.TRANSACTION_COSTS_BPS`
  per-side by the stock's tier. Print alongside the existing Sharpe table: mean daily
  turnover, annualized cost drag, and gross vs net Sharpe for HRP and EQW.
- DECIDED: this tool remains the honest lens; do NOT change rebalance frequency or the
  construction itself (banded rebalancing = design work, deferred to Amit — see HUMAN TASKS).
- VERIFY: `python -m tools.portfolio_nav` runs; net Sharpe < gross Sharpe for both books;
  turnover prints in the ~15-25%/day range the audit measured (if it prints ~0 or >100%,
  your Δw basis is wrong — fix before committing).
- Commit: `feat(portfolio): turnover + net-of-cost columns in portfolio_nav — all prior reads were gross (audit Port-F1)`

**Task 4.4 — Run the paper-portfolio backfill (audit Port-F1, second half).**
- Read `paper_portfolio.py` end-to-end FIRST. Preconditions to proceed: it writes only
  `paper_positions/paper_trades/paper_nav_history` (all currently 0 rows), reads only local
  tables, no external calls. If it has a backfill/CLI mode, run it for the full available
  `daily_picks` history. If it only supports day-by-day, loop the dates in a scratchpad
  driver script.
- STOP-IF: it references stale schema (it predates the 3.3c cutover and may not run at all) —
  spend max 2 fix attempts on import/schema errors; then BLOCKED with the traceback pasted
  under this task, and note "superseded by Task 4.3's net-of-cost NAV" (which delivers the
  same verdict).
- VERIFY: `sqlite3 ... "SELECT COUNT(*), MIN(nav_date), MAX(nav_date) FROM paper_nav_history;"` — nonzero and spanning the picks history.
- Commit: `feat(portfolio): first-ever paper_portfolio cost-aware backfill run (audit Port-F1)`

---

## PHASE 5 — Mutual-fund corrections (scoring honesty)

**Task 5.1 — Exclude IDCW variants from scoring (audit MF-F7 part).**
- File: `signals/mf_metrics.py` (the scheme-selection query, near the TRUSTED filter ~line 517).
- DECIDED: exclude schemes whose name/option field marks them IDCW/Dividend from `mf_metrics`
  scoring (their price-NAV returns are structurally wrong without dividend adjustment). Find
  the plan/option column in `mf_scheme_master` (query the schema first:
  `sqlite3 ... "PRAGMA table_info(mf_scheme_master);"`); if no structured column exists, filter
  `scheme_name NOT LIKE '%IDCW%' AND scheme_name NOT LIKE '%DIVIDEND%'` (case-insensitive).
  They stay in the master + browsable; they just don't get scored.
- DECIDED: full Direct/Regular dedup (canonical-variant selection via etm_id) is OUT of scope
  (needs identity-mapping design) — HUMAN TASKS.
- VERIFY: recompute latest snapshot (same entry point as Task 1.3);
  `SELECT COUNT(*) FROM mf_metrics WHERE as_of_date=(MAX...) AND scheme_code IN (SELECT scheme_code FROM mf_scheme_master WHERE UPPER(scheme_name) LIKE '%IDCW%')` → 0.
- Commit: `fix(mf): stop scoring IDCW/dividend variants — payout-depressed NAV understates returns (audit MF-F7)`

**Task 5.2 — Make category-relative percentile the primary rank (audit MF-F2).**
- File: `cockpit/mf.py` (~line 177 area / the universe listing query+sort). The absolute
  `composite_score` is the default sort; `score_percentile` (within-category) exists as
  secondary.
- DECIDED: default sort = `score_percentile` DESC (within the user's selected category filter;
  when "all categories" is selected, sort by `score_percentile` still — it is
  category-normalized so cross-category listing by it is fair). Keep `composite_score` as a
  visible column and a selectable sort. Add one-line caption near the table: "Default rank is
  within-category percentile; absolute score compares across asset classes and chases recent
  asset-class returns." (Match the cockpit's existing caption/HTML idiom — look at how other
  pages annotate tables.)
- STOP-IF: `score_percentile` is NULL-heavy in the latest snapshot
  (`SELECT COUNT(*), COUNT(score_percentile) FROM mf_metrics WHERE as_of_date=(MAX...)`) —
  if >20% NULL, first find why (likely the un-populated peer_rank columns are different from
  score_percentile; verify which column actually holds the within-category percentile — read
  `mf_metrics.py` to see what it writes) — if no populated within-category field exists,
  compute it in the cockpit query with a window function
  (`PERCENT_RANK() OVER (PARTITION BY category ORDER BY composite_score)`) instead of a schema change.
- VERIFY: `curl -s localhost:3000/mf | head -50` if the cockpit is serving (do NOT restart
  anything; if it isn't reachable, verify via the template/query unit-level in a scratchpad
  python call to the route function).
- Commit: `fix(mf-cockpit): default rank = within-category percentile, not cross-category absolute score (audit MF-F2)`

**Task 5.3 — Label the benchmark proxy honestly (audit MF-F6, cheap half).**
- File: `signals/mf_metrics.py` `_build_benchmark_nav` (~83-110): docstring claims
  "cap-weighted ... correlation ≈ 0.99" — it is a price-weighted average of today's top-50
  LARGE closes, price-return basis. DECIDED: fix the docstring to state exactly that
  (current-constituent, price-weighted, price-return; overstates fund spreads by ~1-1.3%/yr
  vs TRI), and in `cockpit/mf.py` rename any UI label from "vs Nifty" style to "vs large-cap
  proxy". Do NOT display bench_spread for debt-category funds: suppress in the cockpit when
  the scheme's category is a debt/liquid/gilt bucket (reuse the category list Task 5.1 read).
- DECIDED: real NIFTY TRI ingestion = external fetch = HUMAN TASKS.
- Commit: `fix(mf): label benchmark proxy honestly + suppress equity-proxy spread on debt funds (audit MF-F6)`

---

## PHASE 6 — Registry hygiene & standing monitors

**Task 6.1 — Build `tools/verify_factor_library.py` (audit Factor-F2; promised by ADR 0017).**
- Spec: pure read-only checker, exit 0/1. Partition rule: every id in `BACKTEST_SIGNALS` must
  be in exactly one of {keys of any tier in `SIGNAL_WEIGHTS`} ∪ {`FACTOR_LIBRARY`} ∪
  {explicit status set}. For the status set: add a new config list
  `FACTOR_STATUS = {"<signal_id>": "PROPOSED|BLOCKED|SUPERSEDED|CONTROL", ...}` to config.py
  and populate it for the current limbo signals so the checker passes TODAY: run the checker
  first, list every violator, then classify each — pre-answered classifications:
  - sub-1.5 named by the audit → move into `FACTOR_LIBRARY` proper: `share_momentum`,
    `debt_to_equity`, `position_52w`, `profit_margin`, `financial_quality`,
    `revenue_growth_yoy`, `short_selling_signal`, `earnings_beat_rate`.
  - `insider_signal` → FACTOR_LIBRARY with comment `# upstream feed frozen 2026-05-02`.
  - KEEP-grade unwired (`value_composite`, `eps_revision_yoy`, `earnings_persistence`) →
    `FACTOR_STATUS: "PROPOSED"` (visible promotion candidates — do NOT wire them; wiring is
    Amit's promotion-review decision).
  - `industry_id` and pure controls → `"CONTROL"`. Zero-backtest-row READY ids
    (`fii_dii_cash_net`, `fii_dii_fno_positioning`, `macro_sector_signal`,
    `momentum_composite`, `news_volume`, `regulatory_sector_signal`) → `"PROPOSED"`.
  - Anything else you find: `"PROPOSED"` with a `# TODO amit: classify` comment.
- Wire into `tools/health_report.py` as a WARN when the checker fails (import + call, or
  subprocess — match the house style).
- VERIFY: `python -m tools.verify_factor_library` exits 0; break it deliberately in a
  scratchpad copy to confirm it catches a violation; health_report still runs clean.
- Commit: `feat(registry): verify_factor_library partition check + FACTOR_STATUS + classify 38 limbo signals (audit Factor-F2, ADR 0017 debt)`

**Task 6.2 — Factor decay monitor (audit Factor-F4).**
- New file `tools/factor_decay.py`, read-only: for every wired factor (from SIGNAL_WEIGHTS),
  per tier, compute per-anchor Spearman IC of the factor column in `daily_snapshots_pit` vs
  `fwd_return_20d` (mimic `backtest_pit`'s IC computation — read it and reuse/import its
  helper rather than re-deriving; if not importable, copy the exact formula), then report:
  mean IC over the last 12 anchors vs mean IC over all anchors, and flag
  `DECAYED` when sign(last-12 mean) ≠ sign(weight) or |last-12 mean| < 0.25 × |all-time mean|.
- Wire a WARN line into health_report when any wired factor is DECAYED (expected immediately:
  `governance_resignation` flags — that is correct behavior, the audit measured its yearly IC
  at −0.081→−0.002).
- VERIFY: run it; governance_resignation MID shows the decay flag; output includes n anchors
  per factor so thin panels are visibly thin.
- Commit: `feat(monitor): tools/factor_decay — rolling 12-anchor IC vs wired sign, WARN in health report (audit Factor-F4)`

**Task 6.3 — Backtest the never-tested library factor (audit gap-map #5).**
- `python -m tools.reconstruct_pit --signal gross_profitability` for the available anchor
  range (read the tool's date-flag semantics first; extend all anchors that have
  `fundamentals_screener` PIT coverage), then `python -m tools.backtest_pit --signal gross_profitability`.
- DECIDED: whatever the verdict, it goes in `pit_ic_by_tier_v2` + one line in
  `docs/reference/signal-weights.md`'s library section. Do NOT wire it regardless of t-stat
  (promotion is a human review with the haircut + gate; you just produce the evidence).
- VERIFY: `sqlite3 ... "SELECT * FROM pit_ic_by_tier_v2 WHERE signal LIKE '%gross_profit%';"` has rows.
- Commit: `feat(backtest): first gross_profitability PIT backtest — registered 2026-05, never run (audit gap #5)`

**Task 6.4 — Survivorship exposure report (audit Data-F1, measurement half only).**
- DECIDED: do NOT rebuild the PIT panel against `historical_universe` (that is a redesign with
  unfixable fundamentals gaps for dead names — Amit's call). Instead: new read-only tool
  `tools/survivorship_exposure.py` that, per backtest anchor date, reports
  `absent = symbols in historical_universe active on that date that never map to a current sid`
  as a count and % of that date's true universe, printed per year. Add its headline number
  (worst-year %) to the docstring of `tools/backtest_pit.py` so every future reader sees the
  caveat.
- VERIFY: tool runs, prints a per-year table, numbers roughly consistent with the audit's
  1,381 never-mapping symbols (1,017 present since 2023).
- Commit: `feat(backtest): survivorship_exposure report — quantifies survivors-only bias per anchor (audit Data-F1, measurement)`

---

## FINAL — wrap-up (mandatory)

1. Re-run the three standing checks: `python -m tools.health_report`,
   `python -m tools.verify_factor_library`, `python -m tools.factor_decay`. Paste their
   summaries into HANDOFF.
2. Update `docs/plans/0000-checklist.md`: tick what shipped, BLOCKED list verbatim.
3. `/handoff` (writes HANDOFF.md with: Left off / Pick up here / Watch out — Watch out MUST
   name: pt_upside pulled + renormalized weights now live in the daily screener; screener
   picks changed by the 45d staleness floor; any BLOCKED tasks).

## HUMAN TASKS (for Amit — Sonnet must NOT attempt these)

- Screener.in auth repair (needs credentials) — until then the Task 1.1 alarm fires daily, correctly.
- Banded/hysteresis rebalancing design (top-8/2pp-drift spec in the audit) — the single
  highest-leverage realized-Sharpe improvement; touches ADR 0044 design.
- Financial-sector routing decision: wire `financial_signal_scores` into the screener vs
  exclude Financials from picks (model change requiring a backtest).
- LARGE-tier verdict: no wired LARGE factor survives scrutiny — candidate fix = build/backtest
  low-vol + short-term reversal + asset-growth (data in-house; needs PIT helpers per the
  ship-as-one-unit rule).
- Direct/Regular canonical dedup via etm_id; AMFI TER/AUM ingest; NIFTY TRI series ingest.
- Anthropic Batch API migration for classify_regulatory; the 500/day cap question.
- Whether Tickertape's forecastsHistory API currently serves future-embedded values (external
  probe; the memory note `forecast_history_price_contaminated` needs upgrading to "year-ahead
  realized close", which is worse than documented).
