# HANDOFF
Updated: 2026-10-14 | Branch: master (pushed with this commit) | HEAD: feat(mf): New money column + filter on /mutual-funds (parent 9bfc0d6)

## Left off
Plan 0025 phase 7 closed with no deployment: the theme book graded B but was the 2023-24 capex regime (order wins fail as a factor, `tools/order_wins.py`), and the mania screen fails. The SMALL long-hold rank is live in the cockpit, and /mutual-funds now flags funds closed to new money (Groww page flags → `mf_scheme_master.lumpsum_open / sip_open / closed_reason`; New money column, filter, fund-page notice). A parallel session's cockpit-scale fix is built on branch `cockpit-scale` but not merged.

## Pick up here
1. **Fix the winner-hunter gate, then run 6.1.** In `tools/winner_hunter.py` `check`, count only SMALL+MID stocks trading by 2021-01 (160 of 173 "short" names listed later; as written the 70 % gate tops out ~63 %). Amit has not approved yet. Ask, note it in the docstring as a pre-run correction, then `python -m tools.winner_hunter run` once the `nse_results` harvest finishes (1,569 of ~2,650 stocks done; likely today's 16:00 / 21:00 UTC windows).
2. **Merge `cockpit-scale`** (575f7b2…8aa44de) once the sessions with uncommitted edits to `cockpit/app.py` (/book methods tab), `db.py`, `schema.sql` and `tables.py` (plan 0017 retirements) have committed — the MF edits to `cockpit/api.py`, `app.py`, `mf.py` are committed now; expect a small conflict in `cockpit/mf.py` (`_mf_universe_pool` gained the subscription columns, cache `mf_universe_pool_v5`). Steps: `git merge --ff-only --autostash cockpit-scale` (or a real merge), full pytest incl. `tests/test_cockpit_scaling.py`, restart both cockpits, delete `/etc/systemd/system/alpha-cockpit-ops.service.d/rewarm-off.conf` + daemon-reload + restart ops. Then ask Amit about the 3 `ix_scale_*` indexes and the 28 `shareholding_holders` rows dated 1982–2001.
3. **Build plan 0025 6.2, new listings** (pre-registered in the plan; no tool yet). Pattern: `tools/theme_momentum.py` (score → `tools.lh_book` across 12 starts → ADR 0073 grade). Universe: stocks listed < 12 months, from the 2010+ legacy bhavcopy + `stock_prices_unlisted`.

## Watch out
- **Two sessions share this tree and this file.** `cockpit/app.py`, `pages.py` and `templates/book.html` still carry another session's uncommitted "Ways to weight" tab and the MF filters. 9bfc0d6 was staged as HEAD + its own hunks via `git update-index --cacheinfo`; do the same for those files.
- **`output/paper_sleeve/latest.json` is now a cockpit input** (`_file_paper_sleeve` in `config.FILE_OUTPUTS`, read only by `views.paper_sleeve`). `python -m tools.paper_sleeve status` rewrites it without trading; `rebalance` trades. Never run `rebalance` by hand outside the 2nd.
- **The harvester's "N items · M with data" undercounts by design.** Once its time budget is spent it returns "no data" instantly for every remaining stock; they are picked up next window, not lost.
- **MF "New money" status is only as fresh as the Groww rotation** (`sources/mf_holdings_groww.py`, each fund re-checked ~every 14 days; 47 funds not reached by the 80-min backfill, 326 plans have no Groww page and stay "—"). 12 plans (3 Axis/Bandhan target-maturity funds) have a last NAV of 2026-09-11 yet are still in AMFI's file: NAV-feed gap or early closure, unchecked.
- **Ops re-warm is off via a systemd drop-in (`rewarm-off.conf`), not code.** Leave it until `cockpit-scale` (6 h TTL) is live.

## Active plan
docs/plans/0025-slow-core-and-fast-tactical.md (phase 7 done; 5.1 harvesting; 6.1 / 7.2 gated on it; 6.2 open) · cockpit scaling: branch `cockpit-scale` (merge pending)
