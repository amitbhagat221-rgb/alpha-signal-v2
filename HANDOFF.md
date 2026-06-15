# HANDOFF
Updated: 2026-06-15 | Branch: master (this session's commit = 1st unpushed until push) | HEAD: `e6ca5b5` (pre-commit; today's commit becomes HEAD)

## Left off
Shipped the **Track 3.3c portfolio-construction spine**: HRP sizing module ([portfolio_construction.py](portfolio_construction.py)) → new `portfolio_weights` table, a cockpit `/portfolio` "Sized Book — HRP" card (incl. weighted analyst-PT **expected-1Y +31.6%**), and a daily `PIPELINE_STEPS` build right after the screener — all **ADVISORY** (no capital until rank-skill clears). Everything verified green (15-name book, ex-ante vol 16.9% < 17.7% eq-wt, eff-N 11.4, health 82→83 fresh, [ADR 0044](docs/decisions/0044-hrp-over-mean-variance-portfolio.md)); uncommitted on top of `e6ca5b5`.

## Pick up here
1. **HRP book → realized-return harness** (chosen next track): track the HRP book head-to-head vs the equal-weight Model Portfolio in [paper_portfolio.py](paper_portfolio.py) / [tools/compute_pick_outcomes.py](tools/compute_pick_outcomes.py) — the §3.3c gate evidence; daily `portfolio_weights` history started accumulating 2026-06-15. Add a 3.3c checklist bullet before starting.
2. **3.3b-3 within-group orthogonalization** — [tools/factor_marginal.py](tools/factor_marginal.py) has steps 1-2; orthogonalize correlated factors within group so the weighted sum stops double-counting.
3. **`credit_beta` un-bench** via jugaad-data `stock_prices`→2018 (free quick-win). _Date-gated reminders: `validate_rank_skill` re-run ~2026-07-06 (63d outcomes); `pt_upside` re-verify ~2026-08-01._

## Watch out
- **Cockpit persisted-cache survives restarts**: `data/.cockpit_cache/*.pkl` hold `(payload, mtime)` with a 60s TTL. After deploying `cockpit/api.py` changes, a pre-edit pickle serves for up to 60s while the new template renders the missing field as Jinja *Undefined* → e.g. "Expected 1Y" showed **+0.0% / blank coverage** for ~1 min post-restart, then self-healed. To force-refresh: delete the pkl. (Today it was the cache, not a code bug.)
- **`portfolio_weights` covariance uses RAW `stock_prices.close`** winsorized ±0.5 (no adj_close exists) — a genuine >50% one-day move gets clipped. The `config.PORTFOLIO["hrp"]` caps (stock 12% / sector 35%) **intentionally differ** from top-level `max_stock_weight_pct=5.0`, which is infeasible for a 15-name book (1/15≈6.7%).
- **`portfolio_construction` step is `critical:False`** — a thin-day build failure logs FAILED but never blocks dossier/email; `run()` raises on an empty book (no placeholder). `asof_date` was added to `db._table_date_range` DATE_COLS (only `portfolio_weights` uses it) so it now freshness-tracks like `daily_picks`.

## Active plan
docs/plans/0002-100-factors-and-model.md (Phase 3.3c — spine shipped, hard gate pending ~18-24mo).
