# HANDOFF
Updated: 2026-05-22 | Branch: master (7 unpushed) | HEAD: `4ddcc20` refactor(docs): rule-of-3 doc system + Track 1/2/3 rename + chronological plan numbering

## Left off
Today was meta — collapsed the doc system to rule-of-3 (3 root files · 3 docs/ folders · 3 HANDOFF sections), renamed C/D/F-tracks to Track 1/2/3 ([ADR 0015](docs/decisions/0015-track-numbering-and-rename.md)), renumbered plans chronologically ([ADR 0016](docs/decisions/0016-plan-numbering-fresh-start.md)), and shipped `docs/plans/0000-checklist.md` as the live status view. No factor or portfolio code changed — Track 3 Phase 3.2 is in the exact same spot as 2026-05-10.

## Pick up here
1. `git push origin master` — 7 commits sitting locally (oldest 11 days, today's mega-refactor on top)
2. Verify Track 3.1a schedules scrape finished: `ps -ef | grep schedules` + `sqlite3 data/alpha_signal.db "SELECT COUNT(DISTINCT sid) FROM fundamentals_screener WHERE line_item='Trade Payables';"` (expected ~1,800–2,000)
3. Resume Track 3 Phase 3.2 — ship the 6-factor batch (`cash_conversion_cycle`, `gross_margin_trend`, `roiic`, `working_capital_intensity`, `debt_structure`, `asset_tangibility`) each paired with `pit_<x>(sid, eval_date)` in [tools/reconstruct_pit.py](tools/reconstruct_pit.py); retrofit PIT helpers for live `roic` + `fcf_yield`

## Watch out
- New numbering convention is live everywhere. Reading any pre-2026-05-22 commit needs the mapping table in [ADR 0015](docs/decisions/0015-track-numbering-and-rename.md) + [ADR 0016](docs/decisions/0016-plan-numbering-fresh-start.md) to translate D14/F1/plan-0005-style refs
- `/handoff` now has a step 1.5 that updates `docs/plans/0000-checklist.md` — don't skip it or the checklist drifts from the plans
- 11-day gap between previous code work (2026-05-12) and today is still uninvestigated — the F1.2 (now 3.1a) scrape may have completed silently or failed silently

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Track 3 Phase 3.2 (factor batch + PIT helpers)
Also queued: [docs/plans/0004-consumer-demand-pulse.md](docs/plans/0004-consumer-demand-pulse.md) — research phase R1, side-quest while Track 3 ramps
