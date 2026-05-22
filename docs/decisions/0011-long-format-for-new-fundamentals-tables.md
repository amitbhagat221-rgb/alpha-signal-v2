# 0011 — Long-format for new fundamentals tables; legacy stays wide
**2026-05-10 · Accepted**

**Decision.** Track 3 (factor model) and onward use long format. Legacy wide tables (`quarterly_income`, `annual_balance_sheet`, `annual_cash_flow`, `shareholding`) stay wide.

- `fundamentals_screener` — PK `(sid, period_end, period_type, line_item)` + `value REAL`. New line items reach the table by name, no DDL.
- 3.1a (xlsx Data Sheet, 36 items) and 3.1a schedules JSON (per-company-variable, e.g. RELI gets `Trade Payables`, `Plant Machinery`, etc.) both write into the same long table.

**Why.**
- **Absorbs new line items free.** Cost of a 37th item = zero. Wide would need migration → backfill → update every consumer → re-validate.
- **Pivots cleanly on read.** `df.pivot_table(index=["sid","period_end"], columns="line_item", values="value")` at the top of `_compute()`. 1–2 lines, no measurable cost on ~700K rows.
- **Sparsity is honest.** Banks don't have "Trade Payables" — wide gives a NULL column, long gives no row.

**Why not migrate legacy too.** Three legacy signals (Piotroski, Forensic, Accruals) reproduce v1 C13b t-stats exactly. Switching would risk breaking that validation across all of them at once for zero operational gain. Clean cut at the Track 3 edge.

**Templates.** [signals/roic.py:62-74](../../signals/roic.py#L62-L74), [signals/fcf_yield.py:62-77](../../signals/fcf_yield.py#L62-L77).

**Related.** ADR 0009 (parent) · plan 0002 (implementation)
