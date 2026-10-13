# Plan 0024 — A model that gives stocks time: long-horizon factors and a long-hold book

Status: **implemented** (pre-registered 2026-10-12; verdict 2026-10-12: H3 fails in every tier). Follow-ups carried into [plan 0025](0025-slow-core-and-fast-tactical.md). Owner: Amit. Read-only research: no weight, pick, book or schema change until Amit approves the verdict.

## Why
The paper book is rebuilt daily with a 5-in / 8-out band. Measured 2026-07-06 → 2026-10-12: one-way turnover 9.0 %/day (~189 %/month), median holding 5 trading days, SMALL ~18 new names a month for 5 slots. Nobody can follow that with real money, and it never lets a stock deliver. Root causes:
1. Every factor was chosen and weighted on its **20-session** IC (`pit.forward_returns`, the panel's `fwd_return_20d`), which favours fast signals. SMALL's largest weight, `delivery_anomaly_z`, is a one-month signal (IC t 6.2 at 1 month, 0.3 at 12).
2. The book's band is narrow and daily, so rank noise becomes trades.
3. Nothing was ever judged at the horizon an investor holds.

A quick read (2026-10-12, monthly anchors, overlap-adjusted t) shows slow factors exist: MID `piotroski_f` IC 0.046 → 0.131 from 1 to 12 months, SMALL `cons_beat_rate_4q` t 5.0 at 6 months, SMALL `avg_delivery_pct_30d` / `sector_tilt` t 3–4 at 6 months, `forward_looking_intensity` stronger with horizon.

## Questions and pre-registered tests
**H1 — slow factors.** For every panel factor × tier, rank IC at 21 / 63 / 126 / 252 sessions (true multi-month labels from `pit.forward_returns`, Newey-West t scaled for overlap). A factor is *slow* if its 126-session |t| ≥ 2.5 and its IC at 126 ≥ its IC at 21. Haircut with `tools/multiple_testing.py` over every (factor, tier, horizon) tried. Robustness: sign holds in 2020-22, 2023-24 and 2025-26.

**H2 — a slow composite works out of sample.** Walk-forward (expanding window, monthly anchors, embargo ≥ the label length, ≥ 24 training anchors): choose and weight factors on the 126-session label from the training window only. Pass: OOS rank IC t ≥ 2.0 at 126 sessions in MID or SMALL. Controls: the live 20-session weights (not OOS), `select` on 20 sessions, and fast + slow combined. LARGE is tested too; default stays the index.

**H3 — a long-hold book earns after costs and tax.** Monthly-anchored simulation of books built from the H2 OOS scores. Variant grid (all reported, ≤ 48 variants, deflated for the count):
- rebalance monthly or quarterly
- buy the top N (10 / 15 / 20); sell only below rank k·N (k = 2 / 3 / 4)
- rank on the score or its 3-month average
- minimum hold 0 / 6 / 12 months (forensic red flag overrides)
- tax-aware: defer a sale whose gain turns long-term within 6 weeks

Costs: Zerodha delivery fees + half-spread + impact by liquidity, calibrated on the real 2026-10-12 fills. Tax: STCG 20 % under 12 months, LTCG 12.5 % above ₹1.25 L a year, losses set off. Benchmark: the tier's cap-weighted index where history exists (NIFTY 50; Smallcap 250; Midcap 150 from 2023-06), else the tier equal-weight average.

**Pass bar for a tier (all of):** OOS net-of-cost-and-tax excess vs the benchmark with t ≥ 2.0 after the variant-count haircut; median holding ≥ 9 months; one-way turnover ≤ 100 % a year; worst 12-month excess no worse than −15 %.

## Decision
- A tier passes → ADR proposing the long-hold book for that tier (replaces the 5/8 daily band), plus a plan to rebuild `portfolio_construction` and the monthly review list.
- A tier fails → that tier is the index; the model stays a research and screening tool there.
- Fast signals may survive only as an entry-timing overlay, tested separately, never as membership.

## Method notes
- Read-only on the DB (`file:…?mode=ro`); never copy it. New code lives in new files (`tools/lh_*.py`), one owner per file.
- Survivorship: fundamentals hold today's universe only; report the bias direction, and rerun prices-only factors on `daily_snapshots_pit_unlisted` where possible.
- References: Novy-Marx & Velikov (2016) trading costs of anomalies; Gârleanu & Pedersen (2013) trade partially toward the aim portfolio; DeMiguel, Martín-Utrera, Nogales & Uppal (2020) transaction costs and factor combination; Qian, Hua & Sorensen IC decay; buy/hold-spread banding.

## Deliverables
`docs/studies/long-horizon-2026-10.md` (verdict first), the per-step notes in `docs/studies/long-horizon-2026-10/`, a proposed ADR if a tier passes. Run as a multi-agent workflow (Amit 2026-10-12: "go ahead with the multi agent session please"), with an independent re-derivation and a look-ahead / overfitting audit before the verdict.

## Implementation notes

**2026-10-12 — verdict ([study](../studies/long-horizon-2026-10.md)).** H3 fails in all three tiers: best variants after the 48-variant haircut t 0.00 (raw t LARGE 1.26, MID 1.44, SMALL 1.81; about 3.5 needed). Per the Decision rule every tier is the index; no ADR proposed. H2 passes in MID (OOS t 5.68) and SMALL (3.29); H1 holds only in SMALL once overlap is counted (audit). Re-derivation and audit confirm, no critical issue. Follow-ups found: `pit.forward_returns` session-count bug (2024-05-18 partial session, 2026-09-14 stray row), `avg_delivery_pct_30d` SMALL loses its 6-month evidence on the full market, cost placeholders 2–5× the measured Zerodha cost. Status stays in progress until Amit reads the verdict.
