# LARGE re-audit, 2026-10-10: still no new LARGE factor

Verdict: none of about 100 registered factors, and none of three new consensus-surprise factors, qualifies for a LARGE weight. Every factor that clears |t| 1.5 on LARGE either breaks a promotion rule or has a recent t ≤ 0. Separate finding: the consensus beat rate is a promotion candidate in **MID**.

Script: `tools/large_reaudit.py` (read-only). 83 monthly anchors, 2019-12 → 2026-10, 20-day rank IC on the corrected panel (point-in-time tier, entry next session, adjusted label). Halves split at 2023-01-01; "recent" means since 2024-09 (25 anchors), the same window as the promotion review.

## A. Every registered factor on LARGE (|t| ≥ 1.5, ≥ 20 anchors)

| factor | t | recent t | halves | why it can't be wired |
|---|---|---|---|---|
| announcement_car | 2.75 | −0.14 | agree | wired; nothing since 2024-09 |
| forward_looking_intensity | 2.42 | 0.29 | agree | wired; weak recently |
| asset_growth_yoy | −2.37 | −0.83 | agree | wired; right sign but fading |
| gross_profitability | −2.30 | −0.86 | agree | sign opposite the prior |
| oil_beta | 2.17 | 0.83 | agree | an exposure, not a selection signal |
| interest_coverage | −2.05 | −1.21 | agree | sign opposite the prior |
| metals_beta | 1.97 | 1.83 | agree | an exposure, not a selection signal |
| cons_surprise (new) | 1.87 | −1.47 | agree, second half ≈ 0 | gone since 2023 (IC 0.047 → 0.008) |
| debt_structure | 1.76 | 1.24 | agree | the only clean one: weak, no clear prior, 0.38 correlated with forward_looking_intensity |
| max_pain_distance | −1.73 | −1.77 | 26 anchors, one half | options family (iv_skew wired); too short |
| roic | −1.62 | −0.72 | agree | sign opposite the prior |
| z_score | −1.51 | −0.95 | agree | sign opposite the prior |

The full-sample bar is a weak test on LARGE: the wired LARGE set is about zero since 2024-09, and so is everything that clears it.

## B. Consensus EPS surprise (Yahoo `analyst_estimates`, source `yahoo_calendar`, 2002 →)

Pre-registered 3 factors × 3 tiers (≈ 299 hypotheses now; the Bonferroni bar stays ≈ 4.2). Report date strictly before the anchor. Estimates are labelled `pit_unverified`: whether Yahoo back-revised them is not checked.

| factor | LARGE t (recent) | MID t (recent) | SMALL t (recent) |
|---|---|---|---|
| cons_surprise: latest report ≤ 90 d, (actual − est)/\|est\| | 1.87 (−1.47) | 2.52 (−0.71) | 5.22 (1.77) |
| cons_beat: sign of that surprise | 1.33 (−1.85) | 3.21 (0.51) | 5.25 (2.59) |
| cons_beat_rate_4q: share of beats, last 4 reports | 0.89 (−0.96) | **4.00 (2.98)** | 4.94 (2.49) |

After removing the tier's wired factors (rank OLS per anchor):
- MID `cons_beat_rate_4q`: t 2.39, recent 1.93. Halves agree (0.023 / 0.055), coverage 77%. It is most correlated with `residual_momentum_12_1` (0.25) and `consensus` (0.22). **Candidate for the next MID review.**
- SMALL: t 2.98 / 3.18 after the wired factors, but coverage is only 23% of the tier (analyst-covered names).
- `cons_surprise` overlaps `announcement_car` (0.25 MID, 0.36 SMALL); after the wired factors MID drops to 1.48.

## What would change the LARGE verdict
Nothing in the data we hold. The open routes are: our own revision history (`yahoo_trend`, weekly since 2026-09-28; testable around 2027-09); a check that Yahoo's past estimates were not back-revised; or accepting an equal-weight, low-conviction LARGE model.
