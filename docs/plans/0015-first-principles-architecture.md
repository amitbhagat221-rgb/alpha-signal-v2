# Plan 0015 — First-principles architecture: seven blocks, one as-of graph

**Status:** active — approved 2026-09-27 (Amit: "agree with all", D1–D6 as recommended) · **Decision:** [ADR 0052](../decisions/0052-seven-building-blocks.md) · **Target one-pager:** [architecture.md](../reference/architecture.md)
**Method:** Step 1 ("what is this system?") was written from README, CLAUDE.md and architecture.md only. Four read-only auditors then mapped the repo (orchestration+quality, data, features+evidence, presentation). Every load-bearing claim below was re-verified in code or with read-only SQL. About 1 in 10 auditor claims was wrong and has been corrected here (e.g. "CLAUDE.md has no 2 s rule": it does, at line 39).

## 1. What the system is
**Purpose.** Every trading morning, turn public Indian-market data into a point-in-time-honest, tier-ranked list of picks with an explanation. Also carry the evidence that both the picks and the data behind them can be trusted.

**Capabilities:**
1. Acquire
2. Derive features
3. Decide: segment, rank, gate, size
4. Explain (LLM)
5. Surface (email, cockpit)
6. Prove (backtest, promotion, FDR)
7. Guard (freshness, trust, politeness)

**Invariant candidates → verdict**
- **As-of: KEEP.** It is the master invariant. PIT adjustment (ADR 0010), the forecast_history look-ahead (ADR 0045) and transcript `available_date` are all the same rule.
- **Rank within tier: KEEP** as "Segment". Tiers become data, and `pickable` absorbs the MICRO exclusion.
- **Episodic snapshots: MERGE with the INSERT OR IGNORE/REPLACE rule** into "kind decides write, cadence decides freshness". The PT rule and the write-mode rule are one rule. The CLAUDE.md write-mode line currently contradicts `db.upsert_df`, which exists *because* OR REPLACE nulls columns.
- **0 output = failure: MERGE with LLM no-numbers** into "a node succeeds only when its post-checks pass". Refinement found in code: bhavcopy legitimately returns 0 when its 7-day window is already loaded. The post-condition is therefore "output fresh as of the expected date", not "rows > 0". That rule catches both the failed download and the silent zero.
- **No two harvesters, ≥2 s per host: KEEP** as "Politeness", widened to budgets. The Moneycontrol 90-min budget and the LLM spend cap are the same concept as the per-host gap.

## 2. Hypothesis verdicts
| H | Verdict | Evidence (verified) |
|---|---|---|
| H1 live = backtest at t=today | **ACCEPT, and it is a correctness fix, not only a refactor** | See the bullets below this table. |
| H2 pipeline is a dataflow graph | **ACCEPT, with one refinement: lagged edges** | 85 steps, **0 declare inputs**, order = list position; ordering rules live in comments (config.py:437, :699). The 2026-09-27 incident (bd7dc24) is a real edge: `fetch_yf_analyst` → `analyst_consensus` → consensus → screener. A naive toposort would put the 14-min weekly fetch **back** before the email. Rule: an edge from a coarser-cadence or slow writer is *lagged* (the reader takes the last good version and the freshness Check covers it), and lagged writers run after the email. Today's run (03:30 start, before the 04:28 fix) was still inside that fetch at 05:09, with no picks yet. |
| H3 table kind fixes semantics | **ACCEPT, replacing today's taxonomy** | `tables.TABLES.kind` is provenance (RAW/COMPUTED/…), not semantics. By PK shape the tables fall into 17 event, 19 series, 10 state, 70 feature and 19 log. Write mode is chosen per writer: 57 upsert_df, 31 insert_df and 82 raw write statements in 39 files. `date_col` is ingest time, not business date, on ~9 tables. |
| H4 quality is declarative on the graph | **ACCEPT** | About 8 registries hold ≈1,000 hand-kept fields: health.TABLE_PROFILES 36, data_sanity 39, plausibility 34, continuity 9, cross-source 3, integrity 8, health_report sets, and the critical-step lists in 3 disagreeing places. There are 3 different M-score ranges. health.py:662 flags all 569 MICRO stocks invalid. Freshness uses the last producer of a table, the watchdog heals via the first (db.py:945 vs freshness_watchdog.py:48). Zero output is checked nowhere centrally, with 26 hand-rolled raises in 19 producers. |
| H5 presentation reads named read-models | **ACCEPT** | "Current picks" is queried **11 ways with 3 gate sets**. 180 SQL call-sites across the apps and output. Adding a factor to the display means 8 hand lists. Verified consequences: dossiers only ever cover the LARGE top 5 (`ORDER BY cap_tier, rank … head(5)`, dossier.py:504-513); the email colours the live `CALM` regime as unknown (email_sender.py:405); change-severity sort never matches (lowercase vs `HIGH`, api.py:792). |
| H6 evidence is a function of the graph | **ACCEPT; the roster already derives, the data doesn't** | backtest_pit picks its factors from `SIGNAL_COLUMN_MAP` automatically. But `promotion_gate` uses a second forward-return implementation without the anchor-proximity guard (ic_decay.py:72 vs reconstruct_pit.py:394). Evidence is scattered across 2 IC tables, factor_horizon_gate and stdout. |

H1 evidence:
- **Piotroski.** Live `piotroski_scores` and `daily_snapshots_pit` disagree on **819 of 2,220** overlapping (sid, date) rows. Live drops Financials and filters to consolidated statements (piotroski.py:35-54); PIT does neither.
- **Pledge quality.** It disagrees on 431 of 2,382 rows, with about 180 differing by more than 0.005. Live and PIT use separate implementations.
- **Consensus.** PIT is EPS revision; live is a PT/growth tier blend (reconstruct_pit.py:601 vs consensus.py:86). The backtest t-stat for `consensus` therefore measures a different signal from the one the weight is applied to.
- **Frozen panel.** The PIT panel ends 2026-07-01 and was last rebuilt 2026-07-11; reconstruct_pit is not scheduled. The monthly backtest re-scores that frozen panel.
- **Shared compute.** About 45 of 67 PIT producers already share the live function, about 8 share it partially, and about 14 are separate or PIT-only.

## 3. The repo mapped onto the blocks (essential / accidental)
| Package | Block | Essential | Accidental (hand-kept, duplicated, workaround) |
|---|---|---|---|
| config.PIPELINE_STEPS (473 LOC) | Node | name, module, fn, cadence | order by position; free-text `source`/`data_freq` never parsed; ordering rules in comments; single `table` cannot express multi-output |
| pipeline.py (237) | Node runner | import/call/log/gate | 0 rows = SUCCESS; `critical` arg unused; retry is at most 1 whatever the config; email-on-failure stub; dead code |
| crontab (11 lines) + run_*.sh (134) | Node schedule | 3 slots (03:30, 14:00, health/watchdog) | preamble copied: venv 10×, env 8×, lock 5×; 9+ jobs live outside the step list, e.g. screener_pull `--universe` feeding about 20 signals |
| tables.py (637) + schema.sql (1869) | Dataset | DDL/PK; stale overrides, coverage, quarantine | a kind that ignores PK; display text; producer derived 3 ways; 16 in-code CREATE TABLEs (kite_* exist only in code) |
| db.py (1306) | Dataset + Check | get_db, upsert/insert, future-date guard | regex lineage scan (112, skips tools/); producer merge; quarantine DDL by regex (inline-PK bug: `analyst_consensus_quarantine` keeps `sid PRIMARY KEY`, so a sid can be quarantined only once) |
| sources/ (37 files, 12.0K) | Host + Node | parse and map | 10 modules bypass `_http`, 4 partly (Moneycontrol adds a redundant `sleep(12)` on top of `polite_get`); 14 HEADERS dicts; LLM model ids hard-coded in 3; 4 derivations (fno_iv, pcr, universe, mf_quality) are not fetchers |
| signals/ (68 files, 10.7K) | Feature | pure math (~5K) | per-module live `_load_data` with no as-of; copied filters; 4 non-factor models (mf_metrics, multibagger, …) |
| factors.py (2558) | Feature | per-factor metadata + derived views | parallel `PIT_PRODUCERS` (68); inferable fields (pit_column_v2 = key in 91 of 105; replay_col, screener_col); `live_table` read by nothing; two family taxonomies |
| tools/reconstruct_pit.py (1972) | AsOf + Feature | knowable_* lag slicing (~40) | ~600 LOC delegators; ~650 LOC PIT-only math; `load_raw` duplicating live SQL; current-universe base |
| tools/pit_replay.py (427) | Check | freeze and diff | the historical mode stubs coverage and uses today's eligibility |
| lineage.py (1271) | Feature/Check | column-level reads, UNIT_CONTRACTS | 105 entries with the same keys as FACTORS; source tables disagree for 46 of 100; module ≠ producer for 27 |
| scoring/ (2123) + portfolio (825) | Model | rank, weight, gate, HRP | quality_gate (241) is a **critical** step whose output nothing reads; regime is display-only; 3-tier loops |
| validators/ (1737), health.py (1167), health_report (763), data_sanity (1136), watchdog (270) | Check | write-time gates; semantic SQL checks; the report | 4 engines stitched into one page; duplicated ranges and enums; continuity and cross-source not wired live |
| cockpit/ + cockpit_ops/ (6.9K py, 8.8K tpl) | View + Surface | pages | inline SQL per route; sector/industry twin functions; 4 nav lists; per-function TTLs; `/sql` on a read-write connection with no auth |
| output/ (2056) | Surface (+ LLM Host) | dossier validator, email | email re-queries with its own SQL and palette; hand signal lists |

**Facts stated twice or more → the owner that should hold them**
- **Table producer and cadence** (steps.table, TABLES freq/stale, regex scan, watchdog) → **Node**.
- **Factor inputs** (FACTORS.source_tables, lineage.reads, step `source` text) → **Feature `reads`**.
- **Factor key set** (FACTORS, FACTOR_LINEAGE, PIT_PRODUCERS) → **FACTORS**.
- **Tier list** (config.TIERS 4 tiers vs factors.TIERS 3; 43 literal sites; 5 tier-keyed dicts; the VIX positional tuple) → **config.TIERS**.
- **Ranges** (pit_range, plausibility, integrity, data_sanity, health profiles, module clips) → **Feature/Dataset range + Check**.
- **Critical steps** (config, test_smoke, health_report substrings, which disagree) → **Node `critical`**.
- **Pick gate** (api.py:835, email_sender.py:357; the integrity-only copies in dossier/diff) → **View `picks()`**.
- **Politeness** (config.API, 6 module constants, 14 HEADERS) → **Host**.
- **Model ids** (config.LLM, 3 modules, db price table) → **Host `anthropic`**.
- **Filing lags** (reconstruct_pit, config.BACKTEST, FACTORS strings) → **Dataset availability lag**.
- **Forward return** (reconstruct_pit, ic_decay) → **one Feature `fwd_return_20d`**.
- **Nav, status and tier colours** (4 nav lists, 2 tier palettes, 2 regime vocabularies) → **PAGES + one formatting map**.

## 4. Change locality: before → after
| Scenario | Today (files · sites) | After | The edit |
|---|---|---|---|
| Add a data source | 4–9 files: fetcher, schema.sql, tables.py, PIPELINE_STEPS **at the right position** or crontab+wrapper, config.API; optionally health profiles, data_sanity, lineage, identity, ops DATA_MODEL_GROUPS | **2** | module (`NODE` + `run`) + schema.sql |
| Add a table | 2–3 (schema.sql, tables.py, ops groups) | **1** (+1 only if non-default) | schema.sql; kind is inferred |
| Add a factor (live+backtest+weight) | 10–11 files · 13–16 sites | **2** | `signals/` fn + FACTORS entry (with `weights`) |
| Add a pipeline step | 1–8 (position; ops layer map; 2 critical lists; budget constant) | **1** | `NODE` + fn in its module |
| Add a quality check | 1 of 5 competing homes; a trust gate = 4 files | **1** | a field (range/stale/coverage) or one `CHECKS` entry |
| Add a cockpit page | 5–6 (route, api fn, template, 2 nav lists, prewarm/TTL) | **2** | `PAGES` entry + template (view fn if new) |
| Change cadence/threshold | 1–3; a step's frequency silently changes freshness; cron tables need crontab+TABLES+wrapper | **1** | the `NODE` cadence or the field |
| Rename a factor | `delivery_anomaly_z`: 13 files / 47 code sites + DB rows | **2** | FACTORS key + `RENAMES` entry (migration applies to panel column + evidence rows) |
| Rename a core column | `cap_tier` 65 files / 426 hits; `price_target` 19 / 118 | **3** (honest miss) | schema + `RENAMES` + the view/model functions that name it |
| Add a tier | 43 literals / 27 files + 5 dicts + VIX tuple + schema CHECK | **1** (+ weight content) | `config.TIERS` entry |
| Replay any past date | not possible end-to-end (stubs, today's eligibility) | **0** | `pipeline.py --asof 2025-12-01 --through picks --db <copy>` |

After-state examples (≤10 lines each):
```python
# sources/nse_block_deals.py   (+ CREATE TABLE block_deals … in schema.sql)
NODE = {"writes": ["block_deals"], "hosts": ["nse_archives"], "cadence": "daily"}
def run(ctx):
    csv = ctx.get("nse_archives", f"{BASE}/block_{ctx.t:%d%m%Y}.csv")   # paced, locked, budgeted
    return {"block_deals": parse(csv)}      # event kind → insert-or-ignore; post-check: fresh as of ctx.t
```
```python
# factors.py — a new factor. Live, PIT column, backtest roster, eligibility and lineage all follow.
"gm_slope": {"fn": "signals.margins.gm_slope", "reads": ["quarterly_income"], "range": (-1, 1),
             "cadence": "monthly", "family": "Quality", "eligible": {"exclude_sectors": ["Financials"]},
             "weights": {"SMALL": 0.05}},     # no weights → LIBRARY bench
# signals/margins.py:  def gm_slope(quarterly_income, t): ... return frame[sid, gm_slope]
```
```python
CHECKS["one_pick_per_sid"] = {"on": "daily_picks", "severity": "CRITICAL",                 # checks/custom.py
    "sql": "SELECT sid FROM daily_picks WHERE pick_date=:t GROUP BY sid HAVING COUNT(*)>1"}
PAGES.append({"path": "/insiders", "view": views.insider_flow, "ttl": 300, "nav": "Research"})  # cockpit/pages.py
config.TIERS["NANO"] = {"carve_from": "MICRO", "rule": "adtv_cr < 0.1", "pickable": False}
```

## 5. Stress tests
1. **PT cadence.** `analyst_consensus` is `state`, refreshed daily. `analyst_consensus_snapshots` is a `series` whose node has cadence `monthly:1`. `write()` rejects rows off the cadence anchor, so a daily row is impossible. The monthly snapshot becomes a node in the morning slot with a post-check. The 2026-06-03 "cron silently no-op'd" failure then has no home.
2. **Financials (ADR 0048).** Eligibility is a Feature field (`exclude_sectors`). The Model has no sector routing. Today live piotroski excludes Financials *inside* compute while PIT doesn't, which is one cause of the 819 mismatches. Moving the exclusion to one field fixes that by construction.
3. **Quarantine.** A dataset override `quarantine: True` plus write-time Checks (identity, plausibility) divert failing rows. Mirror DDL is generated from `PRAGMA table_info` with no PK, which fixes the inline-PK bug.
4. **MICRO.** `TIERS.MICRO = {pickable: False}`. The health tier enum is derived from TIERS, which fixes health.py:662. Finding: **no code writes LARGE/MID/SMALL**; only SMALL↔MICRO is toggled. Tiers are frozen state (see D3).
5. **LLM steps with budgets.** Host `anthropic` = `{budget_usd_day, max_calls, model}`. `ctx.llm()` logs llm_usage and raises BudgetExhausted, and the node ends PARTIAL. The `no_numbers` Check is attached to narrative columns. Empty credits (all 5 dossiers were 400s on 2026-09-26) show up as a failed post-check, i.e. a CRITICAL.
6. **Rate-limited scraper with a time budget.** Host `moneycontrol` = `{gap: 12, budget_min: 90}`, paced by the door only (today a redundant `sleep` sits on top of `polite_get`). Budget stop → PARTIAL, with the resume cursor kept in the node's own state. The node is slow and its edges are lagged, so it runs after the email.
7. **Weekly and monthly cadence.** Cadences are `weekly:sun`, `monthly:1` and `monthly:1,15`. The cron-only jobs become nodes in slots. Staleness is the cadence period plus the dataset tolerance. For a multi-producer table, staleness uses the finest producer and heal runs whichever producer is due, which ends the first-vs-last disagreement.
8. **The critical-path incident.** `fetch_yf_analyst` is weekly and its reader is daily, so the edge is lagged and the node is scheduled after `email`. "Slow" is derived from `pipeline_log` p90 duration, not hand-set. Gate: the email-ancestor set must be ⊆ today's, and the sum of p50 durations to the email must be ≤ today's.

## 6. Projected reduction (accidental code only; `tools/` research excluded)
| Removed | LOC | Removed | LOC |
|---|---|---|---|
| reconstruct_pit delegators + load_raw + DDL + special cases | ~760 | signals `_load_data` live loaders | ~600 |
| cockpit + ops duplicated queries, twin functions, hand lists | ~1,100 | sources pacing/headers/session + in-code DDL | ~500 |
| factors inferable fields + PIT_PRODUCERS | ~400 | lineage table-level duplication | ~350 |
| PIPELINE_STEPS text/comments → NODE dicts | ~270 | health TABLE_PROFILES + data_sanity dup ranges + report sets | ~475 |
| db regex scan + producer merge | ~170 | quality_gate (dead critical step) | ~241 |
| email own SQL/palette, pit_replay stubs, shell preamble, raises | ~480 | **Added:** graph 250, runner +110, views 400, checks 250, hosts 60 | **+1,070** |

**Net: about −4.5K LOC (range −3.5K to −6K), roughly 8% of the 59K live Python.** The larger gain is in hand-kept entries: about 1,000 quality fields, 105 lineage entries, 68 PIT_PRODUCERS, 43 tier literals and 11 picks queries all go. Files a newcomer must read drop from ~10 core files (≈10K LOC) to 6: README, architecture, graph.py, and one example each of a Node, a Feature and a View.

## 7. Migration (strangler; each phase ships alone, in a worktree, and deletes its old path)
| # | Phase | Deletes | Equivalence gate |
|---|---|---|---|
| 0 | **Bug batch**: §9 items, each a separate commit | — | each is an intentional change, with its impact measured |
| 1 | **Graph**: `reads/writes/slot` added to the existing step dicts in place; `graph.py` toposort + lagged edges + critical path; runner uses derived order; producers, /flow and table lineage derived; crontab → `run.sh <slot>` | hand order, `table_step_meta` merge, watchdog `_producer_for`, ops layer map, lineage table-level, 9 cron preambles | 3 days in **shadow mode** (derived order logged beside the real one); `--dry-run` step set identical for every weekday; declared reads ⊇ observed (SQLite authorizer on a DB copy); email-ancestor runtime ≤ today |
| 2 | **Host door**: `hosts.HOSTS`, `ctx.get`, `ctx.llm`; migrate the 14 bypassing modules | module sleeps, HEADERS, model ids, redundant pacers | 3-item smoke per host under `flock -n`, ≥ gap; parsed rows identical on recorded fixtures |
| 3 | **Live = PIT**: `db.asof`, `features_at(names, t)`; the panel node writes t=today daily and anchors monthly; screener reads the panel | signals `_load_data`, reconstruct_pit delegators and loader, pit_replay stubs | `reconstruct_one_date` on 3 monthly dates identical (rtol 1e-12, same NaNs) for all non-D1 factors; today's tier ranks identical for non-D1 factors; D1 factors reported as diff + IC before/after |
| 4 | **Checks**: dataset kinds, `write(dataset, df)`, one runner, post-checks, one verdict table; health email/push/watchdog/ops page become views | TABLE_PROFILES, duplicated ranges, 26 raise sites, criticality sets | health, sanity and email output identical on a frozen DB copy, apart from the listed fixes |
| 5 | **Views + pages**: `views.py`, `picks()` with one gate; cockpit, ops, email and dossier migrated; PAGES → nav | inline SQL, twins, hand lists, the email's SQL | both apps on :3100/:3101 with `COCKPIT_CACHE_DIR` in scratch: all routes 200 and normalized HTML identical; email HTML byte-identical apart from fixes |
| 6 | **Registry compression**: weights into FACTORS, inferred fields, TIERS as data, `RENAMES`; CLAUDE.md rules deleted once they are enforced by construction | PIT_PRODUCERS, SIGNAL_WEIGHTS, factors.TIERS, lineage table-level | a snapshot test of every derived dict is identical before and after |

Every phase must pass the full test suite, `pipeline.py --dry-run`, and an import of every module. Leverage order: 1 → 3 → 4 → 5, with 2 and 6 fitting between. Rough size: P0 1 session, P1 2, P2 1–2, P3 3–4, P4 2, P5 2–3, P6 1. At most 4 subagents, each with an explicit file-ownership list.

## 8. Decisions for Amit
- **D1 — canonical definition for the 6 divergent wired factors.** They are piotroski, accruals, book_to_price, iv_skew_25d, pledge_quality and consensus.
  - Recommendation: keep live's data-hygiene filters (consolidated statements, 75-day lag) in the one shared function, then re-backtest and keep each weight only if its t-stat holds.
  - For `consensus`, adopt the PIT quantity (EPS revision) live until `analyst_consensus_snapshots` has 12 months, i.e. 2027-05. Today its live weight rests on no evidence for the quantity it scores.
- **D2 — approve the Phase 0 bug batch** (§9). Each item is a separate commit with its measured impact.
- **D3 — tier refresh.** Nothing assigns LARGE/MID/SMALL, so tiers are frozen. Is that intentional? Recommendation: a monthly segment node that ranks by market cap. This is a behaviour change.
- **D4 — accept the ADR 0004 amendment**: nodes may return frames and the runner writes them. Also move weights into FACTORS entries, which amends ADR 0017. The rule "weights are hand-set, never derived" is unchanged; only their location moves.
- **D5 — quality_gate.** It is a critical step that computes SMALL-cap exclusions and penalties from `config.QUALITY_GATE`, but its output is never used. Either delete it, which removes an abort point, or wire it into the screener gate, which changes picks.
- **D6 — the ops console (:3001).** It listens on 0.0.0.0 and the host firewall accepts new connections to 3001. It has no auth, `/api/sql` runs on a read-write connection behind a keyword denylist, and POST `/api/pipeline/rerun/{step}` spawns steps without the harvest lock. Recommendation, independent of this plan: open the SQL connection read-only (`mode=ro`), bind to localhost or the VPN, and take the lock on rerun.

## 9. Phase 0 bug batch (all verified; none fixed yet)
1. `fetch_bhavcopy`, the only critical fetcher, returns 0 on a failed download and is logged SUCCESS, so the screener then ranks on stale prices (sources/nse.py:195, pipeline.py:111).
2. Dossiers only ever cover the LARGE top 5, because `ORDER BY cap_tier` sorts alphabetically and is followed by `.head(5)` (output/dossier.py:504-513).
3. The email maps PANIC/STRESS/NEUTRAL/EUPHORIA, but live regimes are CALM/NORMAL/CAUTION/CRISIS, so CALM and CRISIS render blue (email_sender.py:405).
4. The email's target/stop block can never render, because the validator marks any dossier carrying those fields unpublishable (email_sender.py:182, dossier.py:208). The footer also links `/signals` (no such route) and `/system` on :3000.
5. The change-severity sort compares lowercase values against `HIGH`/`MEDIUM` in the DB (cockpit/api.py:792).
6. health.py:662 treats `MICRO` as an invalid cap_tier, which covers 569 stocks.
7. Freshness judges a table by its last producer while the watchdog heals via its first. As a result `macro_history` and `analyst_consensus` are judged on one cadence and healed by another (db.py:945, freshness_watchdog.py:48).
8. `analyst_consensus_quarantine` keeps `sid PRIMARY KEY`, so a sid can be quarantined only once (db.py:163 strips only table-level PKs).
9. Critical-step lists disagree: config has bhavcopy, quality_gate and screener; health_report matches the substrings screener, snapshot and dossier.
10. M-score valid range is set three ways: (−5, 2), (−10, 10) and (−20, 20). Close price is also set three ways.
11. `promotion_gate` forward returns lack the anchor-proximity guard (tools/ic_decay.py:72).
12. The PIT panel is unscheduled and frozen at 2026-07-01, and the monthly backtest re-scores it.
13. `tables.py` says fundamentals_screener has "no automated cron", but a cron refreshes it on the 1st and 15th.

## 10. Top risks
1. **Live = PIT changes picks** for the 6 D1 factors. Mitigation: per-factor sign-off plus a before/after IC.
2. **Hidden reads could produce a wrong order.** Mitigation: the authorizer test and shadow mode before cut-over.
3. **Critical-path regression.** Mitigation: the runtime gate, with slow nodes derived from pipeline_log.
4. **An abandoned strangler leaves two ways of doing things.** Mitigation: every phase deletes its old path and stands alone.
5. **Concurrent sessions touch config.py, factors.py and the cockpit APIs.** Mitigation: short-lived branches, ownership lists, and a check of ListAgents before each phase.
6. **Replay stays survivorship-biased** until WS2.8, since universe-as-of uses current stocks. This is documented, not solved.
7. **Deploys touch production cron and systemd.** Every merge and restart needs Amit's explicit OK.

## Implementation notes
- **2026-09-27 — approved.** Merge/deploy gate kept: every merge to master (prod runs from it) and every service restart still needs Amit's explicit OK. Phase 1 shadow mode needs a merge to run in prod, so phases are built on branches up to that gate.
- D6 scope decision: code-level hardening only (read-only SQL connection + query timeout + harvest lock on rerun). Binding 3001 to localhost or adding auth would lock out remote access via the DuckDNS host — left to Amit.
