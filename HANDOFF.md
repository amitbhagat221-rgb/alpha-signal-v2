# HANDOFF
Updated: 2026-06-01 | Branch: master (2 unpushed) | HEAD: `f7e3633` fix(trust): per-stock UHS + PT-plausibility guards (ADR 0037)

## Left off
Firefought a data-quality bug a user spotted on `/explorer/SPRE`: a ₹3,960 sell-side PT (+3474% on a ₹110 stock) shown next to **UHS 90 · TRUSTED**. Fixed the garbage PT (18 stocks, Yahoo junk for thin-coverage small-caps) with layered guards, AND discovered the deeper issue — UHS plausibility/consistency were computed **universe-wide** so every tier-mate got the identical badge. Rebuilt `rollup_pick_uhs` to be **per-stock**; SPRE now reads **61 · REVIEW** ([ADR 0037](docs/decisions/0037-per-stock-uhs-and-pt-plausibility.md)).

## Pick up here
1. **Reconcile `FACTOR_UPSTREAM_TABLES`** ([scoring/health_score.py](scoring/health_score.py)): it lists raw tables (`quarterly_income`) but Gate-2 verdicts key to derived tables (`piotroski_scores`), so LARGE/MID per-sid plausibility falls back to the universe mean. Map factors → verdict source-tables so per-sid coverage reaches all tiers (SMALL is already full via `consensus_signals`).
2. **ADR 0036 follow-up — horizon-resolved promotion gate** (↔ Track 3.3a): `natural_horizon` in the registry + net-of-cost-IR gate. Data in [tools/ic_decay.py](tools/ic_decay.py); needs `tools/backtest_pit.py` + registry.
3. **§3.2.6 `industry_id` + §3.2.7 macro betas** — last build-now factors; new `signals/` + `tools/reconstruct_pit.py`.

## Watch out
- **UHS has two stores that can diverge:** `daily_picks.uhs_score` (canonical — per-sid, Gate-6-capped, written by `batch_write_pick_uhs`) vs `health_score` `entity_kind='pick'` rows (`compute_uhs` persist). The cockpit badge now reads `daily_picks` (ADR 0037); stale `health_score` pick rows from a pre-fix nightly run are ignored but still present.
- **Per-sid verdict window:** `_gate_pass_rate` looks back 7d ending at `pick_date`, so a verdict dated today reflects on *today's* picks only; older picks lag until the nightly sweep + screener re-stamp them.
- `sweep_pt_plausibility()` runs inside `yfinance_analyst.compute()` (the `fetch_yfinance_analyst` step) — nulls + flags stored implausible PTs daily.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Phase 3.2 (42/50 PIT-shipped). This + the cockpit-UX work were drive-bys, off-roadmap.
