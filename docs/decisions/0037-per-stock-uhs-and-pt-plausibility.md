# 0037 — Per-stock UHS + PT-plausibility guards

**Status:** Accepted
**Date:** 2026-06-01
**Extends:** [ADR 0033](0033-trust-pipeline-uhs.md) (Trust Pipeline + UHS)

## Context
A user spotted SPRE (Speciality Restaurants, ₹110) showing a **₹3960 sell-side PT (+3474%)** while the header badge read **UHS 90 · TRUSTED**. Two distinct failures:

1. **No PT-vs-price plausibility guard at the data layer.** Yahoo intermittently returns absurd `targetMeanPrice` for thinly-covered Indian small-caps (SPRE 35.7×, ABCO ₹34,485 = 159×). The Plan 0007 plausibility gate (`pt_upside_pct`, SMALL hard cap +200%) only validated *freshly-fetched* values **and** depended on `close_map`; a value written during a past Yahoo flicker (pre-gate) then persisted because subsequent fetches return `None` (→ `_fetch_one` early-returns, gate never re-runs). 16 such garbage PTs (+2 downside) sat live.

2. **The UHS badge was universe-wide, not per-stock.** `rollup_pick_uhs` averaged *factor* UHS rows, and `_gate_pass_rate` computed a universe-wide pass-rate (no `sid` filter). So **every SMALL pick returned the identical 90/plaus20/cons19/cov20** — the badge structurally could not reflect SPRE's individual bad datum.

## Decision
1. **Layered PT-plausibility guards.** (a) the per-fetch gate keeps owning fresh garbage (tier-aware → `route_on_plausibility` → quarantine + `gate_2_plausibility=0`); (b) **new `sweep_pt_plausibility()`** ([sources/yfinance_analyst.py](../../sources/yfinance_analyst.py)) runs daily after the fetch: nulls any *stored* PT >3×/<0.33× the close AND records a per-sid `gate_2=0` verdict via **`record_pt_plausibility_fail`** ([validators/plausibility.py](../../validators/plausibility.py)); (c) cockpit display guard never renders an implausible PT ([cockpit/api.py](../../cockpit/api.py)); (d) `PT_RATIO_IMPLAUSIBLE` backstop in [data_sanity.py](../../tools/data_sanity.py). The old silent source-drop was removed — it bypassed the verdict, so the stock's UHS wouldn't reflect the rejection.
2. **Per-stock UHS.** `_gate_pass_rate` takes an optional `sid`; `rollup_pick_uhs` computes **provenance / plausibility / consistency from THIS sid's `trust_verdicts`** over the pick's upstream tables, **falling back to the universe factor-mean** when the stock has no per-sid verdict (keeps coverage broad — no mass-PRELIMINARY). Freshness + coverage stay table/factor-level (a table's recency isn't per-stock).

## Consequences
- SPRE now scores **71 · REVIEW** (plaus 10), ABCO 74 · REVIEW; clean stocks differentiate (ZYDS/ZURI 91 · TRUSTED). The badge finally means what users read it to mean. The per-sid rollup is on-demand in the cockpit and persisted nightly via `batch_write_pick_uhs`.
- 18 garbage PTs nulled + 198 garbage-derived `consensus_signals` rows deleted; tonight's screener recomputes those picks' conviction without the contaminated consensus.
- **Known gaps (follow-ups):** (a) `FACTOR_UPSTREAM_TABLES` lists raw-data tables (`quarterly_income`) not the verdict source tables (`piotroski_scores`), so LARGE/MID plausibility leans on the fallback until the map is reconciled; (b) verdicts are date-stamped — today's verdict reflects on *today's* picks; older picks lag until the nightly sweep + next screener run. Both are acceptable given the daily cadence; reconcile the table-name map when extending gate_2 coverage to fundamentals.
