# Alpha Signal v2 — AI Context

**AI-Native Daily Stock Intelligence for Indian Retail Investors**
Owner: Amit Bhagat | Bengaluru | Oracle Cloud Ubuntu VM
Version 2.0 | Started April 2026

This file is short on purpose. It contains only what an AI assistant needs to start being useful immediately. For everything else, see the pointers at the bottom.

---

## Session Protocol — Read at Start

**Before any work**, in this order:
1. Read `HANDOFF.md` for current state — where I am, what's in flight, next actions
2. Read this file (CLAUDE.md) for project rules
3. Read the active plan in `docs/plans/` if HANDOFF.md references one
4. Read relevant ADRs in `docs/decisions/` for any architectural area being touched

Use `/catchup` slash command to do all of this in one step.

**At session end**, run `/handoff` to:
- Overwrite HANDOFF.md with current state
- File any ADRs for decisions made today
- Update plan status if it changed
- Commit with a descriptive message

Skipping `/handoff` is the single biggest source of context loss. Don't skip it.

---

## Critical Rules — Read Before Every Task

**Environment**
- Always activate venv first: `source ~/alpha-signal/venv/bin/activate` (shared with v1)
- v1 is still LIVE on cron — never touch `~/alpha-signal/` files. All v2 work happens in `~/alpha-signal-v2/`
- Credentials live in v1's `run_pipeline.sh` as export statements — never in code

**Architecture & Code**
- No frameworks, no base classes, no YAML. Plain functions, Python config dict, SQLite. See `decisions/0004-no-base-classes-no-yaml.md`
- ETFs are excluded — universe is 2,448 stocks, not 2,500
- `cap_tier` must be assigned before any ranking — never rank without knowing segment
- Never rank across tiers — always within-segment ranking
- Financial sector stocks route through the financial sub-model — never through main screener value/quality signals
- Tickertape SIDs ≠ NSE tickers (e.g. REDY not DRRD). Always use universe SIDs

**Data Operations**
- Never run two harvester scripts simultaneously — doubles request rate, risks IP block
- 2-second delay minimum between external API calls
- Smoke test with 3 stocks before any full run
- `INSERT OR IGNORE` for append-only tables (insider_trades, bulk_deals, news_articles)
- `INSERT OR REPLACE` for snapshot tables (analyst_consensus, regime_state, signal tables)
- NSE PIT API: `buyQuantity`/`sellquantity` are always 0 — real values in `secAcq` and `secVal`
- NSE bulk deals: today's file only — no historical archive. Must accumulate daily
- Regulatory classifier state lives in `regulatory_events.classifier_status`, not "no row in regulatory_signals". Six terminal states. Verify with `python -m sources.verify_classifier_trace`
- PIB scraper saves only at the END of all 110K iterations. Crash mid-run loses everything. Add incremental save before next run

---

## Decision & Documentation Protocol

When working, the following triggers a doc update — these are not optional:

| Trigger | Action |
|---------|--------|
| Non-obvious technical choice | Propose an ADR before implementing. Don't bury the decision in code. |
| Small choice diverges from active plan | Add to that plan's "Implementation notes" section |
| Pivot or scrap mid-implementation | Run salvage protocol: keep / scrap / redo. Don't patch silently. |
| Recurring bug or landmine discovered | Add a one-line rule to the Critical Rules section above. Every mistake becomes a rule. |
| Plan reaches "Done when" criteria | Update status to Implemented; reflect changes in `architecture.md` / `reference/`; archive within 30 days |
| Something user-visible ships | Append entry to CHANGELOG.md |

**Documentation rules in short** (full version in `docs/runbooks/documentation-rules.md`):
- Project root has exactly **4 files**: README.md, CLAUDE.md, HANDOFF.md, CHANGELOG.md. No floaters.
- Every other doc goes into one of: `docs/decisions/`, `docs/runbooks/`, `docs/reference/`, `docs/plans/`, `docs/_archive/`
- ADRs are write-once. Never edit; supersede with new ADR if needed.
- If you don't know where a doc goes, ask: would I open this file again in 3 months? If no, skip it. If yes, force a category.

---

## Where everything lives

| You need to know... | Read |
|---------------------|------|
| Where I am right now, what's next | `HANDOFF.md` |
| Project intro, how to run | `README.md` |
| What changed recently | `CHANGELOG.md` |
| Map of all docs | `docs/README.md` |
| How the system fits together | `docs/architecture.md` |
| Schema, signals, sources in detail | `docs/reference/` |
| How to do X | `docs/runbooks/` |
| Why we chose X | `docs/decisions/` |
| What's planned next | `docs/plans/` |

---

## Data Source Guardrails (frequent gotchas)

These show up often enough they belong in this file. Anything more detailed lives in `docs/reference/data-sources.md`.

**Tickertape**
- Returns curated subset, not raw filings. No COGS, SGA, inventory, goodwill.
- `operating_profit` is 100% NULL. Use `pbt` or derived `ebitda` instead.
- EBITDA derivation: `pbt + interest + (annual_depreciation / 4)`

**NSE**
- Bhavcopy columns have leading spaces. Always `.str.strip()`
- Bhavcopy format changed Apr 3, 2026 (simplified). Fetch raw from archives.
- PIT API: `secAcq`/`secVal` are the real values, not `buyQuantity`/`sellquantity`
- Bulk deals: today-only CSV. No historical API.
- RBI site needs 2s delay between requests or it blocks

**data.gov.in**
- API sometimes times out. Use 60s timeout + 3 retries.
- Core Sector data: use `ITEM_CODE` (e.g. `INDEX_COAL`) not `ITEM_NAME` (e.g. "Growth of Coal (%)")
- Wide format (months as columns). Needs pivot to long format.

**Google News RSS**
- `after:YYYY-MM-DD before:YYYY-MM-DD` date filters work for 3+ years back
- Returns up to 100 items per query. Free, no API key. 1 req/sec safe.

**General**
- Shareholding has sentinel dates `1899-12-31` — filter out
- Insider archive from v1 had 96.5% duplicates. UNIQUE constraint prevents in v2.

---

## Validated Signal Map (from v1 C13b — 36 monthly periods)

| Signal | LARGE | MID | SMALL |
|--------|-------|-----|-------|
| Consensus | t=3.52 | t=2.20 | t=2.44 |
| CF Accruals | t=0.20 | t=3.20 | t=2.10 |
| Promoter QoQ | t=0.04 | t=0.83 | t=3.20 |
| Earnings Yield | t=1.57 | t=1.01 | t=3.13 |
| Piotroski | t=0.51 | t=2.23 | t=2.81 |
| Book-to-Price | t=0.79 | t=2.33 | t=2.54 |

Weight tiers: `t≥2.5 → 1.0x` | `t=1.5-2.5 → 0.5x` | `t=0.5-1.5 → 0.2x` | `t<0.5 → 0x`

New signals pending backtesting: Insider (2yr reconstructed), Regulatory (3yr events), Macro sector (3yr indicators).

---

## Most-used commands

```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal-v2

# Database health
python db.py
python validate.py
python -c "from db import data_health; print(data_health().to_string())"
python -c "from db import table_counts; table_counts()"

# Pipeline
python pipeline.py --dry-run
python pipeline.py --status
python pipeline.py --step signal_piotroski

# Signals (smoke test individually)
python -m signals.piotroski --dry-run
python -m signals.insider_signal --dry-run
python -m signals.regulatory --dry-run

# Scoring
python -m scoring.screener --dry-run --top 10
python -m scoring.quality_gate
python -m scoring.regime --dry-run

# Data fetchers
python -m sources.macro_yfinance --days 7
python -m sources.nse_insider --months 1
python -m sources.nse_bulk
python -m sources.macro_gov

# SQL explorer
jupyter notebook notebooks/00_sql_explorer.ipynb
```

---

## Current state

For "where am I right now" → `HANDOFF.md` (always current, overwritten each session).
For "what shipped recently" → `CHANGELOG.md`.
For "what's planned" → `docs/plans/`.

Keep this file under 200 lines. If it grows, push detail down into `docs/`.