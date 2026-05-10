---
Status: proposed
Created: 2026-05-10
Last updated: 2026-05-10 (rewrite v2 — adopts IIM Ahmedabad sector-narrative template)
Owner: Amit Bhagat
Implementation: not started — proposed UX/data plan for /sectors deep-dive
Related: 0005-100-factors-and-model.md, ADR 0009-factor-track-parallel-to-d-track.md
Source: docs/_archive/Sector Narratives.pdf (IIM Ahmedabad Consult Club Casebook 2020-21)
---

# 0006 — Sector Intelligence Page (deep-dive)

## What problem are we solving?

Today `/sectors` is a flat grid: one card per sector with macro signal direction (TAILWIND/HEADWIND), avg score, macro score, and a 120-char truncated detail string. That's a "weather report" — fine at a glance, useless for forming a thesis.

The IIM Ahmedabad casebook does this better. Their per-sector page packs five tightly-structured blocks into a single screen:

1. **Value chain** — 5-stage horizontal flow showing how the sector creates value (e.g. for Pharma: R&D → Testing → Approval → Distribution → Marketing)
2. **Key Drivers** — what moves revenue, what moves cost, what enables growth
3. **Segments & KPIs** — how the sector is structurally split, with the right metric to judge each segment
4. **Top Players** — who's actually competing
5. **Market Trends** — narrative bullets on industry size, consolidation, regulatory shifts, secular trends

Anyone reading one IIM sector page in 90 seconds understands the sector deeply enough to ask informed questions. **That's the bar for our `/sectors` page.**

What we add on top of the IIM template — and the reason this isn't just a wikipedia rip — is **our model's view of the sector**: which factors are working *here right now*, the picks our system is making within the sector, and the macro contributors driving today's tailwind/headwind.

## Tab structure

Three tabs, same visual language as the rest of the cockpit (in-page tabs, URL-hash sync):

### Tab 1 — Heatmap (default; today's view, polished)
Same flat grid. Each card adds:
- **Breadth bar**: % of stocks in the sector with `final_score ≥ 0.55` (avg vs concentration)
- **Top 3 tickers** in the sector by composite score, inline
- **Sparkline** of sector avg score over last 30 days (small canvas)
- Click anywhere → drills into Tab 2 with that sector pre-selected

### Tab 2 — Per-Sector (the deep dive)
Sector dropdown at top. Below it, six sub-cards arranged like an IIM page plus our overlay:

**(A) Value Chain** — 5-step horizontal flow with arrows. Each step has a title + 3-5 bullet sub-activities. Identical layout to IIM (it's a known-good template). Static metadata, sourced from the IIM PDF + light editing.

**(B) Key Drivers** — 3-column table:
| Revenue Drivers | Cost Drivers | Growth Drivers |
|---|---|---|
| Loan Book (AUM) | Cost of borrowing | Digital Innovation |
| Interest Yield | Operating Expenses | Macroeconomic / credit policies |
| Branch / Geographic Expansion | Provisions and write-offs | Capitalization / Mergers of PSBs |

Sourced once from the IIM PDF + editing. Per-sector static metadata.

**(C) Segments & KPIs** — table showing how the sector is split + the canonical metric for each split. E.g. Banking: Public Sector Banks / Private & Foreign Banks / Cooperative & Rural Banks; KPIs: NIM, CASA, GNPA/NNPA.

**(D) Top Players** — derived from our `stocks` table (filter by sector, sort by market cap desc). Columns: Ticker · Name · Market Cap · Latest composite score · Sector market-share %. Top 8 by default. Click a row → goes to `/explorer/{sid}`.

**(E) Market Trends** — 4-6 narrative bullets covering industry size, growth, consolidation, regulatory shifts, secular trends. Initial seeding from IIM PDF (2020 vintage); refreshed periodically by:
   - LLM summarization of recent `news_articles` for stocks in this sector (top 50 by news_volume_7d), prompted to extract industry-level themes (not stock-level)
   - Output cached in `sector_trends` table (sector, generated_at, bullets[]); regenerate weekly

**(F) ⭐ Alpha Signal Overlay** (this is the differentiator)
Four sub-panels:

1. **Factor heatmap for this sector** — table of every factor × this sector. Three columns: factor name, sector-specific |t| (when available — see "Per-sector IC" gap below; for v1, sector mean of the factor's score), in-model badge. Sorted by sector-specific |t| descending. Tells you "which factors are working in this sector right now."

2. **Picks in this sector** — top 10 stocks in this sector by composite score with mini-thesis line. Bottom 5 below (avoid candidates: low score + red flags).

3. **Macro contributors** — list of `macro_indicator → indicator_score → sector_weight` for indicators that feed this sector's `macro_score`. Pulled from `macro_sector_map` joined with `macro_indicators`. Lets you see what's *driving* the macro signal, not just the headline.

4. **Recent regulatory events** — last 10 `regulatory_events` rows for stocks in this sector with `classifier_status = 'CLASSIFIED'`, with their tailwind/headwind class. Sorted by date.

### Tab 3 — Trend (historical sector performance)
- Multi-line chart: sector avg-score time series; toggle sectors via legend
- Table: month-over-month rank change (which sectors are climbing / falling)
- Sector rotation matrix: 3-month vs 12-month sector returns, today's pick highlighted
- Fed by `daily_picks` aggregated to sector × date, plus `nse_index_history` for sector-benchmark indices where the mapping exists

## Static metadata structure

The IIM-template panels (A, B, C) are static per sector. Capture them once as Python config or YAML, render uniformly. Strawman shape:

```python
# config/sector_metadata.py
SECTOR_INDUSTRIES = {
    "Financials": [
        {
            "industry": "Banking",
            "value_chain": [
                {"name": "Marketing", "items": ["Advertising", "Branding", "Sales support"]},
                {"name": "Sales", "items": ["Acquisition", "Offering", "Multi-channel mgmt"]},
                {"name": "Products", "items": ["Funding (Deposits, Securitization, Credits)",
                                               "Investment (Credits, Securities)",
                                               "Services (Account Mgmt, Asset Mgmt, Issuance/IPO)"]},
                {"name": "Transactions", "items": ["Payment", "Trading", "Clearing & Settlement", "Custody"]},
            ],
            "drivers": {
                "revenue": ["Loan Book (AUM)", "Interest Yield", "Branch/Geographic Expansion"],
                "cost":    ["Cost of borrowing", "Operating Expenses", "Provisions and write-offs"],
                "growth":  ["Digital Innovation", "Macro / credit policies", "Capitalization / Mergers of PSBs"],
            },
            "segments": [
                {"name": "Public Sector Banks", "kpis": ["Net Interest Margin"]},
                {"name": "Private and Foreign Banks", "kpis": ["CASA"]},
                {"name": "Cooperative / Rural Banks", "kpis": ["GNPA / NNPA"]},
            ],
            # market_trends: not static — auto-generated weekly from news, see below
        },
        {"industry": "Asset Management", "value_chain": [...], "drivers": {...}, ...},
        # ...
    ],
    "Information Technology": [
        {"industry": "IT & ITeS", "value_chain": [...], ...},
    ],
    "Materials": [
        {"industry": "Cement", ...},
        {"industry": "Iron & Steel", ...},
    ],
    "Consumer Staples": [
        {"industry": "FMCG", ...},
    ],
    "Health Care": [
        {"industry": "Pharmaceuticals", ...},
        {"industry": "Healthcare (hospitals)", ...},
    ],
    # ...
}
```

The IIM PDF gave us 16 industries. Our taxonomy uses 11 GICS sectors. **Each GICS sector maps to 1-3 industries** — so the per-sector page becomes a "tabs within tabs" or "industry-picker within sector" UX. Or we collapse industries into a single sector view (e.g. show Banking content for Financials, with a note that Asset Mgmt is the secondary industry).

**Decision needed:** sector vs sector × industry granularity. **My take:** start at sector level for v1 (one industry per sector — pick the dominant one), revisit once the page is in use.

Industry → IIM source mapping for the dominant-industry choice:
| GICS Sector | Default IIM industry to use | Notes |
|---|---|---|
| Energy | Oil & Gas | |
| Materials | Cement | (Iron & Steel is secondary; could split further) |
| Industrials | Logistics | (Airlines is secondary) |
| Consumer Discretionary | Retail | (Hospitality / Automobile / E-Commerce all qualify; pick by stock count) |
| Consumer Staples | FMCG | |
| Health Care | Pharmaceuticals | |
| Financials | Banking | (Asset Mgmt is secondary) |
| Information Technology | IT & ITeS | |
| Communication Services | Telecom | |
| Utilities | (no IIM page) | Need to write our own; or treat as cyclical-of-cement-shape |
| Real Estate | (no IIM page) | Need to write our own |

Two sectors (Utilities, Real Estate) have no IIM source — we'd write the value-chain + drivers ourselves. ~30 min each.

## Data needed (vs what we already have)

| Need | Have? |
|---|---|
| Stock-level scores per sector today | ✓ `daily_picks` + `stocks.sector` |
| Sector breadth (% above score threshold) | ✓ derive from `daily_picks` per snapshot |
| Sector avg score time series | ✓ derive from `daily_picks.snapshot_date` |
| Top players (market cap) | ✓ `stocks.market_cap_cr` (mind the unit gotcha — actually rupees) |
| Per-sector factor IC | partial — `pit_ic_by_tier_v2` tiers by `cap_tier`, not sector. v1 uses sector-mean of factor scores; v2 adds sector dimension to backtest_pit. |
| Macro indicator → sector contribution | ✓ `macro_sector_map` + `macro_indicators` |
| Regulatory events per sector | ✓ `regulatory_events` (filter by classifier_status, join via stocks.sector) |
| Static value-chain / drivers / segments | NEW — `config/sector_metadata.py` (one-time curation from IIM PDF) |
| Auto-generated market-trends bullets | NEW — `sector_trends` table + weekly LLM job summarising news_articles |
| 30-day sector avg sparkline | ✓ `daily_picks` 30-day window |
| Sector benchmark index returns | partial — `nse_index_history` has sector indices; mapping sector name → NSE index name needs ~11 rows |

## What this unlocks

- A real "is this sector worth being in" answer that goes beyond a coloured tag
- A per-sector factor inspector — find which signals are working in IT vs Materials vs Banks (planned output of plan-0005 Phase D)
- A macro narrative builder — see which RBI / commodity / index moves are propagating into the sector signal, instead of treating the macro score as a black-box number
- A sector-rotation hypothesis tester via the Trend tab
- An **explanation surface** — anyone (you, an analyst friend, a future collaborator) can read the page and grok how a sector works in 60 seconds. The IIM template is genuinely good pedagogy.

## Implementation order (when picked up)

1. **One-time metadata curation.** Translate the 16 IIM sector pages + 2 self-written (Utilities, Real Estate) into `config/sector_metadata.py`. ~3 hrs of careful typing. Single PR, no logic.
2. **API additions** in `cockpit/api.py`:
   - `get_sector_overview_v2()` — extend current overview with breadth + top-3 + 30-day score sparkline
   - `get_sector_detail(sector_name)` — pulls value-chain / drivers / segments from metadata, top-players from stocks, factor heatmap from daily_snapshots_pit aggregated to sector, macro contributors from macro_sector_map, regulatory events from regulatory_events
   - ~2 hrs
3. **Tab 1 polish** — extend `cockpit/templates/sectors.html` with the richer card. ~1 hr.
4. **Tab 2 (Per-Sector deep dive)** — new template. Render IIM-style 5-block layout + Alpha Signal overlay's 4 sub-panels. ~4 hrs first pass; subsequent sectors are free since it's data-driven.
5. **Sector trends generator** — weekly cron job summarises `news_articles` per sector via Claude API into 4-6 bullets, writes to `sector_trends`. ~2 hrs (API call + prompt + cache).
6. **Tab 3 (Trend)** — sector × date pivot from `daily_picks`, Chart.js multi-line. ~2 hrs.
7. **(v2) Per-sector IC** — extend `tools/backtest_pit.py` with a `sector` group-by, surface in Tab 2's factor heatmap. ~30 min compute + ~1 hr template work.

**Total v1: ~14 hrs** (metadata 3 + API 2 + tab1 1 + tab2 4 + trends gen 2 + tab3 2). v2 adds ~1.5 hrs.

## Decisions locked in (2026-05-10)

1. **Sources:** IBEF PDFs + top 3 annual reports per sector + our `news_articles` table. Brokerage reports skipped for v1.
2. **Hand-curation budget:** 0 hours. Fully automated. LLM (Claude API) generates all sector content from authoritative sources; no human review pass before publish. If output looks wrong on a specific sector, override via the `sector_metadata` table's `manual` row.
3. **Refresh cadence:**
   - Static structure (value chain, drivers, segments): **annual** — re-run at start of each fiscal year
   - Top players + market share: **quarterly**
   - Trend bullets: **monthly** from `news_articles`
4. **Granularity:** sector level for v1 (one IIM industry per GICS sector — dominant by stock count). Add industry-picker if gap is felt.
5. **Tab 2 v1:** descriptive (sector mean of factor scores). Per-sector IC backtest extension is a v2 add-on.

## Schema (richer than IIM template)

Captured per industry as the structured payload generated by the fetcher:

- **5 value-chain stages × 6-10 sub-items each, with one-line descriptions**
- **3 driver categories × 4-6 items each, tagged `structural` / `cyclical` / `policy-driven`**
- **5-8 segments × 3-5 KPIs each, with canonical formula and direction-of-quality**
- **8-12 top players** (auto-derived from `stocks` filtered by sector, sorted by market cap)
- **6-10 trend bullets** organised: `industry_size`, `structural_shifts`, `regulatory`, `headwinds`, `india_specific`
- **Regulatory bodies** (e.g. RBI for banks, IRDAI for insurance, AMFI for AMCs) with what they regulate
- **Cyclicality notes** (cement = 18-24 month cycle; pharma = 8-15 yr patent cycle)
- **India-specific factors** (e.g. for Banking: CASA dependence, MSME book exposure, agri write-offs)

Roughly 3× the depth of the IIM template, still fits one scrollable page.

## Implementation order

| Step | What | Cost |
|---|---|---|
| 1 | Define schema (Python dataclass + JSON schema) | 1 hr |
| 2 | Manually download IBEF PDFs for ~13 industries (one-time) | 30 min |
| 3 | Build `tools/sector_narrative_fetcher.py` (PDF parsing, Claude API call, schema validation) | 4 hrs |
| 4 | Add `sector_metadata` SQLite table + upsert helpers | 1 hr |
| 5 | Run fetcher for all 13 industries (no hand-review per locked decision #2) | 30 min compute |
| 6 | Cron schedule (monthly trends, quarterly players, annual structure) | 1 hr |
| 7 | Cockpit `/sectors` Tab 2 (per-sector deep-dive renders the schema) | 4 hrs |
| 8 | Cockpit `/sectors` Tab 3 (Trend) | 2 hrs |

**Total: ~14 hrs** of build, then automated forever after.

## What we're not doing

- Per-sector portfolio construction (F3 / D17 territory)
- Sector beta neutralisation
- Inter-sector correlation matrix (nice to have; can add to Trend tab later)
- Industry-level peer comparisons within a sector (defer until v2)
