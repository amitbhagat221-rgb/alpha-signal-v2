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
