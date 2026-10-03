# Reference

How specific things work. Update a file when the underlying thing changes. Don't copy counts that code already knows; point to the code instead.

| File | Contents |
|---|---|
| [architecture.md](architecture.md) | Layers, layout, where the sources of truth live, data flow |
| [data-playbook.md](data-playbook.md) | **The data reference**: every source and endpoint, PIT rules, reconstruction patterns, known issues. Read it before fetching |
| [signal-weights.md](signal-weights.md) | Validated signal map (t-stats per tier), wired weights, promotion rules |
| [cockpit.md](cockpit.md) | Cockpit pages, routes, components, colour tokens |
| [commands.md](commands.md) | Most-used CLI commands |
| [health-checks.md](health-checks.md) | The five health questions, the three severities, where a check lives, how to add one, the data-trust score in plain words |
| [kite-setup.md](kite-setup.md) | Zerodha Kite Connect setup |
| [oss-quant-toolbox.md](oss-quant-toolbox.md) | Open-source libraries mapped to our gaps (step 0 of plan 0014) |

## Live sources of truth in code (not copied here)

- **Pipeline steps + cadence:** `config.PIPELINE_STEPS` (`frequency` = daily / weekly (Sunday) / monthly (1st))
- **Schema:** `schema.sql` + `db.TABLE_META`; live table list: `sqlite3 data/alpha_signal.db .tables`
- **Signals registry:** `db.BACKTEST_SIGNALS` + `db.FACTOR_LIBRARY`
- **Weights:** `config.SIGNAL_WEIGHTS` (rationale in signal-weights.md)
- **Cron:** `crontab -l` (not in git; the table is in [OPERATOR.md](../../OPERATOR.md), §2)

Archived research dumps (multibagger ×4, sector deep-research, PIT-sources research, paid sources, crypto sources, pre-merge api-endpoints) are in [`../_archive/reference/`](../_archive/reference/).
Evidence write-ups (re-baseline, return-prediction report, plan-0012/0013 studies) are in [`../studies/`](../studies/).
