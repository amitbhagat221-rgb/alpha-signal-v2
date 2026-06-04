# HANDOFF
Updated: 2026-06-04 | Branch: master (0 unpushed) | HEAD: `5bbe322` feat(multibagger): conviction monitor — hold winners through drawdowns

## Left off
Reframed multibagger from a SELECTION problem (dead — no at-entry factor ranks 2–4yr winners; stock-score ρ−0.06, sector ρ+0.41 but unpredictable mechanically) to a HOLDING problem: the alpha is *not getting shaken out*. Validated that sector momentum works at 1–6mo (t+3) but is dead by 2–4yr, so it's the MONITORING signal — built/backtested a conviction monitor and wired HOLD/WATCH/REVIEW into `/multibagger`.

## Pick up here
1. **Restart `alpha-cockpit` to activate the conviction column** — `cockpit/api.py` `_conviction_verdicts` is committed but the running :3000 process has the old module cached (template hot-reloads, Python doesn't).
2. **Doc + wire the daily sector tilt** — sector momentum + macro ensemble validated for DAILY picks (t+3, [tools/sector_signal_lab.py](tools/sector_signal_lab.py)) but only the multibagger monitor was built. Overweight top-quintile-momentum sectors in `daily_picks` (needs its own ADR when wired).
3. **Stress-test the monitor on a bear-ending window** — [tools/multibagger_monitor.py](tools/multibagger_monitor.py) only ran two mostly-rising cycles; the eject hatch is under-tested. `stock_prices` starts 2022, so do it sector-index-level via [tools/sector_regime_history.py](tools/sector_regime_history.py).

## Watch out
- `stock_prices` is RAW NSE bhavcopy — a bonus/split is a fake −X% cliff. Any drawdown/path work MUST back-adjust via `corporate_actions` (done in `multibagger_monitor._adjusted_panel` + cockpit `_conviction_verdicts`). My first path stat (84% of winners ≥30% DD) was split-inflated; adjusted = 81%.
- The 3 new monthly accumulators (`sector_analyst_breadth_pit` / `sector_sentiment_breadth_pit` / `sector_policy_pit`) are dormant until **2026-07-01** (pipeline monthly gate = `day==1`, [pipeline.py:59](pipeline.py)). Analyst breadth has only 1 MoM row (needs ≥2 snapshots; July 1 gives the 2nd).
- `macro_gov` data is STALE (IIP ends 2023-02, GST 2023-11) → the specific macro→sector link tests (credit→Financials, IIP-capgoods→Industrials) are blocked until it's refreshed.
- `sector_regime_history.py` caches yfinance at `/tmp/sector_regime_cache.parquet`; `multibagger_cohort --sector-test` reads it — run the history tool first if the parquet is missing.

## Active plan
docs/plans/0008-multibagger-model.md (Phase 5 — holding/conviction monitor shipped; selection-ranking track closed)
