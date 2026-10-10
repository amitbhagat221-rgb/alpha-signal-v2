# HANDOFF
Updated: 2026-10-10 | Branch: master (0 unpushed before this commit) | HEAD: c158cd7 merge master into frontend-polish

## Left off
Option-premium selling went from idea to a running forward test.
- **Study:** on real prices 2019–2026 only the 0.05-delta strangle sold 2 sessions before expiry holds up. The pre-registered 1-session version, the event veto and the VIX veto all failed.
- **Paper book:** `option_book.py` now records it daily (plan 0022, ADR 0067 proposed). First paper trade: NIFTY exp 2026-10-13, sold 23000 CE 5.85 + 21950 PE 7.75.
- **Kite Connect:** live on Amit's account ML5851 (static IP 140.245.248.166).
- **Secrets:** moved out of v1 into `~/.config/alpha-signal/secrets.env` (ADR 0066 proposed).

## Pick up here
1. **Wed 2026-10-14 after the 03:30 run:** check the first settlement with `python -m option_book --show` (or ops `/options`), and that `cron_bse_fo` / `cron_nse_holidays` / `cron_option_book` are SUCCESS in `pipeline_log`. 10-11 is the first morning run on the new secrets file, so check the 04:00 health email arrived.
2. **Tue 10-13 and Thu 10-15, 09:50 UTC:** after Amit's `/kite/login`, `output/kite_quotes.log` should show the SENSEX then NIFTY snapshot and rows in `option_live_quotes` with `chosen = 1` and a basket margin. Amit must first set the Kite app's redirect URL to `https://alpha.rendezvous-app.duckdns.org/kite/callback`.
3. **Add the paper-book line to the daily email:** `output/email_sender.py:_build_html`, a try/except block after `changes_html`, reading `option_book.page_data()["summary"]`.

## Watch out
- **SENSEX volume is in units on BSE.** `sources/bse_fo.py` divides by `NewBrdLotQty` to store lots like NSE. OI stays in units, as on NSE.
- **A closed market has volume 0 and an empty order book in Kite quotes.** The rule (like the backtest) only uses strikes that traded that day, so `kite_quotes --force` on a weekend finds no strikes. Test with real sessions only.
- **The live crontab holds non-v2 lines** (duckdns, project-rendezvous) that `ops/crontab.txt` does not. Never install `ops/crontab.txt` wholesale; append a line, and keep the order the same in both (`test_ops_files` compares order).
- **`fno_bhav` gaps:** before 2024-07-15 it holds only index underlyings. 2021-03-30 and 2024-07-08…12 are missing (no legacy file; NSE's format switch).
- **Untouched v1 copy:** v1's `run_pipeline.sh` still holds the old secrets, which nothing reads. Amit can delete those lines once the 10-11 runs are clean.
- **Not in this commit:** the other session's uncommitted plan 0017 / cockpit-v2 work in `datamodel/sync.py`, `backup_db.sh`, `schema.sql` deletions, `tables.py` deletions, `tests/test_datamodel.py`, `tests/test_checks.py`, and the checklist's cockpit / audit bullets is left unstaged.

## Active plan
docs/plans/0022-option-premium-paper-book.md (Phase 1+2 recording, pass bar after 25 trades) · docs/plans/0017-data-model-redesign.md (other session) · docs/plans/0020-factor-audit.md (close-out)
