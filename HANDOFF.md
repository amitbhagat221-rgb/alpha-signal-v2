# HANDOFF
Updated: 2026-05-31 | Branch: master (1 commit → pushed) | HEAD: `feat(signals): sector_momentum factor + /sectors horizon badges (Plan 0006 Phase E)`

## Left off
Plan 0006 is now **fully shipped (Phases A–E)**. Today closed the three Next-3 items (corp_actions daily wiring, the slug-override registry, Phase D LLM sector dossiers) and then Phase E: a `sector_momentum` factor driving S/M/L horizon badges on `/sectors`. The factor backtested **SMALL t=1.88 WEAK** (MID 0.33 / LARGE −0.60 DROP) → stays on the bench, not wired into screener weights.

## Pick up here
1. **Deploy the Phase E badges** — live `:3000/sectors` shows 0 `sd-horizons` because [cockpit/api.py](cockpit/api.py) + [cockpit/templates/sectors.html](cockpit/templates/sectors.html) changed *after* the last cockpit restart. `sudo systemctl restart alpha-cockpit.service`, then confirm 11 sectors render S/M/L badges (verified in-process, not yet live).
2. **Track 3.1b — NSE F&O OI** (next frontier, unblocks §3.2.2 options cluster) — [sources/nselib_pull.py](sources/nselib_pull.py) already has `pull_fii_positioning` via `nselib.derivatives`; extend to participant/strike OI, design the schema + a daily/forward cron line.
3. **sector_momentum medium-horizon breadth trend** — Plan 0006 Phase E spec wanted the medium horizon to fold in a 4-week `breadth_pct` trend, but `sector_briefs` only has 3 days of history (2026-05-29→31). Once ≥4 weeks accrue, add it to [signals/sector_momentum.py](signals/sector_momentum.py) (currently medium = 3m price-RS only).

## Watch out
- **`sector_momentum` is sector-CONSTANT** — every stock in a sector shares the value (z-score of its sector's medium RS). Within-sector ranking is unaffected; it only differentiates *across* sectors within a cap_tier. On the bench (SMALL t=1.88), **NOT in `SIGNAL_WEIGHTS`** — see its `status_reason` in [db.py](db.py) `BACKTEST_SIGNALS`.
- **PIT backfill onto an existing panel must use explicit `--date`** — I ran `reconstruct_pit --signal sector_momentum --date …` ×148 (existing dates only). Using `--cadence weekly/monthly` would *generate new Fridays* and INSERT partial rows (only sector_momentum + close populated, NaN elsewhere), polluting the panel.
- **sector_momentum uses raw (unadjusted) `stock_prices.close`**, winsorized per-constituent to [−0.6, 3.0] to bound split artifacts — chosen so the live and PIT paths run *identical* logic (no adj_close divergence). A large-cap constituent split still nudges its sector's RS slightly.

## Active plan
[Plan 0006 — Sector dossiers](docs/plans/0006-sector-dossiers.md) — **fully implemented (A–E)**; archive in ~30 days. Next frontier: Track 3 §3.1b (NSE F&O OI), [plan 0002](docs/plans/0002-100-factors-and-model.md).
