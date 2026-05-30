# HANDOFF
Updated: 2026-05-30 | Branch: master (0 unpushed) | HEAD: `ce5cd58` feat(plan-0007): Phase 7

## Left off
**Plan 0007 (Trust Pipeline + UHS) fully shipped across 8 phases over 4 sessions** — 7 gates live (Identity / Plausibility / Temporal / Cross-Source / Unit / Lineage / Anchor), per-pick UHS on every `daily_picks` row, single 🟢/🟡/🔴 colour vocabulary across cockpit + dossier email, 9 historic bugs as permanent pre-push regression tests, 14 redundant data_sanity checks deprecated (runtime-skipped), [ADR 0033](docs/decisions/0033-trust-pipeline-uhs.md) documenting the 95/100 honest-ceiling architecture. Today's 1,689 picks score 1,440 PRELIMINARY + 249 REVIEW + 0 AVOID; system UHS healthy.

## Pick up here
1. **Plan 0007 Phase 8 burn-in monitoring** — let UHS verdicts accumulate for 7 days; expected: most PRELIMINARY labels flip to TRUSTED as gate_4 + gate_5 + gate_7 verdict pools fill. Re-check `health_score` distribution + at least one pick should be UHS-downgraded over the week (proves gates do work). Manual seed for Gate 7 Anchor B (top-50 BSE close, weekly) via `python -m tools.anchor_audit --seed-bse-csv ...` — first run due ~2026-06-06.
2. **Plan 0006 Phase D — LLM-narrated sector dossiers** (resumes from deferred state) — [docs/plans/0006-sector-dossiers.md §Phase D](docs/plans/0006-sector-dossiers.md). New `sector_dossiers` table; 11 LLM calls/night (~₹3-5). Now that UHS feeds `output/dossier.py:_build_uhs_block()`, the sector dossiers should inherit the same hygiene rule (no strength claims when underlying signal UHS < 12 on any dim).
3. **Track 3.1b — NSE F&O OI probe** (resumes from deferred state) — unblocks `§3.2.2` options-implied (8 factors). Probe `nselib.derivatives` (option chain, OI history, participant-wise OI); design `fno_option_chain` + `fno_oi_history` schemas; fetcher with cookie-warm + 2s rate. Independent of UHS.

## Watch out
- **Plan 0007 Phase 6 Anchor B + C are partly-manual** — Anchor A (NSE bhavcopy) is automated daily; B (BSE top-50 close) needs a 30-min weekly seed; C (AMC factsheets) needs a 30-min monthly parse. Cockpit `/system` "Anchors" tile shows next-due-date and goes amber after 7d, red after 14d.
- **The 14 deprecated `data_sanity` checks aren't deleted yet** — they're tagged `deprecated_in_plan_0007` and runtime-skipped. If a gate regresses, set the flag back to False for the offline auditor of that bug class to resurface it. A future plan can delete them after burn-in.
- **`uhs_calibration_log` populates as `pick_outcomes` matures** — today the join returned 0 rows because picks just got UHS; forward returns mature in 5/20/60 trading days. By ~2026-12 there should be 6+ months of (UHS, forward-return) pairs to regress against the uniform 20/20/20/20/20 dim weighting.
- **`output/dossier.py` LLM prompt now includes UHS** — `_build_uhs_block` injects score + worst dim + per-dim hygiene constraints (e.g. "DO NOT claim 'strong fundamentals' if dim_provenance < 12"). If a sector-dossier prompt is built, mirror this pattern.
- **ntfy push now fires on system UHS <60** — `_system_uhs_alert()` in `tools/health_report.py` reads `health_score WHERE entity_kind='system'`. If the geometric mean of tier-1 critical tables drops, a single broken table sets off the phone push before any pick based on that table reaches morning_brief.
- **Plan 0007 Trust Pipeline is now load-bearing** — `daily_picks.uhs_score >= 60` is a hard filter in `cockpit.api.get_top_picks` (drives morning-brief + action_queue) and `output.email_sender._build_html` (daily dossier email). NULL fallback covers legacy rows; once UHS is universal a future plan drops the NULL branch.

## Active plan
[Plan 0007 — Trust Pipeline + UHS](docs/plans/0007-trust-pipeline-uhs.md) — **8 of 8 phases shipped 2026-05-30** ([ADR 0033](docs/decisions/0033-trust-pipeline-uhs.md)). Burn-in monitoring + manual anchor seeding now ongoing.

[Plan 0006 — Sector dossiers](docs/plans/0006-sector-dossiers.md) — Phase D (LLM narration) + Phase E (per-sector horizon scores) remain.
