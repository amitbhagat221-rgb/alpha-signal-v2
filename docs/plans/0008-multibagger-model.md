# 0008 — Multibagger Identification Model

Status: Phase 1 shipped (build), Phase 2b regime-validated, Phase 3–4 queued. Started 2026-06-03 (off an HBL Engineering "+727%" news item).
Full design: `~/.claude/plans/i-was-going-theough-polished-dolphin.md` · Research: `docs/reference/multibagger-research.md` (adversarially verified), `docs/reference/Quantifying Indian Multibagger Stocks.md`, `docs/reference/deep-research-report.md`, `docs/reference/multibagger-data-requirements.md` · Decision: [ADR 0039](../decisions/0039-multibagger-funnel-regime-dominated.md).

## Goal
Identify multibagger candidates (3–10x / 2–4yr) in upper-SMALL/MID Indian equities via a **SEPARATE** 3-stage hurdle/filter funnel (`multibagger_scores`, `/multibagger`), kept **OUT of `daily_picks`** (different objective + horizon).

## Phases
- ✅ **Phase 0** — research (3 reports consolidated) → design. Verdict: quality-gated value funnel, growth-weighted, forensic exclusion, tail-capture validation.
- ✅ **Phase 1** — `signals/gross_profitability.py` (Novy-Marx anchor, full contract + PIT twin, goods-business floor) + `signals/multibagger.py` (S1 gates → S2 hurdles → S3 rank w/ growth×cheapness interaction) + `multibagger_scores` table. 1667→955 gates→**35 survivors**. Beneish gate REUSES `forensic_scores.m_score_flag`. New funnel inputs (pat_cagr/earnings_acceleration/de/ep/peg) computed inline from annual Net profit.
- ✅ **Phase 2b** — survivorship-corrected + split-adjusted cohort study. `tools/build_historical_universe.py` + `historical_universe` (bhavcopy archive, incl. delisted); `tools/multibagger_cohort.py`. Backfilled `corporate_actions` to 2018. **Two-regime finding** (ADR 0039): 2022→26 rally quality UNDERperforms (−0.30x), 2018→21 bear quality OUTperforms (+0.10x) → regime-dominated.
- ⏳ **Phase 2b+** — small-cap EMA regime gate + regime-conditioned weights + ≥1 more independent window (e.g. 2019→2022).
- ⏳ **Phase 3** — acquired-data signals (SME-migration, order-book/TTM, auditor/contingent, earnings calendar) + forensic-trio gates (cfo_ebitda, cwip_gross_block, cfo_pat); deep historical shareholding (for full-funnel PIT — only minor gap left).
- ⏳ **Phase 4** — `/multibagger` cockpit page + weekly `PIPELINE_STEPS` + dossier badge (no-raw-numbers).

## Done when
The funnel, gated on regime, shows a positive survivorship-corrected top-decile ≥3x capture across **≥3 independent regime windows**. Until then: validation-stage, NOT wired to production scoring. Never calibrate thresholds to a single window (the two known regimes calibrate to opposite extremes).
