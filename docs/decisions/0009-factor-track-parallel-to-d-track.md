# 0009 — Track 3 (Factor model) runs parallel to Track 2 (Portfolio), no blocking
**2026-05-04 · Accepted**

> **Terminology updated 2026-05-22 per [ADR 0015](0015-track-numbering-and-rename.md)** — what this ADR originally called "F-track" is now "Track 3 (Factor model)"; "D-track" is "Track 2 (Portfolio)". Integration points F3.3 → 3.3c, F3.2 → 3.3b. The decision itself is unchanged; only the labels.
>
> Filename kept as-is (ADR write-once convention applies to filenames). Body below uses current terminology.

**Decision.** Track 3 (factor depth, plan 0002) runs concurrently with Track 2 (segment models + portfolio, plan 0001). Track 2 phases never block on Track 3 phases.

**Why.** Track 2's final phase 2.5 (XGBoost) is data-blocked until ~early 2027 (needs ≥6 months of accumulated PIT snapshots). Sequential would lose 12+ months waiting. Most retail quant projects collapse precisely because they spend years on track 1 and never reach track 2.

**Integration points (declared now to avoid late conflicts).**
- **2.4 ↔ 3.3c** — both produce per-stock weights into `portfolio_holdings`. Whichever ships first owns it; the other swaps in.
- **2.5 ↔ 3.3b** — 2.5 (XGBoost) trains on the orthogonalized factor matrix from 3.3b if it's ready, else raw.

**Rule.** If Track 3 Phase 3.1 slips, Track 2.2 still ships using existing 40 READY factors. Factor-model upgrade is value-additive, not gating.

**Reversal cost.** Low. If Track 3 loses traction: stop work on plan 0002, archive it, Track 2 is self-sufficient. The 10 hours of Track 3 scaffolding already done (apply_splits, news_volume) is independently useful.

**Consequences.** Resource allocation is a per-week call ("Track 2 or Track 3 this week?"). Backtest harness is shared. Two cockpit pages eventually emerge (`/portfolio`, `/factor-attribution`) — designed in parallel.
