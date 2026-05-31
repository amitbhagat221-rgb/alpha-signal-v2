# HANDOFF
Updated: 2026-05-31 | Branch: master (2 unpushed) | HEAD (pre-commit): `feat(fno): 4 F&O OI factors built + backtested (Track 3.2.2 OI half)`

## Left off
**Closed §3.2.2 options-implied (8/8)** by shipping the 4 IV factors — and the key win: the IV half was *not* forward-only/blocked as feared. `sources/fno_iv.py` recovers the EOD IV surface by **Black-76 inversion of the settle prices already in `fno_bhav`** (implied forward via put-call parity, OTM-wing IVs, ±25Δ skew interpolation) → `fno_iv_history` + daily `compute_fno_iv` step. **Validated**: NIFTY ATM IV tracks India VIX (our own `macro_history`) to ~0.1-2 vol pts and sits just below it (textbook-correct); CE/PE IV match exactly at ATM (parity holds). `fno_bhav` **backfilled 6mo→12mo (250 dates)** so `iv_percentile_1y`'s 1y window fills. New [signals/fno_iv_factors.py](signals/fno_iv_factors.py) (4 factors) fully wired (PIT helper, cols, BACKTEST_SIGNALS/CADENCE/MAP, lineage — drift clean). [ADR 0035](docs/decisions/0035-fno-iv-derived-from-bhav.md).

**Backtest (25 weekly periods, NW3):**
- **`iv_skew_25d` MID t=+4.61 KEEP** — IC +0.096, bootstrap CI [2.28, 9.84] strictly >0. First F&O factor to clear the bar; downside put-skew → MID outperformance. Standout promotion candidate.
- `iv_realised_spread` MID t=-1.95 WEAK (CI excludes 0; rich variance premium → underperformance).
- `iv_term_structure` MID t=-1.80 WEAK. **SMALL "KEEP" t=-4.94 is a 7-period/23-stock ARTIFACT** (CI [-32.7,-3.1]) — flagged, NOT promoted. ~20% stock coverage (index-level signal at heart).
- `iv_percentile_1y` DROP all tiers (regime/timing read, not cross-sectional).

All 4 on the bench (`FACTOR_LIBRARY`); none wired. Also shipped: **Kite Connect scaffold** ([sources/kite_pull.py](sources/kite_pull.py) + [setup doc](docs/reference/kite-setup.md)) — auth/TOTP token-refresh + instrument map + bar backfill + aggregates, **pending live creds, NOT in PIPELINE_STEPS**.

## Pick up here
1. **`iv_skew_25d` promotion review** — strongest candidate from the whole F&O batch. Run `tools/walk_forward.py` OOS before any `SCREEN.weight_tiers` add (signal-weights.md — never mechanical). Caveat: single ~6mo regime.
2. **Build 6 daily-derivable §3.2.3 microstructure factors** — `signals/microstructure.py` off `stock_prices` OHLCV (3 clean: range-compression, closing-strength, opening-gap-freq; 3 proxies: vwap-dev, Corwin-Schultz spread, Amihud-kyle). Feasible now, no Kite, deep daily backtest. Only `volume_clock_concentration`/`tick_imbalance_5d`/`intraday_momentum_persistence` need Kite (3.1c).
3. **Kite activation** — user has a trading account; needs a Connect dev-app (₹500/mo) + 5 env exports in `run_pipeline.sh` (see setup doc). Then `--check-auth` → `--instruments` → `--backfill-bars`, wire `fetch_kite_bars` into PIPELINE_STEPS. Starts the ~90d clock for the 3 intraday factors.

## Watch out
- **The IV-surface compute is CPU-heavy (~1hr for 250 dates).** The daily incremental (`compute_fno_iv`, 1 date) is ~15s — fine. But a full recompute is long; it self-heals (skips done dates).
- **`iv_term_structure` is ~20% stock coverage** by nature (Indian single-stock options are liquid only in the near month). Its backtest runs on a thin, liquidity-biased subset — the SMALL "KEEP" is the canonical small-sample trap. Treat as index-level.
- **`fno_iv_history` not in the DuckDB mirror until tonight's `duckdb_refresh`** — backtest reads SQLite, fine; cockpit reads via `read_sql_fast` would miss it until rebuild.
- **Kite headless TOTP login is undocumented/brittle** — if it breaks, the `--request-token` manual fallback always works (see setup doc).
- HEAD is still the OI commit; this session's work (IV factors + Kite scaffold + 12mo backfill) is uncommitted until the commit below lands.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — §3.2.2 **fully done (8/8)**; §3.2.3 reframed (6 of 9 daily-derivable, feasible now). State: 32/50 PIT-shipped.
