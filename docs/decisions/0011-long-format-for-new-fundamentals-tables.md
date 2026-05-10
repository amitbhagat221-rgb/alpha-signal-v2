# 0011 — Long-format for new fundamentals tables; legacy wide tables stay wide

**Status:** Accepted
**Date:** 2026-05-10
**Decided by:** Amit (with Claude Code)

## Context

v1 + v2 had used wide-format tables for fundamentals: `quarterly_income`, `annual_balance_sheet`, `annual_cash_flow` each have one column per line item (revenue, net_income, pbt, total_assets, current_assets, etc.). Adding a new line item meant a schema migration plus updating every consumer's column list.

When F1 (the F-track data layer) landed today, two design questions came up:

1. **F1.1 — Screener Premium xlsx export:** the Data Sheet has 36 annual line items. Wide format would mean 36 columns at minimum, with the certainty that future Screener releases would add more (Screener has been adding line items year over year — `Other Mfr. Exp` and `New Bonus Shares` are recent additions).
2. **F1.2 — Screener schedules JSON:** unblocked today (commit `6bd5a38`). Each company's "Other Liabilities", "Borrowings", "Other Assets", and "Fixed Assets" expansions return a per-company-variable set of sub-items: RELI has 23 new line items including `Trade Payables`, `Long term Borrowings`, `Plant Machinery`, `Ships Vessels`. A bank has none of those. A pharma company has different ones. Wide format would mean a sparse, ever-growing column set with no clear schema authority.

## Decision

**New fundamentals tables (F-track and onward) use long format. Legacy wide tables (`quarterly_income`, `annual_balance_sheet`, `annual_cash_flow`, `shareholding`, etc.) stay wide.**

Concretely:

- `fundamentals_screener` — long format from day one. PK `(sid, period_end, period_type, line_item)`, with a single `value REAL` column. New line items reach the table by name (`"Trade Payables"`, `"Plant Machinery"`) without DDL.
- F1.1 (xlsx Data Sheet) and F1.2 (JSON schedules) both write into the same long table — line_items just don't collide because Screener's own naming is consistent across the two endpoints.
- Existing wide tables stay as-is. They have working consumers (Piotroski, Forensic, Accruals, Consensus) and migrating them would change the cross-section of validated factors. Not worth it.

## Why

**Long format absorbs new line items for free.** The cost of adding a 37th line item to `fundamentals_screener` today is zero — the parser already writes whatever Screener returns, and consumers query by `line_item IN (...)`. With wide tables we'd need: schema migration → backfill → update every signal that has a column list → re-validate.

**It pivots cleanly to wide on read.** All F-track signals that need wide data (`signals/roic.py`, `signals/fcf_yield.py`) do `df.pivot_table(index=["sid","period_end"], columns="line_item", values="value")` once at the top of `_compute()`. That's 1–2 lines of pandas; no measurable cost on the ~700K-row table.

**Sparsity is honest.** Bank balance sheets don't have "Trade Payables" in any meaningful sense. Wide format would give them a NULL column; long format gives them no row. Long is the more accurate representation of what the source actually said.

**Migration would be costly without payoff.** The legacy wide tables back signals that reproduce C13b t-stats exactly (verified today via `tools/backtest_pit.py`). Switching them to long would risk breaking that validation across all four legacy quality signals at once. The wide-vs-long boundary at the F-track edge is a clean cut.

## Alternatives considered

- **Wide for everything (migrate legacy plus F-track).** Rejected — schema-migration churn every time Screener adds a line item, and adds risk to validated factors that don't gain anything from the migration.
- **Long for everything (migrate legacy too).** Rejected — three signals (Piotroski, Forensic, Accruals) read the wide tables and reproduce v1 t-stats. The migration cost (six tables, four signals, full re-validation) buys nothing operational.
- **Hybrid: per-section wide tables for F-track** (`fundamentals_pl`, `fundamentals_bs`, `fundamentals_cf`). Rejected — same column-bloat problem at finer grain. The Schedules endpoint expansions don't fit any one section anyway (e.g. Trade Payables is BS, but Plant Machinery is also BS, and they're different parents under the same section).

## Consequences

- Future fundamentals sources (Trendlyne, Tijori, EODHD if we add it) follow the long-format convention by default.
- New factor modules consume `fundamentals_screener` via the pivot pattern. `signals/roic.py:62-74` and `signals/fcf_yield.py:62-77` are the canonical templates.
- The wide-vs-long boundary documented above. Anyone touching this code can read this ADR before designing the next fundamentals table.

## Related

- ADR 0009 — F-track parallel to D-track (parent decision).
- Plan 0005 — F1.1, F1.2 implementation (schema discussion).
- Commits: `1757abf` (F1.1 long-format `fundamentals_screener`), `6bd5a38` (F1.2 schedules scraper writing into the same table).
