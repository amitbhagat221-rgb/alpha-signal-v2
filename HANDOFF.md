# HANDOFF
Updated: 2026-06-01 | Branch: master (4 unpushed) | HEAD: `0fb4ef1` feat(cockpit): headline holding horizon + maturing state on /model/outcomes

## Left off
Started on a cockpit/email health divergence (`/system` read 14 CRITICAL, email read 0) and it cascaded into an evaluation-methodology thread. Fixed the false alarm (all 14 were expected-empty quarantine/paper/calibration tables), switched `pick_outcomes` to trading-day horizons 20/63/126, wired the silently-dead benchmark fetch, and shipped a read-only IC-decay diagnostic that confirms factors have heterogeneous natural horizons — the registry's single-20d t-stat is the wrong lens for slow factors. **Nothing in the live model changed.**

## Pick up here
1. **Decide ADR 0036's follow-up** — store `natural_horizon` in the registry + switch the promotion gate to net-of-cost IR at that horizon (data already in [tools/ic_decay.py](tools/ic_decay.py) / `data/ic_decay.json`; needs `backtest_pit.py` + registry + a turnover/cost model). The real lever from today; ties into Track 3.3a.
2. **Resume §3.2.6 `industry_id` one-hot + §3.2.7 macro betas** — today's *intended* work before the drive-bys. Check `macro_history` coverage first; new `signals/` + `tools/reconstruct_pit.py` wiring.
3. **`pt_upside` artifact re-verify (due 2026-08)** — now reinforced: ic_decay shows IC=0.67 / t=28 at 252d (survivorship). Re-run `python -m tools.backtest_pit --signal pt_upside` once ≥3 fresh `analyst_consensus_snapshots` exist → un-cap or pull.

## Watch out
- **ic_decay raw-|IC| "peak" classifies almost everything SLOW@252d** — partly mechanical (IC grows with horizon) + long-horizon survivorship (current-names-only universe). Read shape + sign-stability, NOT absolute peak. Do **not** wire a natural-horizon off raw peak |IC| without the net-of-cost normalization.
- **`pick_outcomes` 63d/126d are EMPTY until ~2026-07-06 / ~2026-10-02** (picks maturing). `/model` `headline_window` auto-promotes; empty is expected, not broken.
- `data/ic_decay.json` is gitignored → `--plot-only` reads it, so the committed `output/ic_decay_curves.png` can't be redrawn without the full ~3-min recompute.
- ic_decay graph "bold = live" matches only 4 factors (`config.SIGNAL_WEIGHTS` uses screener names ≠ backtest signal-ids) — known impedance mismatch, not a bug.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Phase 3.2, 42/50 PIT-shipped; §3.2.6 + §3.2.7 next. [ADR 0036](docs/decisions/0036-horizon-resolved-factor-evaluation.md) opens a Track-3.3a-adjacent methodology thread.
