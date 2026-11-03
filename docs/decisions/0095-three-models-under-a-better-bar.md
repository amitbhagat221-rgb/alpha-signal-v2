# ADR 0095 — Paper books run three models per tier: Slow, Fast, Blend, each under a bar chosen by a pre-registered test

**Status:** accepted 2026-11-03 (Tier B: research and the paper-books page; no live weight, no sleeve change) · **Supersedes:** ADR 0092 §1–2 (six books, 3–4 weight options)

## Decision

1. Mid and Small each carry exactly three models: Slow, Fast, Blend. The cards have no model buttons. Multibagger and Published stay, with their basket sizes.
2. Slow uses the long-side bar: |t| ≥ 2.5, at least 24 training months, and the best-ranked fifth beat the tier with t ≥ 2. Fast uses the multiple-testing bar: Benjamini-Yekutieli 5 % over every eligible factor, at least 24 months. Blend is their mean. Rules: Slow as ADR 0073; Fast as ADR 0073; Blend top 20, sell below 50, 6-month hold.
3. `tools/model_select.py` holds the test and `--score` writes `data/lh/model_select/models.parquet`. Live `factors.SIGNAL_WEIGHTS` and the paper sleeve (`slow_v2`, `fast_select`) stay as they are; changing them is Tier A.
4. The frozen record restarted 2026-11-03, replayed to the 2026-11-02 anchor. The earlier six-book record is kept at `data/paper/paper_books.2026-11-02-six-books.json`.

## Why

Amit (2026-11-03): "have 3 models at max slow fast and blend and use a better bar, do backtesting and select the three models." The rule was committed before any result (e886d2e): one bar per model across both tiers, highest mean book t on 2022-06 to 2026-06, the stricter bar on a tie within 0.25, June 2026 onward held out.

## Consequences

- Every model is grade C (ADR 0073). The tiers' money stays the index. Evidence: [study](../studies/model-select-2026-11.md).
- The better bar added nothing to Slow (Small −1.0 pp/yr, t −0.18); it won the tie-break. It helped Fast in Small (+6.1 pp/yr, t 1.55).
- Mid Fast is mostly cash in the test and now rests on one factor with unverified estimates and tied ranks. The card says so. It stays because the rule chose it.
- Slow IC-weighted, the no-bar control, was the strongest slow result in Small (+17.2 %/yr, t 2.18). It stays a control; adopting it would be a new decision on seen data.
- The monthly job must run `tools.model_select --score`, then `tools.paper_books`, after that anchor's close is loaded (Tier A: the recipe is in HANDOFF).
