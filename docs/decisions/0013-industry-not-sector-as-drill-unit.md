# ADR 0013 — Industry, not GICS sector, is the primary drill unit

**Status:** Accepted
**Date:** 2026-05-11
**Owner:** Amit Bhagat
**Related:** ADR 0009 (factor-track), plan 0006 (sector intelligence page), plan 0007 (market share momentum)
**Supersedes:** —

## Context

Until 2026-05-10, the cockpit `/sectors` page and all sector-level analytics drilled at the **GICS sector** level — 11 buckets (Energy, Materials, Industrials, Consumer Discretionary, Consumer Staples, Health Care, Financials, Information Technology, Communication Services, Utilities, Real Estate).

Two problems became unignorable while building the IIM-style sector deep-dive:

1. **11 buckets is too coarse for India.** "Consumer Discretionary" lumps Auto OEMs, Auto Components, Hotels, Retail, E-Commerce, and Consumer Durables into one card with one composite. Their drivers are unrelated. The value-chain narrative for a 6-way mixed bucket is necessarily generic.
2. **Source GICS sector tags were sometimes wrong for Indian platforms.** Eternal (Zomato) and Swiggy ship in source data tagged `Communication Services` (GICS's catch-all bucket that includes "interactive media"). Neither is a media company in any operationally useful sense; they're food-delivery / e-commerce platforms competing with Reliance Retail and Tata Cliq. A composite that includes them under Comm Services is not a useful signal.

## Decision

**Drill at industry level (25 IIM-style industries nested under 11 GICS sectors).** Sectors stay as a visual grouping only — the heatmap groups industry cards under sector headers so the user can see structure, but the unit of analysis everywhere else (overview composite, narrative, competitive landscape, our picks) is industry.

Specifically:

1. **Taxonomy.** [tools/classify_industries.py](../../tools/classify_industries.py) defines `INDUSTRIES_BY_SECTOR` — 25 industries explicitly listed under their parent sector. Banks vs NBFCs vs AMCs vs Insurance vs Capital Markets are 5 separate industries under Financials; Automobiles vs Auto Components are 2 under Consumer Discretionary; Power Generation vs Power T&D vs Gas Utilities are 3 under Utilities; etc.
2. **From-scratch classifier.** `tools/classify_industries.py --from-scratch` ignores the source GICS sector tag and picks from all 25 industries via Haiku 4.5 closed-set classification. It then writes **both** `stocks.industry` and `stocks.sector` — `stocks.sector` is the parent rolled up from the chosen industry, overwriting any wrong source value. Run once across all 2,448 stocks → 38 distinct industry values populated (3 extras beyond 25 are legacy / manual edge cases that fell outside the taxonomy).
3. **Routing.** `/sectors?industry=X` is the primary URL; `/sectors?sector=X` is back-compat for the previous cards. `cockpit/api.py` has parallel `get_industry_*` and `get_sector_*` helpers; the industry ones are the canonical entry points going forward.
4. **Schema convenience: `sector_metadata.sector` is now a generic taxonomy key.** The column holds an industry name for industry-keyed narratives (37 of them today) and a sector name for legacy sector-keyed rows. PK `(sector, source)` is preserved. The column name is misleading but renaming it touches every read path; defer.

## Composite weighting — equal vs market-cap (sub-decision)

Adopted **market-cap-weighted** for the industry composite, formula `Σ(score × mcap) / Σ(mcap)`. Reasons:

- The composite reflects what an investor's portfolio actually sees (index weight, not stock count).
- Within an industry, the small-cap tail of obscure tickers shouldn't drown out the signal coming from the names that actually matter.

The opposing argument (equal-weighted shows breadth — whether smalls are also doing well, not just the giants) is real but better served by a separate "breadth" diagnostic if we ever want it; the headline composite should be index-weighted.

## Consequences

**Positive:**
- Per-industry composites are interpretable (the Aviation composite is about aviation, not blended with retail).
- Source data quality issues at the GICS sector level (Eternal/Zomato) are resolved by the from-scratch classifier writing canonical values.
- Plan 0007 (market share momentum) has a well-defined unit of analysis (within-industry share shift).
- The IIM-style narrative is genuinely useful — value chain / segments / KPIs / drivers are industry-specific, not a smear of 6 unrelated industries.

**Negative:**
- 38 cards on the heatmap is denser than 11. Mitigated by the sector-header grouping.
- We've overwritten the original GICS sector tags. They're recoverable from the v1 import scripts in git history if ever needed, but the live table no longer carries them.
- The 3 extra industries (38 vs 25) need periodic cleanup — they're rows with legacy or manual values outside the canonical taxonomy.
- The from-scratch classifier is best-effort, not authoritative. A retag run can shift a stock's industry. Treat `stocks.industry` as a current-best classification, not a stable identifier.

## Alternatives considered

- **Stick with 11 GICS sectors + just rebadge Eternal/Zomato manually.** Rejected: doesn't solve the coarseness problem, and a one-off manual fix doesn't generalize as new platforms list.
- **GICS sub-industries (~158 globally).** Rejected: too granular for India's universe size (2,448 stocks — most sub-industries would have 0 or 1 stocks); also not stable across data vendors.
- **NIC / NSE sectoral indices as the taxonomy.** Rejected: NSE indices are commercial / index-construction units, not analyst-grade industry buckets. Many are overlap-heavy ("Nifty India Consumption" is not an industry).
- **Free-text industry from the narrative source.** Rejected: not stable / not joinable.

## Migration / rollback

- Forward-only. `stocks.industry` and `stocks.sector` were overwritten in place by the from-scratch classifier. Rollback would require re-running v1's GICS-based import.
- Sector-keyed `sector_metadata` rows are preserved (back-compat); industry-keyed rows added alongside.
- Cockpit accepts both `?sector=` and `?industry=` query params, with industry as the primary path.
