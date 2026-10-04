# ADR 0062 — Factor audit: the inputs are corrected as one model change

**Status:** accepted 2026-10-03 (Amit: "yes please fix all and institute the new checks as required").
**Context:** [plan 0020](../plans/0020-factor-audit.md), findings in [factor-audit-2026-10.md](../studies/factor-audit-2026-10.md).

## Decision

The factor formulas were right; several inputs were not. They are corrected together, the panel is rebuilt on every anchor and the evidence re-run. Weights are unchanged except one sign that follows from a column choice (5).

1. **A source field is named for what it holds.** `quarterly_income.interest` → `operating_expenses`, `annual_cash_flow.depreciation` → `dividends_paid` (Tickertape `qIncOpe`, `cafTcdp`). Real interest and depreciation come from the Screener annual statement. Piotroski's margin test is (revenue − operating expenses) ÷ revenue; Altman's EBIT is profit before tax + interest.
2. **Price and share count sit on one basis** (`signals._fundamentals.shares_and_book`). The vendor's share count is on the basis of its last fetch: it is carried to the date by the split and bonus factors still to come, and replaced by the Screener statement count only when the two disagree and a split is recent or the vendor row jumped more than 5× on the year. Book equity excludes minority interest.
3. **The return label is a total return on adjusted prices.** A split inside the window is not a loss.
4. **Fiscal-year EPS is known 75 days after year-end**, not on the year-end date. The `consensus` factor is reported EPS growth, computed as change over |base| and winsorised.
5. **A weight sits on the column its evidence was measured on.** MID accruals: −0.22 on `cf_accruals` (t = −2.90), replacing +0.22 on the four-part `accruals_signal` blend, which has no evidence of its own. The blend stays in the panel, unweighted.
6. **Sector tilt computes its macro leg as of the date**, from macro history, never from a stored table.
7. **A stored trading day must be the day asked for.** The price harvester refuses a file whose own date differs (NSE serves the previous session on a holiday); 44 copied days were deleted (kept in `output/phantom_price_rows_2026-10-03.csv.gz`).
8. **Every wired factor declares who should have a value** (`eligibility`; a test enforces it). An option reading older than 7 days is not used.
9. Smaller: a bonus of preference shares is not a price adjustment; Piotroski is scaled to 9 points whatever the number of components (≥ 6); the earnings window takes the first filing of a result and must be a real 3-day window; duplicate resignation filings count once.

10. **A past date carries the tier of that date** (`pit.tiers_at`, the panel builder only; live keeps the production tier), and **the label enters at the session after the signal**.
11. **The daily price file is kept whole**: rows for symbols outside `stocks` go to `stock_prices_unlisted`, and NSE's rename list (`symbol_changes`) gives a renamed stock its earlier history.

## Guards added

- `tools/reconcile.FUND_FIELDS`: every statement column a factor reads is compared with the Screener line item that must hold the same quantity (was: revenue only). The old "interest" would have failed on day one.
- Health checks `PRICE_DAY_COPIED` and `PRICE_JUMP_UNEXPLAINED`, each with a fire drill.
- Backtest: no verdict or interval below 12 anchors; one `evidence()` reader; the decay monitor uses the backtest's anchors and the ranked column.

## Consequences

- The ranking of 2026-10-04 differs from 2026-10-03 by construction. Same inputs day, old code vs new: score rank correlation LARGE 0.94, MID 0.93, SMALL 0.92; top-30 kept 25, 24 and 15. `PICKS_RESHUFFLED` will fire once; replaying a freeze from before the change will show drift.
- Evidence after the rebuild replaces what `signal-weights.md` records. Known already: `consensus` LARGE t 1.74 → 1.05 with the filing lag, below the 1.5 bar. No weight is changed for that here: it goes to the promotion review.

## Not decided here

- Financials in MID are still scored on three factors with book-to-price ranked against non-financials (study R9). A model question, for the factor-model stage.
- Historical tiers, the survivorship-free universe and versioned inputs (study §3, §5): the backtest redesign.
- Statements arriving later than the 75-day lag assumes (study R11); demergers in the adjustment table (P3).
