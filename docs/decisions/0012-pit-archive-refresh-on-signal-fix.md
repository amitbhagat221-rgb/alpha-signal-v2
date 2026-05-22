# 0012 — Refresh v2 PIT archive when signal logic changes; v1 archive stays frozen
**2026-05-10 · Accepted**

**Decision.** Any signal-side fix that changes which stocks get scored, or how, triggers `tools/reconstruct_pit.py` + `tools/backtest_pit.py`. Post-fix `v2_recompute` t-stats are the truth. `v1_archive` rows in `pit_ic_by_tier_v2` stay as historical reference. Promotion to scoring weights uses post-fix t-stats only.

**Why.** Today's financial-sector-exclusion fix (commit `af94835`) had been a silent no-op across 5 modules since v2 began — `SCREEN["financial_sectors"]="Financial Services"` while `stocks.sector="Financials"`. The reflex "archives are immutable" was wrong: matching a buggy reference doesn't make the numbers correct, just consistently wrong.

**Two distinct concepts, previously conflated.**
- **Port correctness** — does v2 reproduce v1's logic faithfully? One-time check at the rebuild boundary, then irrelevant.
- **Financial truth** — do the numbers measure what we want? This is what we care about after the rebuild boundary.

**Post-fix shifts measured today.** `cf_accruals_ratio` MID t=−2.89 → −1.93 (KEEP → WEAK). Financials had been amplifying the signal; cleaner sample is honestly weaker. Other quality signals barely moved.

**Cost.** ~4 min for full reconstruct (7 dates × 26 signals × 2,448 stocks). Cheap enough that "fix-forward only" was performative caution.

**Documentation rule.** Retire "matches v1 exactly" framing in go-forward docs. Use: "v1 archive is the historical reference; v2_recompute reflects current logic."

**Related.** ADR 0010 (sibling — same forward-only-fix issue, same answer)
