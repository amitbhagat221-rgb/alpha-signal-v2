# HANDOFF
Updated: 2026-10-11 | Branch: master (5 unpushed before this commit) | HEAD: 85affb0 feat(book): YTD return of the paper book beside the expected return

## Left off
The Kite minute-bar backfill (ADR 0072, `sources/kite_bars.py`) has been running since 20:06 UTC: 12/2,448 stocks, 12.2 M bars from 2015-02-02 in 38 MB. It stops at 23:50 UTC and resumes hourly after each of Amit's Kite logins, ~4–5 days in all. The server was cleaned the same session: 52 GB of scratchpad DB copies deleted, boot volume grown to 200 GB (126 GB free), 8 GB swap, journald capped. Also added: a `DISK_LOW` check, the Sunday `run.sh sweep`, an OCI "VM not reporting" email alarm, and a boot-volume backup plus a `monthly-3` policy.

## Pick up here
1. **Watch the backfill:** `python -m sources.kite_bars --status` and `output/kite_bars.log`. Contract rejections show as `item_error` in `python -m runlog bundle kite_intraday`. When it reports "nothing left", write the compaction step (`_staging/sid=*` → `month=YYYY-MM/part-0.parquet`, ADR 0072) and the `intraday_daily` summary table (VWAP, volume concentration, buy/sell imbalance, first and last 30-minute moves). Then the three blocked §3.2.3 factors in `factors.FACTORS`.
2. **Kite dataset ② cost snapshot** (checklist "Kite data — 5 datasets"):
   - `quote_snapshots`: `kc.quote` for the universe, 500 per call, 10:45 and 14:30 IST.
   - Monthly `trade_charges` via `kc.get_virtual_contract_note`. Price buy and sell in **separate calls**: together they're taxed as intraday (STT 0.025% sell-only instead of delivery 0.1% each side).
   - Then ③ circuit flag, ④ `kite_instruments`, ⑤ `broker_trades`.
3. **Wed 2026-10-14 after the 03:30 run** (carried): `python -m option_book --show`; check `cron_bse_fo` / `cron_option_book` are SUCCESS and `option_live_quotes` has `chosen = 1` rows if Amit logged in. Still open from 10-10: Amit's cockpit-QA decisions ①–⑥, the price-history gaps feeding `signals/residual_momentum.py:84`.

## Watch out
- **Kite rewrites history for splits and bonuses, prices and volumes alike.** KOTAKBANK's raw close of 2133.3 on 2026-01-12 is 426.7 on Kite. Archive levels are on the basis of `intraday_files.fetched_on`; rescale with `corporate_actions` before comparing with `stock_prices`.
- **Kite's cached token is good until midnight UTC (05:30 IST)** (`kite_pull._cached_token` keys on the UTC date). A later login gives the backfill fewer hours.
- **Oracle halved the Always Free A1 allowance to 2 OCPU / 12 GB on 2026-06-15.** This 4 / 24 VM isn't billed (PAYG since 2026-03-19, no invoices), but **never terminate or recreate it**: a new one may be capped. Keep at most 5 boot-volume backups (1 manual + `monthly-3`), and don't use Bronze/Silver/Gold.
- **`tests/test_org.py::test_grade_attaches_to_the_memo_and_feeds_the_scorecard` failed at 19:21 UTC (already the 12th in IST)** with no org code changed. Probably a UTC/IST date-boundary bug in the test; not verified.
- **Not in this commit:** the other sessions' dirty files: plan-0017 `datamodel/*`, their hunks in `schema.sql` / `tables.py` / `feeds.py` / `tests/test_checks.py`, `backup_db.sh`, `cockpit/*`, `factors.py`, `pit.py`, ADR 0071 + `signals/consensus_beat.py`, `tools/{names_per_tier,large_reaudit,nonlinear_benchmark,session_classify}.py`, their checklist bullets, `anc.js`.

## Active plan
ADR 0072 Kite archive (backfill running) · docs/plans/0022-option-premium-paper-book.md (recording) · docs/plans/0020-factor-audit.md (close-out) · docs/plans/0017-data-model-redesign.md (other session)
