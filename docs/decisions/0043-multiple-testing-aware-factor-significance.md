# ADR 0043 — Multiple-testing-aware factor significance (HLZ haircut)

**Status:** accepted · 2026-06-14
**Context:** Track 3.3a evaluation methodology; extends [ADR 0036](0036-horizon-resolved-factor-evaluation.md) / [ADR 0038](0038-horizon-resolved-promotion-gate.md); ↔ [ADR 0017](0017-factor-library-two-tier-registry.md).

## Context

We have backtested **269 deduped (signal, tier) hypotheses** (`pit_ic_by_tier_v2`). Selecting
winners by the naive `|t|≥2.5` "KEEP" bar ignores multiple testing: under the null, 269 tests at
α=0.05 yield **~13.5 false discoveries by chance** — and we currently read 33 KEEPs. Harvey-Liu-Zhu
(2016, "…and the Cross-Section of Expected Returns") show the equity factor zoo needs a higher bar
(|t|≈3.0) once the search is accounted for.

## Decision

Adopt a standing **read-only** multiple-testing diagnostic — [tools/multiple_testing.py](../../tools/multiple_testing.py)
— over the full t-stat cross-section. One test per (signal, tier), represented by its most-powered
source; two-sided p from Student-t (df=n−1, so thin-n KEEPs are penalised). Report Bonferroni / Holm
(FWER) and Benjamini-Hochberg / **Benjamini-Yekutieli** (FDR). **BY is the headline** — it controls FDR
under arbitrary dependence, which correlated factor tests have.

**`|t|≥2.5` is necessary, not sufficient.** The Bonferroni bar at our M is **|t|≈4.2**; BY-FDR passes
only **8 of 269** (5 wired). The robust core that survives BY: **pt_upside (all tiers), pledge_quality,
delivery_anomaly_z**. Borderline (pass BH, fail BY): governance_resignation, iv_skew_25d, sector_tilt.

**Evidence only — this does NOT mechanically unwire anything** (same stance as ADR 0038; weights stay a
human decision). Factors kept as deliberate diversification ballast or on doubly-validated v1×v2 history
(consensus, book_to_price, piotroski, accruals…) stay wired on that rationale. But: (a) a factor that
**fails the haircut is not given *added* weight**, and (b) a **new** factor's KEEP must be read through
this lens before wiring.

## Consequences

- Retroactively confirms 2026-06-14 calls: `uncertainty_word_density` LARGE t=2.9 → p_BY=0.53 (parked,
  correct); thin-n KEEPs (eps_growth_yoy n=8, avg_delivery n=5, sentiment_7d n=4, promoter_trend n=6,
  iv_term_structure n=7) all fail → `FACTOR_LIBRARY` parking justified.
- Run `python -m tools.multiple_testing` in factor-promotion reviews alongside the horizon gate.
- Does not replace the gate (net-of-cost horizon) — it is the orthogonal *data-mining* lens.
