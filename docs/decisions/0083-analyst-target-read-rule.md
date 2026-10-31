# ADR 0083 — Analyst targets: rebased when read, shown as an upside only when plausible, current and ≥ 3 analysts

**Status:** accepted 2026-10-23 (Amit: "yes work on the suggested fixes"). Amends ADR 0076's analyst ≥ 3 rule (valuation only → every upside shown).

## Decision
- **One read rule for every surface** (stock page, Today, book expected return, Explorer, MCP `stock_analyst`, valuation football field, the weekly Yahoo sweep, `ANALYST_TARGET_IMPLAUSIBLE`): `views.target_basis` + `validators.plausibility.pt_status` / `rebase_targets`.
- **Rebase when read, never store a rebased target.** `target_basis` dates each target (the earlier of `price_target_changed_at` and the first monthly snapshot of the unchanged run) and multiplies the split / bonus / consolidation / demerger factors in `corporate_adjustments` with `set_by < ex_date <= today` (dividends left out).
- **Upside only when `pt_status == "ok"`.** Implausible (outside `PT_CLOSE_RATIO`) is hidden as before. Stale (price moved > `PT_STALE_MOVE` = 50 % since the target was set) and thin (< `PT_MIN_ANALYSTS` = 3) still show the target and analyst count, with the reason (`pt_note`), but no upside, and they stay out of the book's expected return.

## Why
- 2026-10-23: of 9 flagged targets, 2 were good calls on the old share basis (IFIB 20 on Re 1 shares = 200 after the 2026-10-13 consolidation; HEG 750 median = 280 after the 2026-09-07 demerger). The weekly sweep would have nulled both: right data destroyed.
- Rebasing in a writer does not hold. Yahoo keeps serving the stale value; after a 2:1 split it passes the 3× gate, overwrites the stored rebase each week and moves `price_target_changed_at`, so the stale call then looks freshly revised.
- One or two analysts is one or two opinions, not a consensus. ADR 0076 already refused them in valuation; the cockpit showed them as confident upsides (FINOP +210 % on one house). 276 of 941 targets (259 SMALL) have 1–2 analysts.
- A target the price has run 77 % past (KME, one analyst, unchanged since May) read as a −20 % "downside": the call predates whatever moved the price.

## Consequences
- 2026-10-23 live: 665 ok · 272 thin · 2 stale (KME, RATNA) · 2 implausible (HMSD, FINOP, stale calls; the Sunday sweep nulls them). Explorer shows an upside for 664 stocks. `ANALYST_TARGET_IMPLAUSIBLE` 4 → 2 bad.
- `ANALYST_TARGET_IMPLAUSIBLE` is now an `fn` check on rebased targets (drill: a pre-consolidation target passes). `ANALYST_TARGET_IS_PRICE` stays SQL (rebasing never moves a target onto the price).
- `set_by` is an upper bound (first seen, not first set). A share change between the real set date and the first observation is missed; the 3× gate still catches a large one.
- The `pt_upside` factor (`signals/consensus.py`, LIBRARY since ADR 0045) is untouched: factor values are not display.
- Tests: `tests/test_analyst_targets.py`, the drill in `tests/test_check_drills.py`.
