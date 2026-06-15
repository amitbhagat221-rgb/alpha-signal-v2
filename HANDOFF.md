# HANDOFF
Updated: 2026-06-15 | Branch: master | HEAD: `f549e35` (3.3c spine, pushed) + uncommitted realized-return harness on top

## Left off
Track 3.3c now has BOTH halves: the **sizing spine** ([portfolio_construction.py](portfolio_construction.py) → `portfolio_weights`, cockpit "Sized Book — HRP" card w/ weighted analyst-PT expected-1Y, daily build, [ADR 0044](docs/decisions/0044-hrp-over-mean-variance-portfolio.md)) committed as `f549e35`, AND the **realized-return harness** ([tools/portfolio_outcomes.py](tools/portfolio_outcomes.py) → `portfolio_outcomes`: 47 historical books backfilled, HRP vs equal-weight-same-names vs tier-NIFTY per asof_date×window, daily after `compute_pick_outcomes`) — this part is **uncommitted** on `f549e35`. Early 20d read (n=16, ADVISORY): HRP −2.01% vs eqw −1.91% (edge −0.10%, win 38%) — noisy/early, 20d≠HRP horizon; health all-green (84 fresh).

## Pick up here
1. **Risk-adjusted comparison** — the §3.3c gate is risk-*adjusted* but `portfolio_outcomes` is raw-return only. Build a book-NAV/Sharpe path (extend [paper_portfolio.py](paper_portfolio.py), `paper_nav_history` is empty) so HRP-vs-eqw is compared on vol-adjusted terms, not just mean return.
2. **Let windows mature** — 63d/126d book outcomes fill automatically (~Jul/Sep) via the daily [tools/portfolio_outcomes.py](tools/portfolio_outcomes.py) step; re-check `python -m tools.portfolio_outcomes --report-only`.
3. **3.3b-3 within-group orthogonalization** ([tools/factor_marginal.py](tools/factor_marginal.py) steps 1-2) OR **`credit_beta` un-bench** via jugaad-data `stock_prices`→2018 (free quick-win). _Date-gated: `validate_rank_skill` ~2026-07-06; `pt_upside` re-verify ~2026-08-01._

## Watch out
- **Cockpit persisted-cache survives restarts**: `data/.cockpit_cache/*.pkl` hold `(payload, mtime)` with a 60s TTL. After deploying `cockpit/api.py` changes, a pre-edit pickle serves for up to 60s while the new template renders the missing field as Jinja *Undefined* → e.g. "Expected 1Y" showed **+0.0% / blank coverage** for ~1 min post-restart, then self-healed. To force-refresh: delete the pkl. (Today it was the cache, not a code bug.)
- **`portfolio_weights` covariance uses RAW `stock_prices.close`** winsorized ±0.5 (no adj_close exists) — a genuine >50% one-day move gets clipped. The `config.PORTFOLIO["hrp"]` caps (stock 12% / sector 35%) **intentionally differ** from top-level `max_stock_weight_pct=5.0`, which is infeasible for a 15-name book (1/15≈6.7%).
- **`portfolio_construction` step is `critical:False`** — a thin-day build failure logs FAILED but never blocks dossier/email; `run()` raises on an empty book (no placeholder). `asof_date` was added to `db._table_date_range` DATE_COLS (only `portfolio_weights` uses it) so it now freshness-tracks like `daily_picks`.

## Active plan
docs/plans/0002-100-factors-and-model.md (Phase 3.3c — spine shipped, hard gate pending ~18-24mo).
