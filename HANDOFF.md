# HANDOFF
Updated: 2026-06-05 | Branch: master (0 unpushed) | HEAD: `68d625e` docs: handoff + checklist (REXP exclusion, bear-stress guard…)

## Left off
Un-deferred and wired the validated daily sector tilt: built `sector_tilt` as a first-class backtestable factor ([signals/sector_tilt.py](signals/sector_tilt.py) + `pit_sector_tilt` twin), backtest-gated it (SMALL t+3.18 KEEP / LARGE +0.92 / MID +0.64 DROP — beats the benched 63d-RS cousin in every tier, clears only SMALL), and wired it **SMALL-only @0.10** in `config.SIGNAL_WEIGHTS` ([ADR 0041](docs/decisions/0041-sector-tilt-backtest-gated-small-only.md)). REXP deeper detectors parked as 💤 TBD per your call.

## Pick up here
1. **Re-judge `sector_tilt` LARGE (t+0.92) / MID (t+0.64)** as the monthly PIT panel deepens — `python -m tools.backtest_pit --signal sector_tilt` once anchors thicken (now 34); wire only if either clears |t|≥1.5 ([config.py](config.py) `SIGNAL_WEIGHTS`, signal-weights.md review).
2. **`pt_upside` artifact re-verify (due 2026-08)** — `python -m tools.backtest_pit --signal pt_upside` once ≥3 fresh `analyst_consensus_snapshots`; un-cap or pull (currently capped 0.15–0.25 in `config.SIGNAL_WEIGHTS`).
3. **MID accruals/consensus + smart_money (n=6) re-judge** as anchors thicken — [tools/promotion_gate.py](tools/promotion_gate.py) `--reeval-live`.

## Watch out
- `sector_tilt` is **sector-constant** (11 distinct values → ties within a sector); it's a 0.10 *tilt*, not a stock-selector — it won't reorder names within a sector, and the backtest t=3.18 is on exactly this tie-heavy percentile structure. Don't bump the weight expecting finer discrimination.
- **New PIT columns need `db._ensure_columns()`** to ALTER the live `daily_snapshots_pit` — `reconstruct_pit`'s `CREATE TABLE IF NOT EXISTS` will NOT add a column to the existing table (hit this today: `no column named sector_tilt` until the migration ran). The `_COLUMN_MIGRATIONS` entry alone isn't enough; the migration has to be invoked.
- Don't confuse `sector_tilt` (6m basket + macro ensemble, SMALL-wired) with the benched `sector_momentum` (63d cap-wtd RS, unwired) — same family, different construction.

## Active plan
[docs/plans/0008-multibagger-model.md](docs/plans/0008-multibagger-model.md) (Phase 5 complete). Sector-tilt thread closed → [ADR 0041](docs/decisions/0041-sector-tilt-backtest-gated-small-only.md). Working plan: `~/.claude/plans/sunny-plotting-milner.md` (implemented).
