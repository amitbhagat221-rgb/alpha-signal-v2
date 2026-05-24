# HANDOFF
Updated: 2026-05-24 (session #4, late-stage) | Branch: master (1 unpushed after commit) | HEAD: `5d05158`

## Left off
**Phase D of plan 0005 fully shipped in one session.** Started the day at confidence 75; current estimate **88-90/100**. Today the cockpit's factor library went from claiming KEEP/WEAK/DROP for 50+ factors on n=6 (statistically meaningless) → 17 KEEPs all backed by n=18-40 with 95% bootstrap CIs displayed inline. The journey:

1. **n<12 INSUFFICIENT gate** (commit `5d05158`) — `cockpit.api.get_factor_health` now classifies any factor with n_periods < 12 as INSUFFICIENT regardless of t-stat magnitude. Source selection also fixed: previously preferred v2_recompute (n=6) over v1_archive (n=35) by hardcoded order, masking the deeper signal. Now picks adequate-n sources first.

2. **Bootstrap 95% CI on t-stat** (same commit) — `tools.backtest_pit._bootstrap_t_ci()` resamples IC series B=1000 times, takes 2.5/97.5 percentiles. Works for both classical and Newey-West SE. New columns `pit_ic_by_tier_v2.t_stat_ci_lo/_hi` (idempotent migration). Cockpit displays `95% CI [lo, hi]` beneath each t-stat with tooltip.

3. **Extended monthly PIT 7 → 60 snapshots** — ran `tools.reconstruct_pit --months 60` in background (~17 min). New depth: **147 distinct dates from 2022-08 to 2026-05** (60 monthly + 87 weekly Fridays). 112,608 rows written to `daily_snapshots_pit`.

4. **Re-ran `tools.backtest_pit`** with the deeper window — 197 rows in `pit_ic_by_tier_v2`. Most factors now have n=18-40 (was n=6). CIs populated for every backtested factor.

5. **Result**: validation distribution went `KEEP 8 / WEAK 2 / DROP 4 / INSUFFICIENT 42 / NONE 7` → **KEEP 17 / WEAK 15 / DROP 16 / INSUFFICIENT 8 / NONE 7**. The 8 remaining INSUFFICIENT are genuinely new factors. CIs reveal robust vs marginal: `pt_upside` t=9.14 CI [6.58, 13.96] is rock-solid, while `cf_accruals` t=-2.53 CI [-6.19, -0.47] barely clears the threshold.

Also in this session before Phase D: shipped A + B fully (per-signal eligibility + per-stock integrity validator) and ~80% of Phase C (regulatory feed alive, yfinance price fallback 86%→99.9%, eligibility regression check armed).

## Pick up here
1. **Plan 0005 Phase E — End-to-end PIT replay validator (90 → 93)** — the next confidence climb. Freeze 6 historical dates (1 per quarter 2024-25), persist exact picks/scores. `tools/pit_replay.py` reconstructs from scratch using ONLY data available at that date, compares vs frozen snapshot. Catches "did a producer rewrite drift PIT?" class of bug. ~2-3 sessions.
2. **Verify regulatory_signals after classifier completes** — classifier still running (~38 batches, started 19:00 IST, ETA ~1.5hr total). Once done, re-run `signals.regulatory` to recompute sector tilts. Should clear the WARN `regulatory_signals OUTDATED (44d)`.
3. **Phase F — Risk decomposition + sub-models (93 → 95)** — already partially on roadmap (Track 2.2 financial sub-model, Track 3.3d Barra-style risk decomp).

## Watch out
- **Classifier still in flight (background task `b2o6xe2ih`)** — ~$3.41 Anthropic spend in progress, batches 5+ of 38 when I last checked. Don't kill it; the budget is already committed and we want the `regulatory_signals` table refreshed before the next pipeline run.
- **`pit_ic_by_tier_v2` PK is (signal, cap_tier, source)** — multiple source rows per signal/tier. Cockpit picks best per rule "adequate n first, then v2 over v1, then highest |t|". If you query the table directly, filter by source or you'll see duplicates.
- **Bootstrap CI is fixed-seed (42)** — same inputs reproduce same CI bounds. Good for diff-ability; if you ever change B or want true randomness, change the seed.
- **The 8 INSUFFICIENT factors** are mostly Track 3 newcomers (less than 12 months of v2 data). They'll naturally exit INSUFFICIENT as more snapshots accumulate.
- **bsoning out for the day's commits**: 4 commits since session start, all clean. graphify hook fires on each.

## Active plan
[docs/plans/0005-data-confidence-to-95.md](docs/plans/0005-data-confidence-to-95.md) — **A + B + ~80% of C + D shipped today**. Phase E (PIT replay) and Phase F (risk decomp) remain. Confidence 75 → ~88-90.
