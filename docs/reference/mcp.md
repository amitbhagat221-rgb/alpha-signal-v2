# Alpha Signal MCP

Plan: [0016](../plans/0016-alpha-signal-mcp.md). Code: [alpha_mcp/](../../alpha_mcp/). Three stdio MCP servers over one codebase. Two of them are read-only; the third, `alpha-work`, is the LLM work queue and the only one that writes.

## Servers and profiles

| Server | Module | Writes? | Registered in | Used by |
|---|---|---|---|---|
| `alpha-research` | `alpha_mcp.research` | never | `.mcp.json`, `ops/mcp.local.json` | every Claude Code session in this repo; the worker (for context) |
| `alpha-ops` | `alpha_mcp.ops` | never | `.mcp.json`, `ops/mcp.local.json` | every session; the worker |
| `alpha-work` | `alpha_mcp.work` | only via `submit` | `ops/mcp.local.json` only | the local LLM worker |

- **Read-only by construction.** `_core.install_readonly()` runs before `views` or `cockpit` is imported. It replaces `db.get_db` (and every module-level copy of it) with a `mode=ro` + `PRAGMA query_only` connection, and points `runlog` at a read-only connection. It also points `COCKPIT_CACHE_DIR` at a temp dir, so the production cockpit's pickles are never touched. [tests/test_alpha_mcp_readonly.py](../../tests/test_alpha_mcp_readonly.py) proves that INSERT, UPDATE, DELETE and DDL all raise.
- **Audit.** Every tool call writes one `mcp_calls` row (ts, profile, role, tool, args hash, rows, ms, error). The row goes through a separate connection whose SQLite authorizer allows INSERT INTO `mcp_calls` and nothing else. The write waits at most 1 s for a lock and never fails the call.
- **Role.** Set `ALPHA_MCP_ROLE` per registration: `claude-code` for interactive sessions, `llm-worker` for the worker. It is stamped on `mcp_calls.role` and `llm_tasks.claimed_by`.
- **No network exposure.** Plan decision D1/D2 (2026-09-30): stdio only; no HTTPS and no cloud routine.

## Output contract
- Compact JSON on the wire. NaN becomes null, dates are ISO strings, and floats keep 6 significant digits.
- Every result has an `as_of` field: the date the data describes.
- List tools page with `limit`/`offset`, or `page` for news, and return `total` and `next_offset`.
- Each result is capped at about 20K tokens. `_core.cap` halves the longest list until the result fits and adds `truncated: {lists_cut, hint}`.
- An unknown sid, ticker, factor, sector or scheme is an error that suggests near matches, never an empty success.

## Tools

**alpha-research.** `stock` arguments accept a sid (`RELI`) or an NSE ticker (`RELIANCE`).

| Tool | Args | Returns |
|---|---|---|
| `picks` | date?, tier?, gated=true, top=10 | ranked picks per tier (rank, final/base score, forensic adj, UHS, mcap Cr, P/E, P/B, ROE) |
| `pick_dates` | n | newest pick dates + ranked count |
| `pick_breakdown` | stock, date? | exact per-factor decomposition of the score (value, tier percentile, weight, contribution, share), rebuilt from `pit_replay_snapshots`; `reproduces_stored_score` |
| `stock` | stock | identity, fundamentals, newest pick row + UHS, display signals, close + returns/52w/RSI, has_dossier |
| `search_stocks` | q | ≤20 matches (sid, ticker, name, sector, tier) |
| `stock_financials` | stock, kind=quarterly\|annual | 10 quarters + TTM/YoY, or 5 years BS/CF + ratios |
| `stock_ownership` | stock | 6 quarters shareholding (+QoQ), 24 months insider by month, 10 bulk deals |
| `stock_news` | stock, days=30, limit=20 | tagged articles + enrichment one-liner/sentiment |
| `stock_analyst` | stock | consensus PT/ratings + EPS/revenue revision history |
| `stock_lineage` | stock, factor? | factors with lineage; with a factor, its declared inputs and emitted source rows |
| `dossier` | stock, date? | published, validated dossier (current = ≤3 days old) |
| `price_series` | stock, days=90 | OHLCV + delivery %, oldest first (≤400) |
| `factors` | status?, family? | registry: id, family, status, weights per tier, best t per tier |
| `factor` | id | definition, eligibility, IC evidence per tier, horizon/cost gate |
| `model_weights` | scheme | weights per tier + registry ids |
| `ic_evidence` | factor?, tier?, limit, offset | best IC row per (factor, tier), sorted by \|t\| |
| `regime` | — | VIX regime + tier allocation |
| `changes` | days, limit, offset | daily_changes, HIGH first |
| `pick_outcomes` | — | realised forward/excess returns + hit rates per tier × horizon |
| `book` | — | advisory HRP-sized book + concentration |
| `risk` | stocks[] | style tilts, sector HHI, tier mix |
| `sectors` | by=sector\|industry | rollup of today's ranking |
| `sector` | name | brief + narrative + material regulatory + macro contributors |
| `macro` | indicator?, months | latest readings, or one indicator's history |
| `news` | topic?, q?, hours, page, page_size | ranked enriched news |
| `news_brief` | date? | the daily brief |
| `regulatory` | sector?, days, material, limit, offset | classified regulatory events × sector impact |
| `mf_search`, `mf` | q / scheme_code | fund search; fund detail |
| `sql` | query, max_rows≤500 | one read-only SELECT (`db.safe_read_sql`, 20 s) |
| `schema` | table? | tables + registry description, or one table's columns |

**alpha-ops:** `health` (the daily email's verdicts, cached 5 min) · `pipeline_status` · `freshness` · `llm_usage` · `queue_status` · `feed_incident` (the `runlog.bundle` for one feed).

**alpha-work:** `task_kinds` · `claim(kind, n?)` · `submit(results=[{task_id, result}])` · `fail(task_id, reason)`.

## The work queue

`llm_tasks` holds one row per unit of LLM work, with `task_id = kind:item_key:input_hash`.

- **Lifecycle:** queued → claimed (30-min lease; `claim` reclaims expired leases itself) → done, or invalid (claimable again) → failed after 3 attempts.
- **What `submit` checks:** the lease must be live and held by this role. The kind's `validate` then checks the result on the server. The kind's `ingest` writes it through the producer's own save path and records `undo_json`.
- **Payloads:** keys starting with `_` never leave the server. Third-party text is wrapped as `{"untrusted_text": ...}`.

```
python -m alpha_mcp.tasks enqueue regulatory [--days N]    # default: full backlog (D6)
python -m alpha_mcp.tasks enqueue news_enrich [--days 7]
python -m alpha_mcp.tasks status
python -m alpha_mcp.tasks rollback <kind> --since <ISO UTC>  # undo ingests newest-first → failed
python -m alpha_mcp.tasks retry <kind>                      # failed → queued
```

| Kind | Replaces | Validate | Ingest |
|---|---|---|---|
| `regulatory` | `classify_regulatory` (Haiku → Sonnet) | `session_classify.validate_reg` (sector/enum whitelist) | `_save_signals_for_event` + `_mark_classified`, or `_bulk_mark('haiku_rejected')`; duplicate headlines copy through `_reuse_classification_existing` |
| `news_enrich` | `classify_news` | non-empty fields + enums, then `news_classifier.normalize` (drops numbers not in the source) | column-level upsert into `news_enriched` (keeps `image_url`) |

**Adding a kind** takes one `TASK_KINDS` entry in [alpha_mcp/tasks.py](../../alpha_mcp/tasks.py): `export(days)` → `[(item_key, payload, priority)]`, `validate(result, payload)` → a clean dict or `ValueError`, `ingest(clean, payload)` → an undo record (it may write any row: a document, a hypothesis, a producer table), `undo(record)`, `schema`, `instructions`, `batch`, `ledger_step`. Add it to `DRAIN_ORDER` and write a test in `tests/test_alpha_mcp_tasks.py`.

**Adding a research tool:** one `@tool()` function in `research.py` that calls a `views.py` / cockpit / registry function (never a table name; if the function you need doesn't exist yet, it belongs in `views.py`).

## Running the local worker
```
ops/llm_worker_local.sh [MAX_BATCHES]                  # default 40 submits, 45-min timeout, model sonnet
ALPHA_DB=/path/to/copy.db ops/llm_worker_local.sh 5    # against a DB copy (calibration)
```
- **What it runs:** `claude -p` with the prompt in [.claude/routines/llm-worker.md](../../.claude/routines/llm-worker.md), `--mcp-config ops/mcp.local.json --strict-mcp-config --tools "" --permission-mode dontAsk`, allowing only `mcp__alpha-work__*` and `mcp__alpha-research__*`. There are no built-in tools, so no shell or file access. It is not `--bare`, which needs an API key.
- **Where it logs:** `output/llm_worker.log`.
- **Exit codes:** non-zero if claude fails, the run reports an error, or items were claimable and none got done.
- **Not yet scheduled.** Phase 3 adds a `run.sh` case, `llm_local) logged llm_local ops/llm_worker_local.sh ;;`, plus cron after the morning run and at 05:07/14:37 UTC.
- **Measured throughput** (calibration, 2026-09-30): 120 items in 129 s over 16 turns; 300 items in about 5 min (Sonnet, 0 invalid results).
