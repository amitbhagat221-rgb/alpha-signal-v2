# Registry re-baseline — fwd_return anchor-proximity guard (2026-07-05)

**What broke.** `tools/reconstruct_pit.py::pit_fwd_return_20d` anchored a sid that
had NO price rows near an old eval date at its FIRST LATER price row (`searchsorted`),
pairing old fundamentals with a wrong-period return. ~40% of response pairs at pre-2023
anchors were late-anchored (the 2020-22 jugaad price backfill covers only ~70% of the
2,448 sids). Every fundamentals-based factor's pre-2023 IC in the `v2_recompute` panel was
contaminated. Price-based factors were immune (their signal already needs a price at the
anchor). Discovered during the 2026-07-05 LARGE-tier build (asset_growth_yoy MID
+2.18→−0.92 on a timely-anchor slice).

**Guard as implemented.** A sid's `fwd_return_20d` at eval_date is valid ONLY IF:
(a) its ENTRY row (first row on/after eval_date) is within **7 calendar days** (≈5 trading
days) of eval_date, AND (b) its EXIT row (entry+20 rows) is within 7 calendar days of the
**target exit date** = 20 trading days after eval_date on the market calendar (union of all
sids' dates). Else NULL. The exit-side guard catches the symmetric case: a sid with a data
gap between entry and exit whose "+20 rows" spans far more than 20 real trading days.
Verified at 2021-06-01: 1234 sids NULL'd by the entry guard, 30 by the exit guard, 1183
survive — and the survivors track the true "sids with a price within 7d" count almost
exactly (1183 kept vs 1213 with-price), confirming no over-rejection.

**Scope.** Only `daily_snapshots_pit` (the deep 2020-2026 `v2_recompute` panel, 182 anchors)
was rebuilt. `daily_snapshots_pit_v1` (the `v1_archive` source, 2023-04→2026-02, 0 NULLs)
was untouched and its t-stats are unchanged — so the v1 C13b header table in
`signal-weights.md` is fully preserved. The re-baseline is isolated to `v2_recompute` rows.

## NULL-rate for `fwd_return_20d`, before → after (per anchor-year)

| Year | rows | NULL% before | NULL% after |
|------|------|--------------|-------------|
| 2020 | 29,376 | 0.1% | **55.1%** |
| 2021 | 29,376 | 0.6% | **51.4%** |
| 2022 | 29,376 | 0.7% | **47.7%** |
| 2023 | 29,376 | 0.6% | **47.0%** |
| 2024 | 102,816 | 10.3% | **43.1%** |
| 2025 | 156,672 | 6.8% | **29.0%** |
| 2026 | 68,544 | 20.1% | 17.5% |

The pre-fix near-zero NULL rate is the smoking gun: `searchsorted` was fabricating a return
for every uncovered sid. Post-fix NULLs = sids genuinely without a nearby quote (illiquid /
newly-listed / suspended). Non-null pairs: ~284.8k. 2026 falls (some pre-fix "returns"
inside the not-yet-elapsed 20d window were spurious).

## Wired-factor diff (`v2_recompute` source — the fixed panel)

Non-moving `v1_archive` headline t's shown in [brackets] for context (unchanged).

| Factor (weight) | Tier | n old→new | t old → new | Δt | Note |
|---|---|---|---|---|---|
| **pledge_quality** (S 0.11) | SMALL | 31→19 | **+5.90 → +1.76** | −4.14 | ⚑ crosses 2.5 **and** 1.5; leaves BY-FDR. Sign +, no flip |
| **governance_resignation** (M −0.11) | MID | 46→48 | **−3.82 → −1.55** | +2.27 | ⚑ crosses 2.5→barely WEAK. Sign − preserved |
| promoter_qoq (S 0.19) | SMALL | 26→16 | +2.62 → +0.47 | −2.15 | crosses 2.5&1.5 in v2 [v1 **3.20** unchanged] |
| consensus (L 0.47 / S) | LARGE | 32→38 | +2.82 → +1.62 | −1.20 | crosses 2.5 in v2 [v1 **3.52**]; SMALL +3.00→**+3.74** ↑ |
| piotroski (S 0.10 / M 0.14) | SMALL | 21→21 | +2.51 → +1.53 | −0.98 | crosses 2.5 [v1 **2.81**]; MID +1.36→**+2.25** ↑ (crosses 1.5) |
| earnings_yield (S 0.14) | SMALL | 18→21 | +2.36 → +1.92 | −0.44 | still WEAK [v1 **3.13**] |
| cf_accruals (M 0.27 / S) | MID | 18→21 | −2.53 → −2.65 | −0.12 | stable KEEP [v1 −3.20]; SMALL +0.07→−0.99 (sign→correct) |
| book_to_price (L/M/S) | MID | 40→46 | +2.04 → +2.37 | +0.33 | ↑ [v1 2.33]; SMALL +1.58→+1.88 ↑ |
| iv_skew_25d (M 0.17) | MID | 48→52 | +3.16 → +2.87 | −0.29 | stable KEEP |
| **delivery_anomaly_z** (S 0.12) | SMALL | 103→107 | **+4.76 → +7.78** | +3.02 | ↑↑ strengthens; contamination removed |
| sector_tilt (S 0.12) | SMALL | 34→41 | +3.18 → +3.69 | +0.51 | ↑ strengthens |
| momentum (S 0.02) | SMALL | 32→38 | +1.59 → +1.34 | −0.25 | unchanged verdict |

## BY-FDR survivor-set change (M=277, dedup one test/(signal,tier), non-v1 preferred)

| | Survivors |
|---|---|
| **BEFORE** | pledge_quality SMALL (5.90) · delivery_anomaly_z SMALL (4.76) · avg_delivery_pct_30d SMALL (4.37) |
| **AFTER** | delivery_anomaly_z SMALL (**7.78**) · avg_delivery_pct_30d SMALL (**5.41**) |

**pledge_quality SMALL dropped out of BY-FDR entirely** (p_BY 0.003 → 1.000). The delivery
family strengthened (the removal of contaminated NULL pairs cleaned its IC). BH-FDR lost the
same pre-2023-inflated fundamentals — governance_resignation MID, gross_profitability,
interest_coverage MID, eps_growth, corporate_action_density, value_composite all fell out;
post-fix BH set = {delivery, avg_delivery, kyle_lambda LARGE, sector_tilt SMALL (new, 3.69),
consensus SMALL (new, 3.74)}.

## Robust core — does it stand?

- **delivery_anomaly_z SMALL: YES, stronger than ever** (t 4.76→7.78, sole *wired* BY-FDR survivor).
- **pledge_quality SMALL: NO — no longer multiple-testing-robust** (t 5.90→1.76, out of BY *and* BH).
  Half the honest robust core was riding contaminated pre-2023 anchors.

## ⚑ LOUD FLAGS (SIGNAL_WEIGHTS **unchanged** — promotion calls, not mine)

1. **pledge_quality SMALL (wired 0.11)** — its "bulletproof" BY-FDR status was a pre-2023
   contamination artifact. Honest t=1.76 on n=19 (fails even naive |t|≥2.5). **Not "clearly
   invalid":** sign stays POSITIVE (no flip) and `factor_decay` shows the recent-12-anchor IC
   healthy (+0.0151 vs +0.0139 all-time) — the *live* edge holds; only the deep-history
   backtest was inflated. Recommend the promotion review revisit its weight / robust-core
   billing. **No weight change made.**
2. **governance_resignation MID (wired −0.11)** — the KEEP that justified wiring (t=−3.82) is
   now −1.55. Sign stays NEGATIVE (correct direction); `factor_decay` recent IC −0.0269 matches
   the wired sign. Weakened, not invalid. Promotion-review item. **No weight change made.**

No wired factor shows the sign-flip + significance-loss pattern that would mandate an
un-wire, so nothing in `config.SIGNAL_WEIGHTS` was touched.

## Non-wired confirmation

- **asset_growth_yoy** (the trigger): MID **+2.18 → −0.90** (LARGE +1.21→−0.88, SMALL
  −0.30→−0.64) — the artifact is gone; all three tiers now show the expected CMA NEGATIVE
  sign, insignificant. Stays in `FACTOR_LIBRARY`, correctly unwired. Matches the −0.92
  timely-anchor prediction.
- `factor_decay`: 5 of 22 wired (key,tier) pairs flagged DECAYED (accruals L/M/S,
  book_to_price SMALL, promoter SMALL) — magnitude/sign drift on the recent window, separate
  from this fix; watch-list, no action.
