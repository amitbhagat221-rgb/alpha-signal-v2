# HANDOFF
Updated: 2026-10-16 | Branch: master (25 unpushed → pushed with the handoff commit) | HEAD: 31812e7 docs(research-0008): independent critique prompt

## Left off
Multibagger desk (plan 0026) is LIVE on /multibagger: the thesis score (ADR 0075, grade C) runs in the weekly `signal_multibagger` step, the 2026-10-15 run has 755 stocks in the pond and a top 100, and valuations exist for those 100; the Candidates / Held lists are empty until Amit promotes his 30. BSE announcements are blocked by an Akamai 403 since 2026-10-13, so new filings come from the NSE route (`sources/nse_announcements.py`, in `run.sh forward`). Research 0008 is a ready-to-paste critique prompt for an outside reviewer.

## Pick up here
1. **Multibagger: after Amit promotes the 30 on /multibagger** — run `python -m output.valuation --book` and queue the `mb_dossier` kind (`output/mb_dossier.py`, registered in `alpha_mcp/tasks.py`, batch 1; the export raises "no candidates" until the book has names).
2. **Multibagger: the auditor-resignation / CIRP gate reads only `bse_announcements`** (`signals/multibagger.py` `live_frame`), which is stale since 2026-10-12 — add the NSE categories `auditor_resignation` / `insolvency` from `nse_announcements`. Then plan 0026 4.3: `signals.mb_watch.new_since()` into the morning email (`output/email_sender.py`) and push.
3. **Merge `cockpit-scale`** (575f7b2…8aa44de): the shared tree is now clean (the ended session's MF/Kuvera work was committed as 985a102 on Amit's approval), so it can merge. Expect conflicts in `cockpit/mf.py`, `schema.sql`, `tables.py`, `cockpit/app.py` (the multibagger routes landed). Steps: real merge, full pytest incl. `tests/test_cockpit_scaling.py`, restart both cockpits, delete `/etc/systemd/system/alpha-cockpit-ops.service.d/rewarm-off.conf` + daemon-reload + restart ops. Then ask Amit about the 3 `ix_scale_*` indexes and the 28 `shareholding_holders` rows dated 1982–2001.

## Watch out
- **`policy_events` / `sector_policy_pit` is NOT point-in-time.** It is 28 events hand-curated in 2026 with hindsight weights (some are outcomes, none after 2025-04). It passed a multibagger test and was disqualified; plan 0025 7.1's theme book (grade B) also used it, so that grade may be inflated.
- **`cron_bse_announcements` will keep failing** until BSE access is back (another egress IP, or Amit drops the route). The NSE route is a separate table (`nse_announcements`, own taxonomy `config.NSE_ANNOUNCEMENT_CATEGORIES`). The governance and credit-rating factors still read BSE only.
- **`multibagger_scores` now also holds financials and MICRO rows** (thesis columns; the old funnel flags are 0), so the Playbooks "Strict compounders" tab shows a larger universe count. D4 (retire that tab) is Amit's.
- **The multibagger edge sits in stocks trading ₹0.5–1 Cr a day** (a ₹1 Cr floor: +12.7 → +5.2 %/yr). It was tested at ₹1 lakh per name; don't size it up without re-testing costs.
- **The first Funnel-tab load after a thesis run takes ~19 s** (100 evidence cards); the startup prewarm and the disk cache `mb_funnel_cards_v2` cover it afterwards.
- **Worktrees to clean up:** `.claude/worktrees/mb-desk` (it has symlinks into `output/` and `data/`), plus the merged agent worktrees (a12aaf…, a25b2a…, a84c70…, aaf54a…, adfa93…, afe309…). Use `git worktree remove`.
- **`output/paper_sleeve/latest.json` is a cockpit input** (`_file_paper_sleeve` in `config.FILE_OUTPUTS`, read only by `views.paper_sleeve`). `python -m tools.paper_sleeve status` rewrites it without trading; `rebalance` trades. Never run `rebalance` by hand outside the 2nd.
- **The harvester's "N items · M with data" undercounts by design.** Once its time budget is spent it returns "no data" instantly for every remaining stock; they are picked up next window, not lost.
- **MF "New money" status is only as fresh as the Groww rotation** (`sources/mf_holdings_groww.py`, each fund re-checked ~every 14 days; 326 plans have no Groww page — Kuvera now covers overseas FoFs). 12 plans (3 Axis/Bandhan target-maturity funds) have a last NAV of 2026-09-11 yet are still in AMFI's file: NAV-feed gap or early closure, unchecked.
- **Ops re-warm is off via a systemd drop-in (`rewarm-off.conf`), not code.** Leave it until `cockpit-scale` (6 h TTL) is live.

## Active plan
docs/plans/0026-multibagger-desk.md (LIVE; open 4.3 alerts, 4.4 announcement PDFs, electoral-bond file, D3 money, D4 strict tab) · docs/plans/0025-slow-core-and-fast-tactical.md (research closed; D3 + the first paper-sleeve rebalance 2026-11-02) · cockpit scaling: branch `cockpit-scale` (merge pending)
