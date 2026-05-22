# 0013 — Industry, not GICS sector, is the primary drill unit
**2026-05-11 · Accepted**

**Decision.** Drill at industry level (25 IIM-style industries nested under 11 GICS sectors). Sectors remain a visual grouping only. `stocks.industry` is load-bearing.

- **Taxonomy.** [tools/classify_industries.py](../../tools/classify_industries.py) `INDUSTRIES_BY_SECTOR` — Banks vs NBFCs vs AMCs vs Insurance vs Capital Markets are 5 separate industries under Financials; Automobiles vs Auto Components are 2 under Consumer Discretionary; etc.
- **From-scratch classifier.** `--from-scratch` ignores source GICS tags, picks from 25 industries via Haiku 4.5, writes both `stocks.industry` AND `stocks.sector` (parent rolled up). One run → 2,448 stocks across 38 distinct industries (3 extras are legacy edge cases).
- **Routing.** `/sectors?industry=X` is primary; `/sectors?sector=X` is back-compat.

**Why.**
- 11 GICS buckets too coarse — "Consumer Discretionary" lumps Auto, Hotels, Retail, E-Commerce into one composite with unrelated drivers.
- Source GICS sometimes wrong — Eternal/Zomato/Swiggy tagged `Communication Services` in source data; they're food-delivery/e-commerce, not media.

**Composite weighting (sub-decision): market-cap-weighted.** `Σ(score × mcap) / Σ(mcap)`. Reflects what a portfolio sees. Equal-weighted shows breadth — better served by a separate diagnostic if ever wanted.

**Trade-offs.**
- 38 cards denser than 11 — mitigated by sector-header grouping in the heatmap
- Original GICS sector tags overwritten; recoverable from v1 import scripts via git history if needed
- `stocks.industry` is current-best, not a stable identifier — a retag run can shift it
- `sector_metadata.sector` column is now a generic taxonomy key (holds industry name for new rows, sector name for legacy). Rename touches every read path — defer.

**Related.** ADR 0009 · plan 0003 (market share momentum has industry as unit of analysis)
