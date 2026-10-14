# Asymmetric sleeves: theme momentum (7.1) and a mania screen (7.3) — 2026-10-13

Plan 0025 phase 7, after the [doubler study](doubler-study-2026-10.md). Both tests were pre-registered in their tool's docstring and committed before any result (`b2137d2`, `35d6c74`).
- [`tools/theme_momentum.py`](../../tools/theme_momentum.py) (7.1)
- [`tools/mania_screen.py`](../../tools/mania_screen.py) (7.3)

Outputs are in `data/lh/v2/theme_*` and `mania_*`.

**Caveats for both tests:**
- The idea comes from looking at the 2019-25 doublers, so neither test is out of sample for the idea.
- Labels cover today's listed universe only. Survivorship flatters SMALL by about 2.8 %/yr.

## 7.1 Policy-capex theme momentum

**Score:** equal-weight within-tier percentiles of four inputs:
- industry 6-month momentum;
- sector policy score;
- BSE order-win filings in the last 6 months;
- 52-week position.

**Gate (the exit rule):** industry momentum > 0, 52-week position ≥ 0.5, and ₹1 cr liquidity. A stock that fails the gate is sold at the next monthly review.

**Book:** top 20 with `tools.lh_book` (measured costs, Indian tax), from 12 starts 2020-06 … 2021-05.

### Asymmetry bar (top 20 per anchor, 2020-06 … 2025-09)
| tier | P(double) | base | lift | P(halve) | base | median excess | mean excess | bar |
|---|---|---|---|---|---|---|---|---|
| SMALL | 22.9 % | 11.5 % | **1.99×** | 1.6 % | 2.5 % | **+18.7 %** | +38.7 % | **fails by a hair** (needs 2.0×) |
| SMALL 2020-22 | 25.5 % | 16.2 % | 1.58× | 1.6 % | 1.7 % | +15.1 % | | fails |
| SMALL 2023-25 | 20.3 % | 8.9 % | 2.28× | 1.6 % | 2.9 % | +21.3 % | | passes |
| MID | 10.9 % | 8.3 % | 1.31× | 0.4 % | 0.9 % | +8.9 % | | fails |

### Book grade (ADR 0073), primary variant (top 20, sell below 40, monthly)
| | SMALL | MID |
|---|---|---|
| excess CAGR vs index, after costs + tax (first start) | **+25.5 %** | +7.1 % |
| t (Newey-West) / after the 6-variant haircut | 2.82 / 2.13 | 1.21 / 0 |
| DSR / PBO | 0.997 / 0.94* | 0.84 / 0.66 |
| starts beating the index | **12/12** (worst start +22.5 %) | 12/12 (worst +7.1 %) |
| calendar years beating (2021-25) | 4/5 (2021 −3.6 %, 2024 +55 %) | 4/5 |
| worst 12-month excess | −9.9 % | −12.6 % |
| turnover / median hold | 405 %/yr / 2 months (mostly short-term gains) | 256 %/yr / 3 months |
| **grade** | **B** | C |

\* PBO is not informative here. The hold-0 and hold-1 variants are identical, so the grid has about 3 distinct books (N_eff 1.28). Grade B passes on DSR, which ADR 0073 accepts as an alternative.

### Post-hoc ablation (added after the results; decides nothing)
SMALL primary book from 2020-06:

| score | excess | t |
|---|---|---|
| full theme | +25.5 % | 2.82 |
| without order wins | +10.1 % | 1.61 |
| without policy | +17.8 % | 2.26 |
| price only (industry momentum + 52-week position) | +11.0 % | 1.56 |
| full theme, no gate | +26.4 % | 3.85 (turnover 282 %) |

- **Order-win intensity is the engine.** Without it, the book is a generic momentum book (about +10 %, like `fast_select`).
- The gate is not what earns the return. The ungated score did as well, with lower turnover. This is a lead for a new pre-registration, not a finding.

### Verdict
- By the letter of the pre-registration, this is **not** a theme sleeve candidate. That needs grade ≥ B **and** the asymmetry bar, and the bar fails at 1.99× vs 2.0×.
- The rule did not say what grade B without asymmetry means. The tool printed "no theme sleeve" for it.
- The book alone meets ADR 0073 grade B, with the strongest 12-start record of plan 0025.
- **Amit's call:** a paper-only forward test of the theme book beside the SMALL sleeve, or nothing.
- Things to weigh:
  - the idea is in-sample;
  - order filings grew about 5× after 2023 (disclosure rules), so the 2023-25 half carries most of the asymmetry;
  - the gains are mostly short-term.

## 7.3 Mania exclusion screen

Flagged names are compared with the unflagged "hot" names (top fifth of 6-month momentum) at the same anchor. Anchors run 2019-12 … 2025-09, with a ₹1 cr floor.

| SMALL | flagged n | P(halve) flagged / hot | median excess flagged / hot | mean excess flagged / hot | bar |
|---|---|---|---|---|---|
| NARROW (hot + no growth + a marker) | 483 | 3.9 % / 3.6 % (1.10×) | −2.8 % / +3.2 % | +21.7 % / +21.5 % | fails (halve, mean) |
| BROAD (hot + any flag; 35 % of hot names) | 3,611 | 4.3 % / 3.2 % (1.34×) | +2.7 % / +3.0 % | +24.6 % / +19.7 % | fails |
| hot + penny | 734 | 6.1 % / 3.4 % (1.80×) | −1.3 % / +3.2 % | **+34.4 % / +20.5 %** | — |
| hot + forensic flag | 493 | 5.7 % / 3.5 % (1.63×) | −2.9 % / +3.2 % | **+36.9 % / +20.7 %** | — |
| hot + low float (promoter ≥ 74.5 %) | 823 | 1.9 % / 3.7 % (0.52×) | +0.1 % / +3.1 % | +22.7 % / +21.4 % | — |
| hot + preferential / warrants | 613 | 5.1 % / 3.5 % (1.44×) | +5.6 % / +2.7 % | +24.9 % / +21.3 % | — |

- **Verdict: no mania screen.**
  - Penny and forensic-flagged momentum names do halve more often and have lower medians. They are two-sided lotteries: their mean is higher, because the big winners pay for the losers.
  - An avoid list would cut those winners too. BROAD would have removed 20 % of the 7.1 theme picks, and those picks earned a mean of +37.6 % against +26.3 % for the ones kept.
- The forensic flag stays a review prompt, as ADR 0073 already has it.

## 7.4 Order-win intensity as a factor (2026-10-14) — fails
Pre-registered in [`tools/order_wins.py`](../../tools/order_wins.py) (`a9f8d72`). It tests whether the count of BSE order-win filings over the last 6 months predicts the return within the tier.

| order_wins_6m at 126 sessions | SMALL | MID |
|---|---|---|
| mean IC / Newey-West t / non-overlap t | 0.018 / 1.01 / 0.93 | 0.037 / 1.55 / 1.22 |
| IC 2019-22 · 2023-24 · 2025-26 | −0.011 · **+0.062** · +0.022 | +0.008 · **+0.095** · +0.013 |
| beyond momentum + 52-week position (residual t) | **−2.65** | +2.31 |
| industry-neutral t | −1.02 | +1.35 |
| stocks with ≥ 1 filing | 8.8 % | 5.2 % |

- **Bars:** SMALL fails all three. MID fails bar 1 (t 1.55 against 2.5). No variant (3m / 12m / change) clears Bonferroni.
- **Verdict: no factor, so D5 = nothing.** Across the whole tier, order wins add nothing beyond momentum and industry. In SMALL, once momentum is controlled for, they point slightly the wrong way.
- **Why the 7.1 book still looked strong:** its edge sits in the top tail of an interaction (policy sector × hot industry × order filer), and mostly in one regime. The 2023-24 capex boom carries the IC (+0.06 / +0.09) and the book's +55 % year. That is a theme that happened, not a repeatable factor.
- **What would change this:** a second capex cycle that shows the same 2023-24 pattern out of sample. The tools are ready to re-run as is.
