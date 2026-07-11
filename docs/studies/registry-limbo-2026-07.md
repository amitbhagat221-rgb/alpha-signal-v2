# Registry limbo classification report (plan 0012 A2)

Read-only evidence report. `tools/verify_factor_library` (built 2026-07-05, audit fastest-win
#8) partitions every `db.BACKTEST_SIGNALS` id into exactly one of `{wired, FACTOR_LIBRARY,
FACTOR_STATUS}`. This report lists everything it currently finds outside all three buckets
("limbo") plus the evidence a human needs to disposition each one. **No config changes made.**

## Tool output (2026-07-11)

```
verify_factor_library: 103 registered signals

✗ 2 signal(s) in NONE of the three buckets (invisible to promotion review):
    mom_12m_adj
    mom_6m_adj
```

**Note on the plan's stated context:** plan 0012 was written 2026-07-06 citing "38 signals
registered but neither wired nor in FACTOR_LIBRARY" from the 2026-07-04 audit. As of this run
(2026-07-11) the count is **2, not 38** — the 2026-07-05 honest weight re-derivation (ADR 0049)
and the subsequent registry re-baseline appear to have resolved the bulk of that backlog by
moving signals into `FACTOR_LIBRARY`/`FACTOR_STATUS` as part of that session's work. The 2
remaining are a *fresh* gap: ADR 0049 dropped `momentum` (→ `mom_6m_adj`) from `SIGNAL_WEIGHTS`
as noise, which un-wires it (and its `mom_12m_adj` SMALL-tier variant) without anyone re-adding
either id to `FACTOR_LIBRARY` or `FACTOR_STATUS` — exactly the invisible-drop pattern this tool
exists to catch.

## Evidence table

| signal | best tier (by \|t\|) | t | n | verdict (clean panel) | recommended bucket |
| --- | --- | --- | --- | --- | --- |
| mom_12m_adj | SMALL | 1.40 | 33 | DROP (all tiers: SMALL 1.40, MID 0.86, LARGE -0.71) | FACTOR_LIBRARY |
| mom_6m_adj | SMALL | 1.34 | 38 | DROP (all tiers: SMALL 1.34, MID 0.04, LARGE -0.85) | FACTOR_LIBRARY |

Bucket rule applied (DECIDED, plan 0012 A2): `|t|>=1.5 & n>=20` → "promotion-review candidate";
has any clean-panel backtest → "FACTOR_LIBRARY"; never backtested → "backtest or retire". Both
signals have clean `pit_ic_by_tier_v2` rows (`source LIKE 'v2_recompute%'`) at every tier, all
DROP, all `|t| < 1.5` — neither clears the promotion bar, so both fall to "FACTOR_LIBRARY".

## Recommendation (human decision, not actioned here)

Add `mom_12m_adj` and `mom_6m_adj` to `db.FACTOR_LIBRARY` (or an equivalent `FACTOR_STATUS`
entry) to close the partition gap `verify_factor_library` flags. The clean-panel evidence
agrees with the 2026-07-05 decision to drop momentum from `SIGNAL_WEIGHTS` — nothing here
argues for re-wiring it.
