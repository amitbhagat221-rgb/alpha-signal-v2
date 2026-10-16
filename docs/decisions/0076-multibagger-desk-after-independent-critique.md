# ADR 0076 — Multibagger desk after the independent critique: tail claim withdrawn, capacity cap, three measured books

**Status:** accepted 2026-10-16 (Amit: "complete all and prepare answer for the reviewer"). **Amends** [ADR 0075](0075-multibagger-thesis-replaces-quality-funnel.md); the thesis score and funnel are unchanged. Evidence: [critique](../research/0008-multibagger-critique-findings.md), [response](../research/0008-multibagger-critique-response.md), `tools/mb_critique.py`, `data/lh/v2/mbc_results.json`.

## Decision
- **Claims kept, with the pond as the second benchmark.**
  - Top 30 beats the equal-weight pond by +8.7 %/yr (survivors, t 2.25) and +9.6 %/yr (full market incl. delisted, price-only, t 1.89), 12 of 12 starts.
  - It holds at a 90-day quarterly lag (+11.0 %/yr) and on a pond built from the live market-cap source (+8.6 %/yr over the pond, t 2.31).
- **Claims withdrawn:**
  - **Fewer blow-ups:** the full-market halving lift is 0.72 and the ≤ 0.3x lift is 1.01; the 0.28 was a survivor effect.
  - **Passing multiple testing:** the honest DSR is 0.764 at 67 counted trials with null variance, below 0.90. The earlier 0.961 used near-clone variance and no skew or kurtosis terms.
- **Grade stays C.** The cockpit label states both the edge over the pond and the two withdrawn claims.
- **Size:**
  - the desk at most about ₹3 crore;
  - each name at most 5 % of its 20-day traded value and at most 10 % of the book at cost;
  - the 10 held at most 10 % of the equity portfolio.
- **Measurement:** three forward paper books (equal-weight pond, equal-weight top 30, Amit's 10) with kill rules:
  - **score:** the top 30 trails the pond by > 5 points over 24 months;
  - **human:** the 10 trail the 30 by > 10 points, or a lower share of names up ≥ 50 %;
  - **risk:** a rolling 12-month excess below −35 % halts buying;
  - **capacity:** a name above 10 % of its 20-day traded value stops adding.
- **Name exits by process, not price:**
  - **automatic:** statutory-auditor resignation, GSM/ESM entry, results not filed on time;
  - **review within a week:** pledge above 50 %, or promoter stake down more than 5 points in two quarters.
- **Valuation:**
  - cost of equity by size, 14 % → 20 % (+1 point when trading is below ₹1 crore a day);
  - the DCF shows its terminal-value share;
  - mid-cycle EV/EBITDA; EV/Sales for loss-makers;
  - analyst targets only with ≥ 3 analysts.

## Why
- An outside reviewer working only from the brief found the benchmark, multiple-testing, survivorship, capacity and human-stage gaps. Their tests were run with their pass bars: 5 passed, 2 failed, 2 overlays were rejected.
- No price stop-loss still stands (ADR 0040: stops eject winners), but it no longer leans on tail protection. Process exits and size carry the risk control.

## Consequences
- **Not adopted:** the promoter-buying part (−0.8 points) and the cash-conversion gate (−1.6 points; it removes 10 % of later winners).
- **Re-test triggers:**
  - 24 months of the three paper books;
  - dated industry classification;
  - fundamentals for delisted companies.
