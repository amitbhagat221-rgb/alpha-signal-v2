# HANDOFF
Updated: 2026-05-31 | Branch: master (unpushed) | HEAD (pre-commit): `feat(fno): F&O OI data foundation (Track 3.1b) + nightly DB backup to Drive`

## Left off
Built + backtested **the 4 F&O OI factors** (§3.2.2 OI half, Track-3 Next-3 #1 done). New [signals/fno_oi_factors.py](signals/fno_oi_factors.py) with one injectable-frame core shared by the live and PIT paths: `pcr_oi`, `pcr_volume`, `max_pain_distance` are direct latest-row reads off [fno_pcr_history]; `oi_buildup_signal` is a 4-state regime score from the **same-expiry** day-over-day ΔOI vs Δprice (roll-safe — Δ never crosses an expiry boundary). Stock-only (`sid IS NOT NULL`). Fully wired end-to-end: PIT helper `pit_fno_oi`, 4 new `daily_snapshots_pit` cols (via `_COLUMN_MIGRATIONS`), PIT_COLUMNS + VALIDATION_RANGES, `BACKTEST_SIGNALS` (new "Options/F&O" group), `BACKTEST_CADENCE`=weekly, `SIGNAL_COLUMN_MAP` + NW3, and 4 `FACTOR_LINEAGE` entries (drift check clean). PIT reconstructed over 30 weekly Fridays.

**Backtest (22 weekly periods, NW3):** `pcr_volume` SMALL **t=-1.69 WEAK** (high put-vol → mild underperformance, sensible sign) · `max_pain_distance` MID **t=-1.68 WEAK** (mean-reversion to max-pain) · `pcr_oi` best |t|=0.36 DROP · `oi_buildup_signal` best |t|=0.45 DROP. None clear the 2.0 screener gate (bootstrap CIs straddle 0 over a single 6mo regime) → **all 4 on the bench (`FACTOR_LIBRARY`), none wired to the screener.** data_sanity 0 CRITICAL, health green.

## Pick up here
1. **Deploy Phase E horizon badges** (still pending from prior session) — `sudo systemctl restart alpha-cockpit.service`; confirm `:3000/sectors` renders 11 sectors' S/M/L badges ([cockpit/api.py](cockpit/api.py) + [cockpit/templates/sectors.html](cockpit/templates/sectors.html) changed after last restart).
2. **IV path verify (weekday)** — confirm `nselib.nse_live_option_chain` / NSE `option-chain-equities` exposes IV (Sun = empty payload). Gates the *other* 4 §3.2.2 factors (`iv_skew_25d`, `iv_term_structure`, `iv_percentile_1y`, `iv_realised_spread`). **Two blockers**: the backfillable EOD bhavcopy has no IV column, and the live chain is forward-only (not backfillable) → those 4 can only accumulate forward into a new `fno_iv_snapshot`, backtest-grade months out.
3. **Re-test the OI four as the window deepens** — only 22 weekly periods, one regime. `pcr_volume` SMALL + `max_pain_distance` MID are the WEAK survivors to watch; they'd cross 2.0 only if the mechanism holds across more periods.

## Watch out
- **`oi_buildup_signal` is NULL right after a monthly expiry roll** — by design. The Δ requires a prior row sharing the current nearest-expiry; the first day on a new series has none, so it's NaN that day (better than roll-noise). ~207-222 stocks score per Friday; 3 pre-backfill Fridays (before 2025-11-27) are correctly all-NULL.
- **Backtest-usable Fridays = 2025-11-28 → 2026-04-24** (~22). After 2026-04-24, `fwd_return_20d` isn't elapsed yet (the panel showed 0 fwd for 2026-05-01+), so newer dates have the signal but no forward return.
- **DuckDB mirror lags the 4 new cols until tonight's `duckdb_refresh`** — backtest_pit reads SQLite (`read_sql`, fine), but any cockpit read of these cols via `read_sql_fast` would miss them until the nightly rebuild. Not a CRITICAL; self-heals.
- Daily reconstruct now includes `fno_oi` in `DEFAULT_SIGNALS`, so the panel extends automatically going forward.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — §3.2.2 now 4/8 (OI half shipped to bench; IV half blocked pending weekday verify). State: 28/50 PIT-shipped.
