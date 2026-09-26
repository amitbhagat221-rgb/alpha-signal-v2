# ADR 0045 — Pull pt_upside (look-ahead artifact) + smart_money (sub-bar) from SIGNAL_WEIGHTS

**Status:** accepted · 2026-07-05
**Context:** [docs/audit-2026-07-04-report.md](../audit-2026-07-04-report.md) Factor-F1 (CRITICAL) + Factor-F3; [docs/_archive/plans/0010-audit-remediation.md](../_archive/plans/0010-audit-remediation.md) Phase 3.

## What was found

`pt_upside`'s t=7.15/8.40/9.14 (LARGE/MID/SMALL) — the whole model's strongest factor, wired at
0.25/0.24/0.15 — was built almost entirely from `forecast_history` (metric='price') rows dated
before 2026-05. Those rows are Tickertape's "year-end forecast" snapshots, but the underlying value
is the stock's REALIZED CLOSE roughly a year *after* the stamped date, not an analyst price target.
Every historical `pt_upside` PIT value inherited this: the "PIT-safe" `date <= eval_date` filter
passed because the row's date was honest, but the row's *value* was drawn from the future. This is
a worse form of the already-documented 2026-05-22 HALC bug (daily lastPrice masquerading as PT) —
that fix addressed the daily feed; the annual archive itself was still contaminated.

`smart_money`'s best-ever backtest (SMALL t=1.06, n=6) never cleared the documented `|t|≥1.5`
promotion bar (audit Factor-F3) and should not have carried production weight either.

## Decision

- `tools/reconstruct_pit.py::pit_pt_upside` now reads `analyst_consensus_snapshots` ONLY (real
  monthly PT data since 2026-05); NULL when no snapshot precedes the eval date, no fallback.
- Purged `daily_snapshots_pit.pt_upside` for `snapshot_date < '2026-05-01'`; rebuilt 2026-05+ from
  the clean source. Re-backtest: n=1 period, INSUFFICIENT in all three tiers.
- Pulled `pt_upside` and `smart_money` from `SIGNAL_WEIGHTS`; remaining weights in each tier
  renormalized proportionally (Σ|w|=1.0, signs preserved) — see `docs/reference/signal-weights.md`.
- `SIGNAL_WEIGHTS_RETURN`/`_SHARPE` (non-production `--variant` diagnostics): `pt_upside` → 0, left
  un-renormalized (dry-run only, no live effect).

## Re-entry condition

≥12 clean monthly `analyst_consensus_snapshots`-only anchors AND |t|≥1.5 in a tier → revisit.
Calendar: ~2027-05 (12 months from the first clean anchor, 2026-05-01).
