# ADR 0074 — "Good enough" factor admission in MID only

**Status:** accepted 2026-10-13 (Amit: "small is already set, see if it improves anything for middle and large, then only relax and make it good enough, else let it be"). Amends [ADR 0043](0043-multiple-testing-aware-factor-significance.md) **for the MID tier only**. LARGE and SMALL keep 0043 / [0063](0063-weights-on-corrected-evidence.md) unchanged. Companion to [ADR 0073](0073-good-enough-book-deployment.md).
**Evidence:** [`tools/lh_relax_test.py`](../../tools/lh_relax_test.py) (pre-registered), [slow-core-tactical-2026-10.md §6](../studies/slow-core-tactical-2026-10.md).

## Decision

In MID, a factor may be wired on **grade-B** evidence at **half** the weight of a grade-A factor:
- **Grade A (unchanged):** |t| ≥ 2.5 on its own label.
- **Grade B:** 1.5 ≤ |t| < 2.5 with the same IC sign in both halves of the evidence window; weight ±0.5 relative to A.
- At most 12 factors in the tier.

**The test is the whole score, not the factor.** A grade-B addition is accepted only if the MID top-20 book, across 12 staggered start months after costs and tax, is no worse than without it.

Applying this to the live MID weights is a separate, pick-changing step: worktree branch, `backtest_pit` re-weighting, Amit's approval. This ADR sets the rule; it does not move a weight.

## Why

Walk-forward test, factors chosen each month from past data only (2022-06 → 2026-10). Top-20 book, 12 start months, measured costs and Indian tax:

| tier · model | strict (0043) median excess · starts beating index | relaxed (grade B at ½) | OOS IC strict → relaxed | pre-registered verdict |
|---|---|---|---|---|
| **MID fast (20-session, the live type)** | −2.2 %/yr · 0/12 | **+3.3 %/yr · 12/12** | 0.048 → 0.050 (IC21) | **relax** |
| MID slow (126-session) | +1.3 % · 9/12 | +0.9 % · 9/12 | 0.087 → 0.104 (IC126) | keep |
| LARGE fast | +5.1 % · 11/12 | +4.8 % · 12/12 | 0.008 → 0.047 | keep |
| LARGE slow | +5.6 % · 12/12 | +5.3 % · 12/12 | −0.004 → 0.061 | keep |

- The relaxed MID fast model mostly adds the momentum family at half weight: `mom_composite` 91 % of months, `mom_6m` 87 %, `residual_momentum_12_1` 77 %, `mom_12m` 66 %. It also adds `debt_structure` 66 %, `fcf_yield` 58 % and `announcement_car` 55 %.
- This is what the [winners post-mortem](../studies/winners-postmortem-2026-10.md) found missing.
- MID fast turnover falls from 5.2×/yr to 3.0×/yr.
- **Relaxing improves ranking (IC) in every MID and LARGE model, but books only in MID fast.** Where books didn't improve, the rule says keep the strict bar.

## What this does not claim

- The relaxed MID fast book is still weak as a book: +3.3 %/yr, median t 0.89, grade C under ADR 0073. The gain is in the quality of MID picks, not in a deployable MID book. MID money stays in the index.
- Grade-B factors are more likely to be luck. The half weight, the 12-factor cap and the whole-score test limit that. Re-check every 6 months; drop a factor whose sign flips.
- The universe is today's listed names (survivorship); costs are the 2026-10 Zerodha fill calibration.
