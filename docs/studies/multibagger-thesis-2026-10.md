# Multibagger thesis test (plan 0026 phase 1, 2026-10-15)

Tool: [`tools/mb_thesis.py`](../../tools/mb_thesis.py) (read-only; rules written in its docstring before the first run, three code-only bug fixes noted there). Outputs: `data/lh/v2/mb_thesis_*`.

## Background
- **Lift** = the top-30's hit rate ÷ the pond's hit rate (1.0 = no better than picking at random from the pond).
- **Pond** = the stocks that pass the safety gates, i.e. the set the score ranks.
- **Arm A** = price signals only (smallness, 6-month momentum, 52-week position) on the whole NSE market, delisted stocks included, from Oct 2011.
- **Arm B** = the full thesis (adds cheapness, latest-quarter results, industry momentum), on today's listed stocks only, from Oct 2015.
- **Grade** = [ADR 0073](../decisions/0073-good-enough-book-deployment.md): B needs t ≥ 1.5, beating the Smallcap 250 in ≥ 3 of the last 5 calendar years and from ≥ 10 of 12 start months, and a worst 12-month excess ≥ −15 %.

## Result
**Pre-registered bar: fails.** T1 passes 4 of 8 anchors (bar 70 %). The book is grade C, and it fails only the worst-12-month test.

**T2 books** (12 staggered start months, annual rebalance, after 31 bps cost and 12.5 % tax on gains, vs the NIFTY SMALLCAP 250):

| book | median CAGR | excess / yr | t | starts beaten | last 5 years | worst 12 months | grade |
|---|---|---|---|---|---|---|---|
| Thesis (arm B), top 30 | 27.1 % | +14.1 % | 2.01 | 12 / 12 | 4 / 5 | −32.8 % | C |
| Thesis (arm B), top 10 | 27.1 % | +14.1 % | 2.02 | 12 / 12 | 4 / 5 | −34.9 % | C |
| Price only (arm A), top 30 | 25.7 % | +11.7 % | 2.22 | 12 / 12 | 5 / 5 | −36.9 % | C |
| Price only (arm A), top 10 | 30.2 % | +16.2 % | 1.60 | 11 / 12 | 5 / 5 | −51.2 % | C |

- The top-10 and top-30 medians match by coincidence: the per-start figures differ (`mb_thesis_book_B_*.csv`). The top-10 spread across starts is wider (+4 % to +31 %/yr).
- **Bad years:** 2019 (−14.5 %, the small-cap bear) and 2025 (−11.6 %). The worst windows run 12–33 % behind the index.
- **Arm A includes delisted stocks**, so its +11.7 %/yr is not a survivorship artefact. **Arm B is survivors only**: take off ~2.8 %/yr (ADR 0073's SMALL survivorship estimate).

**T1 tail capture** (top 30 vs the pond, October anchors):

| | 3x in 3 years, lift | 5x in 5 years, lift | halved in 3 years, lift |
|---|---|---|---|
| Thesis (arm B) | 1.24 | 1.25 | **0.28** |
| Price only, survivors | 0.90 | 0.97 | 0.59 |
| Price only, full market (arm A) | 1.27 | 1.02 | 0.71 |

- **What the thesis does best is avoid disasters.** The top 30's 3-year halving rate is at or below the pond's at every anchor, and 0 % at 5 of 8. The median 3-year multiple is higher at 6 of 8 anchors (e.g. 2021: 3.5x vs 2.1x).
- **It catches multibaggers only modestly better than chance:** about 1.25x. The anchors that pass are 2016 (5y), 2018, 2021 and 2022.
- **It loses in a broad small-cap boom:** 2020 (lift 0.8), when everything ran.

**T3, the old funnel's gates** (ROCE ≥ 18 %, D/E ≤ 0.5, ₹1–20k Cr, 3-year profit CAGR ≥ 20 %): lift 0.27–1.23 on 3x and 0.21–0.80 on 5x. 0–17 names passed before 2020. **Worse than picking at random from the pond.**

## What it means
- **Ship it as a labelled "where to look" list (Amit D1).** Label: *grade C — beat the Smallcap 250 from 12 of 12 start months (+14 %/yr in the backtest, survivors only), but fell up to 33 % behind it in a bad year; a shortlist for judgement, not a mechanical buy list.*
- **Size from the worst case, not the average.** Expect a year 30 % behind the index. ADR 0040's no-stop holding rule applies.
- **Holding 30 beats choosing 10 mechanically:** the medians are similar, but the 10-name book's start-to-start spread and worst year are larger. That is evidence for D3 (still open).
- **Replace the funnel's quality gates.** Keep the halving-avoidance (the forensic and safety gates plus cheapness).

## Limits
- Arm B fundamentals cover today's universe only, and start 2015 (Screener annuals). The business part exists only from 2019 (NSE XBRL quarterly results).
- The safety gates are partly historical: auditor resignations and CIRP from 2019 only; pledge, SEBI orders and GSM are not applied.
- 8 October anchors, so 2–3 independent 3-year windows. One small-cap bull dominates (2020–24).
- The cost model is a flat 31 bps one-way; in the smallest names, impact costs could be higher.

## Phase 1b: everything v1 left out (2026-10-15)
Tool: [`tools/mb_thesis_v2.py`](../../tools/mb_thesis_v2.py) (rules written before the run; outputs `data/lh/v2/mb2_*`). Every book uses realistic costs by liquidity (`tools.lh_costs`, ₹30 lakh book).

**Verdict: v2 = v1.**
- No addition, removal or book rule passed the pre-registered rules. The one that passed (the sector policy score) was disqualified afterwards: its input is a hand-curated list written with hindsight.
- **v1 under realistic costs:**
  - excess +12.7 %/yr over the Smallcap 250, t 1.90, 12 / 12 starts, 4 of the last 5 years beaten;
  - worst 12 months −33.4 %;
  - DSR 0.961 over the 21 full-window variants; PBO 0.29;
  - T1 3x lift 1.24, halving lift 0.28.
- **Grade C**, failing only the worst-12-month bar; everything else meets grade B.

| test | result vs v1 | why rejected / what it shows |
|---|---|---|
| Drop any one part | excess −0.5 to −2.2 pts, and T1 or halving worse | **every part earns its place**; dropping the business part raised excess but doubled halving at T1 and lost the first half |
| One part alone | +4.7 to +8.4 %/yr | no single part is enough; the mix is the edge |
| Superinvestor entry, as a part | −1.4 pts | on its own, entries do 3x more often (25.4 % vs 20.2 %, 158 stocks) but halve as often; better as a watch card than a score |
| Announcement reaction / delivery anomaly / accruals / retail-holder growth / quarterly margin change (2020+) | −0.5 to −2.4 pts | none adds; accruals trims the worst year to −26.5 % but costs return |
| Sector policy score (2020+) | +3.7 pts, worst −23 % | **disqualified**: `policy_events` is 28 events curated in 2026 with hindsight magnitudes, some are outcomes ("record order book"), none since 2025-04 |
| 5 new-listing slots (2020+) | −0.7 pts | no help inside this book |
| No rebalance in a bear market | −2.0 pts in 2016–20 | no help |
| Hold the index in a bear market | worst −23 % but −6.9 pts in 2016–20 | whipsawed in 2016–18; the drawdown fix costs too much |
| Hold 24 months | −3.7 pts | **refreshing yearly beats holding longer** |
| Top-90 band (keep while in the top 90) | ≈ same | no gain |
| ADR 0040 conviction exits (hold until REVIEW) | −5.8 pts | **the "hold with conviction" rule does worse than a yearly refresh for this book** |
| Liquidity floor ₹1 Cr / ₹2 Cr | +5.2 % / +0.7 %/yr | **the edge lives in stocks trading ₹0.5–1 Cr a day**: capacity is small, and execution must be patient |
| Top 10 instead of 30 | ≈ same median, worst −36 % | 30 is safer for the same return |
| Overlap with the SMALL paper books | 2–10 % of names | a different book, so it diversifies the sleeve |

**What changes in plan 0026:**
1. The book refreshes yearly. The conviction verdict is shown as a monitor, not as the exit rule (amends ADR 0075's "keeps ADR 0040's holding rules").
2. Superinvestor entry becomes a context card on the watch page, not a score part.
3. Size and execution: ₹1 lakh per name is what was tested. Do not scale the book without re-testing costs; use limit orders over several days in names under ₹1 Cr a day.
4. A sector-policy input needs a point-in-time source (dated government announcements captured as they happen) before it can be tested again.
