# HANDOFF
Updated: 2026-05-24 | Branch: master (0 unpushed before commit, 1 after) | HEAD: `80ee166` feat(pt): data model v2

## Left off
Triage of "why is ANO the #1 SMALL pick when it has no data" turned into a five-bug fix and an observability rewrite: NSE harvester now accepts SM/BE/ST/IV/RR/BZ series (+175 stocks, ANO recovered with 165 days of prices via 365d backfill), `signals/smart_money.py` no longer substitutes a default 50.0 for missing inputs, `scoring/screener.py` gates `daily_picks` at `weight_coverage ≥ 0.5 AND price_rows ≥ 60` (ANO dropped from rank #1 to #247), Gillette dossier bug ([cockpit/api.py:252](cockpit/api.py#L252)) was a string-sort of RFC-2822 dates pulling 2023 articles into 2026, and `tools/data_sanity.py` got 6 new output-quality checks plus a generic `_generic_coverage_checks()` that auto-emits a check per entry in [db.py:COVERAGE_THRESHOLDS](db.py#L723). Also ran `/graphify` on the whole repo (1,792 nodes / 2,801 edges / 196 communities, 80× per-query token reduction) and installed the post-commit hook so the graph rebuilds on every commit.

## Pick up here
1. Add BSE bhavcopy as price fallback for the 339 NSE-missing stocks (mostly InvITs + recent IPOs + BSE-only) — new `sources/bse.py` registered in [config.py:PIPELINE_STEPS](config.py#L218) after `fetch_bhavcopy`, falling back only for sids without an NSE row that date. Directly addresses the "single-source dependency" criticism.
2. Add yfinance as last-resort price fallback — new `sources/yfinance_prices.py` running after BSE for anything still missing. Skip stocks already covered to keep API calls minimal.
3. Run the NaN-rate audit pass — same shape as today's smart_money sweep, but across all signal tables. Probe `piotroski_scores`, `accruals_scores`, `consensus_signals`, `promoter_signals`, `forensic_scores` for hardcoded-default leakage. The Explore-agent audit earlier flagged `signals/regulatory.py:186` (fixed today) but didn't sweep score-output tables themselves.

## Watch out
- **MCP server registered but only active on next CC restart.** `graphify` server was added to `~/.claude.json` for this project after the session was already running. Tools `query_graph`/`get_node`/`get_neighbors`/`get_community`/`god_nodes`/`graph_stats`/`shortest_path` will appear in a fresh session, not this one. Confirm with `/mcp` after restart.
- **`daily_picks` row count dropped from 2,448 to 2,020** after the pick gate took effect. 428 stocks excluded today (108 below 50% weight coverage, 425 below 60d prices — overlap = 105). If any downstream consumer assumed every universe sid has a row, it'll now silently get nothing for ineligible sids. Spot-checked `output/email_sender.py` + `cockpit/api.py` — both use rank ordering not full-universe assumption, so safe.
- **`regulatory_events` was registered as monthly cadence (50d threshold)** and went silently dark for 43 days. Threshold now 14d ([db.py:STALENESS_OVERRIDES](db.py#L715)). The harvester itself is *not* in `PIPELINE_STEPS` so cron won't auto-rerun it — added to "Pick up here" backlog material, not today's session.
- **Sector taxonomy mismatch.** `regulatory_signals.sector` carries "Financial Services" (1,093 rows) and "IT" (545 rows) but `stocks.sector` uses "Financials" / "Information Technology". Cockpit query now maps aliases, but signals/regulatory.py + the classifier still emit the old taxonomy. New sanity check `REGULATORY_SECTOR_TAXONOMY_MISMATCH` will keep alerting until fixed at source.
- **`graphify-out/` is now gitignored** but the post-commit hook regenerates it locally on every commit. Don't be surprised by it reappearing.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Track 3 Phase 3.1b (NSE F&O OI ingest) is still the named active phase, but today was an unscheduled stop on a P0 data-integrity drive-by (ANO=#1 SMALL with no data + the watchdog being inadequate to catch it). Resume 3.1b after price-fallbacks land.
