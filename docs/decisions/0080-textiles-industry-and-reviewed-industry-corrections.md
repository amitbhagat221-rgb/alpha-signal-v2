# ADR 0080 — Textiles & Apparel industry; industries checked against a second source, corrections reviewed by hand

**Status:** accepted 2026-10-17 (Amit: "this is a textiles company not a paper wood company" → "yes please").

## Decision
- **New industry "Textiles & Apparel"** under Consumer Discretionary (GICS puts textiles, apparel and luxury goods there). Industry code 39 (`signals/industry_id`): it sorts last, so no existing code moves.
- **Second source:** the industry category in each stock's Moneycontrol slug (`stocks.mc_slug`, already stored for 2,258 of 2,448), used only when the slug's company token matches the stock (`tools/industry_audit.py`; 46 slugs point at another company, e.g. TRIDENT → Trent, ASHOKA → Ashok Leyland). NSE's quote page holds the exchange's own classification but answers 403 to this server; it is not worked around.
- **Corrections are reviewed, not mechanical:** 349 stocks disagreed; each was read and 196 were corrected in `tools/industry_review.py` with a reason per stock. Moneycontrol is wrong often enough (IndiGo as logistics, REITs as construction, Dr. Lal PathLabs as pharma, gas distributors as oil drilling) that its category never overwrites an industry by rule.
- **The reviewed list always wins:** `tools/classify_industries.py` re-applies it after every run; a move sets `stocks.sector` to the new industry's parent (the classifier's invariant, 0 breaks on 2026-10-17).
- **Apparel brands that mainly run their own store chains stay in Retail** (Vedant Fashions, ABFRL, Go Fashion, Arvind Fashions, Credo Brands); makers move to Textiles & Apparel.

## Why
- The classifier picked from a closed list with ticker and name only, and the list had no textiles industry: about 80 textile companies sat in Paper / Wood (Vardhman, Trident, Swaraj), Chemicals (Alok, Filatex), Retail (Arvind, Gokaldas), Consumer Durables (Page, Welspun Living) or nowhere (KPR Mill, Lux).
- The industry feeds the multibagger thesis's tailwind part, peers, Sectors' Industry Detail and the macro desk; the sector feeds the wired SMALL `sector_tilt`.

## Consequences
- 196 stocks change industry, 113 change sector. Measured before applying (today, live labels): SMALL top 20 unchanged, top 30 two swaps, score rank correlation 0.994; every sector's tilt value shifts a little because sector baskets change. Multibagger top 30: eight swaps.
- `sector_tilt` and `industry_id` in the PIT panel were built on the old labels; they are recomputed on all panel dates after the change, and `sector_tilt`'s evidence re-run.
- `tools/industry_audit.py` is the re-check for any new listing or re-classification.
