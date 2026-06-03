# 0039 — Multibagger screen: 3-stage funnel, regime-dominated over 2–4yr

Date: 2026-06-03 · Status: accepted (validation-stage; NOT wired to production)

## Context
User asked for a model to identify multibaggers (3–10x / 2–4yr) in Indian small/mid caps. Three research passes (`docs/reference/multibagger-research.md` [adversarially verified, 17 confirmed/8 refuted], `Quantifying Indian Multibagger Stocks.md`, `deep-research-report.md`) converged on a quality-gated value funnel with a hard forensic exclusion; the strongest standalone factor is Novy-Marx gross-profitability, which we didn't have.

## Decision
- A **SEPARATE** screen (`multibagger_scores`, `/multibagger`), OUT of `daily_picks` — different objective + horizon.
- Architecture = **3-stage hurdle/filter funnel** (forensic + leverage gates → ROIC/growth/size hurdles → composite rank with a growth×cheapness *interaction* term), NOT a flat weighted composite.
- New anchor factor `gross_profitability` (full contract + PIT); Beneish gate REUSES `forensic_scores.m_score_flag`.
- Validate by survivorship-corrected, split-adjusted **cohort study** (top-decile ≥3x tail-capture), NOT 20d rank-IC (which calls quality DROP — the wrong lens, per ADR 0036).

## The finding that shapes everything
Across two regimes, the screen's edge FLIPS sign:
- **2022→26 small-cap junk rally:** quality top-decile UNDERperforms (spread −0.30x; bottom decile > top); cheapness helps.
- **2018→21 quality-led bear:** quality OUTperforms (spread +0.10x; top > bottom); cheapness hurts.
- Multibagger base rate is regime-gated (13.4% ≥3x in the rally vs 2.6% in the bear).

⇒ **2–4yr multibagger capture is regime-dominated, not quality-dominated.** The Coffee-Can / Marcellus quality thesis is a multi-DECADE compounding story, not a 2–4yr 3-10x one.

## Consequences
- A regime gate (small-cap EMA, Report C) is ESSENTIAL, not optional; factor weights should be regime-conditioned.
- DO NOT calibrate funnel thresholds to any single window — the two known regimes calibrate to opposite extremes.
- Data unlocked: `corporate_actions` backfilled to 2018 (split adjustment); survivorship-true universe via the bhavcopy archive (`historical_universe`). Free, no paid feed.
- Pairs with plan `docs/plans/0008-multibagger-model.md`.
