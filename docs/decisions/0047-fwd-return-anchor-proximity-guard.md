# ADR 0047 — Anchor-proximity guard on backtest forward returns

Status: accepted 2026-07-05 · Evidence: [rebaseline-2026-07-05.md](../reference/rebaseline-2026-07-05.md) · Commits `528df71`/`2be758b`

## Context
`pit_fwd_return_20d` (`tools/reconstruct_pit.py`) located each sid's entry/exit price by
`searchsorted` on the price series. For sids with **no price near the eval date** (the 2020–22
jugaad backfill covers only ~70% of the universe), it silently grabbed the **first available
later row** — sometimes years off — pairing old fundamentals with a wrong-period return. ~40–50%
of pre-2023 response pairs were fabricated this way (NULL-rate at old anchors was 0.5%, should
have been ~50%). Surfaced by the LARGE-tier trio: `asset_growth_yoy` MID +2.18 collapsed to
−0.90 on a timely-anchor slice.

## Decision
A sid's `fwd_return_20d` at an eval date is valid **only if** (a) its entry row is within ~5
trading days (7 calendar days) of the eval date, **and** (b) its exit row is within ~5 trading
days of the target exit date (eval + 20 trading days on the market calendar). Otherwise emit
**NULL** — never substitute a distant price, never NaN-pad. The exit-side guard catches the
symmetric gap-spanning bug. Only `fwd_return_20d` exists (no 63/126/252d twins in this panel).

## Consequences
- Pre-2023 NULL-rate now 0.5%→~50% (honest missing-data). Full `pit_ic_by_tier_v2` re-baseline
  ran and **persisted** (verified vs pre-snapshot CSV). `daily_snapshots_pit_v1` (v1_archive)
  untouched — its C13b headline t-stats are preserved.
- Materially changed conclusions: `pledge_quality` SMALL 5.90→1.76 (**left BY-FDR** — its robust
  status was a contamination artifact); `delivery_anomaly_z` SMALL 4.76→**7.78** (contamination
  had *masked* it — now the sole wired multiple-testing survivor); `consensus` LARGE 2.82→1.62,
  `governance_resignation` MID −3.82→−1.55, `promoter_qoq` SMALL 2.62→0.47 all deflated.
- **`SIGNAL_WEIGHTS` unchanged.** No factor hit the un-wire trigger (sign-flip + significance
  loss): the deflated ones kept their sign and `factor_decay` shows healthy recent IC — i.e.
  the *deep-history backtest* was inflated, not necessarily the *live edge*. These are
  promotion-review items, decided deliberately, not automated trips.
- General rule now: any PIT response column must assert anchor proximity, not just "a later row
  exists." Related [[ADR 0043]] (multiple-testing), the survivorship caveat (audit Data-F1).
