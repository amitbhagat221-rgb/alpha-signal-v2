# HANDOFF
Updated: 2026-06-04 | Branch: master (0 unpushed) | HEAD: `5895b57` docs: defer daily sector-tilt wiring

## Left off
Off `/catchup`: committed the verified revenue-plausibility REXP exclusion, then bear-stress-tested the multibagger conviction monitor and found the REVIEW eject rule is **inverted in real bears** (fires at 2008/COVID capitulations that ~doubled) — fixed it with a market-regime guard, tightened the watchlist 35→19, and added an in-app usage guide. Also **validated** the daily sector-momentum tilt as genuinely orthogonal to stock momentum (Fama-MacBeth +0.84%/σ, t+3.34) but **parked the wiring** per your call ("optimise later").

## Pick up here
1. **Restart `alpha-cockpit`** — the regime-guard code in [cockpit/api.py](cockpit/api.py) `_conviction_verdicts` (committed `3780c97`) isn't in the running process (it started before the commit). `sudo systemctl restart alpha-cockpit` activates the guard + the live small-cap-DD line in the `/multibagger` guide. Dormant now (small-cap ~−5% off peak), so no functional gap today — just stale code.
2. **Wire the deferred daily sector tilt** (💤, checklist Next-3) — signal proven in [tools/sector_tilt_validation.py](tools/sector_tilt_validation.py); build the LIVE sector-signal producer in [scoring/screener.py](scoring/screener.py) (trailing-6m sector basket mom + latest `macro_sector_signals_pit.macro_score`, z-scored across 11 sectors, mapped per stock), pick mechanism + magnitude (signal-weights.md review), write ADR 0041.
3. **REXP deeper detectors** (checklist Next-3 #4 (2)/(3)) — [signals/revenue_plausibility.py](signals/revenue_plausibility.py) is a patch, not a detector: add Dechow F-score (needs employee count) + standalone-vs-consolidated revenue divergence (needs a standalone pull).

## Watch out
- Cockpit **hot-reloads templates but NOT Python** — a template referencing a new `get_*()` payload key 500s the live `/multibagger` on the old process until restart (hit today with `o.market_dd`; fixed via defensive `{% if … is defined %}` in [cockpit/templates/multibagger.html](cockpit/templates/multibagger.html)). Add new payload keys defensively AND restart promptly.
- Conviction **REVIEW is bear-inverted** at index level. The new market-regime guard fixes market-wide crashes but NOT an idiosyncratic laggard in a recovered market (PSU Bank H2-2020 → +122%). REVIEW now means "reassess", never re-promote it to a mechanical sell.
- `sector_tilt_validation.py` shows **stock momentum was NEGATIVE in 2022+** (FM t−1.6) while the sector signal was +; the tilt win is a distinct orthogonal signal, not "momentum works" — don't conflate them when wiring.

## Active plan
docs/plans/0008-multibagger-model.md (Phase 5 — holding monitor, now bear-stress-hardened + watchlist tightened to 19). Daily sector tilt is a new thread: 💤 deferred → future ADR 0041.
