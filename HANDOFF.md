# HANDOFF
Updated: 2026-05-29 | Branch: master (0 unpushed) | HEAD: `f0bd9c1` feat(sectors): plan 0006 phases A+B+C — sector dossier digest

## Left off
Three parallel commits landed: (a) [DuckDB read-replica](tools/duckdb_refresh.py) + `factor_type_conformance` rewrite ([health.py:534](health.py#L534)) — `/model` cold 5.6s → 1.6s, `/system` 33.9s → 13.1s; (b) [Plan 0006 A+B+C](docs/plans/0006-sector-dossiers.md) — `sector_briefs` + `sector_force_breakdown` tables, classifier, and a new `/sectors` "Today" tab replacing the 47-card heatmap; (c) [Track 2.2b-v2 split](signals/financial_signal.py) + 2 bench factors ([signals/delivery_anomaly.py](signals/delivery_anomaly.py), [scoring/screener.py](scoring/screener.py)) → optimizer's `WIRED_KEYS` coverage now LARGE/MID/SMALL = 100/100/100%. `financial_recovery` MID t=+1.55 / SMALL t=-1.88 — both WEAK, neither routed live; mechanism confirmed, sample size is the rate-limiter.

## Pick up here
1. **Plan 0006 Phase D — LLM sector dossiers** — schema + prompt in [docs/plans/0006-sector-dossiers.md §Phase D](docs/plans/0006-sector-dossiers.md). New `sector_dossiers` table; 11 LLM calls/night (~₹3-5/night). Mirror `output/dossier.py` hygiene contract (no raw numbers in narrative — calendar tokens OK, specific decimals not).
2. **Track 3.1b — NSE F&O OI probe** — unblocks `§3.2.2` options-implied (8 factors). Probe `nselib.derivatives` endpoints (option chain, OI history, participant-wise OI) for date-range support; design `fno_option_chain` (per-strike snapshot) + `fno_oi_history` (time series); fetcher with cookie-warm + 2s rate limit; PIPELINE entry + freshness watchdog. Independent surface, no overlap with sector dossiers.
3. **`financial_recovery` accumulator gate** — re-run `tools.reconstruct_pit --signal financial_recovery --months 36` after Q1 FY27 NBFC results land (~late Jul 2026); re-backtest. If MID t-stat moves toward 2.0, route into `SIGNAL_WEIGHTS[MID]` at ~10% weight. If it regresses, re-think direction-flip framing per [ADR 0028](docs/decisions/0028-two-variant-factor-model.md).

## Watch out
- **`tools/optimize_weights.py:WIRED_KEYS` must stay in sync with `scoring/screener.SIGNAL_COLS`** — they're a manual pair. If you add a factor to the screener but forget WIRED_KEYS, `--filter-wired` silently drops it; if the reverse, you get phantom weights in config that the screener can't compute. Audited 2026-05-29; both have pledge_quality + delivery_anomaly_z + pt_upside + eps_growth.
- **DuckDB replica is a derived artifact** rebuilt nightly by `tools.duckdb_refresh`. If you change `DUCKDB_MIRRORED_TABLES` in [db.py:218](db.py#L218), `rm data/alpha_signal.duckdb && python -m tools.duckdb_refresh` or the next `read_sql_fast()` against a new table errors. Falls back gracefully if file is missing.
- **`read_sql_fast` dialect** — DuckDB rejects SQLite's `[col]` bracket-quoting. Always use double-quotes (`"col"`). Caller responsible for only referencing tables in `DUCKDB_MIRRORED_TABLES`.
- **Ops cockpit latent circular-import** — `cockpit_ops/app.py` must import `cockpit.api` first (see file header). Masked because ops cockpit hadn't restarted since 2026-05-26 back-import; the parallel session's restart exposed it. Don't reorder imports.
- **`factor_type_conformance` samples tables >500K rows** (sample size 200K). For rates that round to score=100 the original was already lossy; for rates that would actually demote, 200K detects with high confidence. Sampled rows flagged "(sampled)" in the issue message.
- **`/sectors` Market force shows "attribution pending"** by design — v2's `fii_dii_cash_flow` is index-level (`category` ∈ {FII,DII,Client}, no sector column). Phase B writes nothing for market; cockpit shows the gap explicitly.
- **Tier-direction-flip rule** (from 2.2b-v2 finding): if any future factor's backtest IC flips sign across cap_tiers (e.g. SMALL t<0 while LARGE t>0), split into two named signals (`X_quality` / `X_recovery` or analogous), don't apply per-tier sign on the composite. See proposed [ADR 0032](docs/decisions/0032-tier-direction-flip-split-signal.md).

## Active plan
[docs/plans/0006-sector-dossiers.md](docs/plans/0006-sector-dossiers.md) — Phase D (LLM narration) next; Phase E (per-sector horizon scores) after.
