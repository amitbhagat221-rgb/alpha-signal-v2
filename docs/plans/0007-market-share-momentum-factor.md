---
Status: proposed
Created: 2026-05-10
Last updated: 2026-05-10 (expanded from single-factor to 4-factor cluster)
Owner: Amit Bhagat
Implementation: not started — factor cluster inspired by IIM sector narratives
Related: 0005-100-factors-and-model.md (factor library), 0006-sector-intelligence-page.md (consumes sector context)
Source: docs/_archive/Sector Narratives.pdf — 16 sector narratives, structural patterns observed across all
---

# 0007 — Sector-Narrative-Derived Factor Cluster

## Overview

Reading all 16 IIM sector pages, four structural patterns repeat across every sector and translate to factor candidates we don't have yet — and that don't replicate any existing F-track or legacy signal:

| # | Factor | Inspiration | Independence vs existing | Cost |
|---|---|---|---|---|
| **A** | **Market-Share Momentum** | "Top Players + Market Share %" — every sector page | Independent of price momentum, quality, value | 3.5 hr |
| **B** | **Sector-Relative Sales Growth** | "Industry CAGR" headline + sector growth-driver bullets | Independent of `revenue_growth_yoy` (which is absolute, not sector-relative) | 1.5 hr |
| **C** | **Inventory Turnover (sector-relative)** | "Inventory turnover" / "Avg inventory" KPIs in Auto, Retail, Logistics, Cement | Different from CCC (just the inventory leg, rank within sector) | 1 hr |
| **D** | **Revenue Volatility (5y CV)** | "Total Active Clients" / "Customer Concentration" KPIs in IT, Pharma; cyclicality flags in Cement, Steel, Auto | Different from `earnings_persistence` (top-line, not bottom-line) | 1 hr |

**Total cluster cost:** ~7 hrs across 4 factors. Each ships as a separate `signals/<x>.py` + PIT helper + score table; same template as `signals/roic.py`.

The headline is Factor A (Market-Share Momentum) — biggest conceptual leap. Factors B/C/D are easier wins on data we already have.

---

# Factor A — Market-Share Momentum

## What problem are we solving?

Reading the IIM sector pages, every single one ends with a "Top Players" table showing market share %. Telecom: Jio 33.85%, Airtel 28.06%, Vodafone Idea 27.37%, BSNL 10.43%. Cement: UltraTech 19%, Shree 8%, ACC 7%, Ambuja 6%. The numbers vary by sector but the structural pattern is the same: **a sector has a fixed total pie, and stocks compete for slices over time**.

Our existing factors don't capture this. Momentum is price-based, not share-based. ROIC measures profitability, not whether the company is winning the sector. Consensus tracks analyst sentiment, not realised competitive position. **Market-share dynamics — who is winning vs losing inside a sector — is independent signal we currently leave on the floor.**

The thesis: stocks gaining share within their sector tend to outperform stocks losing share, controlling for everything else. This is well-known in academic literature (Soliman 2008, Cooper 2008) and shows up in practitioner factor libraries (AQR's "industry-relative growth" cluster). For Indian equities we can compute it cleanly from data we already have.

## The factor, defined

For each stock at any given snapshot date:

```
market_cap_t      = close_price_t × shares_outstanding_t
sector_total_t    = sum of market_cap_t across all stocks in same GICS sector
share_t           = market_cap_t / sector_total_t

share_momentum    = share_t / share_{t-90 trading days} − 1
```

Then, within `cap_tier` (and optionally also within sector — see open question below), Spearman-rank `share_momentum` and use the rank as the signal.

**Why this measures what we want:**
- Stocks whose `share` is rising are gaining ground vs sector peers — they're either growing faster, less affected by sector headwinds, or capturing share from declining peers
- Stocks whose `share` is falling are the inverse — losing relative position
- The ratio formulation (vs raw price change) controls for sector-wide moves: if the whole sector rallied 30%, every stock's price rose, but only the over-performers gained `share`

**Key advantages:**
- Independent of price momentum (different denominator)
- Sector-relative by construction (no need for separate sector-neutralisation step)
- Pure structural reading — no fundamentals needed beyond shares-outstanding

## Data needed (vs what we have)

| Need | Have? | Where |
|---|---|---|
| Daily close per stock | ✓ | `stock_prices.close` |
| Shares outstanding | ✓ | `fundamentals_screener` line item `"No. of Equity Shares"` (annual) — gives ~10 yrs of history |
| Sector classification | ✓ | `stocks.sector` |
| Universe of stocks | ✓ | `stocks` (ticker NOT NULL) |

Shares outstanding is annual not quarterly, but that's actually fine for a 90-day momentum factor — share-count changes happen via splits/bonuses (handled by `corporate_adjustments`) or buybacks/dilutions (annual events). For PIT correctness we'd carry-forward the latest known share count as of the eval date.

## Implementation

### Compute module: `signals/share_momentum.py`

Same shape as `signals/roic.py` and `signals/fcf_yield.py`:

```python
def compute(dry_run=False):
    # 1. Load latest close prices (date = max(stock_prices.date))
    # 2. Load shares_outstanding from fundamentals_screener (latest annual per stock)
    # 3. Compute market_cap_t = close × shares_outstanding
    # 4. Apply corporate_adjustments to share counts for split/bonus events between report and today
    # 5. Group by sector, compute share_t = market_cap_t / sector_total_t
    # 6. Repeat for date_t-90 trading days ago using PIT-adjusted prices
    # 7. share_momentum = share_t / share_{t-90} − 1
    # 8. Filter financials and stocks with market_cap below threshold (₹200 cr)
    # 9. Write to share_momentum_scores
```

Smoothing: 3-yr equivalent for stability isn't applicable for a 90d momentum factor. Use the 90d window as-is, possibly with 3-month winsorisation at p1/p99 to suppress demerger artifacts.

### PIT helper: `pit_share_momentum(sid, eval_date)`

In `tools/reconstruct_pit.py`. Same pattern as the existing `pit_*` functions. Knowable inputs: shares-outstanding from the latest annual filing whose `period_end + 90 days <= eval_date`, plus prices through `eval_date`.

### Schema: `share_momentum_scores`

```sql
CREATE TABLE IF NOT EXISTS share_momentum_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    market_cap_cr   REAL,
    sector_share    REAL,        -- share_t (0.0 to 1.0)
    share_momentum  REAL,        -- (share_t / share_{t-90}) − 1
    PRIMARY KEY (sid, snapshot_date)
);
```

### Pipeline wiring

Add to `config.py PIPELINE_STEPS` after `signal_fcf_yield`. Same `data_freq: 'daily'`, `frequency: 'daily'`. Not in scoring weights yet — needs t-stat validation per the F2 → F3 gating from plan-0005.

## Why this is interesting (vs just "another factor")

1. **Genuinely independent.** Momentum / quality / value / consensus don't capture sector-relative competitive position. This does.
2. **Sector-aware by construction.** Most factor libraries require a separate sector-neutralisation step for IC stability. This factor is sector-relative in its definition — the IC is naturally sector-clean.
3. **Maps to the structural narrative.** When we ship the `/sectors` page (plan-0006) we can show "share momentum leaders" per sector as a card — directly answering "who's actually winning in this sector right now?"
4. **Cyclical insensitivity.** During bear markets all stocks fall but share is preserved at the leaders. During bull markets all stocks rise but share moves to the new winners. Either way the factor reads competitive shifts cleanly.
5. **Uses zero new data.** Everything needed is already in our DB.

## Open questions

1. **Within-tier or within-sector ranking?** Cap tier (LARGE / MID / SMALL) is our default for backtest IC computation. But share momentum is structurally a within-sector concept. **My take:** rank within-sector for the raw signal value, then percentile-tier within `cap_tier` for the IC computation (matching our existing factor convention).
2. **Window length — 90 days or 180?** 90 captures more recent shifts; 180 smooths noise. Backtest both, keep the higher-IC one.
3. **Adjust for sector membership changes?** A stock moving sectors (Tata Motors split into Tata Motors + Tata Motors Passenger) creates a discontinuity. Edge case; flag for review when it happens.

## Out of scope

- Multi-window combinations (60d × 180d × 360d as a composite) — defer to F3 model upgrade
- Inter-sector concentration metrics (HHI as a sector-level signal) — separate factor candidate, separate plan
- Tracking IPO inclusion / delisting effects on sector_total — handle via universe-as-of-eval-date convention

## Implementation cost

| Step | What | Cost |
|---|---|---|
| 1 | `signals/share_momentum.py` (compute today's value) | 1.5 hr |
| 2 | PIT helper in `tools/reconstruct_pit.py` | 1 hr |
| 3 | `share_momentum_scores` table in `schema.sql` | 15 min |
| 4 | Pipeline wiring | 15 min |
| 5 | Run reconstruction across 7 PIT dates + run backtest | 5 min compute |
| 6 | Review t-stat output, decide on within-tier vs within-sector ranking | 30 min |

**Total: ~3.5 hrs** to ship the factor end-to-end with backtest verdict.

## Why ship this before other F-track factors

Most F-track factors in plan-0005's queue (CCC, ROIIC, gross-margin trend) are accounting-derived from `fundamentals_screener`. They're variants on what we already measure. **Market-share momentum is a different conceptual axis** — it's the first factor in our library that uses cross-sectional sector context, not just stock-level fundamentals.

If it lands above t=1.5 in any tier, it's a foundation for a "sector-relative" cluster of follow-on factors (sector-relative ROIC, sector-relative growth, sector-relative dividend yield). That cluster doubles the F-track factor count without inventing new data sources.

---

# Factor B — Sector-Relative Sales Growth

## Inspiration

Every IIM sector page has a CAGR headline (Pharma 22%, Logistics 10.5%, Retail 11%, IT 7%, FMCG 23.15%). Stocks growing *faster than their sector* are taking share or expanding the addressable market — both are alpha. Stocks growing *slower than their sector* are losing the structural battle even if they look fine on absolute growth.

Our existing `revenue_growth_yoy` factor is absolute. A 15% Pharma stock looks fast in isolation but is *underperforming* the 22% sector. Sector-relativising fixes the comparison.

## Definition

```
sales_growth_yoy_t       = (sales_t / sales_{t-4Q}) − 1
sector_median_growth_t   = median(sales_growth_yoy_t for stocks in same sector)
relative_growth_t        = sales_growth_yoy_t − sector_median_growth_t
```

Smoothing: 3-yr median per the existing F-track convention (same as ROIC / FCF Yield).

## Data path

- `Sales` line item from `fundamentals_screener` (annual + quarterly both available)
- `stocks.sector` for the grouping
- Financials excluded (banks/NBFCs report in different format)

## Schema

```sql
CREATE TABLE IF NOT EXISTS sales_growth_relative_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    sales_growth    REAL,
    sector_median   REAL,
    relative_growth REAL,
    PRIMARY KEY (sid, snapshot_date)
);
```

## Cost

| Step | What | Cost |
|---|---|---|
| 1 | `signals/sales_growth_relative.py` | 45 min |
| 2 | PIT helper | 30 min |
| 3 | Schema + pipeline wiring | 15 min |

**Total: 1.5 hr.** Cluster sibling to ROIC / FCF Yield.

---

# Factor C — Inventory Turnover (sector-relative)

## Inspiration

IIM Auto: "Inventory turnover" listed as a KPI. Retail: "Avg transaction value, dwell time." Logistics: "Avg inventory, warehouse capacity." Cement: "Capacity Utilization." Across these, the underlying signal is the same — how efficiently the company converts inventory to sales.

Existing factors don't isolate this:
- CCC combines DSO + DIO − DPO — three legs at once
- Asset turnover (in Piotroski) uses total assets, not just inventory

A clean inventory-turnover factor measures *just the inventory leg* and ranks within sector (since pharma vs retail have different baselines).

## Definition

```
inventory_turnover_t   = sales_TTM / avg_inventory_TTM
                       = sales_TTM / ((inventory_t + inventory_{t-1Y}) / 2)
sector_p50_t           = median(inventory_turnover for stocks in same sector)
relative_turnover_t    = inventory_turnover_t / sector_p50_t
```

Higher = more efficient working capital management. Within-sector relative because pharma (low turnover, ~3-4×) and retail (high, ~10-15×) have very different absolute scales.

## Data path

- `Sales` and `Inventory` line items from `fundamentals_screener` annual rows
- Financials excluded (no inventory)
- Sectors with inherently low inventory (IT services, banks, telecom) excluded — would have meaningless ratios

## Schema

```sql
CREATE TABLE IF NOT EXISTS inventory_turnover_scores (
    sid                 TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date       TEXT NOT NULL,
    inventory_turnover  REAL,
    sector_p50          REAL,
    relative_turnover   REAL,
    PRIMARY KEY (sid, snapshot_date)
);
```

## Cost

**~1 hr** — same template as ROIC, simpler math.

---

# Factor D — Revenue Volatility (5-year CV)

## Inspiration

IIM IT/ITeS lists "Total Active Clients" as a KPI — implying customer concentration risk. Pharma's "Patent cliff" cycles. Cement's 18-24 month supply-demand cycles. Steel's commodity-linked volatility. These are all the same observation: some stocks have stable revenue trajectories, others swing.

Stable-revenue stocks tend to outperform on a risk-adjusted basis (the "low-volatility anomaly"), and they're particularly desirable in cyclical sectors where everyone *else* is volatile. Existing `earnings_persistence` measures EPS CV — bottom-line stability. Top-line stability is a different (sometimes leading) signal: if revenue holds steady but EPS swings, the issue is cost-side; vice versa flags demand-side risk.

## Definition

```
sales_yoy_growth_history = list of (sales_t / sales_{t-1Y} − 1) for last 5 years
revenue_cv_5y            = stdev(sales_yoy_growth_history) / |mean(sales_yoy_growth_history)|
```

Lower = more predictable revenue. Use within-tier rank for IC computation, possibly also within-sector to remove sector-baseline confound.

Edge case: companies with mean growth near zero get unstable CV. Filter `|mean| > 0.02` (≥ 2% average growth) to qualify.

## Data path

- `Sales` line item, last 6 annual periods (need 5 YoY differences)
- Stocks with <6 years of data filtered out (newly-listed)
- All sectors qualify (revenue CV is meaningful everywhere)

## Schema

```sql
CREATE TABLE IF NOT EXISTS revenue_cv_scores (
    sid             TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date   TEXT NOT NULL,
    revenue_cv_5y   REAL,
    years_used      INTEGER,
    PRIMARY KEY (sid, snapshot_date)
);
```

## Cost

**~1 hr** — pure aggregation over Sales line item, no joins.

---

# Cluster summary

| Factor | Concept | Cost | Independence |
|---|---|---|---|
| A — Market-Share Momentum | Δ market_cap_share within sector, 90d window | 3.5 hr | High — orthogonal to price momentum, quality, value |
| B — Sector-Relative Sales Growth | sales_growth − sector_median_growth | 1.5 hr | Medium — relativised version of an existing absolute factor |
| C — Inventory Turnover (sector-relative) | sales / inventory, ranked within sector | 1 hr | Medium — isolates one leg of CCC |
| D — Revenue Volatility (5y CV) | top-line stability over 5 years | 1 hr | High — different from EPS CV (bottom-line) |

**Cluster total: ~7 hrs.** Ships +4 factors in plan-0005's library, all derived from existing data, all sector-aware in their construction.

## Recommended ship order

1. **D — Revenue Volatility** (1 hr) — simplest, no joins, validates the cluster pattern
2. **C — Inventory Turnover** (1 hr) — simplest sector-relative factor, smallest blast radius
3. **B — Sector-Relative Sales Growth** (1.5 hr) — generalisation worth doing before other relativisations
4. **A — Market-Share Momentum** (3.5 hr) — biggest conceptual leap, most worth fighting for, ship after the simpler ones validate the cluster pattern

After all four ship, run `tools/reconstruct_pit.py` once to extend historical archive, then `tools/backtest_pit.py` to get IC + t-stats for the cluster. Promotion to scoring weights gated on |t| ≥ 1.5 in any cap-tier per the standing F2→F3 protocol.
