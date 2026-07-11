# Cadence/EMA parameter sweep (plan 0012 B2)

Read-only, sim-only ({'exit-rank': [8, 10, 12]} x {'drift_pp': [2.0, 3.0, 4.0]} x {'EMA halflife (trading days)': [None, 3, 5, 10]} = 36 cells), via `tools/rebalance_sim.py --sweep`'s in-memory replay of production `portfolio_construction._build_banded()` — nothing written to `portfolio_weights` or config. Production `debounce_days`/`resize` held at their current (ADR 0046 winner) values: debounce=3, resize=partial.

**Acceptance bar (plan 0011 WS1.1):** turnover <= 1.5%/day AND net_ann within 4.0pp of gross_ann AND daily-return corr vs the current production config (rank_exit=8, drift_pp=2.0, EMA=none) >= 0.9.

## All 36 cells

| cell | rank_exit | drift_pp | ema_halflife | turnover_pct_day | gross_ann_pct | net_ann_pct | net_sharpe | corr_vs_reference | pass_all |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| rx8/dp2/emanone | 8 | 2.0 | none | 6.21 | 30.26 | 2.01 | 0.11 | 1.0 | False |
| rx8/dp2/ema3 | 8 | 2.0 | 3 | 6.06 | 37.82 | 4.58 | 0.24 | 0.9564 | False |
| rx8/dp2/ema5 | 8 | 2.0 | 5 | 6.44 | 31.41 | -2.88 | -0.16 | 0.9711 | False |
| rx8/dp2/ema10 | 8 | 2.0 | 10 | 5.25 | 35.51 | 5.89 | 0.3 | 0.9554 | False |
| rx8/dp3/emanone | 8 | 3.0 | none | 6.21 | 30.26 | 2.01 | 0.11 | 1.0 | False |
| rx8/dp3/ema3 | 8 | 3.0 | 3 | 6.06 | 37.82 | 4.58 | 0.24 | 0.9564 | False |
| rx8/dp3/ema5 | 8 | 3.0 | 5 | 6.44 | 31.41 | -2.88 | -0.16 | 0.9711 | False |
| rx8/dp3/ema10 | 8 | 3.0 | 10 | 5.25 | 35.51 | 5.89 | 0.3 | 0.9554 | False |
| rx8/dp4/emanone | 8 | 4.0 | none | 6.21 | 30.26 | 2.01 | 0.11 | 1.0 | False |
| rx8/dp4/ema3 | 8 | 4.0 | 3 | 6.06 | 37.82 | 4.58 | 0.24 | 0.9564 | False |
| rx8/dp4/ema5 | 8 | 4.0 | 5 | 6.44 | 31.41 | -2.88 | -0.16 | 0.9711 | False |
| rx8/dp4/ema10 | 8 | 4.0 | 10 | 5.25 | 35.51 | 5.89 | 0.3 | 0.9554 | False |
| rx10/dp2/emanone | 10 | 2.0 | none | 5.58 | 30.36 | 4.75 | 0.26 | 0.9952 | False |
| rx10/dp2/ema3 | 10 | 2.0 | 3 | 5.36 | 36.84 | 8.86 | 0.47 | 0.9764 | False |
| rx10/dp2/ema5 | 10 | 2.0 | 5 | 5.95 | 32.48 | -0.2 | -0.01 | 0.9644 | False |
| rx10/dp2/ema10 | 10 | 2.0 | 10 | 5.26 | 35.36 | 6.01 | 0.31 | 0.9583 | False |
| rx10/dp3/emanone | 10 | 3.0 | none | 5.58 | 30.36 | 4.75 | 0.26 | 0.9952 | False |
| rx10/dp3/ema3 | 10 | 3.0 | 3 | 5.36 | 36.84 | 8.86 | 0.47 | 0.9764 | False |
| rx10/dp3/ema5 | 10 | 3.0 | 5 | 5.95 | 32.48 | -0.2 | -0.01 | 0.9644 | False |
| rx10/dp3/ema10 | 10 | 3.0 | 10 | 5.26 | 35.36 | 6.01 | 0.31 | 0.9583 | False |
| rx10/dp4/emanone | 10 | 4.0 | none | 5.58 | 30.36 | 4.75 | 0.26 | 0.9952 | False |
| rx10/dp4/ema3 | 10 | 4.0 | 3 | 5.36 | 36.84 | 8.86 | 0.47 | 0.9764 | False |
| rx10/dp4/ema5 | 10 | 4.0 | 5 | 5.95 | 32.48 | -0.2 | -0.01 | 0.9644 | False |
| rx10/dp4/ema10 | 10 | 4.0 | 10 | 5.26 | 35.36 | 6.01 | 0.31 | 0.9583 | False |
| rx12/dp2/emanone | 12 | 2.0 | none | 7.1 | 37.14 | -1.81 | -0.1 | 0.9816 | False |
| rx12/dp2/ema3 | 12 | 2.0 | 3 | 5.5 | 36.56 | 5.61 | 0.29 | 0.9748 | False |
| rx12/dp2/ema5 | 12 | 2.0 | 5 | 5.39 | 41.54 | 10.15 | 0.53 | 0.9701 | False |
| rx12/dp2/ema10 | 12 | 2.0 | 10 | 4.47 | 47.33 | 20.79 | 1.1 | 0.9547 | False |
| rx12/dp3/emanone | 12 | 3.0 | none | 7.1 | 37.14 | -1.81 | -0.1 | 0.9816 | False |
| rx12/dp3/ema3 | 12 | 3.0 | 3 | 5.56 | 35.33 | 4.4 | 0.23 | 0.9762 | False |
| rx12/dp3/ema5 | 12 | 3.0 | 5 | 5.43 | 39.14 | 8.16 | 0.43 | 0.972 | False |
| rx12/dp3/ema10 | 12 | 3.0 | 10 | 4.5 | 45.34 | 19.05 | 1.01 | 0.9563 | False |
| rx12/dp4/emanone | 12 | 4.0 | none | 7.1 | 37.14 | -1.81 | -0.1 | 0.9816 | False |
| rx12/dp4/ema3 | 12 | 4.0 | 3 | 5.56 | 35.33 | 4.4 | 0.23 | 0.9762 | False |
| rx12/dp4/ema5 | 12 | 4.0 | 5 | 5.43 | 39.14 | 8.16 | 0.43 | 0.972 | False |
| rx12/dp4/ema10 | 12 | 4.0 | 10 | 4.5 | 45.34 | 19.05 | 1.01 | 0.9563 | False |


## Verdict

**No cell passes all 3 criteria.** Nearest misses (by normalized violation distance):

| cell | turnover_pct_day | net_gross_gap_pp | corr_vs_reference |
| --- | --- | --- | --- |
| rx12/dp3/ema10 | 4.5 | 26.29 | 0.9563 |
| rx12/dp4/ema10 | 4.5 | 26.29 | 0.9563 |
| rx12/dp2/ema10 | 4.47 | 26.54 | 0.9547 |

**G1: no production default change is recommended from this sweep** — the target as specified isn't reachable within this grid; a human should decide whether to widen the grid, relax the acceptance bar, or pursue a different lever (e.g. sector/name budget caps) instead.


**FYI, not a G1 recommendation:** the single best net_ann cell in the whole grid is **rx12/dp2/ema10** at +20.8% net_ann (turnover 4.47%/day, net Sharpe +1.10) — it fails the strict WS1.1 turnover/gap bar, but is a large improvement over today's production config's +2.0% net_ann / 0.11 Sharpe. EMA-smoothing the ranking score (halflife=10 trading days) shows up repeatedly among the best cells — worth a closer look even outside this specific acceptance bar.
