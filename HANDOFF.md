# HANDOFF
Updated: 2026-06-03 | Branch: master (0 unpushed) | HEAD: `a8ecd4b` feat(model): horizon-gate weight review + /system surface + smart_money validated

## Left off
Closed Next-3 #1 — acted on the gate's live re-eval with a deliberate weight review (gate × v1-history agreement, never mechanical): LARGE cleanup (dropped momentum, equalized accruals/piotroski as labelled diversifiers, trimmed earnings_yield, lifted consensus/book_to_price), SMALL pledge_quality 0.13→0.10 → book_to_price 0.12, MID held (its flags are conflicts). Plus both follow-ups: surfaced `factor_horizon_gate` on `/system`, and registered+backtested `smart_money_score` (was wired with zero backtest; verdict thin/DROP). All in `a8ecd4b`.

## Pick up here
1. **§3.2.7 betas at natural horizon** (Next-3) — gate PROMOTEs `gold_beta` LARGE + `metals_beta` MID @126d vs raw-20d WEAK in [config.py](config.py) `FACTOR_LIBRARY`; n≈19 thin. Re-check after a few more monthly anchors before any wire.
2. **`pt_upside` artifact re-verify** (Next-3, due 2026-08) — capped 0.16–0.25 in `config.SIGNAL_WEIGHTS`. `python -m tools.backtest_pit --signal pt_upside` once ≥3 fresh `analyst_consensus_snapshots` exist → un-cap or pull.
3. **MID conflict re-judge** — `accruals`/MID (0.19, v1 t=3.20 vs gate REJECT) + `consensus`/MID (0.09) held this session; revisit via `python -m tools.promotion_gate --reeval-live` once monthly anchors thicken. `smart_money_score` (n=6) firms up the same way.

## Watch out
- **`get_factor_health` is `@_persisted_cache(300)`** — survives restart on disk (`data/.cockpit_cache/get_factor_health.pkl`). After editing `cockpit_ops/api.py`: `rm` the pkl **AND** `sudo systemctl restart alpha-cockpit-ops` — restart alone serves the stale disk cache.
- **`smart_money_score` is now backtest-registered but PIT-thin** (n=6, monthly cadence). Its gate SMALL-PROMOTE @126d is preliminary — `bulk_deals` has ~1mo depth so the reconstructed composite collapses toward delivery (redundant with `avg_delivery_pct_30d`). Don't act on the 0.06 weight yet.
- **`factor_horizon_gate.is_live` is per-signal (any tier)** — over-counts non-wired tiers. The `/system` funnel computes per-(signal,tier) wired status separately, so the table's `is_live` column ≠ the cockpit's "11/24 live clear".

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Track 3.3a (promotion gate shipped + acted; weights re-reviewed per ADR 0038).
