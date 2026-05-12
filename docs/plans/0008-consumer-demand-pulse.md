---
Status: proposed
Created: 2026-05-12
Last updated: 2026-05-12
Owner: Amit Bhagat
Implementation: not started — research-first signal, validation gates production port
Related: 0005-100-factors-and-model.md (factor library), 0007-market-share-momentum-factor.md (sector-relative pattern)
Supersedes: v1's `scripts/12_google_trends.py` (38 hand-picked keywords, no consumer, last output was 1-byte empty CSV)
---

# 0008 — Consumer Demand Pulse Signal

## Overview

v1 had a Google Trends script that queried 15 brand keywords weekly, generated "search spike/drop" labels, and **wrote them to a file nothing consumed**. The output file has been 1 byte (empty) for at least a week — pytrends has been rate-limited and the cron failed silently. We're disabling that cron and treating this as a fresh research question:

> Does week-over-week change in consumer search interest for a brand predict next-quarter revenue surprise (or 60-day forward stock return) for that brand's listed parent?

If yes → port as a real v2 signal. If no → close this plan and don't touch search-interest data again.

## Why now

- v1 cron just got disabled (2026-05-12); zero search-pulse data flowing today
- F-track (plan 0005) needs more cross-sectional signals that aren't already in BACKTEST_SIGNALS
- Consumer-discretionary, FMCG, auto, and quick-commerce names are 26% of the universe — if search-interest leads revenue for these, it's a real edge
- We just shipped LLM-curated `competitive_landscape` per industry (ADR 0014) — gives us a mapping from "brand the consumer types into Google" → listed sid, with `share_pct` weights. That eliminates v1's hand-curated `BRAND_MAP` of 38 entries

## Validation gate (must clear before any production work)

A backtest answers a single question:

> For the universe of stocks with a mapped consumer-facing brand, does the previous 4-week search-interest Δ (versus 12-week mean) have predictive power on the next 60-day excess return?

**Threshold to promote to production:**
- `|t-stat| ≥ 1.5` on at least one cap tier (large / mid / small) over a 24-month rolling window
- Coverage `≥ 60 stocks` (otherwise it's not a portfolio signal, just curiosity)
- Decay rate sensible (signal half-life > 3 weeks; not just one-week noise)

**Backtest setup:**
- Brand → sid map sourced from `sector_metadata.competitive_landscape.players[*].ticker` (where ticker is non-null). Filter to consumer-facing industries: FMCG, Automobiles, E-Commerce, Retail, Hospitality, Consumer Durables, Aviation, Pharma (retail brands only)
- Search-interest history: try free tier first (pytrends with 2026-grade rate-limit + cookie tricks); fall back to paid if free can't sustain weekly pulls for the validation period
- Forward return: 60-day excess return vs sid's cap-tier benchmark (`stock_prices` already daily, so this is cheap)
- 24 months of historical weekly observations × ~250 brands = ~26K (brand, week) rows — small data, fast iteration

## If validation passes — design

`signals/consumer_demand.py` following the established F-track template:

- **Source data**: a new `consumer_search_interest` table — `(brand_keyword, sid, week_end_date, interest_0_100, interest_4w_avg, interest_12w_avg)`. Populated by a fetcher `sources/search_interest.py`.
- **Score formula**: `(interest_4w_avg - interest_12w_avg) / interest_12w_avg` → percentile rank within cap-tier × sector
- **PIT helper**: `pit_consumer_demand(sid, eval_date)` reads only `week_end_date <= eval_date - 7d` rows (1-week filing lag to model real-world data availability)
- **Score table**: `consumer_demand_scores (sid, snapshot_date, score, raw_change_pct)` — INSERT OR REPLACE on (sid, snapshot_date)
- **Weighting**: starts at the F-track default tier weight (`t≥2.5 → 1.0x`, etc per CLAUDE.md)
- **Cockpit surfacing**: factor card on stock_detail (same template as ROIC/FCF Yield); rolls into Quality composite OR a new "Demand" composite if it doesn't fit

## Phases

| Phase | What | Cost |
|---|---|---|
| **R1** | Brand→sid map from `sector_metadata.competitive_landscape` for consumer industries; deduplicate; cap at 300 sids | 1 hr |
| **R2** | Pull 24-month weekly search-interest history for the mapped brand keywords (free tier first) | 4-6 hr (mostly rate-limit waiting) |
| **R3** | Backtest reconstruction — extend `tools/reconstruct_pit.py` if needed; compute t-stats per cap tier; decay analysis | 2 hr |
| **GATE** | Review with t-stat results. If ≥ 1.5 on any tier → proceed to production. Else archive plan. | — |
| **P1** | If passed: write `sources/search_interest.py` (weekly cron job), `signals/consumer_demand.py`, `pit_consumer_demand` helper | 3 hr |
| **P2** | Cockpit factor card, add to `BACKTEST_SIGNALS`, wire into screener if t≥1.5 promotes per CLAUDE.md weight tiers | 2 hr |

**Total IF validation passes:** ~12-15 hours. IF validation fails: ~7 hours sunk into research, plan archived, lesson noted.

## Done when

**Research phase done when:** backtest t-stats per cap-tier are written to `pit_ic_by_tier_v2` (signal name `consumer_demand`) and a `docs/decisions/` ADR records the verdict — either "promoted to production" or "validated null, archived."

**Production phase done when (if applicable):**
- `consumer_search_interest` table has ≥ 6 months of history for ≥ 200 sids
- `consumer_demand_scores.snapshot_date >= today - 7d`
- Factor appears in `get_factor_health()` with `pit_ready=True`, `coverage_pct ≥ 60`, status READY
- Weekly cron entry added to `run_pipeline.sh` (or separate `run_weekly_pulse.sh`)
- CHANGELOG entry for the day it ships

## Risks & open questions

1. **Rate limits will likely block free-tier pytrends** beyond ~50 keywords/day. Research may need to use a paid proxy (Bright Data, ScraperAPI) or a paid alternative (Glimpse, Exploding Topics). Set a ₹2K budget cap for R2; if blocked, escalate before continuing.
2. **Brand→sid mapping is messy**: "Tata Motors" can mean the listed sid or 4 different subsidiaries; "Reliance" is too broad to map cleanly (per ADR 0014 we explicitly don't fuzzy-match). Solve by using the `competitive_landscape.players[*].ticker` field (which is already strict-matched), not free-text brand search.
3. **Seasonality contamination** — Diwali → "ITC", monsoon → "Asian Paints". Backtest must include same-period prior-year comparison, not just rolling mean.
4. **Sector signal vs stock signal** — "Maggi noodles" search Δ probably tells you more about packaged-food *demand* than Nestle's *stock*. May validate better as a sector-level macro signal (rolled into `macro_sector_signals`) than a stock signal. Design phase chooses based on validation t-stats by aggregation level.
5. **Don't be fooled by p-hacking**: backtest one hypothesis (specified above), one universe (consumer-industry sids with mapped brand), one forward window (60d excess return). No "try every combo of brand/window/sector and pick the best." Record the chosen design before running the backtest. Discipline note from CLAUDE.md backtest hygiene.

## Don't

- **Don't port v1's `12_google_trends.py` mechanically.** The 38-keyword BRAND_MAP, the 15-per-run cap, and the `change_pct > 30 → BUY` threshold are unvalidated artifacts. Treat this as a from-scratch design.
- **Don't add a Trends factor to `BACKTEST_SIGNALS` before validation.** Per the project rule, factors with `t < 1.5` stay in the library, not the model.
- **Don't pay for a data source before R1 maps fewer than 200 sids successfully.** If we can't cleanly map brand → sid for 200+ names, the signal universe is too small for any data spend to pay back.
