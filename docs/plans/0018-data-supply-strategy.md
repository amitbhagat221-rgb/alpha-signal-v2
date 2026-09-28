# Plan 0018 — Data supply: feeds, fallbacks, checks, discovery

**Status:** approved 2026-09-28 (Amit: "approved all", D1–D6 as recommended). **P0 shipped 2026-09-28** together with the Gate 1–2 and canary parts of P1/P2 (see Implementation notes).
**Why now:** data work is manual and reactive. We find broken feeds when a pick looks wrong or when Amit asks, and new sources only when someone thinks to look. Evidence from 2026 alone:
- Transcripts silently stopped on 06-07 (no scheduled step).
- The Screener cookie sat dead from Jul to Sep.
- NSE insider data was empty from 05-02.
- BSE returned 403 from 09-19.
- MF NAV had a parse gap from 08-19 to 09-25.
- LLM credits ran out from 08-24.
- Research 0005 found that pre-2023 delisted prices, a "permanent gap", had been reachable all along.

**Builds on (adds little, reuses most):**
- [ADR 0052](../decisions/0052-seven-building-blocks.md): Host, Node, Check blocks; `sources/_http` door; `checks.post_step`.
- [Plan 0017](0017-data-model-redesign.md): `db.write`, `row_issues`, `check_results`, concepts.
- [Plan 0016](0016-alpha-signal-mcp.md): the MCP `ops` profile plus routines host the DQ agent.
- [Plan 0014](0014-data-acquisition-roadmap.md): *what* to acquire.
- [Research 0005](../research/0005-source-gap-sweep.md): the first discovery sweep and its probe verdicts.

## 1. The idea in one paragraph

Every external data stream becomes a **feed**: one entry in one registry (`feeds.py`). The entry says:
- what kind of data it delivers (**family**)
- how much we depend on it (**tier**, derived from the graph, not typed by hand)
- where it comes from (ordered **routes**: primary, then fallbacks)
- what "good" looks like (**contract**)
- how to test it cheaply (**canary**)
- what has gone wrong before (**runbook** link)

Everything else follows from that entry:
- **Checks run at three gates:** response, frame, cross-source.
- **A failing route falls through to the next one.**
- **Canaries catch API changes before the morning run.**
- **Discovery is a funnel:** new streams enter as `wanted` rows in the same registry and move to `production` through the same tests.
- **A later DQ agent reads the registry, the evidence and the runbook**, and acts within a fixed permission ladder.

**Scope.** One new registry, one raw-response folder and one probe tool. No framework, no YAML, no new database (ADR 0004).

## 2. Organise: the feed registry

### 2.1 Family: what kind of data (decides write rule and PIT rule)

Families line up with plan 0017's concepts, so a family also tells `db.write` how to store the data.

| Family | Delivers | 0017 concept | Current feeds (module) |
|---|---|---|---|
| **Reference** | who exists, identifiers, tiers | reference | `universe`, `scrip_master`, `mf_amfi_master` |
| **Prices** | bars, delivery, F&O, SLB, volatility, indices | bars / series | `nse`, `yfinance_prices`, `fno_pull`, `fno_iv`*, `nselib_pull` (indices, short-sell) |
| **Fundamentals** | statements, results, sector KPIs | fundamentals | `tickertape`, `screener_pull`, `screener_schedules`, `banking_metrics` |
| **Ownership** | shareholding, insider, bulk/block, pledges | fundamentals (family ownership) / events | `tickertape_shareholding`, `nse_insider`, `nse_bulk` |
| **Estimates** | consensus, forecasts, recos | estimates | `yfinance_analyst`, `tickertape_analyst`, `moneycontrol_recos` |
| **Events & documents** | announcements, corporate actions, ratings, transcripts | events / documents | `bse_announcements`, `nselib_pull` (actions, calendar), `transcripts_pull` |
| **Macro & flows** | macro series, FII/DII, nowcasts | series | `macro_yfinance`, `macro_official`, `nselib_pull` (FII/DII) |
| **News** | articles, regulatory items (+ LLM enrichment, plan 0016) | documents | `rss`, `regulatory_harvester`, `news_images` |
| **Funds** | MF NAV, holdings, metadata | series / fundamentals (`mf.db`) | `mf_nav_daily`, `mf_nav_backfill`, `mf_holdings_scrape`, `mf_holdings`, `mf_metadata_enrichment`, `mf_data_quality`* |

\* Derived in-house from another feed, with no external host. It is registered so the chain is visible, and it inherits the upstream feed's tier.

### 2.2 Tier: how much we depend on it (derived, three levels)

| Tier | Rule (computed by `graph.py`, never hand-typed) | Today | Obligations |
|---|---|---|---|
| **T1 Critical** | An ancestor of a **wired factor** (`factors.FACTORS[…]['weights']`) or of the picks/email critical path (`checks.critical_steps()`) | prices (NSE, yfinance fallback), corporate actions, Tickertape fundamentals, shareholding (pledge), F&O bhav → IV, BSE announcements (governance, CAR), forecast_history (consensus), macro market (CAR benchmark, sector tilt), RSS (email) | ≥1 **fallback** or a declared serve-stale limit; **daily canary**; contract enforced **before** write; CRITICAL alert; fix within 2 trading days |
| **T2 Important** | Feeds the cockpit, the MF product, research tables or non-wired factors | insider, bulk deals, Screener, banking metrics, analyst consensus, broker recos, MF feeds, macro official, regulatory, transcripts | weekly canary; contract; WARN alert; fallback optional (serve stale) |
| **T3 Probation** | `status in (candidate, probation)` | research-0005 builds | shadow tables only; daily digest; no alerts |

The tier updates itself when a factor is wired or unwired. **If a T1 feed has no fallback, that is itself a health finding**, not a note in someone's head.

### 2.3 The entry (plain dict; one file shows the whole supply map)

```python
FEEDS["nse_bhavcopy"] = {
    "family": "prices", "node": "fetch_bhavcopy", "writes": ["stock_prices"],
    "status": "production",            # wanted → candidate → probation → production → degraded → retired
    "arrives": ("18:30", "IST", "T+0"),   # expected-by window; a feed not in by then is "late"
    "routes": [                        # ordered; the first route whose contract passes wins
        {"id": "nse_udiff",  "host": "nse_archives", "fn": "sources.nse:fetch"},
        {"id": "hf_tejhq",   "host": "huggingface",  "fn": "sources.hf_bars:fetch"},   # fallback
        {"id": "last_good",  "serve_stale_days": 1},                                   # final floor
    ],
    "contract": {"rows": "band(20)", "keys": ["symbol", "date"], "coverage_pct": 95,
                 "required": ["open", "high", "low", "close", "volume"], "no_future_dates": True},
    "canary": {"fn": "sources.nse:canary", "items": ["RELIANCE"], "every": "daily"},
    "pit": "available_at = publish date of the file",
    "tos": "public archive",
    "runbook": "feed-runbook.md#nse_bhavcopy",
}
```

**Why a central `feeds.py`** (D2): it sits beside `hosts.py`, `tables.py` and `factors.py`, so one file answers "where does our data come from, and what happens when it breaks?". `tests/test_feeds.py` enforces that:
- every `sources/*.py` producer and every step that writes a RAW table maps to exactly one feed
- every `production` feed has a schedule (step or `run.sh` case), an arrival window and a canary. This closes the "orphan feed" class: transcripts, `corporate_adjustments`.
- every T1 feed has a fallback route or `serve_stale_days`

## 3. Fallbacks

**Four route kinds, tried in order:**
1. **Alternate host.** Independent failure; preferred for T1.
2. **Alternate path on the same host.** An API vs an archive file (e.g. nselib UDiFF vs `nsearchives` direct).
3. **Last good (serve stale).** Allowed only up to `serve_stale_days`. Consumers see the staleness; the email says so.
4. **Manual drop.** A file placed in `data/inbox/<feed>/` goes through the same contract. This is the human fallback for multi-day outages.

**Rules:**
- **Every row carries `source`,** the route id. Plan 0017 `bars_daily` already keys on it.
- **When the primary recovers, overlap days are reconciled** (Gate 3), and fallback rows are kept or restated through `restate=True` plus a `row_issues` audit.
- **The feed's status becomes `degraded` while it runs on a fallback,** and clears after 3 green primary runs.
- **Fallbacks never lower politeness:** same `_http` door, same lock.

**T1 fallback matrix, today → target** (P3 builds the top 3 by risk):

| T1 feed | Primary | Fallback today | Target fallback (research 0005 verdict) | Risk if primary dies |
|---|---|---|---|---|
| Prices | NSE bhavcopy | yfinance, **missing sids only** | HF `tejhq` adjusted parquet ✅ probed; BSE bhavcopy | picks stop |
| Fundamentals | Tickertape via `Bharat_sm_data` (**last release 2025-07**) | none | Screener exports (already harvested) → NSE results XBRL ✅ probed | 3 wired factors freeze |
| Shareholding (pledge) | Tickertape | none | BSE `Corp_Shareholding_ng` XBRL ✅ probed | `pledge_quality` freezes |
| Corporate actions | nselib | none | HF `actions/` parquet; BSE corp actions | adjusted returns wrong |
| F&O bhav | nselib UDiFF | none | `nsearchives` direct files ✅ probed | `iv_skew_25d` freezes |
| BSE announcements | BSE API | none | NSE announcements API | governance/CAR freeze |
| Forecast history | Tickertape | none | Yahoo `earnings_estimate` (partial) | serve stale, 35 days |
| Macro market | yfinance | none | `nse_index_history` (nselib) | CAR benchmark |

## 4. Upstream DQ: three gates

The checks runner (ADR 0052) and `db.write` (plan 0017) already exist. This plan adds the **feed-level** gates that run **before** data reaches a table.

| Gate | Runs on | Checks | Catches (historical example) |
|---|---|---|---|
| **1 Transport** | the raw response | HTTP status; content-type (HTML where JSON was expected means a bot page); byte size vs band; **shape fingerprint**, a hash of column names or JSON keys and types, diffed against the last good response | BSE Akamai 403 (09-19); BSE `Origin` header returns a 1814-byte error shell; **API changes: an AMFI column was added and NAV parsing broke from 08-19 to 09-25** |
| **2 Content** | the parsed frame, pre-write | row count within the trailing-20-run band; key uniqueness; required-column null rate; catalog ranges (0017); coverage vs universe; no future dates; as-of date = expected | the bhavcopy "0 rows logged SUCCESS" bug; the NSE insider endpoint going **silently empty** (05-02); future-dated insider rows |
| **3 Consistency** | stored data, weekly and on route switches | cross-source sample (20 random sids: NSE close vs HF vs yfinance); continuity (no missing trading days); arrival vs window; semantic spot-checks listed in the runbook | **semantic drift:** `forecast_history.price` was a year-ahead close (ADR 0045); Moneycontrol `reco_date` defaulting to today |

**Verdicts:**
- **PASS:** write.
- **WARN:** write and flag the feed.
- **FAIL:** don't write; try the next route; if every route fails, **raise** (CLAUDE.md silent-failure rule).
- Row-level rejects go to `row_issues`. Gate outcomes go to `check_results` (0017; `trust_verdicts` until 0017 stage 2).

**Raw landing zone** (D3): `data/raw/<feed>/<date>/`, gzip, 30-day retention, 2 GB cap. It keeps **the last good response plus every failing response**. That serves three purposes:
- test fixtures (§6)
- the evidence behind a shape-fingerprint diff
- replay after a parser fix, with no re-download and no extra load on the upstream

## 5. Known issues: symptom classes + runbook

**Eight symptom classes** cover every 2026 incident. Each class has one standard first response, which the DQ agent (§8) also follows.

| Class | Signature | First response | 2026 incidents |
|---|---|---|---|
| **A Blocked** | 403, connection reset, 200 HTML challenge | Headers/Referer, cookie warm, TLS impersonation (`hosts impersonate`). **Never bypass a captcha or auth.** | BSE Akamai (09-19); VAHAN reset (research 0005) |
| **B Moved** | 404, or 200-empty, or a row-count cliff | Check wrapper changelogs (nselib, NseIndiaApi, jugaad), exchange circulars and `daily-reports` manifests; probe candidates | NSE insider → `corporates-pit-gg`; results → `integrated-filing-results` (2025); BSE `AttachLive` → `AttachHis` |
| **C Auth** | login page, 401 | Re-login path; alert if that fails | Screener ~30-day session (dead Jul–Sep) |
| **D Shape drift** | fingerprint diff | Parser fix + new fixture + replay from the raw zone | AMFI NAV "Plan;Option" columns |
| **E Partial / zero** | count or coverage below band | Next route; check for a holiday; heal | bhavcopy 0 rows logged SUCCESS; bulk_deals price=0 rows |
| **F Semantic drift** | plausible values that mean something else | Gate 3 cross-source; PIT audit; pull the field | `forecast_history.price` (ADR 0045); reco_date fabricated |
| **G Quota / billing** | 429, 400 "credit balance" | Budget, backoff, alternate executor | Anthropic credits (08-24) → plan 0016 routines |
| **H Orphan** | feed not scheduled or cron no-op | `test_feeds.py` schedule rule | transcripts (06-07); corporate_adjustments (04-30); cron missing `cd` |

**`docs/reference/feed-runbook.md`**, created in P0, has one section per feed. Each section lists: failure signatures → cause → fix → date verified → commit. P0 seeds it from the table above, research 0005 and git history. **Every incident ends with a runbook line**; that is how a fix stops being tribal knowledge.

## 6. Testing: a five-rung ladder

| Rung | What | When | Cost |
|---|---|---|---|
| **1 Fixture** | Offline pytest per feed: ≥1 recorded good response and ≥1 recorded bad one, from the raw zone, parsed to golden output | every push (pre-push hook) | 0 requests |
| **2 Canary** | 1 live item per feed; runs Gates 1 and 2 only; no write | T1 daily **02:45 UTC** (before the 03:30 run), T2 weekly | ~1 request per feed |
| **3 Smoke** | 3 items (L/M/S) end to end into a scratch DB (`ALPHA_DB`, 0017 stage 0) | before any full run, backfill or parser change (CLAUDE.md rule) | ~3–10 requests |
| **4 Shadow** | full scheduled runs into a shadow table; Gates 1–3 each run; parity vs the incumbent if one exists | probation: **10 green runs or 2 cadence cycles** | normal run |
| **5 Reconcile** | sample compare vs a second source before switching routes or writing history | backfills, route switches | ~20 items |

**One probe tool serves both discovery and ongoing health.** `tools/probe.py` turns this session's `smoke_sources.py` into a permanent tool: each feed's `canary` fn is also its discovery smoke test. `run.sh canary [feed]` runs under the harvest lock, sequentially, through `_http`.

## 7. Discovery: a funnel with a clock

**Stages.** These are the `status` values of the same registry entry, so the backlog and production live in one place.

| Stage | Entry | Exit (all required) | Kill if |
|---|---|---|---|
| **wanted** | a gap: a factor idea, a failing T1 fallback, a plan-0014 item | a scout note names ≥1 route | superseded |
| **candidate** | desk research (research-0005 style: route, depth, PIT, ToS) | canary passes on 3 items; verdict recorded | ToS-grey, captcha/auth bypass needed, or PIT-unsafe for its intended use |
| **probation** | ingestor built with a contract | rung 4 passes (10 green runs); backfill reconciled; runbook section exists | contract fails twice after fixes |
| **production** | tier assigned automatically | — | — |
| **retired** | unused ≥90 days or superseded | — | — |

**Scoring:** `(value × confidence) ÷ effort` (plan 0014), behind two hard gates: **ToS-clean** and **PIT-honest**.

**Cadence, so discovery doesn't depend on someone remembering:**
- **Quarterly sweep, first week after results season:** re-run the research-0005 six-agent sweep. It is saved as a named workflow, `.claude/workflows/source-sweep.js`, so it's one command. Output: new `wanted`/`candidate` rows plus a research note.
- **Monthly ecosystem watch** (`tools/ecosystem_watch.py`, no LLM): PyPI versions of the libraries we depend on (nselib, jugaad-data, Bharat_sm_data, yfinance, nse, curl_cffi) and the last push of watched GitHub repos (research 0005's list). A release or a >12-month silence becomes a digest line, e.g. "Bharat_sm_data silent since 2025-07 → T1 risk".
- **On demand:** any factor idea that needs data adds a `wanted` row first, the same rule as the checklist.

## 8. The DQ agent (commissioned later; contract fixed now)

**Trigger:** a canary FAIL, a gate FAIL, a CRITICAL in `health_report`, or a feed `late` past its window.

**Loop:**
1. Classify the symptom (A–H).
2. Look up the feed's runbook for a known fix.
3. Act within its permission level.
4. Verify with canary + smoke.
5. Write the incident to `row_issues`/`check_results` and append a runbook line.

**Reads:** the MCP `ops` profile (plan 0016) plus the raw zone, `feeds.py`, the runbook and the feed module's git log.

| Level | May | Default |
|---|---|---|
| **L0 Diagnose** | read everything above; post a diagnosis (class, evidence, proposed fix) | on from day 1 |
| **L1 Operate** | rerun a feed within its host budget; switch to a *declared* fallback route; run the declared re-login path; mark a feed `degraded` | on after 4 weeks of accurate L0 diagnoses |
| **L2 Repair** | parser/endpoint fix **on a branch**, with a new fixture and a passing smoke test; opens a PR for Amit | PR only, never merges |

**Never:**
- merge to master
- touch secrets or credentials
- lower `hosts` politeness
- bypass captcha, auth or a WAF challenge
- write production tables outside the feed's own write path
- change factor weights or eligibility
- run two harvesters at once

**Measured by:** time-to-detect, time-to-fix, and **silent failures**, i.e. failures that surfaced first in picks, research or Amit rather than in DQ. The target for silent failures is 0.

## 9. Phases (strangler rule: each ships alone, with a visible payoff the same session)

| Phase | Builds | Visible payoff | Size |
|---|---|---|---|
| **P0 Inventory** | `feeds.py` for all ~40 feeds (family, status, routes as they are today, arrival, derived tier); `test_feeds.py`; a **Feeds** section in `health_report`/cockpit ops; `feed-runbook.md` seeded | one page shows the supply map, **T1 feeds without a fallback**, and orphans (transcripts is flagged immediately) | 1 session |
| **P1 Gates + raw zone** | Gates 1–2 in the runner around T1 feeds; shape fingerprint; raw landing; results → `check_results`/`row_issues` | the first shape-drift alert fires on a real diff | 2 sessions |
| **P2 Canaries + fixtures** | `tools/probe.py`; a canary per T1 feed; `run.sh canary` at 02:45 UTC; fixtures from the raw zone in pre-push | the morning health email opens with a "canaries: N/N green" line | 1–2 sessions |
| **P3 Fallbacks** | route runner (ordered routes, `source` column, degraded status); the top 3 T1 fallbacks (prices full-universe, fundamentals, shareholding) | a route switch drill: disable the primary, get the same picks from the fallback | 2–3 sessions |
| **P4 Discovery loop** | research-0005 candidates entered; probation/shadow mechanics; `ecosystem_watch.py`; the saved `source-sweep` workflow | the first candidate (BSE SHP retail counts) promoted through the funnel | 1 session + recurring |
| **P5 DQ agent** | routine + `ops` MCP + runbook loop, L0 → L1 → L2 | the first incident diagnosed without Amit asking | after plan 0016 P1–3 |

**Ordering with in-flight work:**
- P0 and P2 need nothing new and can start now.
- P1 writes through `check_results`/`row_issues`, so it lands with or after 0017 stage 0.
- P5 needs plan 0016's MCP.

## 10. Decisions for Amit

| # | Decision | Recommendation |
|---|---|---|
| D1 | Three derived tiers (T1 critical / T2 important / T3 probation) | **approved** |
| D2 | One central `feeds.py` (next to `hosts.py`), not a per-module dict | **approved** |
| D3 | Raw landing zone: last good + every failure, 30 days, 2 GB cap | **approved** |
| D4 | Canary cron 02:45 UTC daily (T1), Sunday (T2), under the harvest lock | **approved** (installed) |
| D5 | DQ agent ceiling: L1 autonomous after 4 weeks of L0; L2 = PR only | **approved** |
| D6 | Fallbacks that need an account (Fyers, Upstox, Breeze, Kite) are out of scope until you open accounts | **approved** (out of scope) |

## Implementation notes
- **2026-09-28: P0 shipped, plus the canary and Gate 1–2 parts of P1/P2** ("ensure checks are robust at this stage itself").
  - **Registry: `feeds.py`.**
    - 30 live feeds (17 T1 / 13 T2, tiers derived), 22 discovery entries (research 0005 probe verdicts) and 3 retired dead ends.
    - Also holds `SYMPTOM_CLASSES`, `INCIDENTS` (16 incidents), and `log_steps()`, which parses `run.sh` so cron log names are never hand-copied.
    - **Tier rule as built:** an external feed is T1 when it writes a RAW table that a critical step reads or writes, or that a wired factor uses. A derivation (`derived_from`) is judged on its outputs of any kind, so `fno_iv` is T1 through `iv_skew_25d`, while `llm_enrichment` stays T2.
  - **Canaries.**
    - 23 canaries in `sources/canaries.py`: one module, not a function per source module (deviation from §2.3's `sources.nse:canary`). Each reuses its feed module's URL constants and fetch helpers.
    - The runner is `tools/canary.py`: Gate 1 transport, Gate 2 content plus a shape fingerprint vs `data/raw/<canary>/baseline.json`, symptom classification A–H, raw landing and pruning, and `--accept`.
  - **Storage.** Verdicts go to a new LOG table, **`feed_checks`** (schema.sql + tables.TABLES, `freq: daily`). It was not written into plan 0017's `check_results`: that table keys on `catalog` ids, which don't exist yet. It maps onto `check_results` at 0017 stage 2.
  - **Verdicts:** `checks/feeds.py`.
    - Severity by tier: T1 CRITICAL on drift or auth at once, and on a 2nd consecutive failure; T2 WARN.
    - Missing canary, orphan, no-fallback, single-source (INFO) and registry drift are also flagged.
    - Wired into `tools/health_report` (3+ missing canaries collapse into one "is the canary cron running?" issue).
  - **Surface:** ops page `/feeds` "Data Supply" (+ `/api/feeds`), with 5 tabs: Overview, Feeds by family, Discovery funnel, Known issues, Strategy.
  - **Runbook:** [feed-runbook.md](../reference/feed-runbook.md) is organised per symptom class rather than per feed (deviation from §5). The per-feed facts live in the registry and on the page.
  - **Schedule:** cron `45 2 * * * run.sh canary` (harvest lock, `logged cron_canary`). ops/crontab.txt and the live crontab are in sync.
  - **Tests:** `tests/test_feeds.py`, 28 tests.
    - Coverage: every source module, source step and RAW table is covered.
    - Schedules point at real steps and cron jobs.
    - T1 resilience and canaries.
    - Offline gate cases for every HTTP code, HTML-where-data, empty, floor, removed vs added fields, column order, auth checks, exception classes, raw-zone pruning and verdict severities.
    - An offline page render.
  - **First live run (all 23): 22 PASS, 1 WARN.** The WARN is a real find: scrip_master's GitHub ListOfScrips fallback returns 404. That route is marked `dead` and no longer counts as resilience.
  - The first dry run also caught a canary bug: BSE's API returns 0 rows for date *ranges*, and the harvester queries single days. Fixed before recording.
  - **Standing findings on the page:**
    - transcripts is an orphan (H)
    - 15 of 17 T1 feeds are single-source (serve stale only)
    - P3 fallback order stands: prices full-universe, Tickertape fundamentals, shareholding
  - **Not built yet:**
    - Gate 3 cross-source reconciliation
    - fixtures from the raw zone in pre-push (rung 1)
    - the ordered-route runner (P3)
    - `ecosystem_watch.py` and the saved sweep workflow (P4)
    - the DQ agent (P5)
- **2026-09-28: Ingestor code audit (Amit: "no repetition, no repeat implementations, no bloat, uniformity").**
  - **Method:** an AST pass over `sources/` (36 modules, 12.4K lines), looking for:
    - functions defined in ≥2 modules
    - near-identical bodies (ratio ≥0.8)
    - a per-module census of 25 idioms: CLI, write path, HTTP, pacing, sid lookup, raise-on-zero, dates, LLM
  - **Literal duplication was already low** after the 2026-09-26 cleanup (4 near-identical pairs). The real repetition is idiom-level: the same problem solved slightly differently per module.
  - **Merged today** (golden traces in `tests/test_sources_door.py` unchanged, 253 tests green, live 3-item smoke of each touched harvester):
    - `db.insert_df(lock_retries=)` replaces two hand-rolled "INSERT OR IGNORE + database-is-locked backoff" writers (`bse_announcements._store`, `transcripts_pull._store_rows`). The retry is real: write-write contention raises SQLITE_BUSY despite busy_timeout. Live: 506 new BSE rows through it.
    - `_http.write_tagged(tagged, tables)` replaces the identical multi-table `write()` in `tickertape_analyst` and `yfinance_analyst`.
    - `_http.to_float` replaces `_safe_float` in `nse_bulk` and `nse_insider`.
    - `screener_schedules` imports `screener_pull.get_targets` (it was a 100%-identical copy).
    - `tickertape_shareholding` reuses `sources.tickertape._get_client`: one client and one Bharat_sm_data path hack, not two.
    - Dead imports removed. Tests follow the moved code: `test_sources_door` / `test_sources_silent_failures` now patch `db.upsert_df` and `screener_pull.read_sql` / `insert_df`.
  - **Remaining, ranked by value ÷ risk.** Each is behind the golden traces + canaries; one module per commit.
    1. **Hand-rolled per-item harvest loops → `_http.run_harvester`** (5 modules use it, 7 hand-roll it):
       - `banking_metrics`, `screener_pull`, `screener_schedules`, `transcripts_pull`, `moneycontrol_recos`, `mf_holdings_scrape`, `nse_insider` (XBRL loop)
       - Budgets, checkpoints and 429 pauses go in as `run_harvester` options only when ≥2 modules need them.
       - 6 of the 7 have golden tests.
    2. **In-module retry/backoff sleeps that duplicate the host door:**
       - `banking_metrics` (429 → sleep)
       - `mf_holdings_scrape` (own exponential backoff + chunk pauses)
       - `regulatory_harvester` (403 → sleep 5)

       Declare them in `hosts.HOSTS` (retries / gap / budget) and let `polite_request` back off.
    3. **13 modules write their own `SELECT sid, ticker|slug FROM stocks …` target query.** Make it one `targets(col, tier=, sid=)` helper, landed with plan 0017's `identifiers`, so it's written once, against the new schema.
    4. **Raw SQL writes in 11 modules** go to plan 0017 `db.write` (stage 1). Not pre-empted here.
    5. **LLM modules** (`news_brief`, `news_classifier`, `regulatory_classifier`) each have their own Anthropic client, JSON parsing and rate sleeps, while `output/_llm.py` already has `llm_text`/`llm_json`. Folded into plan 0016, which replaces them with routines. Not touched now: another session has uncommitted edits in `news_classifier.py`.
    6. **MF manual CSV paths:** `mf_holdings.ingest_from_csv` ≈ `mf_metadata_enrichment.ingest_from_csv` (~70 lines each), plus 3 `status()` copies. One CSV-ingest helper when the manual route is next used; low value now.
  - **Kept, already uniform:**
    - argparse CLI + `__main__` in all 36 modules
    - `print` logging in all 36
    - raise-on-zero in 21 modules + `run_harvester`
    - no direct `requests.get`; every call goes through the door
  - **Bloat or orphan found:**
    - `screener_schedules` is never scheduled (manual CLI only). Schedule it after `screener_universe`, or retire it.
    - `kite_pull` (298 lines) stays a candidate until D6.
    - `mf_nav_backfill` stays as the NAV feed's fallback route.
- **2026-09-28: Structured run log for agents** (Amit: "detailed and queryable logs, so an outside agent over MCP can find the exact failure point and send instructions").
  - **Design.**
    - One module, `runlog.py`, writing one table, **`run_events`** (LOG, 90-day retention), keyed by a `run_id` per step, cron job or manual source run.
    - Event types: `run_start`, `request`, `item_error`, `exception`, `summary`, `note`, `canary`, `run_end`, `run_exit`.
    - Each failure carries the symptom class A–H, the exact **failure point** (innermost non-library frame), the **origin** (innermost frame in the feed's own module), traceback frames, and the redacted upstream response snippet.
    - `run_end` carries per-host request/status counters, retries, latency, rows written per table, and the output tail.
  - **No per-module logging code.** Hooks sit at the shared choke points:
    - `_http.polite_request` / `pace` / `run_harvester`
    - `db.insert_df` / `upsert_df`
    - `pipeline.run_step` (its `error_message` now ends in `@ file:line`)
    - `tools/canary` (adopts the cron run)
    - `run.sh logged`, which exports `ALPHA_STEP` / `ALPHA_RUN_ID` to the child, auto-starts the run there, and records the exit code under the same id
  - **Hand-rolled loops** (not yet on `run_harvester`, audit item 1) get one `runlog.item_failed` / `item_error` line each: banking_metrics, screener_pull `log_error` (also covers screener_schedules), nse_insider, mf_holdings_scrape, regulatory_harvester, bse_announcements, transcripts_pull.
  - **Safety.**
    - Redaction: query params, auth headers, cookies, bearer tokens, and the literal values of secret env vars.
    - Per-run caps: 50 request events, 200 item errors.
    - Writes are best-effort and never raise.
    - `tests/conftest.py` gives every test a throwaway run-log DB. A first run leaked ~30 test events into the live table; they were caught and deleted.
  - **Query surfaces.**
    - `python -m runlog runs|events|bundle <feed>`
    - ops `/api/runs`, `/api/run-events?feed=&level=&since=`, `/api/feeds/{feed}/incident`
    - Data Supply detail rows show each feed's last run and recent problems with file:line
    - **For plan 0016:** the MCP `ops` profile should expose `runlog.runs` / `events` / `bundle` read-only (a `feed_incident(feed)` tool). Not added to 0016 here because another session holds uncommitted edits to it.
  - **Tests:** `tests/test_runlog.py` (15).
    - Covers redaction, failure location, exception classes, lifecycle counters and tail, flood caps, the pipeline hook, run adoption, `item_failed`, and the bundle.
    - **Two tests run a real child process with the cron env** (uncaught exception → `exception` event with frames; `sys.exit(3)` → FAILED).
  - **Found on its first live use — two silent banking_metrics bugs, both fixed + tested:**
    1. BJAT was dropped as a false identity-gate `WRONG_ENTITY`: `&amp;` vs "and" (`validators/identity_check._normalise_company_name` now unescapes).
    2. **Every banking quarantine write failed** on the in-flight `_book_value_cr` key (`quarantine_row` now drops underscore helper keys; `write_verdicts` failures are now run-log WARNs).

    Both were visible only as printed lines before.
- **2026-09-28: New sources onboarded — judgement call** (Amit: "decide yourself what's genuinely useful and backfill it"). Criteria: value to the picks/research × request cost × fit with plan 0017's concept tables.
  - **Two new concept tables, shaped like plan 0017's so its migration is a rename:**
    - `market_events` (≈ `events`: type, subtype, sid, event_time, available_at, source, source_key, JSON payload). One table for three streams.
    - `analyst_estimates` (≈ `estimates`, versioned: an unchanged value only bumps `last_seen_at`).
    - Shareholder counts are one column, `shareholding.n_shareholders`.
    - No per-thing tables (ADR 0054).
  - **Built, status `probation`:**
    - **`nse_credit_ratings`** (`sources/nse_events.py`).
      - Backfilled 2025-01 → now: 6,897 events.
      - **Direction comes from comparing the earlier and new ratings** on the long-term or short-term scale, not from the action label. The label hid downgrades under "Other" and mislabels ("Reaffirm" on an actual upgrade).
      - Debt ISINs link to the equity through the **7-char issuer prefix**: 73% of events linked, up from 1%.
      - Honest limits: ~100 listed issuers (banks/NBFCs dominate), and only 26 downgrades in the window (benign cycle). The factor's downgrade signal will come from forward collection.
      - Daily in `run.sh forward`.
    - **`nse_ipo_master`:** 1,457 issues from 2003, with anchor lock-in dates by rule. Daily in `forward`.
    - **`index_membership`:** NSE's own inclusion/exclusion log, 9,121 events, 1996 → 2020-09. Loaded once; the file is no longer updated.
    - **`yahoo_earnings_history`** (`sources/yahoo_estimates.py`).
      - Per-report estimate vs actual, ~2007+ for large caps, labelled `pit_unverified`; upcoming estimates are dated at the fetch.
      - Plus weekly EPS-trend snapshots (point-in-time honest).
      - Backfill: history for LARGE/MID/SMALL, trend for covered stocks.
      - Weekly cron `run.sh estimates` (Saturday 10:00 UTC): trend for covered stocks + history for stocks reported in the last 21 days.
    - **Shareholder counts:** parsed from the Screener company page the harvest already loads (0 extra requests, ~12 quarters). Exception-safe, so a parse failure can never cost the fundamentals.
    - **F&O 2024-07 → 2025-05 backfill** through the existing `fno_pull` + `fno_iv`. It lengthens the history of the wired `iv_skew_25d` from ~14 to ~24 months (+~0.5 GB).
  - **Declined, with reasons:**
    - delisted-price panel + pre-2020 delivery (plan 0014 D3: supervised, needs 0017 `entities`)
    - BSE shareholding XBRL (~15 h of requests; the Screener route gives the counts free — kept as a candidate for the retail split + filing date)
    - VAHAN / energy / FBIL / RBI credit / PPAC (no factor needs them yet)
    - filing-day results XBRL (next build: two parsers)
    - Fyers/Upstox (accounts), GST (blocked), SLB (too thin), CMVOLT (duplicates our own volatility)
  - **Bugs caught by the new tests before shipping:**
    - `analyst_estimates.fetched_at` was part of the key at second precision, so a changed value written in the same second was silently dropped. Now microseconds.
    - The Screener table regex cut off `<table`, and the parse returned nothing.
    - `analyst_estimates` freshness now keys on `last_seen_at`.
  - **Tests:** `tests/test_new_sources.py` (15).
  - **Backfill discipline:** one sequential queue under the harvest lock, clear of the 14:00 / 15:00 crons, with budgeted resumable Yahoo passes.
- **2026-09-28: Ingestion close-out** (before moving on to data sources → factors → models → portfolio).
  - **transcripts** scheduled: weekly `run.sh transcripts` (Sunday 07:00) covers stocks reported in the last 45 days, then fills BSE filing dates. It had been orphaned since 2026-06-07. A Jun→Sep catch-up is queued tonight.
  - **bulk_deals:** `--repair-prices` refills the 12,787 price-0 rows (Jun 2025 – Apr 2026) as an update-only run.
  - **insider July:** the low count (314) matches SEBI's trading-window closure after the June quarter-end (April shows the same dip). A re-list of July is queued to confirm.
  - **moneycontrol:** decided keep (dispersion + cross-source price-target check), not a factor input.
    - 71% of stored reco dates were imputed. They now carry `reco_date_imputed = 1`: exact going forward, a date = fetch-day heuristic for history.
    - Header un-PAUSED.
    - `db._ensure_columns` now applies column migrations to quarantine mirrors too. A missing mirror column would have broken quarantine writes, the same class as the `_book_value_cr` bug.
  - **screener_schedules** scheduled quarterly (3rd + 4th of Jan/Apr/Jul/Oct, 20:30 UTC) as two resumable 5-hour windows (`--budget-min` + checkpoint).
    - It is the only source of "Intangible Assets" (goodwill_to_assets, asset_tangibility), which was 4.5 months stale.
    - A first pass is queued tonight, budgeted to stop by 02:30.
- **2026-09-28: The four DQ gaps closed** (P1 core + test-ladder rung 1).
  1. **Write contracts: gate BEFORE write.**
     - `tables.TABLES[t]["contract"]` (`max_null`, `not_all_zero`) for 14 raw tables.
     - Enforced in `db.insert_df` / `upsert_df` on every batch of ≥ 20 rows, on the columns the batch carries. A violation raises `db.ContractViolation` (run log class F) and **nothing is written**.
     - Thresholds validated against every live batch since 2025-06: they flag only the 2026-05-03 price-0 bulk_deals backfill, which would have been blocked.
  2. **Row-count band** (`checks/feeds.volume_bands`).
     - Latest rows vs the median of the previous 20 runs (`pipeline_log.rows_affected` + `run_events` `run_end`).
     - **Self-calibrated:** only steps whose own history falls below 0.6× in ≤ 5% of runs are judged, so news, corporate actions and calendars aren't.
     - Below 0.6× → WARN (T1 below 0.25× → CRITICAL); above 3× → WARN.
  3. **Gate 3** (`tools/reconcile.py`, daily inside `run.sh canary`):
     - **Prices:** NSE close vs Yahoo's unadjusted close on 20 random LARGE/MID stocks (±0.5%, PASS ≥ 90%).
     - **Fundamentals:** Tickertape vs Screener quarterly revenue on up to 200 stocks (±5%, PASS ≥ 80%; the sources define revenue differently: RELIANCE Jun-26 2.1% apart).
     - Results go to `feed_checks` (`reconcile`). A T1 FAIL → CRITICAL.
     - First run: fundamentals PASS, 85% agree. It surfaced **MMTC 156.68 vs 0.68 Cr** and **GOCL 66.65 vs 4.29**, unit or company errors in one source, to investigate.
  4. **Replay tests** (`tests/test_fixture_replay.py`). 8 scrubbed real-response fixtures in `tests/fixtures/feeds/`, refreshed with `python -m tools.canary --save-fixtures`. They run the **real** code:
     - `nse._fetch_date` with the HTTP call patched, guardrails included, plus the stock_prices contract
     - `nse_bulk._parse_deals` + contract (and the price-0 bug replayed)
     - `parse_navall`, `parse_shareholders`, the rss parser, the ETMoney portfolio URL shape, NSE JSON keys
  - Canary raw captures are now JSON, not `repr`, so future captures are replayable.
  - **Also fixed:** Screener shareholder counts now UPDATE Tickertape rows only. The first version created 6,755 NULL-% rows that would have become the "latest" shareholding row for `pledge_quality`; they were deleted, and a waiter re-cleans after tonight's in-flight harvest.
  - Tests: 295.

