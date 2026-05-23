# 0018 — Analyst PT data model: episodic, three-table
**2026-05-23 · Accepted**

**Decision.** Analyst price targets live in three tables, not one, because PTs are episodic events (sell-side analysts revise ~quarterly) and the three views serve different consumers:

| Table | PK | Cadence | Source | Consumer |
|---|---|---|---|---|
| `analyst_consensus` | `sid` | Daily refresh (overwrite) | yfinance for `price_target` + `total_analysts`; Tickertape for `forward_eps` / growth fields | Cockpit "current PT" card; `signals/consensus.py` (live pt_upside) |
| `analyst_consensus_snapshots` | `(sid, snapshot_date, source)` | Monthly @ 1st business day | yfinance | Backtest + revision signals over 3/12-month windows |
| `forecast_history` | `(sid, metric, date)` | Annual (Tickertape year-end Dec 27-28); plus 4/8/...month EPS+revenue points | Tickertape (after `_extract_forecast_rows` filters today-entry contamination) | Long-horizon backtest (2022-2025), `pit_pt_upside` fallback when monthly snapshot missing |

**Why.** Three latent bugs collapsed into one HALC cockpit page (see HANDOFF 2026-05-22):

1. Tickertape's `forecastsHistory.price[-1]` was the intraday `lastPrice`, not an analyst PT. Daily ingestion wrote it into `analyst_consensus.price_target` and as a daily row in `forecast_history`. **Result:** PT ≈ close for 95.6% of universe, `pt_upside` signal flat near zero, screener silently ranking on garbage.
2. The data model assumed PTs change daily — they don't. Daily storage created the room for the `lastPrice` contamination to slip in unnoticed: the value "always" changed, so no one looked.
3. The "validated" `pt_upside` |t|=16.29 backtest result was contamination + price-anchor mechanism (stale year-end PT / current close = -recent_return), not real analyst-consensus alpha. Real IC for analyst-PT factors is 0.05-0.15; we were measuring 0.65+.

**The three-cadence model fixes all three:**
- The **field owner** of each value is unambiguous. `price_target` is yfinance-only; Tickertape no longer writes it (see `sources/tickertape_analyst.py:_extract_analyst_row`). If yfinance lacks coverage, the field is NULL — better than stale contamination.
- The **cadence** matches the phenomenon. Sell-side analysts publish ~quarterly; monthly snapshots capture material revisions while filtering daily noise; year-end snapshots from Tickertape give us 4 years of clean historical anchors for long-horizon backtests.
- The **schema** makes the rule load-bearing. Writing a daily PT row would have to mean writing to `analyst_consensus_snapshots`, which would fail the `PRIMARY KEY (sid, snapshot_date, source)` if attempted twice in a day. The model prevents the failure mode rather than relying on discipline.

**Ingestion rules (encoded in producers + checked by `tools/data_sanity.py`):**

- `sources/tickertape_analyst.py:_extract_forecast_rows` — drops any `metric='price'` entry within 90 days of fetch date (the lastPrice contaminant).
- `sources/tickertape_analyst.py:_extract_analyst_row` — does NOT touch `analyst_consensus.price_target`. Writes only the eps/revenue fields it owns.
- `sources/yfinance_analyst.py` — default mode writes only `price_target` + `total_analysts` + `has_analyst_data` (narrow upsert; doesn't clobber Tickertape's eps/revenue). `--snapshot` mode additionally appends a row to `analyst_consensus_snapshots`.
- Daily cron: yfinance default mode via `PIPELINE_STEPS:fetch_yf_analyst`.
- Monthly cron: `30 4 1 * * ... yfinance_analyst --snapshot`.

**Cadence rule generalized** (CLAUDE.md "Data-cadence rule"): When adding any new "PT-like" producer, ask first "is this episodic?". If yes, store at the natural cadence (monthly/quarterly), not daily. Daily storage of an episodic value is phantom precision and creates room for source-value contamination.

**Promotion path for `pt_upside` weight.** The cleanup-era backtest gave |t|=7.20 LARGE / 6.32 MID / 8.23 SMALL — still suspiciously high (academic literature: 2-4 typical). Likely still a price-anchor artifact: with monthly PTs, daily prices move further from the anchor over the month, mechanically inflating the IC vs forward returns. Don't bump `SCREEN.weight_tiers["pt_upside"]` until ≥3 monthly snapshots accumulate (calendar: 2026-08) and the backtest stabilizes.

**Rollback.** Restore the previous `_extract_analyst_row` to write `price_target` from `price_hist[-1]`. Drop `analyst_consensus_snapshots`. Remove the 90-day filter in `_extract_forecast_rows`. v1 still ingests this way; no data loss.

**Related.**
- [HANDOFF 2026-05-22](../../HANDOFF.md) — original bug surface ("16.5% downside at ₹1038")
- [docs/reference/data-playbook.md](../reference/data-playbook.md) — Consensus group section, updated for the new model
- [ADR 0011](0011-long-format-for-new-fundamentals-tables.md) — same long-format principle applied to fundamentals_screener
- CLAUDE.md "Data-cadence rule" — the generalized rule this ADR instantiates
