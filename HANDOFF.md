# HANDOFF
Updated: 2026-06-14 | Branch: master (this session's commit will be the 1st unpushed) | HEAD: `53a7649` (pre-session)

## Left off
Big factor-evaluation + cleanup session, all uncommitted on top of `53a7649`: wired `governance_resignation` MID −0.08 (the first NEGATIVE weight in the live scheme), fixed the transcript look-ahead bias + a 247-fund MF NAV-splice bug, built the multiple-testing ([ADR 0043](docs/decisions/0043-multiple-testing-aware-factor-significance.md)) + horizon-aware marginal diagnostics, benched the §3.2.4 NLP factors, resolved the long-held MID accruals/consensus conflict, and compressed the checklist 231→82 lines. Everything verified green (data_sanity 0 CRITICAL, health all-healthy, screener re-run 1698 picks) — nothing committed yet.

## Pick up here
1. **Track 3.3c — portfolio construction** (next 3.3 sub-step): turn within-tier ranks into sized positions; `tools/hrp_prototype.py` is a start. Gated-but-related: re-run `tools/validate_rank_skill.py` (still <6 independent 20d windows → don't deploy capital yet; 63d outcomes mature ~2026-07-06).
2. **`pt_upside` artifact re-verify** (Next-3 #2, ~2026-08): `python -m tools.backtest_pit --signal pt_upside` once ≥3 fresh `analyst_consensus_snapshots` exist (cron 1st-of-month → 3rd on 2026-08-01) → un-cap (0.16–0.25) or pull. It's the model's load-bearing robust factor.
3. **3.3b-3 within-group orthogonalization** ([tools/factor_marginal.py](tools/factor_marginal.py) is steps 1-2) OR un-bench `credit_beta` via jugaad-data `stock_prices`→2018 (free quick-win).

## Watch out
- **`factor_marginal`/`multiple_testing` dedup**: `pit_ic_by_tier_v2` has multiple `source` rows per (signal,tier) — pick the MOST-POWERED (max `n_periods`), NOT "prefer monthly", else `delivery_anomaly_z` reads its n=5 monthly row not the n=103 weekly validation.
- **The 20d marginal lens UNDER-credits slow factors** — `book_to_price`/`accruals` look redundant at 20d but earn their weight at 252d (`book_to_price` SMALL incr_t −3.9→+13.3). Always sweep horizons in `factor_marginal` before any value-factor trim.
- **MF `clean_nav_series` is applied at READ-time** (`mf_metrics.compute` + `cockpit/mf.get_mf_nav_series`), NOT stored — raw `mf_nav_history` keeps the ÷10/÷100/leading-zero artifacts. Any NEW consumer of `mf_nav_history` must call `clean_nav_series` or it'll show the phantom step again.
- **`amit_personal_docs/` is untracked + personal — never commit it.**

## Active plan
docs/plans/0002-100-factors-and-model.md — Track 3.3b done (gate + multiple-testing + horizon-aware marginal); 3.3c (portfolio) next. Rides Next-3 (#1 ✅, #3 ✅, #2 gated).
