---
Status: proposed
Created: 2026-05-10
Last updated: 2026-05-10
Owner: Amit Bhagat
Related: 0002-100-factors-and-model.md, 0006-sector-intelligence-page (archived)
Source: docs/_archive/Sector Narratives.pdf — 16 IIM sector pages
---

# 0007 — Sector-Narrative-Derived Factor Cluster

Reading 16 IIM sector pages, four structural patterns repeat across every sector and translate to factors we don't have yet:

| # | Factor | Inspiration | Independence | Cost |
|---|---|---|---|---|
| **A** | **Market-Share Momentum** | "Top Players + Market Share %" — every page | High — orthogonal to price momentum, quality, value | 3.5 hr |
| **B** | Sector-Relative Sales Growth | "Industry CAGR" headlines | Medium — relativised version of absolute growth | 1.5 hr |
| **C** | Inventory Turnover (sector-relative) | "Inventory turnover" KPI in Auto/Retail/Logistics/Cement | Medium — isolates inventory leg of CCC | 1 hr |
| **D** | Revenue Volatility (5y CV) | "Customer Concentration" KPIs in IT/Pharma; cyclicality flags | High — top-line, not EPS like earnings_persistence | 1 hr |

**Cluster total: ~7 hr.** Each ships as `signals/<x>.py` + PIT helper + score table; same template as `signals/roic.py`. All sector-aware in construction, all derived from existing data.

Ship order: D → C → B → A (simple to complex; D/C/B validate the cluster pattern before fighting for A).

---

## Factor A — Market-Share Momentum (the headline)

### The thesis

Every IIM sector page ends with a "Top Players" table showing market share %. Telecom: Jio 33.85%, Airtel 28.06%, Vi 27.37%, BSNL 10.43%. The structural pattern: **a sector has a fixed pie; stocks compete for slices over time.** Stocks gaining share within their sector tend to outperform stocks losing share, controlling for everything else (Soliman 2008, Cooper 2008; AQR's "industry-relative growth" cluster). We currently leave this on the floor — momentum is price-based not share-based, ROIC measures profit not winning, consensus tracks sentiment not realised position.

### Definition

```
market_cap_t      = close_price_t × shares_outstanding_t
sector_total_t    = Σ market_cap_t across same GICS sector
share_t           = market_cap_t / sector_total_t
share_momentum    = share_t / share_{t−90 trading days} − 1
```

Within `cap_tier` Spearman-rank `share_momentum` for the signal value.

**Why this works:** ratio formulation controls for sector-wide moves (if the whole sector rallies, only over-performers gain share). Independent of price momentum (different denominator). Sector-relative by construction.

### Data

| Need | Have? | Where |
|---|---|---|
| Daily close | ✓ | `stock_prices.close` |
| Shares outstanding | ✓ | `fundamentals_screener` line item `"No. of Equity Shares"` (annual, ~10y history) |
| Sector | ✓ | `stocks.sector` |

Annual share-count is fine for a 90-day momentum factor — share-count changes are splits/bonuses (handled by `corporate_adjustments`) or buybacks/dilutions (annual). PIT: carry-forward latest known.

### Implementation

```python
# signals/share_momentum.py — same shape as signals/roic.py
def compute(dry_run=False):
    # 1. Load latest close prices
    # 2. Load shares_outstanding from fundamentals_screener (latest annual)
    # 3. market_cap_t = close × shares_outstanding
    # 4. Apply corporate_adjustments to share counts for split/bonus between report and today
    # 5. Group by sector, compute share_t = market_cap_t / sector_total_t
    # 6. Repeat for t−90 trading days using PIT-adjusted prices
    # 7. share_momentum = share_t / share_{t-90} − 1
    # 8. Filter financials + stocks with market_cap < ₹200 cr
    # 9. Write to share_momentum_scores
```

PIT helper `pit_share_momentum(sid, eval_date)` in `tools/reconstruct_pit.py`. Knowable inputs: shares-outstanding from latest annual where `period_end + 90d <= eval_date`, prices through `eval_date`.

**Schema:**
```sql
CREATE TABLE share_momentum_scores (
  sid           TEXT NOT NULL REFERENCES stocks(sid),
  snapshot_date TEXT NOT NULL,
  market_cap_cr REAL,
  sector_share  REAL,                -- 0.0 to 1.0
  share_momentum REAL,               -- (share_t / share_{t-90}) − 1
  PRIMARY KEY (sid, snapshot_date)
);
```

### Why ship before other Track 3 factors

Most queued Track 3 factors (CCC, ROIIC, gross-margin trend) are accounting-derived from `fundamentals_screener` — variants on what we measure. **Market-share momentum is a different conceptual axis** — first factor using cross-sectional sector context. If it lands at t ≥ 1.5 in any tier, it founds a "sector-relative" cluster (sector-relative ROIC, sector-relative growth, sector-relative dividend yield) — doubles Track 3 factor count without new data.

### Open questions

1. **Within-tier or within-sector ranking?** Default within-tier for IC. **Take:** rank within-sector for the raw signal value, then percentile-tier within `cap_tier` for IC (matches existing factor convention).
2. **Window length 90d or 180d?** Backtest both, keep higher IC.
3. **Sector membership changes?** A stock moving sectors creates a discontinuity. Edge case — flag for review when it happens.

---

## Factors B / C / D — quick specs

| | Definition | Data | Notes |
|---|---|---|---|
| **B Sector-Relative Sales Growth** | `relative_growth_t = sales_growth_yoy − median(sales_growth in sector)`. 3-yr median smoothing (matches ROIC convention). | `Sales` line item from `fundamentals_screener` (annual+quarterly); `stocks.sector`. Financials excluded. | A 15% Pharma stock is *underperforming* a 22% sector. Our existing `revenue_growth_yoy` is absolute and misses this. |
| **C Inventory Turnover (sector-relative)** | `inventory_turnover = sales_TTM / avg_inventory_TTM`; `relative_turnover = inventory_turnover / sector_p50`. Within-sector because pharma (~3-4×) and retail (~10-15×) have very different baselines. | `Sales` + `Inventory` from `fundamentals_screener` annual. Financials + IT services + telecom excluded. | Isolates the inventory leg of CCC. Different from Piotroski's asset turnover (uses total assets). |
| **D Revenue Volatility (5y CV)** | `revenue_cv_5y = stdev(sales_yoy_growth, last 5y) / |mean(sales_yoy_growth)|`. Lower = more predictable. Filter `|mean| > 0.02` to avoid unstable CV near zero. | `Sales` last 6 annual periods (need 5 YoY diffs). All sectors qualify. | Top-line stability is a different signal from `earnings_persistence` (bottom-line CV). Stable revenue + swinging EPS = cost-side issue; swinging revenue = demand-side risk. |

Each ships with its own `*_scores` table indexed by `(sid, snapshot_date)`, same template as ROIC/FCF Yield.

---

## Done when

After all four ship: run `tools/reconstruct_pit.py` to extend historical archive, then `tools/backtest_pit.py` for IC + t-stats per cap-tier. Promotion to scoring weights gated on `|t| ≥ 1.5` in any cap-tier per 3.2 → 3.3 protocol.

## Out of scope

- Multi-window combinations (60d × 180d × 360d composite) — defer to 3.3
- Inter-sector concentration (sector-level HHI) — separate factor, separate plan
- IPO inclusion / delisting effects on `sector_total` — handle via universe-as-of-eval-date convention
