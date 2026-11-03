# Three models under a better bar (2026-11-03)

Amit: "have 3 models at max slow fast and blend and use a better bar, do backtesting and select the three models."
Tool and pre-registration: `tools/model_select.py` (committed e886d2e before any result). Raw output: `data/lh/model_select/results.json`.

## Answer

| Model | Bar chosen | Mid over index /yr (t) | Small over index /yr (t) | Grade |
|---|---|---|---|---|
| Slow | long-side (\|t\| ≥ 2.5, 24 months, best fifth beats the tier) | +1.5 % (0.48) | +6.8 % (1.24) | C, C |
| Fast | multiple-testing (BY 5 %) | −18.9 % (−2.44), mostly cash | +8.2 % (1.79) | C, C |
| Blend | mean of the two, top 20, sell below 50, 6-month hold | +2.6 % (0.56) | +0.3 % (0.18) | C, C |

20-name books, 2022-06 to 2026-06, after measured costs and Indian tax, over the tier index. No model reaches grade B (ADR 0073). Small Fast comes closest: it passes every B test except the luck test (DSR 0.70, PBO 0.69).

## Every bar

Decision rule: one bar per model, both tiers, highest mean t; within 0.25 the stricter wins. Slow: long is within 0.25 of old, so long wins. Fast: fdr has the highest mean.

| Model | Bar | Mid /yr | Mid t | Small /yr | Small t | Mean t |
|---|---|---|---|---|---|---|
| Slow | old (control) | +1.7 % | 0.60 | +8.7 % | 1.41 | 1.00 |
| Slow | fdr | +0.4 % | 0.13 | +8.4 % | 1.11 | 0.62 |
| Slow | **long** | +1.5 % | 0.48 | +6.8 % | 1.24 | 0.86 |
| Slow | full | +2.0 % | 0.59 | +1.8 % | 0.44 | 0.51 |
| Fast | old (control) | −5.9 % | −1.59 | +1.0 % | 0.19 | −0.70 |
| Fast | **fdr** | −18.9 % | −2.44 | +8.2 % | 1.79 | −0.33 |
| Fast | long | −8.2 % | −2.18 | −2.0 % | −0.35 | −1.27 |
| Fast | full | −19.2 % | −2.47 | +5.3 % | 0.83 | −0.82 |

Controls, never selectable:

| Control | Mid /yr | Mid t | Small /yr | Small t | Note |
|---|---|---|---|---|---|
| Slow v2 | +4.6 % | 1.00 | +2.8 % | 0.66 | Chosen with these years in view |
| Slow IC-weighted | +3.7 % | 0.78 | +17.2 % | 2.18 | No bar; Small start months run +2.6 % to +26.1 % |
| The old blend | −1.6 % | −0.41 | +9.5 % | 1.43 | Old 12-month slow rule |
| Fast v1 (live weights) | +15.1 % | 3.86 | +8.5 % | 1.87 | Chosen with these years in view; Mid grade B is hindsight |

## What it means

1. **The better bar did nothing for Slow.** Long-side minus today's bar: Mid 0.0 pp/yr, Small −1.0 pp/yr (t −0.18). It won on the tie-break, not on evidence.
2. **The better bar helped Fast in Small only.** Multiple-testing minus today's bar: Small +6.1 pp/yr (t 1.55). Whether that is real is not settled by this sample.
3. **Mid has no fast model.** Every walk-forward fast bar loses to the index in Mid. Under the chosen bar no factor qualifies before May 2026. Since then the book runs on `cons_beat_rate_4q` alone, whose estimates are `pit_unverified`, and 14 to 17 names tie at the top score, so the choice among them is arbitrary. The live weights' +15.1 %/yr in Mid exists only with hindsight.
4. **The strongest slow result had no bar at all.** Slow IC-weighted in Small beat the chosen Slow by +8.5 pp/yr (t 1.57). It averages about 30 factors. That points to averaging many weak factors over selecting few, but it was pre-registered as a control and its start-month range is wide. Adopting it is a separate decision and needs its own forward test.
5. **Blend's score ranks well but its book does not.** Whole-tier rank IC in Small is 0.058 (t 7.0), above either parent, while the book earns +0.3 %/yr. The fixed midpoint rule was not searched, by design. The likely gap is between ranking the tier and owning 20 names on this holding rule; this test does not prove the cause.

## Hold-out

June to October 2026 took no part in the decision. Over the index after tax: Mid Slow +4.1 %, Mid Fast +11.9 %, Mid Blend +9.6 %, Small Slow +7.9 %, Small Fast +6.5 %, Small Blend +4.1 %. Four months, positive throughout, and not evidence on its own. The first hold-out run showed Small Slow at +15.7 %: its first basket lacked the 3-month average. Fixed before the page was built; the decision never used it.

## Corrections

- The earlier page quoted Small slow select at +19.7 %/yr (t 2.08). That is not a 20-name result, and its source was not traced. Plan 0024's 20-name book made +10.1 % (t 1.71). This test makes +8.7 % (t 1.41), with the ₹1 crore floor, trusts excluded and no forensic sale.
- The test's fast `old` bar reproduces `fast_select` in 102 of 106 tier-months and its slow `old` bar reproduces `slow_select` in 106 of 106.

## Limits

Today's listed universe (survivorship about 2.8 %/yr in SMALL). Mid's benchmark before 2023-06 is the tier equal-weight average. Staggered starts begin with no earlier scores, so the slow book's first basket in each uses fewer than three months, as in `tools/lh_timing_luck.py`. DSR and PBO run over the 13 series in each tier, a mix of model types, which is harsher than a same-model grid. LARGE was not tested: earlier work found no out-of-sample skill.
