# HANDOFF
Updated: 2026-10-10 | Branch: master (85 unpushed before this commit) | HEAD: a6ba433 test(checks): volume-spike verdict test no longer depends on a live backfill window

## Left off
Cockpit v2 is live: Today (book changes) · Explorer · Stocks screener · Markets · Sectors (38-industry tile grid) · Investor Playbooks · Book · Model · Funds, and ops Health/Feeds/Flow/Boardroom/Options. Two Playwright sweeps of every page × tab at 1440 + 375 came back clean, and stock charts now show date, close and volume on hover. Amit's "blank charts" were a stale cached `cockpit.js`, now fixed with `?v=` + cache rules (ce3ed29). The options paper book (plan 0022) keeps recording; plan 0023's dynamic filters all failed (ADR 0068).

## Pick up here
1. **Amit's open decisions from the cockpit QA** (checklist "Cockpit v2 LIVE", ①–⑥). The pick-changing one is the price-history gaps: 22 ranked stocks (KOV #1 SMALL; 7 share a 2023-10-25→2026-04-20 hole) feed `signals/residual_momentum.py:84`, which uses ROW windows. That needs an ISIN-keyed bhavcopy backfill plus a gap guard, run on a branch and approved before it ships. Also waiting: the `bulk_deals` cleanup (scratchpad `apply.sql` was refused by the classifier), the INDIANB coverage gate, single-flag THYROCARE, and weekend `daily_picks`.
2. **Wed 2026-10-14 after the 03:30 run:**
   - `python -m option_book --show` for the first NIFTY settlement.
   - Check that `cron_bse_fo` / `cron_option_book` / `cron_management` (first run 11-03) are SUCCESS.
   - If Amit used `/kite/login`, `option_live_quotes` should have `chosen = 1` rows.
3. **Sunday 10-11 Yahoo run:** check that `analyst_consensus` refills the 179 NULLed averages and that `total_analysts` is Yahoo's count again (LODHA showed "1 analyst" vs 18 ratings). The check `ANALYST_TARGET_IMPLAUSIBLE` now also fails an average outside its own low–high range.

## Watch out
- **Every `/static` script or stylesheet needs `?v={{ asset_version(...) }}`** (`tests/test_static_cache.py`). An untagged file is served `no-cache`; before that fix, browsers ran new pages against days-old JS. Test in a stale-cache browser, not only a fresh one.
- **Don't delete CSS you think is unused.** `tests/test_cockpit_css.py` fails when a template class has no rule; a v2 merge had pruned the industry dossier's 240 lines.
- **`mf_scheme_master` categories were re-normalised 99→54 in place** (`sources/mf_amfi_master.renormalise_master`). Older `mf_metrics` snapshots keep the old labels.
- **`daily_picks` has weekend/holiday rows** (morning cron runs daily). `pick_outcomes` now drops them; anything else counting pick dates must too.
- **Not in this commit:** the plan-0017 session's dirty `datamodel/*`, `schema.sql`, `tables.py`, `feeds.py`, `backup_db.sh`, `tests/test_checks.py`, `tests/test_datamodel.py`; the non-linear-benchmark session's `tools/nonlinear_benchmark.py`, `docs/studies/nonlinear-benchmark-2026-10.md` and its checklist bullet; `anc.js`.

## Active plan
docs/plans/0022-option-premium-paper-book.md (recording; pass bar after 25 trades) · docs/plans/0020-factor-audit.md (close-out) · docs/plans/0017-data-model-redesign.md (other session)
