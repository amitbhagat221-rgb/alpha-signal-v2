# HANDOFF
Updated: 2026-06-03 | Branch: master (0 unpushed) | HEAD: `43cf21a` feat(model): multibagger screen + cron-freshness drive-by

## Left off
Two workstreams landed today, both in `43cf21a` (parallel sessions — committed together because the freshness edits were intermingled with multibagger edits in `config.py`/`db.py`, not separable without interactive add):

**(A) Multibagger screen** — Novy-Marx `gross_profitability` anchor (full factor contract + PIT twin) + a 3-stage hurdle/filter funnel in `signals/multibagger.py` → `multibagger_scores` (35 credible survivors incl. TIPS/Steelcast/Manyavar/Natco), validated survivorship-corrected + split-adjusted across two regimes. The verdict IS the headline: 2–4yr multibagger capture is **regime-dominated** — the same quality screen makes +0.10x spread in the 2018→21 bear and −0.30x in the 2022→26 junk rally. Next build is a regime gate, not more quality factors. See ADR 0039.

**(B) Cron-freshness blind-spot closed** (drive-by, fully done) — the monthly `analyst_consensus_snapshots` cron had silently failed every run (cd-less `python -m` → `ModuleNotFoundError`; June 1 missed, likely never succeeded — the lone 2026-05-01 anchor was a manual backfill). **Root-cause class**: standalone-cron tables (outside `PIPELINE_STEPS`) get NO freshness benchmark → invisible to watchdog/health/email; trust gates validate rows that exist, not absence. Fixed: cron `cd`; recovered June anchor (907 rows @ 2026-06-01); registered 5 standalone tables in `config.RAW_TABLES` + tuned `STALENESS_OVERRIDES`; wired `short_selling` into `run_daily_forward.sh` (recovered 5/24→6/03); fixed `pull_surveillance_today` F&O-ban parse crash (`'int'.strip()` — first `FNO_BAN` rows ever). Health 68→73 fresh, 0 CRITICAL. CLAUDE.md cron rule added.

## Pick up here
1. **Regime gate + regime-conditioned weights** (multibagger) — `signals/multibagger.py` uses static `PILLAR_WEIGHTS`; `tools/multibagger_cohort.py` shows quality AND cheapness flip sign by regime. Add Report C's small-cap EMA trend gate (reuse `scoring/regime.py`/`macro_history`).
2. **A 3rd independent regime window** — `python -m tools.build_historical_universe --dates 2019-04-01,2022-04-01` then `python -m tools.multibagger_cohort --anchor 2019-04-01 --end 2022-04-01`. Two overlapping windows ≠ a verdict.
3. **Surface (Phase 4)** — `/multibagger` cockpit page + weekly `PIPELINE_STEPS` entry for `signals.multibagger` (NOT yet wired; keep OUT of `daily_picks`).

## Watch out
- `stocks.market_cap_cr` is in **RUPEES not crores** (÷1e7); `stocks.debt_to_equity`/`pe_ratio` are **EMPTY** (compute D/E + PE from Screener). `quarterly_income` too shallow (43 sids ≥12q) → growth from **ANNUAL** `Net profit`.
- `bhav_copy_with_delivery` only reaches ~2020; pre-2020 universe uses the old-format archive (`tools/build_historical_universe.py:_old_bhav`). Cohort assigns delisted names 0x (`DEATH_MULT`).
- `gross_profitability` 20d backtest = DROP (n=6) — **wrong lens** (quality is long-horizon; `roic` looks dead at 20d too). Not a kill.
- **(freshness)** `short_selling_data` `STALENESS_OVERRIDE=7` is PROVISIONAL — tighten after observing the first few `run_daily_forward.sh` cron cycles (NSE posts T+1 with quiet-day gaps). The crontab `cd`-fix is **live on the VM, outside git** (backup `/tmp/cron_backup_20260603.txt`).
- **(freshness)** Next-3 #2 `pt_upside` re-verify now has 2 monthly anchors (May+June); the fixed cron makes 3 on July 1 → re-verify lands ~August as planned.

## Active plan
docs/plans/0008-multibagger-model.md (Phase 1 shipped, Phase 2b regime-validated, Phase 3–4 next) · freshness drive-by tracked at docs/plans/0000-checklist.md Next-3 #0 (✅ done)
