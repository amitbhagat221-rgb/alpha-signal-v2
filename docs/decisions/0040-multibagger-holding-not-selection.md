# 0040 — Multibagger is a holding problem, not a selection problem

Date: 2026-06-04 · Status: accepted · Extends [0039](0039-multibagger-funnel-regime-dominated.md)

## Context
ADR 0039 found the multibagger screen's RANKING has no edge (regime-dominated, top-decile spread zero-to-negative). This session exhausted the at-entry SELECTION search and reframed the whole problem.

Evidence (`tools/multibagger_cohort.py --sector-decomp`, `tools/sector_signal_lab.py`, `tools/sector_regime_history.py`, `tools/multibagger_monitor.py`):
- **No at-entry factor predicts the 2–4yr winner.** Stock score ρ −0.06 vs forward multiple; momentum, value, quality, macro, dispersion all ~0 or mean-reverting at 2–4yr.
- **The SECTOR realised return dominates the outcome** (ρ +0.41; tailwind-sector top-decile 1.51x vs 0.96x headwind) — but which sector wins at 2–4yr is unpredictable mechanically (it's a forward-judgment call: capex cycle, PLI, defense orders).
- **Sector momentum DOES work — but only at 1–6mo** (cross-sectional ρ +0.17→+0.26, t +3.0 to +4.3; ensemble with the orthogonal `macro_sector_signals_pit` engine → t +3.0). It decays to ρ≈0 by 36mo. So it is a MONITORING signal, not a selection one.
- **Multibaggers draw down brutally** (split-adjusted): 81% of eventual 3x+ winners endure a ≥30% drawdown → a stop-loss ejects you from winners (−30% stop: portfolio 1.88x→1.56x). Winners (−41% / 10mo underwater) vs losers (−62% / 27mo) separate on DEPTH + DURATION + whether sector momentum and relative strength stay intact.

## Decision
Operate the multibagger screen as a **holding** discipline, not a ranked product:
1. The hard GATES define a junk-stripped POND (no ranking within it — the score is noise).
2. Buy a **20–30 name equal-weight basket** spread across sectors (bootstrap: 20–30 names → P(≥1.5x) 85–91%, near-zero loss floor; concentration is a lottery).
3. **HOLD with conviction — no stop-losses.**
4. Monitor on a rolling 3–6mo cadence via a per-name **conviction verdict** (HOLD / WATCH / REVIEW) driven by drawdown depth+duration + sector momentum + relative strength; sell only on the full loser signature. Surfaced on `/multibagger` (`cockpit/api.py:_conviction_verdicts`), validated by `tools/multibagger_monitor.py` (retains 94–100% of winners ≈ buy-hold, crushes naive stops).

## Consequences
- The validated daily sector-momentum signal is reused as the multibagger monitor, not wasted; it is also the basis for a future daily-picks sector tilt (separate ADR when wired).
- No mechanical 2–4yr sector/factor tilt is wired (none validated) — sector at 2–4yr stays a forward-judgment context lens.
- Three monthly PIT accumulators started (`sector_analyst_breadth_pit`, `sector_sentiment_breadth_pit`, `sector_policy_pit`) so the remaining at-entry sector candidates become backtestable in ~12 months.
- **Caveat (resolved 2026-06-04):** both stock-price windows mostly rose, so the eject hatch was under-tested. Stress-tested by replaying the live rule on 15yr of 11 NSE sector indices (`tools/multibagger_monitor.py --sector-stress`, the only pre-2022 daily path data). Finding: the un-guarded REVIEW rule is **inverted in real bears** — it fires at market-wide capitulations (IT @2008 −55%, PSU Bank/Media @COVID), exactly the points that then ~doubled (REVIEW fwd24 +110% vs HOLD +27%). Fix: a **market-regime guard** — suppress REVIEW when NIFTY SMALLCAP 250 is itself ≥20% off its trailing peak (textbook bear line; eject only IDIOSYNCRATIC weakness). Shipped to `_conviction_verdicts`. It removes the market-wide false ejects (0 REVIEWs now fire in bear months) and preserves the one genuine structural decline (Realty 2011, fwd24 −36%). **Residual limit:** an idiosyncratic laggard in a recovered market (PSU Bank H2-2020 → +122%) can still mis-flag — no regime guard catches that — so the UI and rule now frame REVIEW as **"reassess the thesis," not a mechanical sell**.
