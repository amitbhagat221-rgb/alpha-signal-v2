# ADR 0075 — The multibagger desk ranks a loose pond by an evidence-based thesis, not a quality funnel

**Status:** accepted 2026-10-15 (Amit D1: "ship as 'where to look'" even if the grade is C). **Supersedes** the funnel of [ADR 0039](0039-multibagger-funnel-regime-dominated.md). Takes [ADR 0040](0040-multibagger-holding-not-selection.md)'s no-stop-loss rule but **not** its hold-until-REVIEW exit (phase 1b: a yearly refresh beats it). Plan [0026](../plans/0026-multibagger-desk.md); evidence in [multibagger-thesis-2026-10.md](../studies/multibagger-thesis-2026-10.md).

## Decision
- **Pond:** safety gates only.
  - Market cap ≤ ₹5,000 Cr and ADTV ≥ ₹0.5 Cr.
  - Revenue > 0.
  - No statutory-auditor resignation or CIRP filing in the last 12 months.
  - Pledge ≤ 50 %, not GSM.
  - No ROCE, D/E, profit-growth or promoter hurdle. Forensic flags are shown, not cut.
- **Thesis score:** equal-weight within-pond percentiles of smallness, cheapness (book / sales / earnings to price), the price trigger (6-month momentum + 52-week position), the business trigger (latest-quarter EBITDA change + revenue YoY), and the industry tailwind (6-month industry momentum). Nothing is fitted.
- **Funnel:**
  - longlist of 60 (≤ 4 per industry);
  - **30 candidates**, each with a written thesis;
  - **10 held**, picked by Amit (D2), each pick logged with a reason.
- **Label:** shown as ADR 0073 **grade C**: "a shortlist for judgement".
- **Holding:** no stop-losses. The 30 are refreshed yearly from the score (phase 1b: 24-month holds −3.7 points, conviction exits −5.8 points). Quarterly reviews read events and results; the conviction verdict is a monitor.
- **Size:** tested at ₹1 lakh per name. The edge sits in stocks trading ₹0.5–1 Cr a day (a ₹1 Cr floor cuts it from +12.7 % to +5.2 %/yr), so capacity is small.

## Why
- **The old funnel picked from the wrong group:**
  - its gates caught 3 of the 74 Oct-2016 survivors that went 10x;
  - on the thesis harness its lift is below 1 at most anchors;
  - the 10-year study found size and cheapness raise the odds and quality lowers them.
- **The thesis book**, 30 names, after costs and tax: +14.1 %/yr over the Smallcap 250, t 2.01, 12 of 12 start months, 4 of the last 5 years. The price-only part, with delisted stocks included: +11.7 %/yr, t 2.22.
- **Grade C only because of its worst 12 months (−33 %).** Its top 30 also halved far less often than the pond (lift 0.28).

## Consequences
- `signals/multibagger.py` is rewritten to the thesis score (plan 0026 phase 2). The old columns stay until plan 0017 retires them.
- Phase 1b ([study §1b](../studies/multibagger-thesis-2026-10.md)) tested 25 changes; none passed, so v1 stands. Under realistic costs: +12.7 %/yr, t 1.90, DSR 0.961, PBO 0.29, worst 12 months −33 %.
- The Playbooks "Strict compounders" tab loses its meaning (D4).
- Re-test once delisted fundamentals or another regime (a small-cap bear) are in the data.
