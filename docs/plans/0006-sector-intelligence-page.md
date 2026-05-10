---
Status: proposed
Created: 2026-05-10
Owner: Amit Bhagat
Implementation: not started — proposed UX/data plan for /sectors deep-dive
Related: 0005-100-factors-and-model.md, ADR 0009-factor-track-parallel-to-d-track.md
---

# 0006 — Sector Intelligence Page (deep-dive)

## What problem are we solving?

Today `/sectors` is a flat grid: one card per sector with macro signal direction (TAILWIND/HEADWIND), avg score, macro score, and a 120-char truncated detail string. That's a "weather report" — fine at a glance, useless for forming a thesis. The real questions you ask about a sector aren't there:

- Which factors are firing inside this sector? Where's the alpha actually coming from?
- What's the breadth of strength — is the avg score driven by 2 outliers or by 30 names?
- What macro indicators (RBI rates, sector index, regulatory events) actually move the macro score, and which way are they trending?
- Who are the top 5 picks inside this sector right now? And the bottom 5 (avoid list)?
- How does today's sector ranking compare to a month ago / six months ago?
- Which signals have a *sector-specific* edge (e.g. consensus drives tech but not utilities)?

A serious sector page answers each of these in one screen, drillable per sector.

## Sketch of the redesign

Three tabs, same visual language as the rest of the cockpit (in-page tabs, URL-hash sync):

### Tab 1 — Heatmap (default; today's view, polished)
Same flat grid but each card adds:
- Breadth bar: % of stocks in the sector with `final_score ≥ 0.55` (visualises whether the avg is concentrated or broad)
- Top 3 tickers in the sector by composite score, inline as tickers
- Sparkline of sector avg score over last 30 days (small canvas)
- Click anywhere on the card → drills into Tab 2 with that sector pre-selected

### Tab 2 — Per-Sector (the deep dive)
Sector dropdown at top. Five sub-cards below:

1. **Snapshot card** — current macro signal, avg score, breadth, % stocks with regulatory tailwind, % with headwind. Shown as a compact metric grid.
2. **Factor heatmap** — table of every factor × this sector. Three columns: factor name, sector-specific |t| (when available — needs a per-sector backtest extension; for now, sector mean of the factor's score), in-model badge. Sorted by sector-specific |t| descending. Tells you "which factors are working in this sector right now."
3. **Picks list** — top 10 stocks in the sector by composite score, with mini-thesis line. Bottom 5 below (avoid candidates with low score and red flags).
4. **Macro contributors** — list of `macro_indicator → indicator_score → sector_weight` for indicators that feed this sector's macro_score. Pulled from `macro_sector_map` joined with `macro_indicators`. Lets you see what's *driving* the macro signal, not just the headline.
5. **Recent regulatory events** — last 10 `regulatory_events` rows for stocks in this sector with `classifier_status = 'CLASSIFIED'`, with their tailwind/headwind class. Sorted by date.

### Tab 3 — Trend (historical sector performance)
- Chart: sector avg-score time series, all sectors stacked or selected via radio
- Table: month-over-month rank change (which sectors are climbing / falling)
- Sector rotation matrix: 3-month vs 12-month returns, with this month's pick highlighted
- Fed by `daily_picks` aggregated to sector × date, plus `nse_index_history` for sector benchmark indices where available

## Data needed (vs what we already have)

| Need | Have? |
|---|---|
| Stock-level scores per sector today | ✓ `daily_picks` + `stocks.sector` |
| Sector breadth (% of stocks above score threshold) | ✓ derive from `daily_picks` per snapshot |
| Sector avg score time series | ✓ derive from `daily_picks.snapshot_date` |
| Per-sector factor IC | partial — `pit_ic_by_tier_v2` tiers by `cap_tier`, not sector. Two options: (a) re-run `tools/backtest_pit.py` with a sector dimension; (b) for v1 of this page just show sector mean of each factor's score, no IC. |
| Macro indicator → sector contribution | ✓ `macro_sector_map` + `macro_indicators` already wired |
| Regulatory events per sector | ✓ `regulatory_events` (filter by classifier_status, join via stocks.sector) |
| 30-day sector avg sparkline | ✓ `daily_picks` 30-day window |
| Sector benchmark index returns | partial — `nse_index_history` has sector indices; mapping sector name → NSE index name needs a small lookup table (~11 rows) |

The key gap: per-sector factor IC. v1 of the page can ship without this; v2 adds a sector × factor dimension to `pit_ic_by_tier_v2` (about 30 min of work in `tools/backtest_pit.py` to add a `sector` group-by alongside `cap_tier`).

## What this unlocks

- A real "is this sector worth being in" answer that goes beyond a coloured tag
- A per-sector factor inspector — find which signals are actually working in IT vs Materials vs Banks, which is one of the headline planned outputs of plan-0005 Phase D (factor-model sector overlays)
- A macro narrative builder — see which RBI / commodity / index moves are propagating into the sector signal, instead of treating the macro score as a black-box number
- A sector-rotation hypothesis tester via the Trend tab: did the model rotate into Materials when commodities turned, or did it follow into Tech instead?

## Implementation order (when picked up)

1. **API additions to `cockpit/api.py`**: `get_sector_overview_v2()` returning the richer card payload (add breadth, top-3 tickers, 30-day score history per sector). Backwards-compatible alias keeps the current view working.
2. **Tab 1 polish** — extend `cockpit/templates/sectors.html` cards with breadth bar + sparkline + top-3 inline. ~1 hr.
3. **Tab 2 (Per-Sector)** — new template fragment + new API helper `get_sector_detail(sector_name)`. ~3 hrs the first time; subsequent sectors are free since it's data-driven.
4. **Tab 3 (Trend)** — sector × date pivot from `daily_picks`. Chart.js multi-line. ~2 hrs.
5. **(Optional v2)** — extend `tools/backtest_pit.py` with a `sector` group-by, populate `pit_ic_by_tier_v2.sector`, surface per-sector factor IC in Tab 2's factor heatmap. ~30 min compute + ~1 hr template work.

## Out of scope (for v1)

- Per-sector portfolio construction (different problem; F3 / D17 territory)
- Sector beta neutralisation
- Inter-sector correlation matrix (nice to have; can add to Trend tab later)

## Open question

Tab 2's "Factor heatmap" is the most interesting cell of this page. Without per-sector IC the table is descriptive (sector means of factor scores), not prescriptive (does this factor predict in this sector). Decision needed: ship v1 descriptive and add IC in v2, or block v1 on the IC extension. **My take:** ship v1 descriptive — most of the page's value is in the Picks + Macro Contributors + Regulatory Events panels, which don't need IC. Add per-sector IC as v2 once it's clear the page is being used.
