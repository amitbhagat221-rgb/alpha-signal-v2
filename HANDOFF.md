# HANDOFF
Updated: 2026-05-23 | Branch: master (0 unpushed, all session work uncommitted) | HEAD: `f8d1358` docs: handoff 2026-05-22 + ADR 0017 + /handoff includes commit+push

## Left off
Pulled the HALC cockpit thread, found Tickertape's `forecastsHistory.price[-1]` was `lastPrice` masquerading as analyst PT (95.6% of universe degenerate). Replaced with yfinance for `analyst_consensus.price_target` (902 stocks covered), rebuilt the PT data model into 3 tables × 3 cadences, and shipped the observability stack (`tools/health_report.py` + `tools/data_sanity.py` + watchdog file-output coverage) so the next class of silent failure surfaces automatically.

## Pick up here
1. Fix the `daily_picks` rank tie-break in [scoring/screener.py](scoring/screener.py) — `SANITY:DAILY_PICKS_RANK_DUPLICATE` fires CRITICAL (16 stocks share SMALL rank 2183). Add a secondary sort key (e.g., `sid`) to break ties.
2. Resume Track 3.2 batch — 13 new factors shipped today raised count from 6/50 to 19/50. Next in queue: `nse_fo_oi` ingest (Phase 3.1b) to unblock §3.2.2 options-implied factors. Alt path: §3.2.5 event-time/PEAD signals from existing data.
3. Decide `share_momentum` and `dso_change_yoy` scoring weights — both hit KEEP (|t|=3.21 and -2.81 LARGE respectively) but stay out of `SCREEN.weight_tiers` per CLAUDE.md "never mechanically." Manual ~0.5× or wait for Track 3.3a IC-stability framework.

## Watch out
- `pt_upside` |t| dropped 16.29 → 7.20 LARGE after the cleanup but is still suspiciously high; likely still a price-anchor artifact. Don't bump its weight in `SCREEN.weight_tiers` until ≥3 monthly `analyst_consensus_snapshots` accumulate (calendar: 2026-08).
- `analyst_consensus.price_target` is now NULL for ~1,538 stocks without yfinance coverage (mostly SMALL caps). Any signal that consumes it (`consensus_signals.pt_upside`, `signals/consensus.py`) silently produces NaN for those — by design, but `daily_picks` for SMALL is now ranking with a missing feature.
- New cron entries: watchdog @ 15:00 UTC, health_report @ 04:00 UTC, monthly snapshot @ 30 4 1 * *. First snapshot landed today (902 rows @ 2026-05-01); next at 2026-06-01.
- v2 cron now imports v1's exports via `eval "$(grep '^export ' /home/ubuntu/alpha-signal/run_pipeline.sh)"` — if v1's run_pipeline.sh is ever rewritten, v2 loses credentials silently. Treat the v1 file as load-bearing.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Track 3 Phase 3.2 (19/50 factors PIT-shipped). Phase 3.2.1 forensic/capital-allocation: 11/15 done. Next: §3.2.5 event-time OR §3.2.2 options-implied (needs Phase 3.1b ingest first).
