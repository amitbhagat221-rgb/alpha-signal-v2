# 0017 — Explicit two-tier factor registry
**2026-05-22 · Accepted**

**Decision.** A factor's tier (validated vs library) is now expressed via two structures in [db.py](../../db.py):

1. **`BACKTEST_SIGNALS`** — every factor that has a PIT column (or is on a clear path to one) gets an entry, regardless of t-stat. Status field tracks PIT-readiness (READY/PARTIAL/MISSING/PROPOSED/BLOCKED), `status_reason` carries the latest verdict.
2. **`FACTOR_LIBRARY`** — a flat list of signal ids that are computed but do **not** clear the `|t|≥1.5` promotion bar. Pure pointers into `BACKTEST_SIGNALS`, no duplicated metadata.

Validated tier = `BACKTEST_SIGNALS` entries with signal id **not** in `FACTOR_LIBRARY` **and** present in `SCREEN.weight_tiers`. Library tier = signal ids in `FACTOR_LIBRARY`.

**Why.** Before today, "library factor" was implicit — any `signal_*` step in `PIPELINE_STEPS` whose id wasn't in `BACKTEST_SIGNALS`. Track 3 factors accumulating in this no-man's-land made it impossible to answer "what library factors do we have?" without a `git log` + score-table archaeology session. Two complications hit at once:

- The plan-0007 cluster (`revenue_cv_5y`, `relative_turnover`, `relative_growth`, `share_momentum`) shipped in PIT but never got `BACKTEST_SIGNALS` entries because the CLAUDE.md rule "don't add to `BACKTEST_SIGNALS` until t-stat ≥ 1.5" was being interpreted as "don't register at all". `share_momentum` hit |t|=3.21 yet was invisible to the cockpit's factor inventory.
- Today's 4 new factors (`ccc`, `margin_slope`, `wc_intensity`, `interest_coverage`) would have repeated the pattern.

The fix: re-read the CLAUDE.md rule as a **scoring-weight** rule (don't add to `SCREEN.weight_tiers`), not a registry rule. Library factors get full `BACKTEST_SIGNALS` entries; `FACTOR_LIBRARY` makes their tier explicit.

**Promotion path** (encoded in [db.py](../../db.py) `FACTOR_LIBRARY` comment):
1. Backtest produces `|t| ≥ 1.5` on some cap-tier in `pit_ic_by_tier_v2`.
2. Signal id removed from `FACTOR_LIBRARY`.
3. Deliberate edit of `SCREEN.weight_tiers` per [docs/reference/signal-weights.md](../reference/signal-weights.md) — **not** mechanical.

**What stays the same.**
- CLAUDE.md rule "Don't edit `SCREEN.weight_tiers` mechanically" — the bar that gates real screener influence is unchanged. Only the registry-visibility rule loosened.
- `pit_ic_by_tier_v2` remains the source of truth for t-stats. Both `BACKTEST_SIGNALS.status_reason` and `FACTOR_LIBRARY` membership are summaries — re-derive after each `python -m tools.backtest_pit` run.

**Side effects.**
- `BACKTEST_SIGNALS` grew 41→52: 10 new entries (Track 3 — Library group) + `share_momentum` moved from un-registered to KEEP-validated.
- Cockpit's `data_health` / factor-card renderers iterate `BACKTEST_SIGNALS`, so the 10 new entries auto-appear. No code changes needed downstream.
- `FACTOR_LIBRARY` membership requires manual sync after each backtest — drift risk noted in [HANDOFF.md](../../HANDOFF.md) "Watch out". A `tools/verify_factor_library.py` is a future cleanup if drift becomes a problem.

**Rollback.** Remove `FACTOR_LIBRARY`; drop the 10 Track-3 entries from `BACKTEST_SIGNALS`. Reverts to the pre-2026-05-22 implicit-tier convention. No data loss — score tables and PIT columns are independent.

**Related.**
- CLAUDE.md "Critical Rules" — backtest hygiene: "Ship a factor module and its PIT helper as one unit" + "Don't add to `BACKTEST_SIGNALS` until t-stat ≥ 1.5 on at least one cap tier". The second rule is **clarified by this ADR** to apply only to `SCREEN.weight_tiers`, not the `BACKTEST_SIGNALS` registry itself.
- [memory:feedback_factor_count_vs_weighting](.) — two-tier architecture (validated → scoring, non-validated → library). This ADR is the implementation.
