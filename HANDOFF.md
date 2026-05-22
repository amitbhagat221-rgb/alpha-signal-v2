# HANDOFF
Updated: 2026-05-22 | Branch: master (0 unpushed) | HEAD: `6d70f0f` docs(workflow): tie sessions to the checklist + expand active phase view

## Left off
Verified Track 3.1a scrape completed (1,775 sids with Trade Payables, 388,050 rows, 668 failures — all SMALL/delisted). Tightened the session workflow further: checklist Track 3.2 now shows the active factor with sub-tasks, `/catchup` reads the checklist and names the session bullet, `/handoff` gained rule (e) for phase-start expansion. Ready to ship `cash_conversion_cycle` in the next session.

## Pick up here
1. Ship `signals/cash_conversion_cycle.py` + `pit_cash_conversion_cycle(sid, eval_date)` in [tools/reconstruct_pit.py](tools/reconstruct_pit.py) (unit of work — never separately). Template: [signals/roic.py](signals/roic.py). Score table `cash_conversion_cycle_scores (sid, snapshot_date, dso, dio, dpo, ccc, PK (sid, snapshot_date))`.
2. Wire `signal_cash_conversion_cycle` into `config.PIPELINE_STEPS` after `signal_fcf_yield`. Smoke-test on 3 stocks (e.g. RELI / MARUT / DRRD) before universe run.
3. `python -m tools.reconstruct_pit --signal cash_conversion_cycle` then `python -m tools.backtest_pit` → read t-stat per cap tier from `pit_ic_by_tier_v2`. Promote to scoring weights only if `|t| ≥ 1.5`.

## Watch out
- Track 3.1a's 668 failures (27%) are almost all SMALL / delisted. CCC's eligible universe is ~1,775 sids (not 2,448). Coverage will look weak on SMALL — expected, not a bug.
- Financials don't have meaningful Trade Payables (banks have deposits). Filter `sector != 'Financials'` before computing CCC, per [CLAUDE.md](CLAUDE.md) "financial sector exclusion" rule.
- `/catchup` now names the active checklist bullet at session start. If next session opens and the bullet doesn't match what you intend to work on, *stop and edit the checklist first* — new guardrail per today's CLAUDE.md edit.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Track 3 Phase 3.2 (cash_conversion_cycle is the active factor)
