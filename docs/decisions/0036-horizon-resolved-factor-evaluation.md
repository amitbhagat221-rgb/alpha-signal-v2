# 0036 — Horizon-resolved factor evaluation (IC term structure)

**Status:** Accepted (diagnostic shipped); promotion-gate change Proposed
**Date:** 2026-06-01

## Context
Every factor t-stat in the registry is computed against a **single** forward horizon — `fwd_return_20d` ([backtest_pit.py](../../tools/backtest_pit.py): `_response = fwd_return_20d`; the v1 C13b "36 monthly periods"). But factors don't share a horizon: short-term reversal, microstructure/liquidity, PEAD and news factors peak in days–weeks then **decay or flip**; value, quality, profitability, low-vol and forensic factors accrue edge over **months**. Judging all of them at 20d conflates "wrong horizon" with "no alpha" — a slow factor looks dead at 20d even when it's real. This is the standard IC-decay / alpha-horizon problem (Qian–Hua–Sorensen, *Quantitative Equity Portfolio Management*; Grinold–Kahn Fundamental Law `IR ≈ IC·√Breadth`, where breadth depends on horizon).

This came out of the same review that found `pick_outcomes` was scoring at 5/20 **calendar** days (5d ≈ 3 trading days = noise) while the backtest measures 20 **trading** days — a units mismatch now fixed (windows → 20/63/126 trading days).

## Decision
1. **Ship a read-only IC term-structure diagnostic** — [tools/ic_decay.py](../../tools/ic_decay.py). Computes Spearman IC vs forward return at a grid of horizons {5, 20, 63, 126, 252} trading days per (signal, cap_tier), reusing `backtest_pit`'s IC + Newey-West machinery (NW lag scaled up for the larger fwd-return overlap at long horizons). Classifies each factor's **natural horizon** = peak |mean IC|, bucketed FAST (≤20d) / MEDIUM (21–63d) / SLOW (>63d), with a sign-flip (reversal) flag. Outputs `output/ic_decay_report.txt`, `data/ic_decay.json`, and curve graphs `output/ic_decay_curves.png` (`--plot-only` redraws from JSON without the ~3-min recompute).
2. **Changes nothing in the live model yet** — no weights, no promotions. It is the evidence surface for deciding whether to evaluate/weight factors at their own horizon.

## Consequences
- First read (230 signal,tier classified): **FAST 54 · MEDIUM 41 · SLOW 132 · 131 sign-flippers.** Shapes are sensible — `delivery_anomaly_z` decays (fast microstructure), `value_composite` rises monotonically (slow value), `roic` grows negative (expensive-quality reversal). Confirms the heterogeneity.
- **Two confounds, do not over-read:** (a) raw IC mechanically grows with horizon (longer returns accumulate more signal), so "SLOW 132" is partly structural — the trustworthy read is the **shape + sign-stability**, not the absolute peak; (b) long horizons are survivorship-biased (current-names-only universe, ~4.4%/yr delisting) and thinner (fewer non-overlapping periods). `pt_upside` IC=0.67 / t=28 at 252d is an artifact, not alpha — consistent with it already being capped pending re-verify.
- **Proposed follow-up (needs its own decision):** store `natural_horizon` in the registry and switch the promotion gate from raw-IC t-stat to **net-of-cost IR at the natural horizon** (turnover-aware), then re-evaluate current weights. Composite shape (horizon-bucketed sleeves vs blended horizon-matched scores) is part of that decision. Ties into Track 3.3a (IC stability).
- Known limitation: the graph's "live = bold" highlight only matches factors whose `config.SIGNAL_WEIGHTS` key equals the backtest signal-id (the Track-3 promotions); the screener-name↔signal-id impedance mismatch is not papered over.
