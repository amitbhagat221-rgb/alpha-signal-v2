---
paths:
  - "factors.py"
  - "pit.py"
  - "config.py"
  - "sleeves.py"
  - "portfolio_construction.py"
  - "signals/**"
  - "scoring/**"
  - "eligibility/**"
  - "tools/backtest_pit.py"
  - "tools/reconstruct_pit.py"
  - "tools/lh_*.py"
  - "tools/factor_*.py"
  - "tools/promotion_gate.py"
  - "tools/multiple_testing.py"
  - "tools/optimize_weights.py"
  - "tools/paper_sleeve.py"
  - "tools/classify_micro_tier.py"
---
# Factors, scoring and backtests

**Tiers**
- `scoring/segment.py` re-tiers LARGE/MID/SMALL monthly (±10 % hysteresis) before the screener; `tools/classify_micro_tier.py` carves MICRO. Live tiering uses `pit.tier_inputs`, the backtest's own inputs (ADR 0065).

**One factor, one function**
- The screener takes every factor from `pit.features_at(today)` — the same code the backtest panel stores. Input hygiene (consolidated filter, Financials exclusion) lives INSIDE the compute function, never in a live-only loader.
- Register every factor ONCE in `factors.FACTORS` (compute producer, range, cadence, eligibility, bench, and — if wired — `weights: {tier: w}`). `BACKTEST_SIGNALS`, `FACTOR_LIBRARY`, `PIT_COLUMNS`, `SIGNAL_WEIGHTS`, lineage reads are derived — `tests/test_factor_registry.py` (ADRs 0017, 0052).
- A wired factor with no value scores as the middle of its tier (`config.MISSING_FACTOR_SCORE`); never re-spread its weight over other factors (ADR 0064). A result print is `factors.RESULT_FILING_SQL`, not `category='Result'` alone.
- A weight sits on the column its evidence was measured on.

**Prices and shares on one basis (ADR 0065)**
- Market cap is `signals._fundamentals.market_caps` (live tiers, backtest tiers, MICRO carve-out, `stocks.market_cap_cr` in ₹ crore). Per-share values come from `shares_and_book`; returns from adjusted prices (`pit.forward_returns` is the one label). Never divide a vendor share count by a raw close.

**Financials (ADR 0048)**
- Financials rank through the MAIN screener with generic weights, not a sub-model. `accruals` + `piotroski` are INELIGIBLE for Financials in `eligibility/registry.py`, so `eligible_coverage` renormalizes. `financial_signal_scores` is display-only (within-financials IC t 0.73). A mis-wired eligibility once silently dropped every MID Financial from `daily_picks`.

**Evidence bars**
- No `weights` until t ≥ 1.5 on at least one cap tier, never mechanically — `docs/reference/signal-weights.md`; run the multiple-testing haircut (ADR 0043) in every promotion review.
- Judge a book (not a factor) on ≥ 20 names across 12 staggered start months (`tools/lh_timing_luck.py`): one 10-name start swung +0.8 % vs +18.4 %/yr on the same rule. Fast scores only via walk-forward `fast_select`; live weights on history are in-sample.

**Hindsight inputs**
- `policy_events` / `sector_policy_pit` is a hand-curated 2026 list (hindsight weights, outcomes as events): never in a backtest or a score — `tools/mb_thesis_v2.py` docstring, plan 0026 1b.

**PIT writes**
- `reconstruct_pit.py` writes only the columns the requested signals produced, so `--signal X` is safe on existing dates. Never pad missing `PIT_COLUMNS` with NaN before the write — the UPDATE would wipe every untouched column.
