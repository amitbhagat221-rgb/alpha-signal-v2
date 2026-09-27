# Architecture review — 2026-09-27

**Scope:** alpha-signal-v2 as built after [ADR 0052](../decisions/0052-seven-building-blocks.md) / [plan 0015](../plans/0015-first-principles-architecture.md), master `cb65dd5`. Read-only. Heavy SQL ran on a `.backup` copy; Python ran under an LD_PRELOAD `connect()` shim; the test cockpit ran on :3100.
**Method:** 12 questions and 10 scenarios were pre-registered before any code was read (§A). Four read-only agents gathered evidence. Every claim behind a score or a top-15 finding was then re-verified by the lead in code or SQL; unverifiable claims were dropped.
**Known, not re-reported** (plan 0015 implementation notes): NODE dicts sit in `config.PIPELINE_STEPS`, not in modules · no verdict table · invariant 1 is approximate for revised sources (no first-seen timestamps) · D6 network binding left to Amit · MICRO `market_cap_cr` bug · `news_classifier.py` model literal · 3-day shadow run skipped.

## 1. Scorecard

| Dimension | Score | Verdict | Key evidence |
|---|---|---|---|
| Explainability | **5** | Docs lag the code; a pick can't be explained from the DB | 8.5/12 where-is-X correct · 4 of 6 provenance hops need code · 6.5/20 sampled doc claims false · 5 of 10 wired factors shown on no surface |
| Hygiene | **5** | Registries exist but leak; 3 of 5 invariants aren't held by anything | no `signals/`-no-db test (42/69 import db) · no `write(dataset, df)` · 192 tests pass in 13.3 s, but pytest isn't in the prod venv and nothing runs the suite |
| Ease | **6** | Common changes are cheap, but adding a factor isn't | ≤2 files for 5/10 scenarios · add-a-factor 5 files (target 2) · 4/6 runbook steps work · offline loop 43.8 s, only via a hand-written harness |
| Scalability | **6** | Survives 2× except the 1st-of-month email; 5× needs harvest scheduling | email on time 7/31 days · 1st-of-month critical path 237 min · `load_raw` 52.8 s / 2.1 GB peak · the one harvest lock skipped 8 of 8 Sunday forward jobs |
| Expandability | **5** | Blocks extend well inside one market/model/book; outside it, a fork | `daily_picks` PK (sid, pick_date) has no model id · the screener deletes by date · ~170 bare `date.today()` calls |
| Enterprise grade | **4** | Good decision records and backups; little automated safety | no CI · pre-push gate can't fail · URGENT on 31/31 days · :3000/:3001 open without auth · no run id/sha on picks · restore never drilled |
| **Overall** | **31/60** | | |

**Summary.** Plan 0015 delivered what makes the system *run*: derived order, the host door, `pit.features_at` for live and backtest, `views.picks`, derived weights. It didn't deliver what makes it *hold*. Invariants 1, 3 and 5 are described as "held by the runner or a test", but no test or runner code enforces them. Alerts have been red every day for a month. Weekday tests don't guard the path that breaks on the 1st of the month. **The three things most likely to hurt next:**
1. **The 2026-10-01 email will land around 07:30 UTC.** Two monthly Tickertape fetches are blocking ancestors of the email (F1).
2. **Real failures are invisible.** Alerts fire every day, ntfy was never configured, and cron jobs exit 0 on total failure: the Screener harvest has failed 2448/2448 since August (F2, F3).
3. **No automatic gate stops a bad change.** The pre-push hook can't fail, pytest isn't installed, and production runs from a shared working tree (F4, F8).

## 2. Per dimension

### A. Explainability (5/10)

**Where-does-X-live** (doc answers pre-registered from README + architecture.md):

| Q | Verdict | Evidence |
|---|---|---|
| Q1 factor weight | ✅ | `FACTORS[f]["weights"]` → `factors.SIGNAL_WEIGHTS` |
| Q2 what runs before the email | ❌ | the docs say list order runs and graph.py is shadow-only; actually `config.PIPELINE['derived_order']=True` (config.py:211), and pipeline.py:223 runs `graph.order` |
| Q3 staleness | ½ | the producer comes from the legacy `table` field (db.py:1005), not declared `writes`; `graph.producers` is unused; 6 written tables have no cadence, so their post-check can never fail |
| Q4 pick gate | ½ | split between `screener._pick_eligible` (write time) and `views.PICK_GATE_SQL` (views.py:109); `portfolio_construction.py:80-84` reads with no gate |
| Q5 host rate limit | ½ | true for HTTP; the Anthropic classifiers bypass the door and pace with `time.sleep` (regulatory_classifier.py:180,434,545,595) |
| Q6 tiers · Q7 ranges · Q8 critical · Q9 model ids · Q10 live=PIT · Q12 cron | ✅×6 | config.py:36 / checks/ranges.py:31 / config.py:254,640 / hosts.py:94 / screener → `pit.features_at` / `crontab -l` |
| Q11 write mode | ❌ | there is no `db.write`. Writers choose the mode at ~170 sites; `tables.dataset_kinds()` is read only by tests/test_checks.py:154 |

**Score 8.5/12.**

**Pick provenance** (2026-09-27: ULTC LARGE #1 at 0.8370, GALK SMALL #1 at 0.8775):

| Hop | Answerable by query? |
|---|---|
| pick → score, rank, gate columns | yes, but "in the book" needs code |
| score → per-factor inputs | only in `pit_replay_snapshots.inputs_json`, which no doc names |
| input → percentile × weight → score | code: weights and column map live only in factors.py; `daily_picks.*_adj` are hard-coded 0 (screener.py:436-444) |
| factor → raw rows + dates | code: `signal_lineage` covers 1 of 10 wired factors |
| raw row → fetch time | mostly yes (`fetched_at`); `stock_prices` has none |
| table → Host | code: free-text `source`, no link to HOSTS |

- **4 of 6 hops need code.**
- The stored scores reproduce exactly only with the *pre-deploy* consensus column. Today's code gives ULTC 0.810, not 0.837, and nothing in the DB records which code or weights produced a pick.

**Doc–code drift: 6.5 of 20 sampled claims false.**
- In the sample:
  - architecture.md "Today" (shadow order)
  - CLAUDE.md: Financials eligibility lives "in eligibility/registry.py"; it is actually in factors.py
  - CLAUDE.md: "every cron line is run.sh"; `backup_db.sh` isn't
  - OPERATOR §5: `config.SIGNAL_WEIGHTS` / "order matters"
  - OPERATOR §6: "each signals module writes a *_scores table"
  - OPERATOR: "two run wrappers"
  - OPERATOR: the pick-gate location (half right)
- Also wrong, outside the sample:
  - README "85 steps" (there are 86)
  - signal-weights.md:11 and reference/README:20 name `config.SIGNAL_WEIGHTS`
  - OPERATOR "51 ADRs" (there are 50 files)
  - HANDOFF "113 unpushed" (0)
  - the `views.picks` docstring says the portfolio uses the gated set

**Concepts with two or more homes (11):**
- pick gate (3)
- eligibility (3)
- health/quality (8+: health.py `TABLE_PROFILES`, checks/, validators/×4, data_sanity, health_score, watchdog)
- lineage (5)
- table producer (3)
- tier lists (6)
- "kind" (two taxonomies in tables.py)
- "cadence" (4 meanings: `frequency`, `data_freq`, `freq`, factor `cadence`)
- `daily_snapshots_pit` DDL (schema.sql and reconstruct_pit)
- the DuckDB replica registered twice
- score explanation (`*_adj`, `daily_snapshots`, `inputs_json`)

**Keep doing:** HANDOFF plus ADRs, `/flow` drawing the 382 real edges, and a `factors.FACTORS` entry as the single weight owner.

### B. Hygiene (5/10)

| Test | Plan 0015 baseline | Today |
|---|---|---|
| `upsert_df` / `insert_df` / raw write statements | 57 / 31 / 82 in 39 files | 59 / 32 / 80 in 43 files |
| In-code `CREATE TABLE` | 16 | 15 (+5 ALTER) |
| `INSERT OR REPLACE` on state/series tables (CLAUDE.md forbids) | — | regime.py:85, regulatory_classifier.py:786, scrip_master.py:157, mf_holdings_scrape.py:575/583 |
| Tier literals | 43 sites | ~20 real sites; 3 tier palettes disagree (formatting.py:80, cockpit.css:573, model_outcomes.html:33) |
| Forward-return implementations | 2 | 4 |
| `daily_picks` read outside views.py | 11 query forms | 19 files |
| Tests | — | 23 files, **192 passed in 13.3 s** (tmp/`:memory:` DBs, safe); pytest is **not installed** in the prod venv |
| TODOs | — | 18 (17 are the same `factors.py` "TODO amit: classify") |
| requirements.txt | — | 13 pins match `pip freeze`, but 13 imported packages are missing (fastapi, uvicorn, duckdb, nselib…); the venv is shared with v1 |

**Design says X, code does Y** (not in plan 0015's implementation notes):

| Design claim | Code | Evidence |
|---|---|---|
| Inv 1: "`signals/` cannot import db (test)" | no test exists | `grep` shows 42/69 `signals/*.py` import db |
| Inv 3: writers never choose a mode; `write(dataset, df)`, `asof()` | neither exists; kinds feed tests only | db.py; tables.py:688 |
| Inv 3: the runner rejects off-cadence rows | not built; `pt_snapshot` writes on any day it is run | run.sh:58 |
| Inv 4: post-check = fresh **and** in range | freshness only; cron-only jobs get none | pipeline `_post_check`; run.sh |
| Inv 5: one door with a budget; reads ⊇ observed "(test)" | Anthropic bypasses the door with no budget; the authorizer check only writes a JSON nothing reads, and there is no test | hosts.py:94-103, pipeline.py:270 |
| §4: replay = `pipeline.py --asof … --db` | no such flags | pipeline.py:302-305 |
| §6: delete PIT_PRODUCERS, TABLE_PROFILES, table_step_meta, `_producer_for` | all still present | factors.py:1798, health.py:648, db.py:1022, freshness_watchdog.py:39 |
| Phase 6: RENAMES "is one registry entry" | `apply_renames` has no caller outside tests | factors.py:2203 |
| "nothing in the graph imports tools/" | 7 steps run `tools.*` | config.py `module` fields |

**Untracked production files:**
- `backup_db.sh` (in cron) and `backup_secrets.sh` (gitignored by `*.sh`)
- `.git/hooks/pre-push`
- systemd units
- the crontab

`.gitignore` also ignores `*.json` and `*.csv` repo-wide.

**Can break with every test green:**
- a new db import in `signals/`
- a `requests.get` outside `sources/`
- `OR REPLACE` on a state table
- an undeclared read
- a weight with no t-stat evidence
- an off-cadence snapshot row
- a cron job writing 0 rows
- a new ungated `daily_picks` reader
- a lost pre-push hook

**Keep doing:** `test_tables` and `test_factor_registry` as guards on the registries; the M-score range, HEADERS dicts and critical-step lists are now single-owner.

### C. Ease (6/10)

| Scenario | Target | Today | Main extra touches |
|---|---|---|---|
| Add a data source | 2 | 4–6 | hosts, schema, tables.TABLES, step dict with reads/writes/lagged |
| Add a table | 1 | 2 | tables.TABLES (plus `_COLUMN_MIGRATIONS` for a new column) |
| Add a factor (live + backtest + weight) | 2 | **5** (9–10 to display it) | pit.py helper, a hand-kept `PIT_PRODUCERS` row, panel column in schema.sql, live ALTER |
| Add a pipeline step | 1 | 2 | step dict (62 copies of the `stocks@classify_micro_tier` boilerplate) |
| Add a check | 1 | 1 | but 6 competing homes |
| Add a cockpit page | 2 | 3–4 | route, api/views fn, template, PAGES |
| Change a cadence or threshold | 1 | 1–3 | UHS 60 literal at 3 sites; pick floors in screener.py, not config |
| Rename a factor | 2 | 2 nominal, not operable | `apply_renames` uncalled; 4 keyed tables uncovered; `delivery_anomaly_z` spans 10 files / 38 sites |
| Add a tier | 1 | 3 (non-pickable) / ~10 (pickable) | schema CHECK, `regime_state.alloc_large/mid/small` read in 10 files |
| Replay a past date | 0 | 1 command, limited | `tools.pit_replay --date` only for 131 frozen dates, with today's tiers |

- **Onboarding for a factor:** 12 files, ~6.2K LOC (the plan projected 6 files). No "add a factor" page exists.
- **Runbook, 4 of 6 steps work:**
  - There's no stale-table entry (the watchdog's `--dry-run`/`--tables` are undocumented).
  - The Screener-cookie alert needs ntfy, which is unset.
  - "No email by 09:30 IST" fires on most normal days.
  - There's no `run.sh step <name>`: a manual `--step` needs a hand-copied credentials preamble and takes no lock.
- **Dev loop:**
  - There is no `--db`/`ALPHA_DB` override: `DB_PATH` is hard-coded at config.py:16.
  - A 20-line harness ran the screener dry-run on the copy offline in **43.8 s**.
  - Trap: unless `DUCK_PATH` is patched too, `read_sql_fast` silently reads the prod DuckDB replica.
  - Two dev worktrees symlink `data/` to the prod DB.

### D. Scalability (6/10)

| Baseline | Measured |
|---|---|
| DB | 8.72 GB: bse_announcements 2.2, fno_bhav 1.47, mf_nav_history 1.15, transcripts 0.73 GB. Growth ~0.35–0.5 GB/month, so 13–15 GB in 12 months; disk isn't a constraint (90 GB free) |
| Email (last 31 days) | 31/31 sent; **7/31 finished by 04:00 UTC**, 24/31 by 04:15. Start-to-email p50 32.5 min, p90 59.5 |
| Critical path, derived order (sum of p50s) | weekday 7.6 min · Sunday 22 min · **1st of month 237 min** |
| Morning run total | p90 1,097 min (Sunday runs of 15–19 h before the Moneycontrol budget) |
| Screener step | p50 102.8 s, p90 104.7 s |
| `pit.load_raw()` | 52.8 s, **2.1 GB peak**; full history, prices loaded twice (690 MB) |
| Screener PIT core | 16.3 s load + 26.8 s `features_at`, 1.2 GB |
| `refresh_pit_panel` | ~85 s per anchor; a full 202-anchor rebuild is ~4–5 h |
| Cockpit, cold → warm | /model 18.8 s → 0.01 s · / 1.3 s · /explorer 0.4 → 0.09 s (1.27 MB of HTML). 10 concurrent users: ~2–2.4 s (1 uvicorn worker, 968 MB) |
| LLM | ~$1.6–1.9/day and ~900 calls/day while credits last ($39.50 in August); $0 since 08-24 (credits empty) |

**Hotspots:**
- `pit.py:1088` (a per-sid boolean filter inside a loop: quadratic)
- per-sid loops in signals/accruals, eps_revision, piotroski and _prices
- a full-history price load in screener.py:95
- `compute_pick_outcomes` re-reading all 279k picks every day
- `_ttl_cache` without a lock (thundering herd)
- `busy_timeout` 5 s (20 "database is locked" errors between 05-31 and 07-05)
- the one global harvest lock (run.sh:33)
- a per-process `_LAST_CALL` host gap

No N+1 query pattern was found in views.py or the cockpit APIs.

### E. Expandability (5/10)

| Extension | Hard-coded assumptions hit | Files | Fits a block? |
|---|---|---|---|
| Second sleeve (plan 0011 compounder, special situations) | `daily_picks` PK (sid, pick_date), no model id (schema.sql:364-381); the screener deletes by date (screener.py:473); single-book `portfolio_weights`; 28 direct readers | 12–20 | **No**: needs a Strategy/Book block |
| US equities | 52 FKs to `stocks(sid)`, ₹/Cr in 56 files, tier CHECK enum, India VIX regime, holidays inferred from a 404 (nse.py:48-63), ~170 `date.today()` | 60–100 (a fork) | **No**: needs Market/Universe + Calendar |
| Crypto (plan 0009) | the plan already calls for a separate repo | — | reuse the spine as a library |
| Weekly-only product | cadence gate pipeline.py:54-65 | 2–4 | Node |
| Intraday | date-grain PKs; freshness in days | 40+ | none (non-goal) |
| Read-only JSON API | views return dicts/frames; 14 ad-hoc `/api` GETs, no `/api/picks`, no auth | 2–3 | View |
| Second user/portfolio | no user or portfolio id anywhere | 10–15 | none (non-goal) |
| One dataset to DuckDB/Postgres | connections central (db.py:82), but 143 files run raw SQL: 42 OR REPLACE, 31 PRAGMA, 20 sqlite_master | 8–12 for the PIT panel | Dataset needs a `store` attribute; the DuckDB replica is the precedent |

**Verdict:** Host, Dataset, Feature, Check and View are the right extension points. Model is a singleton, and three concepts fit no block: **Strategy/Book** (model id, weights, positions), **Market/Calendar** (currency, trading days, local date) and **Run** (run id, git sha, slot). All three are cheaper to add before a second sleeve than after.

### F. Enterprise grade (4/10) — see §4

## 3. Top 15 findings, ranked (impact × likelihood ÷ effort)

| # | Finding and evidence | Failure scenario | Fix | Effort | Block |
|---|---|---|---|---|---|
| F1 | **1st-of-month email is ~3.6 h late by construction.** In the derived order, `fetch_analyst` (6,681 s) and `fetch_shareholding` (6,224 s) are *needed* ancestors of `email` (`graph.ancestors(needed_only=True)` on the daily+monthly step set). 09-01 email sent 07:47 UTC. | **2026-10-01** (Thu) email lands ~07:30 UTC, the same day `segment_tiers` re-tiers 24 stocks | Declare both edges lagged (screener reads last month's values), as was done for `fetch_yf_analyst`; add a test that the 1st-of-month email path's p50 sum is ≤ 15 min | S | Node |
| F2 | **Alerts are permanently red.** 82 URGENT emails, 31 of 31 days, 6–16 CRITICALs a day; `NTFY_TOPIC` unset (82/82 "skipping ntfy push"); 5 steps failing nearly daily (insider feed dead since 05-02, 3 LLM steps with empty credits, `fetch_mf_nav_daily`) | A new CRITICAL (e.g. stale bhavcopy) is indistinguishable from the standing ones; the dead Screener cookie (August) went unnoticed | Bench known-broken steps (acknowledged state with an expiry); URGENT only on a *new* CRITICAL; set `NTFY_TOPIC` | M (ntfy: S) | Check |
| F3 | **Failures exit 0.** `screener_pull --universe` logged `failures: 2448/2448`, 0 rows, twice (screener_universe_refresh.log:4902,7353), exit 0; `fundamentals_screener` was last fetched 07-15. Cron-only jobs get no post-check. The pipeline exits 0 after a critical failure; `email_on_failure` is a stub (pipeline.py:280-281) | Silent staleness in ~20 signals' inputs; nothing but the 04:00 digest ever turns red | `run.sh` runs `checks.post_step` on each cron job's declared outputs and propagates non-zero; the pipeline exits 1 on critical failure; run.sh sends the URGENT | S | Check/Node |
| F4 | **No automated gate can fail.** pre-push captures `rc=$?` after `\| tail` without `pipefail` (lines 20-21, 34-35, 54-55), so all 3 gates always pass; pytest isn't installed in the venv; no CI; hooks aren't versioned | A regression in scoring ships and changes picks with every gate "green" | `set -o pipefail`; `core.hooksPath=ops/hooks` (versioned); install pytest (dev requirements); pre-push runs the 13 s suite | S | Check |
| F5 | **Cockpits open, unauthenticated.** Both bind 0.0.0.0:3000/3001 (`ss -ltn`); iptables accepts both; GET /sql, /system, /flow return 200 without login; POST `/api/pipeline/rerun/{step}` is unauthenticated. The SQL guard itself is solid (ro URI, `query_only`, 20 s, 500 rows). *Known, D6, left to Amit; still open.* | Anyone who can reach the port reads the DB or triggers a 4 h harvest or LLM spend. The VCN security list, which may block this upstream, was not verified | Bind to 127.0.0.1 behind nginx basic-auth + TLS (the pattern other apps on this VM use) | S | View |
| F6 | **Picks aren't reproducible or attributable.** No run id, git sha or weights hash on `daily_picks`/`portfolio_weights`; `*_adj` columns hard-coded 0 (screener.py:436-444); today's scores reproduce only with pre-deploy code | "Why did X drop out on Tuesday?" is unanswerable; a backtest-vs-live gap can't be attributed | `pick_contributions(sid, date, factor, raw, pctile, weight, contrib)` + `run_id`/`git_sha` on picks and `pipeline_log`; drop `*_adj` | S–M | Model |
| F7 | **The explanation isn't the model.** 5 of 10 wired factors (announcement_car, sector_tilt, delivery_anomaly_z, iv_skew_25d, governance_resignation) appear on no surface: 0 hits in email_sender.py, dossier.py, cockpit/, views.py. Their weight: LARGE 0.57, MID 0.40, SMALL 0.56. The dossier feeds the LLM "PT upside" (weight 0, ADR 0045) | The thesis cites signals that didn't drive the pick; Amit acts on a story the model didn't tell | One `views.score_breakdown(sid, date)` built on F6's table feeds the email, dossier and stock page | M | View |
| F8 | **Prod runs from a shared working tree.** Uncommitted `sources/news_classifier.py` (another session's) runs in the `classify_news` step. Untracked `tools/session_classify.py` wrote 16,669 zero-token calls to prod `llm_usage`. Two worktrees symlink `data/` to the prod DB; no DB override | One session's half-edit runs in the 03:30 cron; a dev test writes to prod | Deploy = `git worktree` at a tag (`/opt/alpha-prod`); `ALPHA_DB` env (derive `DUCK_PATH` from it); worktrees get a copy | M | Node (runner) |
| F9 | **One global harvest lock and per-process politeness.** The 14:00 `forward` job skipped 8 of 8 Sundays (08-02 → 09-20) and the watchdog 10 times; `pt_snapshot`, `backtest` and `expected_return` take no lock; the host gap `_LAST_CALL` is per process | Forward-only feeds (FII/DII, BSE announcements) lose days permanently; Yahoo is hit by two processes on the 1st | Per-host `flock` (`/tmp/alpha_host_<name>.lock`) inside `sources/_http`; the harvest lock becomes per slot | M | Host |
| F10 | **Invariants 1, 3 and 5 are documented as enforced but aren't** (design-vs-code table, §B). OR REPLACE is still used on 4 state/series tables | Another OR REPLACE nulls a column owned by another producer (the analyst_consensus class of bug) with nothing stopping it | AST tests: no `db` import in `signals/` (with a shrinking allowlist), no OR REPLACE on state/series kinds; `db.write` dispatching on kind; record the deviations in plan 0015 | M | Dataset |
| F11 | **Docs drifted within a day of the rebuild:** 6.5/20 claims false (§A) | The next session or an inheritor follows OPERATOR §5 into `config.SIGNAL_WEIGHTS` / "order matters" | Rewrite architecture "Today", OPERATOR §5/§6, signal-weights.md:11; add a test that every dotted `module.symbol` named in the docs imports | S | Docs |
| F12 | **Freshness ignores declared writes.** `db.table_producer` uses the legacy `table` field (db.py:1005); 6 declared outputs have no cadence, so `post_step` can't fail them; PIT_PRODUCERS, TABLE_PROFILES and `_producer_for` are still alive | A multi-output step's second table goes stale with no alert and no heal | Producer and cadence from `graph.producers`; delete `table`, `table_step_meta` and `_producer_for` | S | Node/Check |
| F13 | **Ops files unversioned, DR undrilled:** `backup_db.sh`, `backup_secrets.sh` (unscheduled), hooks, systemd units and crontab are untracked; no restore has been tested; backup freshness is unmonitored; secrets in a 0775 plaintext file | Losing the VM costs days (RTO) and the credentials | `ops/` dir in git with `crontab.txt` and a test that every line calls `run.sh`; schedule the secrets backup; a quarterly restore drill into scratch; add backup.log to `FILE_OUTPUTS` | S | Check |
| F14 | **No LLM spend cap; Anthropic bypasses the door.** No `budget` in `hosts.HOSTS["anthropic"]`; `time.sleep` pacing in regulatory_classifier.py; plan 0015 stress test 5 promised `ctx.llm()` + BudgetExhausted | Refilled credits: the regulatory backfill (60% of spend) runs unbounded; 15 dossiers/day since Phase 0 | `_http.llm()` enforcing `budget_usd_day` from `llm_usage`, PARTIAL on exhaustion | S | Host |
| F15 | **The book bypasses the pick gate.** `portfolio_construction.select_candidates` reads `daily_picks` with no gate (portfolio_construction.py:80-84). Impact measured: 2 of the top-15 rows in 119 days failed the gate | A UHS < 60 or integrity-FAIL name (LIC on 06-01) enters the HRP book but not the email | `views.picks(gated=True, per_tier=…)`; move the UHS 60 and floors into config | S | View |

Also found, lower rank:
- add-a-factor takes 5 files (PIT_PRODUCERS hand-kept)
- `apply_renames` is never called
- requirements.txt misses 13 packages
- `load_raw` does full-history loads
- `pit.py:1088` is quadratic
- 5 merged worktrees (82 MB)
- dead code: `sources/kite_pull.py` and `sources/mf_holdings.py`

## 4. Enterprise gap list

| Item | Status | Evidence |
|---|---|---|
| Environments / promotion / rollback | **partial** | Prod is the working checkout (F8). No tags. Rollback = `derived_order` flag + `backups/plan15-deploy/` |
| CI/CD | **absent** | no `.github/`; pre-push can't fail (F4); 192 tests run by nothing |
| Email SLO | **partial** | no SLO defined; 31/31 sent, **7/31 by 09:30 IST** |
| Retries / idempotency | **partial** | 1 retry; `daily_picks` delete-then-upsert is idempotent; forward-only feeds lost when the lock skips |
| Critical-path failure handling | **partial** | bhavcopy aborts correctly; exit code 0; `email_on_failure` stub |
| Graceful degradation (LLM / host dies) | **partial** | the email still ships without dossiers; failing steps show FAILED, but in a permanently red digest |
| Structured logs / metrics | **absent** | plain text, no per-line date, no logrotate (`pipeline.log` 37 MB); `pipeline_log` is the only metric |
| Alert routing / fatigue | **partial** | email works; push unset; URGENT 31/31 days |
| Dashboards | **present** | ops :3001 Health Center, `/flow` |
| Network exposure / auth | **absent** | F5 |
| Secrets | **partial** | outside the repo, but plaintext 0775; `PEXELS_API_KEY` undocumented |
| SQL console guard | **present** | db.py:1300-1365 (ro, `query_only`, 20 s, 500 rows) |
| Dependency pinning / CVEs | **partial** | 13 pinned, 13 missing; shared venv; CVEs not measured (pip-audit needs the network) |
| Lineage | **partial** | derived table edges and /flow; column lineage for 1 of 10 wired factors |
| PIT / vintage | **partial** | as-of by lag rules; no first-seen timestamps (known) |
| Quarantine | **partial** | mirror tables exist; not wired as write-time checks everywhere |
| Reproducibility | **absent** | F6 |
| Backup | **present** | nightly `VACUUM INTO` + integrity check + Drive, 2.0 GB gz today; RPO ~24 h |
| DR / restore test | **absent** | never drilled; secrets backup unscheduled; RTO 2–4 h, or days if the VM is lost |
| Change management / audit | **present** | 50 ADR files, plans, checklist, conventional commits; single approver (Amit) |
| Cost control | **partial** | `llm_usage` ledger; no cap (F14) |

## 5. Roadmap

**Quick wins (S; ~2 sessions in total, in this order):**
1. F1: lag the monthly fetch edges before 10-01.
2. F4: `pipefail`, versioned hooks, pytest.
3. F3: exit codes and cron post-checks.
4. F2: set `NTFY_TOPIC`.
5. F5: nginx + localhost.
6. F14: the LLM budget.
7. F15: gate the book.
8. F12: producers from the graph.
9. F11: doc sweep.
10. F13: `ops/` dir and a restore drill.
11. F6 (schema half): `run_id`/`git_sha`.

**Structural (M/L):**
- F2 acknowledged-state alerting (M)
- F6 + F7 contributions table and `score_breakdown` (M)
- F8 tagged deploy + `ALPHA_DB` (M)
- F9 per-host locks (M)
- F10 `db.write` by kind and the invariant tests (M)
- add-a-factor down to 2 files: auto panel column, drop PIT_PRODUCERS (M)
- **Strategy/Book block (model id) before Engine 2** (M)
- first-seen vintage for statement datasets (L)
- Market/Calendar blocks only when a second market is real (L)

**Explicit non-goals:**

| Non-goal | Why not |
|---|---|
| Staging VM / blue-green | a tagged prod worktree gives 90% of the value for one operator |
| Kubernetes / IaC | a single VM; the `ops/` dir plus the restore drill is the DR plan |
| Airflow / Dagster | graph.py plus one runner already covers ordering, lineage and critical path (ADR 0052) |
| Postgres migration | SQLite holds 5×; move only the PIT panel to DuckDB if needed |
| Multi-tenant users / RBAC | one user; basic auth is enough |
| Prometheus / Grafana SLO stack | `pipeline_log` + the ops page + one on-time metric is enough |
| SIEM / SOC2 audit logging | no capital, no clients |
| Vault / KMS | an encrypted secrets file + off-host passphrase closes the real risk |
| Intraday grain | the product is daily; date-grain PKs are right |

## 6. Scale-break table

| Growth | Breaks first | When | First remedy |
|---|---|---|---|
| Universe 2.4K → 5K | 1st-of-month email ~11:00 UTC; Moneycontrol full coverage cycle 12 → ~25 weeks | at 5K | F1 lagged edges; per-host locks + sweeps spread across days |
| Universe → 10K | weekly Yahoo ~6.5 h; lock held 10+ h on Sundays and the 1st; screener ~7 min; `load_raw` ~20 GB → **OOM** on 23 GB with 3× history | at 10K | windowed loads (≤ 300 days for prices), prices loaded once, vectorize `pit.py:1088` |
| Factors 105 → 300 | full panel rebuild ~14 h (width is fine: ~310 of SQLite's 2,000 columns) | ~200 factors | incremental per-signal rebuild; parallel anchors |
| Hosts ×2 | wall time adds up under the one lock and the sequential runner | now (Sunday skips) | F9 per-host locks; parallel fetch nodes per host |
| History ×3 | fine alone (~6 GB peak); OOM combined with 10K stocks | with 10K | windowed loads; PIT panel to DuckDB |
| Two runs/day | (sid, date) PKs mean run 2 overwrites run 1; runs collide with Sunday and 1st-of-month jobs; the lock skips silently | immediately | slot/run id in the step cadence and PKs (Run block) |
| 10 cockpit users | ~2.4 s pages; unlocked TTL cache stampedes | now | cache rendered HTML, lock the cache, 2–3 uvicorn workers |

**Not measured, and why:**
- The first derived-order production run: it happens 2026-09-28.
- CVEs: pip-audit needs the network.
- VCN security list: not visible from the VM.
- Restore time: no restore was run, per the review's safety rules.
- End-to-end screener step: it writes `daily_picks`, so only its core was timed.
- Ops-cockpit latency: not started.
- Today's 30.6 s screener run: cause unknown.
- Per-host request counts: no request log exists; they were estimated from wall time ÷ gap.
