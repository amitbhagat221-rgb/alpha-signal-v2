# ADR 0048 — Financials rank through the generic screener, not a sub-model

Status: accepted 2026-07-05 · Supersedes the old CLAUDE.md "route through the financial sub-model" rule · Related [ADR 0045](0045-pull-pt-upside-lookahead.md)

## Context
CLAUDE.md claimed Financials route through a dedicated `financial_signal_scores` sub-model.
The shipped path never did — Financials were always ranked by the generic `SIGNAL_WEIGHTS`, and
the sub-model (`signals/financial_signal.py` → `financial_signal_scores`) is consumed only by the
cockpit dossier, nothing in `scoring/`. A 2026-07-05 evidence run settled whether to wire it:
over 36 clean monthly anchors, the tier-routed sub-model's within-financials IC is **t=0.73**
pooled (best single cell MID recovery t=1.83, fails the ADR 0043 multiple-testing bar), covers
only ~50% of the ex-MICRO financial universe, and its Screener-sourced input is auth-fragile. The
generic score's IC *inside* Financials was positive on every observable window. So: keep generic.

Separately, a **live regression** surfaced: after ADR 0045's pt_upside pull + renormalization, all
MID Financials vanished from `daily_picks`. Cause — `eligibility/registry.py` marked Financials
ELIGIBLE for `accruals` + `piotroski` (they have the underlying tables), but those signals are
structurally NULL for banks, so their `weight_coverage` fell below the pick gate and
`eligible_coverage` couldn't rescue them (the ineligibility that would have was never recorded).

## Decision
1. Financials rank through the **main screener with generic weights** — no separate sub-model in
   the ranking path. `financial_signal_scores` stays dossier/display-only.
2. Mark `accruals` + `piotroski` **INELIGIBLE for Financials** in `eligibility/registry.py`
   (`WHERE sid NOT IN (SELECT sid FROM stocks WHERE sector='Financials')`) — mirrors the
   `sector_exclusions: ["Financials"]` already in `lineage.py`. `eligible_coverage` then
   renormalizes over the signals that apply to banks (book_to_price, earnings_yield, consensus,
   promoter, momentum — all meaningful for financials).

## Consequences
- MID Financials restored: today's `daily_picks` MID 117→136 (+19 Financials), LARGE/SMALL
  unchanged. `refresh_eligibility` is a pipeline step before the screener, so this persists nightly.
- Sub-model promotion is deferred, not dead: re-review once Screener auth is stable AND a 63/126d
  slow-horizon test is run (bank asset-quality is plausibly a slow factor, cf. accruals-MID).
