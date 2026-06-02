# 0038 — Horizon-resolved, net-of-cost promotion gate

**Status:** Accepted (gate shipped as an evidence surface; weight changes remain a separate human decision)
**Date:** 2026-06-02
**Extends:** [ADR 0036](0036-horizon-resolved-factor-evaluation.md) (the diagnostic) · ↔ Track 3.3a

## Context
ADR 0036 shipped the read-only IC term-structure diagnostic and proposed a follow-up: *store the natural horizon and switch the promotion gate from the single-20d t-stat to net-of-cost IR at the natural horizon (turnover-aware)*. Until now promotion was a human reading a 20d t-stat off `pit_ic_by_tier_v2` — which conflates "wrong horizon" with "no alpha" for slow factors, and over-credits fast factors whose edge is eaten by turnover cost.

## Decision
Ship [tools/promotion_gate.py](../../tools/promotion_gate.py) + the `factor_horizon_gate` table (one row per signal × cap_tier). For each (signal, tier) it computes the IC term structure (reusing `ic_decay` / `backtest_pit` machinery in one pass so σ(fwd_h) is computed alongside IC) and emits a PROMOTE / LIBRARY / REJECT verdict at the factor's **cost-resolved natural horizon**.

**One objective drives both the horizon and the verdict — net-of-cost annualised IR.** This is the key design choice. We do *not* pick the horizon by raw peak |IC| (ADR 0036's explicit warning: raw IC is mechanically inflated at long horizons + survivorship-biased). Instead:

- Per-period gross active return ≈ `IC_h · σ(fwd_h)` (Grinold–Kahn), σ(fwd_h) = cross-sectional dispersion of h-day forward returns (grows ~√h).
- Cost in IC units = `T · c_side(tier) / σ(fwd_h)`, with `c_side = TRANSACTION_COSTS_BPS/1e4` (LARGE 30 / MID 50 / SMALL 150 bps per side) and `T` = one-way turnover per rebalance at the natural horizon (default **0.3** — a z-scored factor reconstitutes ~25–35% of the book each rebalance; T=1.0 implies absurd annualised turnover and rejects everything). Because c_side is fixed while σ grows ~√h, **the cost shrinks as the horizon lengthens — fast factors are charged more**, which is the turnover-awareness ADR 0036 asked for.
- `net_ic = max(0,|IC_h|−cost)·sign` → `net_t = (net_ic/std_ic)·√n` → `net_IR_yr = (net_ic/std_ic)·√(252/h)`.
- **natural horizon h\*** = argmax of net annualised IR over horizons with ≥5 non-overlapping periods, with a survivorship guard (a 252d horizon with <8 periods can't be h\*). Verdict at h\*: PROMOTE if net_t ≥ 2.0 AND sign-stable; LIBRARY if 1.5 ≤ net_t < 2.0; REJECT otherwise (or if cost eats the whole edge).

It writes `factor_horizon_gate` + `output/promotion_gate.txt`. **It does not touch `config.SIGNAL_WEIGHTS`** — promotion stays a human decision (CLAUDE.md: "never mechanically"); this is the evidence the decision now reads. `--reeval-live` re-scores only the production-wired factors (the ADR's "re-evaluate current weights" step); `--turnover` tunes the cost assumption.

## Consequences
First read (242 signal,tier scored, turnover=0.3): **PROMOTE 36 · LIBRARY 40 · REJECT 163.**

- **The central ADR 0036 thesis is quantified.** Slow value/quality factors that look dead at 20d PROMOTE at their long natural horizon: `value_composite` SMALL (252d, net_t 19.5, IR 3.7), `book_to_price` SMALL/MID (252d/63d), `earnings_yield` SMALL (252d), `ccc` / `nwc_to_revenue` / `fcf_yield` SMALL (252d). `kyle_lambda` (Amihud illiquidity) promotes on all three tiers at 63–252d — the illiquidity premium, consistent with its raw 20d KEEP.
- **The cost-aware horizon selection works — it dodged the artifact ADR 0036 named.** `pt_upside`'s natural horizon resolved to **5d** (FAST, IR ~8–10), *not* the survivorship-inflated 252d (IC 0.67/t=28) the ADR flagged — because at 5d its net IR is far higher. The objective self-corrected; we didn't have to special-case it.
- **Live re-eval: 8/18 production (signal,tier) clear the net-of-cost bar at their natural horizon.** The 10 that don't are informative, not alarming: `earnings_yield`/MID and `book_to_price`/LARGE land LIBRARY (sign-unstable across horizons / just under the bar); the fast wired factors `delivery_anomaly_z` LARGE+MID and `iv_skew_25d` SMALL REJECT because at their 5d natural horizon turnover cost eats the edge. These are **candidates for a weight review**, surfaced for a human — no weight was changed.
- **New §3.2.7 betas resurface at their natural horizon:** `gold_beta` LARGE (126d, net_t 4.7) and `metals_beta` MID (126d, net_t 2.7) PROMOTE — better than their raw-20d WEAK/DROP verdict, because the cyclical exposure pays off over a quarter, not a month. n is thin (~19) so treat as a hint pending more history.

**Known limitations (read verdicts as evidence, not gospel):**
- **252d survivorship persists.** The guard only blocks *thin* 252d (n<8); the v1 archive's long horizon is still current-names-only (~4.4%/yr delisting), so 252d net_t magnitudes are inflated. The annualised IR column is the fairer cross-horizon comparator. A delisting-adjusted panel would be the real fix.
- **Cost model is a one-parameter approximation** (constant T at the natural horizon, gross ≈ IC·σ_fwd which understates the decile-spread return → conservative). Relative ordering is robust to T∈[0.2,0.5]; absolute net_t is not a portfolio backtest.
- The gate is on-demand, not in the daily pipeline (it's a promotion-review tool, not a monitor).

## Next
Use `--reeval-live` output to decide weight changes deliberately (signal-weights.md process), starting with the sign-unstable LIBRARY live factors and the cost-rejected fast ones. Feeding `factor_horizon_gate` into the `/system` Promotion Funnel is a candidate follow-up.
