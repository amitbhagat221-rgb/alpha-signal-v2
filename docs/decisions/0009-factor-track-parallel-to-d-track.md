# 0009 — F-track runs parallel to D-track (no blocking)

**Status:** Accepted
**Date:** 2026-05-04
**Decided by:** Amit (with Claude Code)

## Context

The original v2 master plan ([v1 CLAUDE.md](../../../alpha-signal/CLAUDE.md)) was a two-track plan:

1. **Engineering track** — rewrite v1 scripts as a clean SQLite + Python codebase. Shipped on 2026-05-01.
2. **Intelligence track (D-phases)** — graduate from a per-tier ranked list into a real portfolio with sector sub-models, cyclical overlays, segment weights, regime overlay, and per-stock/per-sector position discipline. Phases D14 ✅ → D15 → D16 → D17 → D18.

A 2026-05-04 audit added a third track:

3. **Factor-depth track (F-phases)** — scale from the current 42 factors to ~100, then upgrade scoring from weighted-sum to a real factor model with IC-stability weighting, orthogonalization, mean-variance portfolio construction, and Barra-style risk decomposition. Phases F1 (data) → F2 (50 new factors) → F3 (factor model upgrade). See [docs/plans/0005-100-factors-and-model.md](../plans/0005-100-factors-and-model.md).

The decision question: how does F-track relate to D-track on the timeline?

There were two legitimate options:

- **(a) Sequential.** Finish D17 (capstone) and D18 (XGBoost overlay), then start F-track. Conceptually clean — one track at a time.
- **(b) Parallel.** F-track and D-track run concurrently with documented integration points where they touch.

D18 is data-blocked until ~early 2027 (needs ≥6 months of accumulated PIT snapshots). Option (a) means F-track doesn't start for 12+ months.

There are two integration points where the two tracks would touch:

- **F3.3 (mean-variance portfolio construction)** vs **D17 (segment models + portfolio construction).** Both produce per-stock weights. Whichever ships first owns `portfolio_holdings`; whichever ships second swaps in.
- **F3.2 (orthogonalization)** vs **D18 (XGBoost overlay).** XGBoost trains best on orthogonalized features; raw correlated features cause feature-importance instability. F3.2 should ship before D18 is trained.

## Decision

**F-track runs parallel to D-track.** Both are tracked in the project blueprint ([0003-mother-plan.md](../plans/0003-mother-plan.md)). Integration points are documented:

- F3.3 ↔ D17 — whichever ships first owns the portfolio construction surface; the other swaps in. Both write to the same `portfolio_holdings` table.
- F3.2 ↔ D18 — D18 trains on the orthogonalized factor matrix from F3.2 if F3.2 has shipped; on the raw factor matrix otherwise.

**Hard rule:** D-phases must not block on F-phases. If F1 takes longer than expected, D15 still ships using the existing 40 READY factors. The factor-model upgrade is value-additive, not gating.

## Alternatives considered

- **Sequential (option a).** Rejected — loses 12+ months waiting for D18. Most retail quant projects collapse precisely because they spend years on the *first* track and never reach the *second*. Parallelism is risk reduction, not premature scope.
- **Informal parallel.** No documented integration points. Rejected — without explicit handoff, D17 and F3.3 will both write to `portfolio_holdings` with subtly different schemas, and we'll discover the conflict after both ship. Better to declare the seam now.
- **Single combined track.** Merge F-phases into the D-ladder as D19/D20. Rejected — D-phases are about *deployment of validated signals*; F-phases are about *deepening the model itself*. Conflating them muddles the per-phase definition-of-done. They share a registry but not a goal.
- **Defer F-track to a v3.** Rejected — there's no architectural reason to wait. v2 has spare capacity in the registry, the PIT reconstruction harness is general, and the F-track work strengthens (rather than refactors) what's already built.

## Reversal cost

**Low.** If the F-track loses traction or the user decides factor depth isn't worth the dev time:

- D-track is fully self-sufficient. D17 ships portfolio at equal-weight; D18 trains on existing factors. Neither phase has a hard dependency on F-track output.
- No code change required to roll back. Stop work on plan 0005, archive it, continue D-track.
- The ~10 hours of F-track scaffolding work already done (apply_splits, news_volume signal, Screener strategy doc) is independently useful — improves momentum signal quality and adds 2 factors regardless.

## Consequences

- **Resource allocation becomes a per-week call.** "This week: D-track or F-track?" needs a deliberate answer. The mother plan has both phase ladders visible to support that.
- **Two parallel cockpit pages will eventually emerge.** D17's `/portfolio` and F3.4's `/factor-attribution`. Designed in parallel to avoid duplication.
- **Backtest harness is shared.** [tools/backtest_pit.py](../../tools/backtest_pit.py) services both tracks — no fork.
- **Plan 0005 is now load-bearing.** It's the F-track spec. Treat it with the same discipline as v1's `D14_claude_code_instructions.md`.
