# HANDOFF
Updated: 2026-05-31 | Branch: master (1 unpushed) | HEAD: `feat(fno): F&O OI data foundation (Track 3.1b) + nightly DB backup to Drive`

## Left off
Built **Track 3.1b F&O data foundation**: [sources/fno_pull.py](sources/fno_pull.py) ingests the whole NSE F&O EOD grid via `nselib.derivatives.fno_bhav_copy` (one call = entire market, backfillable) into `fno_bhav` (raw grid, **2.83M rows / 122 dates / 6mo backfill**) + `fno_pcr_history` (PCR + max-pain rollup, 216 underlyings/day), wired as two daily `PIPELINE_STEPS`. Also stood up **offsite DB backup** — `backup_db.sh` (VACUUM-INTO → integrity → gzip 534MB → rclone to a 5 TiB Google Drive) on a 05:00 UTC cron; first upload confirmed in Drive.

## Pick up here
1. **Build + backtest the 4 OI factors** — `pcr_oi`, `pcr_volume`, `oi_buildup_signal`, `max_pain_distance` off [fno_pcr_history] — new `signals/` modules + PIT helpers + `BACKTEST_SIGNALS`. **NOT clock-gated** (6mo backfill already exists). Plan 0002 §3.2.2.
2. **Phase E badge deploy still pending** — `sudo systemctl restart alpha-cockpit.service`; confirm `:3000/sectors` renders 11 sectors' S/M/L badges ([cockpit/api.py](cockpit/api.py) + [cockpit/templates/sectors.html](cockpit/templates/sectors.html) changed after last restart).
3. **IV path verify (weekday)** — confirm `nselib.nse_live_option_chain` / NSE `option-chain-equities` exposes IV (today Sun = empty payload). Gates the *other* 4 §3.2.2 factors (`iv_skew_25d`, `iv_term_structure`, `iv_percentile_1y`, `iv_realised_spread`) → then add `fno_iv_snapshot`.

## Watch out
- `fno_bhav` stores **only rows with oi>0 OR volume>0** (16.3K of 35.6K/day) — dead far-OTM strikes dropped. Fine for PCR/max-pain; a future factor needing the *full* grid must re-fetch raw.
- Index underlyings (NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY/NIFTYNXT50) carry **sid=NULL** in both tables — symbol-keyed. Filter `instrument_type='STO'` or `sid IS NOT NULL` for stock-only factor work.
- `compute_fno_pcr` MUST stay ordered **after** `fetch_fno_bhav` in `PIPELINE_STEPS` (it aggregates rows just written). `STALENESS_OVERRIDE=6` on both tables — `trade_date` sits at Friday across weekend+holiday clusters.
- `backup_db.sh` is **VM-only** (`*.sh` gitignored, [.gitignore:94](.gitignore)) — like `run_pipeline.sh`, not in git. rclone remote `gdrive` (scope=drive.file) authed to amitbhagat221@. Restore = `gunzip` → plain sqlite db (verified restorable).

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Phase 3.1b data **done**; §3.2.2 options factors next (OI half now unblocked, IV half pending weekday verify).
