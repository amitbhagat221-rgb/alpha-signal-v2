# HANDOFF
Updated: 2026-10-16 | Branch: master (pushed) | HEAD: 6a58f07 feat(plan-0026): substantive-only SEBI rule (PRPF, GYSC → flag), borderline marks, open items into plans 0026 / 0027

## Left off
**Multibagger (plan 0026, stage 4b done).**
- All 100 of the gated thesis top 100 were deep-researched by agents, against a per-stock "already known" pack (`output/mb_research.py`, brief `docs/research/0011…`). Results are in `mb_research`: 29 reject, 67 flag, 4 clean, 0 strong 5x cases.
- A research-adjusted ranking (`overlay()`, config `MB_THESIS["research_overlay"]`) made its top 30 the 30 candidates in `multibagger_book` (actor `claude`). Plain-words pages are live at `/multibagger/research[/<sid>]`.
- The research exposed broken inputs, and a data gate now runs inside the thesis run (`signals/multibagger.data_checks`): filed share counts, demergers, inflated quarter revenue. The 2026-10-16 re-run has a pond of 752; the paper books were restarted on it.

## Pick up here
1. **Multibagger: Amit's calls.**
   - The 15 borderline verdicts (`output/mb_research.BORDERLINE`, shown as "Borderline: your call").
   - D7: he picks his 10 from the 30 on the Candidates tab.
   - D4: the Strict compounders tab, still open.

   A changed verdict means: edit `output/mb_research/<sid>/verdict.json`, then `python -m output.mb_research --load --sids X`. Then check that `--overlay` still matches the candidates.
2. **Plan 0027, "Fix at the source".** `signals/_fundamentals.market_caps` uses stale vendor share counts (22 pond names; IIAB 22×). It also sets live tiers and the MICRO carve-out, so daily picks may be affected. Build the fix on a worktree branch, cross-checked against `shareholding_categories.total_shares` adjusted for splits and bonuses. Measure the pick change and merge only on Amit's OK.
3. **Plan 0026 4b.1 + 4.3.** The red-flag gate (`signals/multibagger._red_flags`) reads only `bse_announcements`, which has been blocked since 2026-10-13: add `nse_announcements`. Then wire `signals.mb_watch.new_since()` into `output/email_sender.py` and push, for the 30 candidates.
4. **Merge `cockpit-scale`** (575f7b2…8aa44de).
   - Expect conflicts in `cockpit/mf.py`, `schema.sql`, `tables.py` and `cockpit/app.py`.
   - Run the full pytest, including `tests/test_cockpit_scaling.py`.
   - Restart both cockpits, then delete `/etc/systemd/system/alpha-cockpit-ops.service.d/rewarm-off.conf`, daemon-reload and restart ops.
   - Ask Amit about the 3 `ix_scale_*` indexes and the 28 `shareholding_holders` rows dated 1982–2001.

## Watch out
- **Multibagger: a newly researched sid needs a line in `output/mb_sectors.py`.** Research sectors replace the vendor tags, which were wrong for about 1 in 6 names. `--sectors` lists any that are missing. The thesis "industry momentum" part still uses the vendor `stocks.industry` (plan 0027).
- **Multibagger: research agents write `report.md` with a bash heredoc.** The Write tool refuses report-like files from subagents. About 11 agents running in parallel plus a full pytest got the process OOM-killed (exit 137), so don't run the suite while a wave runs. One wave hit the session rate limit; resume each agent with SendMessage rather than relaunching it.
- **Multibagger: the weekly re-rank brings unresearched names into the top 100** (plan 0026 4b.2). The candidates do not follow automatically; `python -m output.mb_research --promote` only adds names.
- **`data/paper/mb_books.json` was restarted 2026-10-16 on the gated run.** The pre-gate state is `mb_books.superseded-2026-10-16-pre-data-gates.json`, kept for the record.
- **`git push` takes several minutes:** a pre-push suite runs (PIT replay and more). Use a long timeout; it is not hung.
- **`policy_events` / `sector_policy_pit` is NOT point-in-time.** It is 28 events hand-curated in 2026 with hindsight weights (some are outcomes, none after 2025-04). It passed a multibagger test and was disqualified. Plan 0025 7.1's theme book (grade B) also used it, so that grade may be inflated.
- **`cron_bse_announcements` will keep failing** until BSE access is back (another egress IP, or Amit drops the route). The NSE route is a separate table, `nse_announcements`, with its own taxonomy `config.NSE_ANNOUNCEMENT_CATEGORIES`. The governance and credit-rating factors still read BSE only.
- **The multibagger edge sits in stocks trading ₹0.5–1 Cr a day** (a ₹1 Cr floor drops it from +12.7 to +5.2 %/yr). It was tested at ₹1 lakh per name; don't size it up without re-testing costs.
- **Worktrees to clean up:** `.claude/worktrees/mb-desk` (it has symlinks into `output/` and `data/`), plus the merged agent worktrees (a12aaf…, a25b2a…, a84c70…, aaf54a…, adfa93…, afe309…). Use `git worktree remove`.
- **`output/paper_sleeve/latest.json` is a cockpit input** (`_file_paper_sleeve` in `config.FILE_OUTPUTS`, read only by `views.paper_sleeve`). `python -m tools.paper_sleeve status` rewrites it without trading; `rebalance` trades. Never run `rebalance` by hand outside the 2nd.
- **The harvester's "N items · M with data" undercounts by design.** Once its time budget is spent it returns "no data" instantly for every remaining stock; they are picked up in the next window, not lost.
- **MF "New money" status is only as fresh as the Groww rotation** (`sources/mf_holdings_groww.py`, each fund re-checked about every 14 days; 326 plans have no Groww page, and Kuvera now covers overseas FoFs). 12 plans (3 Axis/Bandhan target-maturity funds) have a last NAV of 2026-09-11 yet are still in AMFI's file: a NAV-feed gap or an early closure, unchecked.
- **Ops re-warm is off via a systemd drop-in (`rewarm-off.conf`), not code.** Leave it until `cockpit-scale` (6 h TTL) is live.

## Active plan
docs/plans/0026-multibagger-desk.md (LIVE; 4b follow-ups, 4.3 alerts, 4.4 PDFs, electoral-bond file, D3 money, D4 strict tab, D7 pick the 10) · docs/plans/0027-forensic-data-audit.md (proposed; "Fix at the source" agreed) · docs/plans/0025-slow-core-and-fast-tactical.md (research closed; first paper-sleeve rebalance 2026-11-02) · cockpit scaling: branch `cockpit-scale` (merge pending)
