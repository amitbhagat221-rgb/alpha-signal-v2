# Reference

How specific things work. Updated when the underlying thing changes.

## Files

| File | Contents |
|---|---|
| [architecture.md](architecture.md) | The 5 layers, project layout, pipeline steps, DB groups, data flow |
| [data-playbook.md](data-playbook.md) | **THE data reference** — every source, PIT rules, reconstruction patterns, gotchas. Read before fetching. |
| [api-endpoints.md](api-endpoints.md) | Working API catalog — function signatures, history depth, install commands, probe dates |
| [paid-data-sources.md](paid-data-sources.md) | ₹5K/mo budget allocation + decision tree |
| [pit-data-sources-research.md](pit-data-sources-research.md) | Deep-research (money-no-object) on 5 PIT gaps: consensus/earnings dates, India rates+curves, survivorship-free fundamentals, NBFC asset-quality, transcripts. Ranked picks + best stack + open questions |
| [cockpit.md](cockpit.md) | Pages, routes, components, color tokens |
| [signal-weights.md](signal-weights.md) | Validated signal map (t-stats per tier) + weight tier rules |
| [commands.md](commands.md) | Most-used CLI commands |

## What's live source-of-truth in code (not duplicated here)

- **Schema** — `db.TABLE_META` and `schema.sql`
- **Signals registry** — `db.BACKTEST_SIGNALS`
- **Pipeline steps** — `config.PIPELINE_STEPS`

Code is canonical for these; docs would drift.
