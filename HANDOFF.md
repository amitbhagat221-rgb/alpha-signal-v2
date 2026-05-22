# HANDOFF
Updated: 2026-05-22 | Branch: master (6 unpushed) | HEAD: `8f1150d` docs(plans): plan 0004 — consumer demand pulse signal

## Left off
Last code work was 2026-05-12 (data fetchers, freshness watchdog, cockpit cache, plan 0004 filed). Today's session was meta: simplified the doc system to rule-of-3 (3 root files, 3 docs/ folders, 3 HANDOFF sections) and renamed C/D/F-tracks to Track 1/2/3 ([ADR 0015](docs/decisions/0015-track-numbering-and-rename.md)). Track 3 Phase 3.2 still paused since 2026-05-10.

## Pick up here
1. `git push origin master` — 6 commits sitting locally for 10 days
2. Verify Track 3.1a schedules scrape finished: `ps -ef | grep schedules` + `sqlite3 data/alpha_signal.db "SELECT COUNT(DISTINCT sid) FROM fundamentals_screener WHERE line_item='Trade Payables';"` (expected ~1,800–2,000)
3. Resume Track 3 Phase 3.2 — ship the 6-factor batch (`cash_conversion_cycle`, `gross_margin_trend`, `roiic`, `working_capital_intensity`, `debt_structure`, `asset_tangibility`) each paired with `pit_<x>(sid, eval_date)` in [tools/reconstruct_pit.py](tools/reconstruct_pit.py); also retrofit PIT helpers for live `roic` and `fcf_yield`

## Watch out
- 10-day gap between last commit (2026-05-12) and today — context is reconstructed from git log, not fresh recall
- Doc system reorg today: `CHANGELOG.md` deleted, `docs/runbooks/` merged into `docs/reference/`, `docs/architecture.md` moved to `docs/reference/architecture.md`, CLAUDE.md slimmed from 200→~85 lines
- Don't refresh `sector_metadata` narratives before ~2026-06-11 — plan 0003 needs the 2026-05-11 snapshot as the Δ baseline

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) (Phase 3.2 — factor batch + PIT helpers)
Also queued: [docs/plans/0004-consumer-demand-pulse.md](docs/plans/0004-consumer-demand-pulse.md) (research phase R1, side-quest while Track 3 ramps)
