# HANDOFF
Updated: 2026-06-02 | Branch: master (3 unpushed) | HEAD: `f2eb28e` feat(model): horizon-resolved net-of-cost promotion gate (ADR 0038)

## Left off
Cleared three stacked items in one session: the ADR 0037 UHS follow-up, the last build-now §3.2 factors (§3.2.6/§3.2.7), and the ADR 0036 promotion-gate follow-up. The promotion gate is the meaty one — it now re-judges every factor at its cost-resolved natural horizon and flagged that 10/18 production (signal,tier) pairs don't clear net-of-cost at their own horizon, which is the live thread to pull next.

## Pick up here
1. **Act on the gate's live re-eval** — [tools/promotion_gate.py](tools/promotion_gate.py) `--reeval-live` (table `factor_horizon_gate`). Deliberate weight review (signal-weights.md process, never mechanical) on the flagged live factors: `earnings_yield`/MID + `book_to_price`/LARGE are sign-unstable (LIBRARY not PROMOTE); `delivery_anomaly_z` LARGE/MID + `iv_skew_25d` SMALL REJECT (fast, turnover-eaten at 5d). Counterpart: `book_to_price`/`earnings_yield` SMALL validate strongly at their **252d** natural horizon — candidates to weight at horizon, not 20d.
2. **§3.2.7 betas at their natural horizon** — the gate PROMOTEs `gold_beta` LARGE (126d, net_t 4.7) + `metals_beta` MID (126d, net_t 2.7), better than their raw-20d WEAK in [config.py](config.py) `FACTOR_LIBRARY`. n≈19 is thin — re-check after a few more monthly anchors before considering a wire.
3. **Surface `factor_horizon_gate` on `/system`** — feed it into the Promotion Funnel tile ([cockpit_ops/api.py](cockpit_ops/api.py) `get_factor_health`), so the horizon-resolved verdict is visible next to the legacy 20d t-stat (ADR 0038 "Next").

## Watch out
- **promotion_gate.py is on-demand, NOT in PIPELINE_STEPS** — `factor_horizon_gate` only refreshes when you run `python -m tools.promotion_gate`. The first-read rows are turnover=0.3.
- **252d net_t magnitudes are survivorship-inflated** (v1 archive = current-names-only). The guard only blocks *thin* (n<8) 252d; use the `net_ir_annual` column as the fair cross-horizon comparator, not net_t. pt_upside correctly resolved to 5d (not the 252d artifact) — that self-correction is the gate working.
- **Macro betas NULL before ~2024-03** — need ≥1y of `macro_history` (starts 2023-03-13) for the 252d window; early PIT anchors are correctly NULL by construction, not a bug. Reconstructed only on the 27 monthly anchors (not weekly dates).
- **`industry_id` is a CONTROL** — status=CONTROL in BACKTEST_SIGNALS, deliberately absent from SIGNAL_COLUMN_MAP (IC of a categorical code is meaningless). Don't "fix" its missing backtest.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Phase 3.2 (47/50 PIT-shipped: +industry_id control +4 macro betas) + Track 3.3a promotion gate shipped (ADR 0038).
