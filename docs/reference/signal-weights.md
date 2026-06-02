# Validated Signal Map

From v1 C13b — 36 monthly periods, reproduced by `tools/backtest_pit.py` in v2.

| Signal | LARGE | MID | SMALL |
|--------|-------|-----|-------|
| Consensus | t=3.52 | t=2.20 | t=2.44 |
| CF Accruals | t=0.20 | t=3.20 | t=2.10 |
| Promoter QoQ | t=0.04 | t=0.83 | t=3.20 |
| Earnings Yield | t=1.57 | t=1.01 | t=3.13 |
| Piotroski | t=0.51 | t=2.23 | t=2.81 |
| Book-to-Price | t=0.79 | t=2.33 | t=2.54 |

## Weight tiers

| t-stat | Weight |
|---|---|
| ≥ 2.5 | 1.0× |
| 1.5 – 2.5 | 0.5× |
| 0.5 – 1.5 | 0.2× |
| < 0.5 | 0× |

## In PRODUCTION `SIGNAL_WEIGHTS` beyond the v1 C13b set

Promotion wave 2026-05-31 — idle-but-validated factors brought into production after
an **orthogonality sweep** (each new factor's max |ρ| vs already-wired factors shown).
`pt_upside` is **capped** below its t-implied share pending an artifact re-verify (2026-08).

| Signal | Tier(s) | t-stat | Weight | Max \|ρ\| vs wired | Notes |
|--------|---------|--------|--------|---------|-------|
| **pt_upside** | LARGE/MID/SMALL | 7.15/8.40/9.14 | 0.25/0.25/0.16 | 0.27 (vs book/EY) | analyst PT upside; n=35. CAPPED — artifact re-verify 2026-08 (open question). |
| **pledge_quality** | SMALL | 5.90 | 0.13 | 0.08 | promoter-pledge stress; orthogonal to promoter (ρ=0.04) |
| **delivery_anomaly_z** | SMALL | 4.76 (n=103) | 0.11 | 0.08 | delivery z-spike; orthogonal to avg_delivery (ρ=0.08) |
| **iv_skew_25d** | MID | +3.16 (48wk) | 0.14 | 0.19 | in-house IV skew (ADR 0035); F&O-only; LARGE/SMALL DROP |

(pt_upside/pledge/delivery were already in `scoring/screener.py` `SIGNAL_COLS` + the
MaxReturn/MaxSharpe variants since 2026-05-28/29, but carried **zero production weight**
until this wave — they were computed daily and ranked but unused.)

## Horizon-gate weight review (2026-06-02, [ADR 0038](../decisions/0038-horizon-resolved-promotion-gate.md))

Deliberate, non-mechanical review off the net-of-cost gate (`tools/promotion_gate.py`
→ `factor_horizon_gate`), cross-checked against v1 C13b. **Rule applied: move weight
only where BOTH lenses agree; hold every gate↔history conflict.** (Also fixed the gate's
`_live_keys()` alias bug — the live re-eval had been scoring only 6 of the 12 wired
factors.) Changes:

| Tier | Factor | Was → Now | Why |
|------|--------|-----------|-----|
| LARGE | momentum | 0.04 → **0 (dropped)** | t=0.00 broke the t<0.5→0× rule + gate REJECT |
| LARGE | earnings_yield | 0.15 → **0.12** | over-weighted 0.5×-secondary; gate REJECT in LARGE (strong in SMALL, weak here) |
| LARGE | accruals / piotroski | 0.11/0.07 → **0.09/0.09** | equalised diversification ballast (both gate-REJECT — kept only to avoid over-concentrating consensus) |
| LARGE | consensus | 0.30 → **0.35** | doubly-validated anchor; absorbs freed weight |
| LARGE | book_to_price | 0.08 → **0.10** | gate's only LARGE LIBRARY survivor |
| SMALL | pledge_quality | 0.13 → **0.10** | gate demotes to LIBRARY (1.96), single-horizon-fragile + sign-unstable; kept for orthogonal pledge-stress info |
| SMALL | book_to_price | 0.09 → **0.12** | gate's single strongest factor in the model (net_t 13.58 @252d) |

**MID: unchanged.** Its 3 flags are gate↔history *conflicts* — accruals (v1 t=3.20 vs
gate REJECT), consensus (v1 t=2.20 vs gate REJECT), promoter (gate PROMOTE 4.99 but n=11
thin) — not acted on. Watch-list for the next monthly anchor.

**MID accruals/consensus conflict** to re-judge once n thickens.

### `smart_money` validated (2026-06-02, closes the never-backtested gap)

`smart_money_score` (SMALL 0.06, the bulk+delivery composite) was wired with **zero
backtest** — and its config label `t=2.49` was wrong (that was `avg_delivery_pct_30d`'s
number, borrowed via a mis-alias in `_WEIGHT_KEY_TO_SIGNAL` / health_score / promotion_gate).
Registered it properly (`SIGNAL_COLUMN_MAP`, `BACKTEST_SIGNALS`, `BACKTEST_CADENCE`=monthly,
`FACTOR_LINEAGE`) and fixed all three alias maps to point at `smart_money_score`. Verdict:

| Lens | LARGE | MID | SMALL |
|------|-------|-----|-------|
| 20d backtest (`backtest_pit`) | t=−0.10 | t=0.54 | **t=1.06** (n=6, DROP) |
| Net-of-cost gate (natural h) | REJECT 63d | REJECT 63d | **PROMOTE 126d** (net_t 5.03, n=6) |

The two lenses conflict in SMALL (20d weak; a slow-126d edge in the gate), and **n=6 is
thin with a bulk component that has no historical depth** (reconstructed anchors collapse
toward delivery — redundant with `avg_delivery_pct_30d`). **Verdict: PRELIMINARY — held at
0.06, no change.** Now visible to the backtest/gate; re-judge as monthly anchors accrue and
`bulk_deals` depth grows (then it can move to weekly cadence).

## On the bench (validated, deliberately NOT wired)

- **eps_growth** (LARGE t=5.31 / SMALL t=3.23) — **redundant**: ρ=0.63 with consensus in LARGE, ρ≈0.3–0.4 with the value/quality cluster in SMALL. Analyst/growth dimension already carried by consensus + pt_upside. Stays in the variants only.
- **kyle_lambda** (LARGE t=+4.24 / MID t=+4.14, 39mo) — Amihud illiquidity premium, but ρ(kyle, ln_ADTV)=−0.73: a cost-coupled liquidity tilt (you'd pay the spread you're paid for), MID IC decaying. Held as diagnostic.
- **Contrarian/unverified-sign + tiny-n**: interest_coverage (MID t=−3.69, sign-flip vs SMALL), roic/fcf_margin (negative, counterintuitive), iv_term_structure (n=7), sentiment_7d (n=4), eps_growth_yoy LARGE (n=8) — parked pending sign/regime verification or more periods.
- F&O OI four + iv_realised_spread / iv_term_structure / iv_percentile_1y — see `FACTOR_LIBRARY`.

## Pending backtesting

- Insider (2yr reconstructed)
- Regulatory (3yr events)
- Macro sector (3yr indicators)
- Track 3 Phase 3.2 factors (plan 0002)
