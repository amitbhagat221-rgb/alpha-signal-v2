# HANDOFF
Updated: 2026-06-03 | Branch: master (0 unpushed; this session UNCOMMITTED) | HEAD: `64d24a8` docs(handoff): wrap horizon-gate weight-review session

## Left off
Built a multibagger screen end-to-end — Novy-Marx `gross_profitability` anchor (full factor contract + PIT twin) + a 3-stage hurdle/filter funnel in `signals/multibagger.py` → `multibagger_scores` (35 credible survivors incl. TIPS/Steelcast/Manyavar/Natco) — then validated it survivorship-corrected + split-adjusted across two regimes. The verdict IS the headline: 2–4yr multibagger capture is **regime-dominated** — the same quality screen makes +0.10x spread in the 2018→21 bear and −0.30x in the 2022→26 junk rally. Next build is a regime gate, not more quality factors. See ADR 0039.

## Pick up here
1. **Regime gate + regime-conditioned weights** — `signals/multibagger.py` uses static `PILLAR_WEIGHTS`; `tools/multibagger_cohort.py` shows quality AND cheapness flip sign by regime. Add Report C's small-cap EMA trend gate (reuse `scoring/regime.py`/`macro_history`).
2. **A 3rd independent regime window** — `python -m tools.build_historical_universe --dates 2019-04-01,2022-04-01` then `python -m tools.multibagger_cohort --anchor 2019-04-01 --end 2022-04-01`. Two overlapping windows ≠ a verdict.
3. **Surface (Phase 4)** — `/multibagger` cockpit page + weekly `PIPELINE_STEPS` entry for `signals.multibagger` (NOT yet wired; keep OUT of `daily_picks`).

## Watch out
- `stocks.market_cap_cr` is in **RUPEES not crores** (÷1e7); `stocks.debt_to_equity`/`pe_ratio` are **EMPTY** (compute D/E + PE from Screener). `quarterly_income` too shallow (43 sids ≥12q) → growth from **ANNUAL** `Net profit`.
- `bhav_copy_with_delivery` only reaches ~2020; pre-2020 universe uses the old-format archive (`tools/build_historical_universe.py:_old_bhav`). Cohort assigns delisted names 0x (`DEATH_MULT`).
- `gross_profitability` 20d backtest = DROP (n=6) — **wrong lens** (quality is long-horizon; `roic` looks dead at 20d too). Not a kill.
- This tree ALSO carries Amit's pre-existing 2026-06-03 cron-freshness drive-by (CLAUDE.md cron rule, `config.RAW_TABLES`, `db.STALENESS_OVERRIDES`, `sources/nselib_pull.py`) intermingled with the multibagger work in `config.py`/`db.py` — `git add -p` unavailable, so it commits together unless split by hand.

## Active plan
docs/plans/0008-multibagger-model.md (Phase 1 shipped, Phase 2b regime-validated, Phase 3–4 next)
