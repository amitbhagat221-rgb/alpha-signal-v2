# HANDOFF
Updated: 2026-10-10 | Branch: master (81 unpushed before this commit: the other session's cockpit-v2 go-live) | HEAD: ce3ed29 fix(cockpit): blank charts after a deploy

## Left off
Plan 0023 tested six pre-registered dynamic filters on the option strangle (premium, trend, skew, stress, positioning, macro). All failed out of sample: the 0.05-delta strike already adapts to volatility, and the static rule earns most in the high-stress quintiles (ADR 0068 proposed). The static paper book (plan 0022, committed 71bb3b0) keeps recording. First trade: NIFTY exp 2026-10-13; next entries SENSEX Tue 10-13 and NIFTY Thu 10-15.

## Pick up here
1. **Wed 2026-10-14 after the 03:30 run:**
   - first settlement: `python -m option_book --show` / ops `/options`;
   - `cron_bse_fo` / `cron_nse_holidays` / `cron_option_book` SUCCESS in `pipeline_log`;
   - the first live snapshot: `output/kite_quotes.log` from Tue 10-13 09:50 UTC, and `option_live_quotes` rows with `chosen = 1` (only if Amit logged in via `/kite/login` and set the Kite app redirect URL to `…/kite/callback`).
2. **Paper-book line in the daily email:** `output/email_sender.py:_build_html`, a try/except block after `changes_html`, from `option_book.page_data()["summary"]`.
3. **Kite minute bars on entry and hold days:** a forward collection for the one untested dynamic idea, intraday management (plan 0023 §5). Extend `sources/kite_quotes.py` or `sources/kite_pull.py --backfill-bars` for NIFTY/SENSEX options; a new table needs `schema.sql` + `tables.TABLES` + a feed entry.

## Watch out
- **`sources/fno_iv.py` now falls back to the next-closest expiry when the ~30-day one can't invert.** That added 495 NIFTY days (2019–21) to `fno_iv_history`. Any IV factor's PIT panel built before today lacks them; re-run `reconstruct_pit` for IV signals before trusting their evidence.
- **`compute_iv` / `compute_pcr` backfills skip a date that has any row,** so a missing underlying on an otherwise-done date never self-heals. Use `compute_iv_for_date(d, symbols=[...])`. `compute_pcr_for_date` recomputes all symbols on the date.
- **SENSEX `fno_iv_history` lacks 25 thin early-2024 days;** the readings treat them as "no signal".
- **Not in this commit:** the other session's dirty `datamodel/*`, `backup_db.sh`, `schema.sql`/`tables.py`/`feeds.py` deletions, `tests/test_checks.py`, `tests/test_datamodel.py`, `anc.js`, `tools/nonlinear_benchmark.py`, plus their checklist lines.

## Active plan
docs/plans/0022-option-premium-paper-book.md (Phase 1+2 recording; pass bar after 25 trades) · docs/plans/0023-dynamic-option-setups.md (done: negative) · docs/plans/0017-data-model-redesign.md (other session)
