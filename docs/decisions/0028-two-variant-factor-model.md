# 0028 — Two-variant factor model: MaxReturn + MaxSharpe from PIT IC

**Status:** Accepted
**Date:** 2026-05-28

## Context
`SIGNAL_WEIGHTS` in [config.py:51](../../config.py#L51) was hand-tuned from the C13b validation in early 2026. The PIT IC backtest has since expanded to **219 (signal × cap_tier) rows** in `pit_ic_by_tier_v2`, but only 8 of those signals carried weight in production. When [tools/optimize_weights.py](../../tools/optimize_weights.py) was run for the first time, the result was stark:

| Tier | Weight on factors already wired into the screener | Weight on backtested-but-unwired factors |
|---|---:|---:|
| LARGE | 14% | **86%** |
| MID | 15% | **85%** |
| SMALL | 35% | **65%** |

The biggest two misses were `pt_upside` (t = 7.15 / 8.40 / 9.14 across tiers) and `eps_growth` (t = 5.31 LARGE, 3.23 SMALL). Both already lived in `consensus_signals` — wiring them into the screener was a one-line column add.

Separately, two objectives are defensible for combining IC into a composite, and they're not equivalent:
- **MaxReturn** — weight each factor by absolute t-stat. Bets on the factors with biggest expected spread between top and bottom deciles. Higher expected return per trade, higher variance.
- **MaxSharpe** — weight each factor by ICIR (mean IC ÷ vol of IC). Bets on consistency over magnitude. Lower expected return per trade, lower variance.

Production needs to choose; the prior model picked neither explicitly.

## Decision
1. **Wire `pt_upside` + `eps_growth` into the production screener** ([scoring/screener.py:_load_signals](../../scoring/screener.py)). Universe coverage: LARGE 100%, MID 95%, SMALL 43%. NULL pt_upside handled by `eligible_coverage`.
2. **Clip `pt_upside` to ±50/+150% on output** in [signals/consensus.py:178](../../signals/consensus.py#L178) — yfinance occasionally returns broken PTs for thin-coverage SMALL caps (CCAVENUE +33,522%, ABCOTS +15,894%). Spearman IC is rank-invariant so the t=9 backtest is unaffected, but per-stock dashboards would surface the absurdity. 18 existing rows updated in-place.
3. **Maintain two backtest-derived weight schemes in parallel** in [config.py:79-129](../../config.py#L79-L129):
   - `SIGNAL_WEIGHTS_RETURN` — `w_i ∝ |t_i| × sign(IC_i)`, per tier, KEEP-only (|t|≥2.5).
   - `SIGNAL_WEIGHTS_SHARPE` — `w_i ∝ |ICIR_i| × sign(IC_i)`, same filter.
   Both rebuilt by `python -m tools.optimize_weights` from `pit_ic_by_tier_v2`. Aggressive normalisation (no caps, no diversification floor) — pt_upside takes 33-47% in LARGE/MID. Tradeoff accepted: model degrades hard if pt_upside breaks; mitigated by the source-redundancy review in `pt_source_landscape_2026_05_23` memory.
4. **Negative-weight signals are honoured** in `score_universe()` — inverse-IC factors (e.g. `cf_accruals_ratio` MID t=-2.53) get a sign-flip on the percentile (`1 - pctile`) before the weighted sum. Keeps the directionality consistent across all factors.
5. **`scoring/screener` accepts `--variant {production, return, sharpe}`**. Variants are print-only — they do NOT write to `daily_picks`. Promoting one to live requires either replacing `SIGNAL_WEIGHTS` outright, OR adding a `variant` column to `daily_picks` (PK becomes (sid, pick_date, variant)) and running all three nightly. Deferred until 30-day side-by-side track.
6. **Variant runs use a lower `eligible_coverage` gate** (0.40 vs production's 0.60) — the variants concentrate ~40% of SMALL weight on analyst-dependent signals (pt_upside, eps_growth), and the strict gate kicked out 864 SMALL caps without analyst coverage, leaving SMALL top-5 starting at rank 20. The relax keeps the non-analyst-covered SMALL caps rankable.
7. **Cockpit page** [/model/variants](../../cockpit/templates/model_variants.html) runs all three live (10s cold / 0s warm via 30-min disk cache at `data/.cockpit_cache/model_variants__top_per_tier=N.pkl`); 3-column side-by-side with each variant's per-tier weight breakdown + top-N picks; divergent picks (appearing in only one variant's tier top-N) marked with ★.

## Rationale (alternatives weighed)
- **Single backtest-derived scheme, hand-pick objective** — clean, but loses the ability to see how much the weight scheme drives the picks. The /model/variants comparison is the most informative diagnostic this codebase has produced; killing one scheme to look cleaner is the wrong tradeoff.
- **Mean-variance over per-date IC matrix** (full Markowitz on the IC time-series) — formally cleaner but needs the per-date IC stored per (signal, tier), which `pit_ic_by_tier_v2` doesn't expose (only aggregates). Defer to §3.3b orthogonalization once the per-date IC table lands.
- **Conservative caps on max-weight per factor** (e.g. 30% cap) — user explicitly chose "aggressive" — let pt_upside dominate where it earns the right via t-stat. The cap is a future option if pt_upside fragility becomes a problem.
- **Promote a variant immediately to `daily_picks`** — too fast given (a) production is on cron with downstream consumers (dossier, morning_brief, action_queue), and (b) no out-of-sample confirmation yet. The 30-day side-by-side is the cheapest hedge against an overfit weight scheme.

## Constraints / known limits
- **Single-factor concentration risk** — pt_upside taking 33-47% means the model is roughly 1/3 to 1/2 a price-target-momentum bet. If yfinance changes its `analystTargetPrice` API, all three tiers degrade simultaneously. The fallback path through Tickertape `forecast_history` documented in `pt_source_landscape_2026_05_23` memory is the planned mitigation.
- **No out-of-sample validation** — the backtest is the same 35-period PIT IC window the optimizer is fit to. Hold-out splits were considered (Q1 2026 as test) but ruled out: 6 months of test data isn't enough to discriminate between RETURN and SHARPE given factor signal noise. The 30-day live side-by-side is the substitute.
- **MID has only 3 factors at |t|≥2.5** (pt_upside, accruals, consensus) so the MID variants are thin. As more bench factors get wired (interest_coverage, ccc, nwc_to_revenue, goodwill_to_assets all have MID t-stats > 2.5), MID variants will broaden.
- **Variants are CLI/cockpit only, no DB persistence** — the per-variant pick history doesn't exist. Building it needs the daily_picks PK change above.

## Consequences
- Production picks change today. Pre-this commit, screener computed picks ignoring pt_upside (was loaded but had zero weight via SIGNAL_WEIGHTS). Post-this commit, SIGNAL_WEIGHTS is unchanged but pt_upside + eps_growth are loaded — they only affect picks when a future commit wires them into SIGNAL_WEIGHTS. **Net behaviour today: production picks identical to yesterday. Variant picks visible at `/model/variants`.**
- The hand-tuned weights in `SIGNAL_WEIGHTS` are now plausibly obsolete. Next session should run the optimizer's MaxReturn scheme through the same daily_picks consumers (dossier, morning_brief, action_queue) in a `daily_picks_experimental` table for 30 days, then decide which to promote.
- Backtest results in `pit_ic_by_tier_v2` are now load-bearing: when factors are added/removed/re-tested, both `SIGNAL_WEIGHTS_RETURN` and `SIGNAL_WEIGHTS_SHARPE` need re-running. Add a docstring pointer to optimize_weights.py from any future weights-touching change.
- 4-7 more bench factors (`pledge_quality`, `delivery_anomaly_z`, `interest_coverage`, `ccc`, `roic`, `fcf_margin`, `nwc_to_revenue`) are the next-cheapest wiring targets — 1-2 lines each, would drop the unwired share from 86% to <20% in LARGE/MID.

## Files
- [tools/optimize_weights.py](../../tools/optimize_weights.py) — reads `pit_ic_by_tier_v2`, emits the two weight blocks. Maps `signal_id` → production key via `SIGNAL_ID_TO_KEY`; tracks `WIRED_KEYS` set so the coverage report flags "needs wiring" warnings.
- [config.py:51](../../config.py#L51) — `SIGNAL_WEIGHTS` unchanged (production), `SIGNAL_WEIGHTS_RETURN` + `SIGNAL_WEIGHTS_SHARPE` added at line 79-129.
- [scoring/screener.py](../../scoring/screener.py) — `_load_signals` reads pt_upside + eps_growth; `score_universe(df, weights=None)` accepts override; `_pick_eligible(df, min_eligible=None)` accepts relaxed gate; `compute(variant=...)` flag.
- [signals/consensus.py:178](../../signals/consensus.py#L178) — `pt_upside.clip(lower=lo, upper=hi)` on output.
- [cockpit/api.py:1438-1513](../../cockpit/api.py#L1438) — `get_model_variants(top_per_tier=10)` with 30-min disk cache.
- [cockpit/app.py:378](../../cockpit/app.py#L378) — `/model/variants` route.
- [cockpit/templates/model_variants.html](../../cockpit/templates/model_variants.html) — 3-column comparison + divergent-pick ★ + footnote.
- [cockpit/templates/base.html:80](../../cockpit/templates/base.html#L80) — nav entry.

## Decision pending
**Which variant becomes live `daily_picks`?** Track production / return / sharpe side-by-side for 30 trading days starting next session. Decision criterion: realised 20-day forward return per pick, averaged across the cap-tier-weighted portfolio, net of tier-specific transaction costs ([config.py TRANSACTION_COSTS_BPS](../../config.py)). Tie-breaker if returns are within 50bps: pick MaxSharpe (lower variance is the second-order win for retail capital psychology).
