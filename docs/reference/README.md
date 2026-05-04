# Reference

Long-lived reference material. Updated when the underlying thing changes.

**Reference vs Architecture vs Runbook:**
- **Architecture** explains *how the whole system fits together*
- **Reference** explains *one specific thing in detail* (a table, a signal, a source)
- **Runbook** tells you *what to type to accomplish a task*

If you find yourself writing prose, it's probably architecture. If you're writing tables and field definitions, it's reference.

## Index

| File | Contents | Status |
|------|----------|--------|
| [data-playbook.md](data-playbook.md) | **THE data reference.** Every source (endpoint, PIT/historical access, depth, gotchas, rate limits), filing-lag rules, the 6 reconstruction patterns we've used, running log of known issues + resolutions, per-signal PIT recipes. Read before fetching; update after every incident. | ✅ canonical |
| [api-endpoints.md](api-endpoints.md) | **Working API catalog.** Per-endpoint reference: function signatures, history depth, quirks, install commands, probe dates. Tier A (free + deep), Tier B (forward-only), Tier C (caveats), Tier D (paid). NSE quirks + things-tried-and-rejected. | ✅ canonical |
| [paid-data-sources.md](paid-data-sources.md) | **₹5K/mo budget playbook.** Stack-ranked paid subs (Zerodha Kite, Screener Premium, EODHD, Trendlyne, TrueData, etc.) with concrete allocation and decision tree. Includes Sensibull skip rationale. | ✅ canonical |
| [cockpit.md](cockpit.md) | Cockpit pages, routes, components | ✅ |
| schema.md | Every SQLite table: columns, types, constraints | ⏳ aspirational — `db.py TABLE_META` is the de-facto source today |
| signals.md | Every signal: formula, inputs, outputs, validated t-stats per tier | ⏳ aspirational — `db.py BACKTEST_SIGNALS` is the source today |
| pipeline-steps.md | The pipeline steps, dependencies, frequency | ⏳ aspirational — `config.PIPELINE_STEPS` is the source today |
