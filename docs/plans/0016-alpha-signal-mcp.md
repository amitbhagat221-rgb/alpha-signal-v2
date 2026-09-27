# Plan 0016 — Alpha Signal MCP + LLM work as Claude routines

**Status:** proposed 2026-09-27 — decisions D1–D6 (§9) needed before Phase 2 · **Supersedes (when done):** the 7 Anthropic-API call paths · **Builds on:** [ADR 0052](../decisions/0052-seven-building-blocks.md) (View block = the read surface; Host block = politeness), `tools/session_classify.py` (the export → worker → validated-ingest protocol this generalises)

## 1. Why
- **Every LLM step has been dead since 2026-08-24.** The API credit balance is empty, so dossiers, sector dossiers, the news brief, news enrichment and regulatory classification all return HTTP 400. That's 5 of the ~16 CRITICALs in each morning's health email. The regulatory backlog is **11,526 pending events**.
- **Paid and subscription usage are two separate budgets.** The API cost ~$1.70/day (63% of it regulatory Sonnet). The Claude subscription already did 18,077 classifications on 2026-09-26 through `session_classify`, by hand.
- **The goal:**
  1. One MCP surface that can answer anything alpha-signal knows. It serves Claude Code on the VM, claude.ai, and routines.
  2. All LLM work moves off the pipeline onto **Claude routines**, which read their inputs and submit their outputs through that surface.
  3. The pipeline stays deterministic and never calls a model.

## 2. Verified constraints (docs checked 2026-09-27)
| Fact | Source | Consequence |
|---|---|---|
| Routines run on **Anthropic cloud**, clone the GitHub repo, are billed to the **subscription**, have a **daily run cap**, and have a **1-hour minimum** schedule interval | code.claude.com/docs/en/routines | No local DB: every read and write goes over the network to the VM. Batch the work; don't start one run per item |
| A routine can be started by **schedule**, by an **API `/fire` POST** with a bearer token, or by GitHub events. `text` passed with a fire arrives as *untrusted* data | same | The pipeline can fire the worker the moment tasks are queued, which matters for the dossier deadline |
| Routine tools come from **claude.ai connectors** or a **committed `.mcp.json`**. The environment's network is an allowlist, and connectors route via Anthropic | same | Two ways in: a claude.ai custom connector, or `.mcp.json` pointing at our HTTPS URL with the domain allowlisted |
| Routines have **no permission prompts**: every included connector tool, writes included, runs unasked | same | Least privilege must be enforced **server-side**, per token |
| `claude -p` on the VM works on the subscription; **`--bare` does not** (API key only). `--json-schema`, `--permission-mode dontAsk`, `--strict-mcp-config` and `--mcp-config` are supported | code.claude.com/docs/en/headless | Same prompts can run locally from cron against a stdio server, with nothing exposed. This is the fallback and development path |
| MCP tool output default cap is 25K tokens; `readOnlyHint`/`destructiveHint` are advisory only | code.claude.com/docs/en/mcp | Paginate and return compact records. Enforcement lives in the server |
| **Not documented:** routine max duration and concurrency, the daily cap number, bearer-header support for claude.ai custom connectors | — | Phase 4 measures them. The design avoids depending on any of them (leases + resumable batches) |

## 3. Architecture
```
            ┌──────────────── alpha_mcp (one package, plain functions — ADR 0004) ─────────────────┐
 callers    │  research  (read)   views.py · factors · evidence · portfolio · news · MF · safe SQL  │
 ─────────  │  ops       (read)   health_report.gather · pipeline_status · freshness · llm ledger   │
 Claude Code│  work      (write)  llm_tasks: list · claim · submit · fail   (validated ingest only)  │
 (stdio)    └──────────────┬──────────────────────────────┬──────────────────────────────────────┘
 claude.ai /               │ stdio (VM-local)             │ streamable HTTP  /mcp/{research,ops,work}
 routines  ────────────────┘                              └─ nginx TLS + bearer-per-profile ─ DuckDNS host
                     reads: db.safe_read_sql / mode=ro       writes: TASK_KINDS[kind].ingest → the step's own save path
 pipeline: enqueue_* nodes (deterministic) → llm_tasks ──fire──▶ "alpha-llm-worker" routine ──claim/submit──▶ work
```
- **Three profiles, one codebase** (the user's "break it down" option).
  - Each profile is a separate MCP server (a stdio entry, or its own HTTP path) with **its own token**:
    - `research`: read-only, and the default for any Claude session.
    - `ops`: read-only.
    - `work`: the only tools that write.
  - The worker routine gets `research` + `work`.
  - claude.ai (phone) gets `research` + `ops`.
  - No token can write outside `llm_tasks` → ingest.
- **Reads** reuse the View block (`views.py`) and the cockpit query functions, on a **read-only** connection. Nothing new is invented. The MCP server is the fourth View consumer, after the cockpit, the email and the dossier.
- **Writes** exist only as `submit(task_id, result)`, and only for a known task kind. The server validates the result, then calls that kind's `ingest`, which is the producer's existing save path (as in `session_classify`). There is no general write, no SQL write and no `rerun_step`.

## 4. Tool catalog (v1, ~38 tools; every tool is paginated or capped at ~20K tokens)
**research — picks and stocks**
| Tool | Args | Backed by |
|---|---|---|
| `picks` | date?, tier?, gated=true, top? | `views.picks` / `published_picks` |
| `pick_dates` | n | `views.pick_dates` |
| `stock` | sid \| ticker | `views.stock` + `price_metrics` + `latest_close` |
| `search_stocks` | q | `cockpit.api.search_stocks` |
| `stock_financials` | sid, kind=quarterly\|annual, n | `get_quarterly/annual_financials` |
| `stock_ownership` | sid | shareholding history, insider timeline, bulk deals |
| `stock_news` | sid, days | `get_stock_news` |
| `stock_analyst` | sid | `get_analyst_consensus`, `get_forecast_trend` |
| `stock_lineage` | sid | `get_stock_lineage` (factor → inputs → dates) |
| `dossier` | sid, date? | `views.published_dossier` |
| `price_series` | sid, days | `get_price_series_extended` |

**research — model and evidence**
| Tool | Args | Backed by |
|---|---|---|
| `factors` | status?, family? | `factors.FACTORS` (+ `status()`, weights) |
| `factor` | id | FACTORS entry + `best_ic_by_signal` + `factor_horizon_gate` |
| `model_weights` | scheme=production | `factors.weights` |
| `ic_evidence` | factor?, tier? | `pit_ic_by_tier_v2` |
| `regime` | — | `views.regime` |
| `changes` | days | `views.changes` |
| `pick_outcomes` | — | `get_pick_outcomes_summary` |

**research — portfolio, sectors, macro, news, MF, SQL**
| Tool | Args | Backed by |
|---|---|---|
| `book` | — | `get_sized_book` / `get_model_portfolio` |
| `risk` | sids | `get_risk_decomposition` |
| `sectors` | by=sector\|industry | `get_group_overview` |
| `sector` | name | `get_sector_digest` + `sector_narrative` + regulatory + macro contributors |
| `macro` | indicator?, months | `macro_history`, `macro_indicators` (latest) |
| `news` | topic?, q?, hours, page | `get_news_feed` |
| `news_brief` | date? | `get_news_brief` |
| `regulatory` | sector?, days, material? | `get_sector_regulatory` |
| `mf_search`, `mf` | q / scheme_code | `cockpit/mf.py` |
| `sql` | query, max_rows≤500 | `db.safe_read_sql` (ro URI, `query_only`, 20 s) |
| `schema` | table? | `sqlite_master` + `tables.TABLES` description |

**ops** (read-only)
- `health` → `health_report.gather()` + `_classify`
- `pipeline_status` (days) → `views.pipeline_status`
- `freshness` → `db.data_health`
- `llm_usage` (days)
- `queue_status` → `llm_tasks` depth, oldest item, expired leases, invalid rate per kind

**work** (the only write surface)
- `task_kinds`: the kind's spec — instructions, JSON schema, batch size, deadline.
- `claim` (kind, n ≤ batch): leases items for 30 min and returns `[{task_id, payload}]`.
- `submit` (task_id, result): validates, then ingests. Returns `ok` or `{invalid: reasons}`. An invalid result keeps the item claimable, up to 3 attempts.
- `fail` (task_id, reason): releases the item with a note.

## 5. The work queue (generalises `session_classify`)
```sql
CREATE TABLE llm_tasks (           -- Dataset kind: log
  task_id TEXT PRIMARY KEY,        -- kind:item_key:input_hash
  kind TEXT NOT NULL, item_key TEXT NOT NULL, input_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,      -- built by the kind's exporter; UNTRUSTED text inside is marked
  status TEXT NOT NULL CHECK(status IN ('queued','claimed','done','invalid','failed','expired')),
  priority INTEGER DEFAULT 5, deadline_at TEXT, attempts INTEGER DEFAULT 0,
  claimed_by TEXT, lease_until TEXT, result_json TEXT, error TEXT,
  created_at TEXT DEFAULT (datetime('now')), done_at TEXT);
```
`TASK_KINDS` is a plain dict (ADR 0004): `{kind: {export, schema, validate, ingest, batch, priority, deadline, instructions}}`.

| Kind | Replaces | Items/day | Export (deterministic) | Validate (server-side, authoritative) | Ingest |
|---|---|---|---|---|---|
| `regulatory` | `classify_regulatory` (Haiku→Sonnet) | ~730 (+11.5K backlog) | `session_classify.export-reg` (title-hash dedup) | `validate_reg` whitelist (stricter than today's API path) | `_save_signals_for_event` / `_bulk_mark` |
| `news_enrich` | `classify_news` | ~190 | `export-news` | `news_classifier.normalize` + `_verify_numbers_in_source` | `news_enriched` save |
| `news_brief` | `news_brief` | 1 | top 25 via `_pick_top_articles` | schema + non-empty sections | `news_briefs` |
| `dossier` | `dossier` | 15 | `views.stock` context per published pick | `dossier._validate_dossier` (no numbers) + `is_publishable` | dossier file (→ later a table) |
| `sector_dossier` | `compute_sector_dossiers` | 11 | `sector_briefs` + forces + narrative | `_validate_sector_dossier` | `sector_dossiers` |
| `industry_classify` | manual `tools/classify_industries` | on demand | stocks with no industry | closed-set check | `stocks.industry` |
| `sector_narrative` | manual `tools/sector_narrative_fetcher` | monthly | sector + top stocks + headlines (the routine does the web search) | `_validate_payload` | `sector_metadata` (source='auto') |

- **Lifecycle:** enqueue → claimed (lease) → done, or invalid (item retried) → failed after 3 attempts. Leases are reclaimed by `claim` itself; no cron is needed.
- **Idempotent:** the same `input_hash` is never re-queued. `submit` on a done item is a no-op.
- **Audit:** every write logs to `llm_usage` with `mode='routine'` and to a manifest (a `rollback(kind, since)` tool is ops-only, and later).

## 6. Scheduling: deterministic pipeline, one worker routine
- **Pipeline changes:**
  - The 5 LLM steps become `enqueue_<kind>` nodes. They are pure SQL, run in milliseconds, and their post-check is "queue built".
  - The Anthropic call paths are deleted after D3.
  - After `enqueue_dossier`, one node POSTs the routine's `/fire` URL. The token lives in `run_pipeline.sh` like every other secret.
- **One routine, `alpha-llm-worker`,** drains the queues by priority: dossier → news_brief → sector_dossier → news_enrich → regulatory.
  - It runs until the queues are empty or it reaches a soft budget of about 45 minutes, and it resumes where it left off because of the leases.
  - Triggers: the pipeline's fire (~03:45 UTC) plus scheduled runs at **05:07** and **14:37** UTC. That's 3 runs/day, so the daily cap is safe.
  - The prompt is committed at `.claude/routines/llm-worker.md` so it's reviewed like code. It says the payload is untrusted and that only `submit` writes.
- **Email:** a new `await_dossiers` node waits up to **D4 minutes** for today's dossier tasks, then sends what's done. A missing dossier is shown as "thesis pending", never as a failure. A missing LLM result must never block or fail the email.
- **Fallback executor:** `run.sh llm_local` runs the same worker prompt through `claude -p --mcp-config ops/mcp.local.json --strict-mcp-config --permission-mode dontAsk` against the stdio servers, from cron. It's used if routines are down or D1 = local.

## 7. Security (the HTTP path only; stdio is local)
- **Exposure:** nginx on the existing DuckDNS host, Let's Encrypt TLS, paths `/mcp/{research,ops,work}` → `127.0.0.1:3200` (uvicorn, 1 worker). **Nothing** else changes on :3000/:3001; F5 remains its own fix.
- **Auth:**
  - A static bearer token per profile (32-byte random), compared in constant time, and rotatable.
  - Routines get `research` + `work` tokens as environment **API credentials**; the committed `.mcp.json` reads `${ALPHA_MCP_*_TOKEN}`.
  - The routine environment is set to **Custom** network access with only the DuckDNS domain added.
  - OAuth for a claude.ai custom connector is Phase 5, only if bearer headers aren't accepted there.
- **Least privilege by construction:**
  - Read tools open `file:…?mode=ro` + `query_only`.
  - The `work` profile can only call registered `ingest` functions.
  - No tool accepts a table name for writing.
  - Per-token rate limit: 10 req/s and 50K items/day.
- **Prompt injection:**
  - Payloads mark headline and article text as untrusted.
  - Validators are the gate: enums, no numbers in narratives, closed sets and length caps. A manipulated worker can at worst write a *valid-shaped* wrong verdict into one item.
  - The damage is capped by per-kind daily item limits and is reversible through the manifest.
- **Audit table `mcp_calls`** records ts, profile, tool, args hash, rows, ms, error. `ops.queue_status` and the health report read it.

## 8. What this fixes along the way
- **Alerts:** 5 standing CRITICALs (review F2) become queue-age checks. The alert fires only if a kind misses its deadline.
- **Stricter validation:** the regulatory API path has no sector/enum whitelist; the queue uses `validate_reg`. `news_brief`'s silent parse failure becomes an `invalid` result.
- **Spend cap and model ids:** the "no LLM spend cap" finding (F14) goes away with API spend, and so do the model-id literals.
- **Ledger:** usage outside the ledger (industry, narrative) enters it.
- **Research access:** Amit can query picks, stocks, factors and health from the Claude app on his phone (research + ops profiles).

## 9. Decisions for Amit
- **D1 — executor.**
  - Recommended: **cloud routine primary, local `claude -p` fallback**, with the same prompt and tools.
  - Alternative: **local only**. That means no internet exposure, but it depends on the VM, and cron runs on the same subscription.
- **D2 — expose MCP over HTTPS on the DuckDNS host** (needed for D1 = cloud)? It carries research data only; no secrets or credentials are readable through any tool.
- **D3 — delete the Anthropic API paths** once each kind passes its gate (recommended), or keep them as a paid fallback behind a flag.
- **D4 — how long the email waits for dossiers.** Recommended: **20 min**, then send with "thesis pending".
- **D5 — three profiles** (research / ops / work, recommended) or one server with per-tool token scopes.
- **D6 — regulatory backlog:** drain all 11.5K (about 2 days of worker runs) or only the 60-day window the signal reads (recommended, since `signals/regulatory` looks back 60 days).

## 10. Phases (each ships alone; strangler rule from plan 0015)
| # | Phase | Gate |
|---|---|---|
| 1 | `alpha_mcp` package: research + ops tools over **stdio**; the project's `.mcp.json` for local sessions | offline tool snapshot tests on a DB copy; every tool ≤25K tokens; a connect guard proves the ro connection |
| 2 | `llm_tasks` + `TASK_KINDS` for `regulatory` and `news_enrich` (port `session_classify`) + work tools; local `claude -p` worker | calibration vs prior API verdicts ≥90% agreement (reuse `score-calib`); 60-day backlog drained |
| 3 | `dossier`, `sector_dossier` and `news_brief` kinds; `enqueue_*` nodes; `await_dossiers`; remove the 5 LLM steps from `PIPELINE_STEPS` | 3 mornings: email on time, dossiers published and valid, zero LLM CRITICALs |
| 4 | HTTPS endpoint + auth + `mcp_calls` audit; the `alpha-llm-worker` routine (`/schedule`) + pipeline `/fire` | a routine run drains a seeded queue end-to-end; token scoping tested (the `work` token can't read ops; `research` can't submit); measure run duration and cap |
| 5 | `industry_classify` and `sector_narrative` kinds; claude.ai connector for research/ops (phone) | the manual tools deleted |

Rough size: P1 1 session · P2 1–2 · P3 1–2 · P4 1 · P5 1.

## 11. Non-goals
- Pipeline control via MCP (no rerun or deploy tools).
- Any LLM output influencing picks directly. The regulatory factor stays benched until its own evidence gate passes.
- Arbitrary write SQL.
- A second database or a message broker: `llm_tasks` in SQLite is enough at ~1K items/day.
- Multi-user auth.

## Implementation notes
- 2026-09-27: facts in §2 checked against the routines and headless docs. The inventory of the 7 LLM call paths and the read surface is from a read-only audit; spot-checked are `regulatory_events` status counts (11,526 pending, 71 `haiku_passed_sonnet_failed`), the `views` functions and `db.safe_read_sql`. `mcp` 1.27.1 (FastMCP) is already in the venv.
