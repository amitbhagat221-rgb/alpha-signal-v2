# Alpha Signal v2

Daily stock intelligence for Indian retail investors. Computes 42 PIT-strict factors across 2,448 stocks, ranks them within market-cap tiers (LARGE/MID/SMALL), and emails the top picks with AI-generated investment theses.

**Owner:** Amit Bhagat | **Stack:** Python + SQLite + Jupyter + FastAPI cockpit | **Status:** In production (v2 took over from v1 on 2026-05-01)

---

## What this does

```
Daily 03:30 IST
    │
    ▼
fetch external data → compute factors → score within tier → email top picks
   (10+ sources)        (40 READY / 42)   (LARGE/MID/SMALL)    (top 5 + dossiers)
```

A single SQLite database (`data/alpha_signal.db`, 51 tables, ~320 MB) is the source of truth. Plain Python orchestrates 24 pipeline steps. No frameworks, no YAML, no surprises.

The factor stack is **PIT-strict**: fundamentals are filtered through `knowable_quarterly` / `knowable_annual` / `knowable_shareholding`, and prices are adjusted for splits/bonuses/dividends at signal-compute time (not at ingest). See [ADR 0010](docs/decisions/0010-pit-strict-corporate-action-adjustment.md).

## Quick start

```bash
source ~/alpha-signal/venv/bin/activate
cd ~/alpha-signal-v2

# See what's in the database
python -c "from db import table_counts; table_counts()"
python -c "from db import data_health; print(data_health().to_string())"

# Run the pipeline (or one step)
python pipeline.py --dry-run
python pipeline.py
python pipeline.py --step signal_piotroski

# Reconstruct a historical PIT snapshot (full = 23 signals, ~216s)
python -m tools.reconstruct_pit --date 2025-12-01

# Open the cockpit (read + limited write surface)
uvicorn cockpit.app:app --host 0.0.0.0 --port 3000

# Open the SQL explorer notebook
jupyter notebook notebooks/00_sql_explorer.ipynb
```

## Project layout

```
~/alpha-signal-v2/
├── README.md           ← you are here
├── CLAUDE.md           ← AI context: critical rules + pointers
├── HANDOFF.md          ← live "where I am right now" (overwritten each session)
├── CHANGELOG.md        ← what changed, when
├── docs/               ← all other documentation (start at docs/README.md)
│
├── config.py           ← all weights, thresholds, paths, pipeline steps
├── db.py               ← database helpers + data_health()
├── schema.sql          ← 51 tables
├── pipeline.py         ← THE orchestrator (24 steps)
├── validate.py         ← shared validators
├── health.py           ← health diagnostics
│
├── sources/            ← data fetchers (one file per source family)
├── signals/            ← 12 signal modules → 42 registered factors
├── scoring/            ← screener, quality_gate, regime
├── output/             ← snapshot, dossier, email
├── tools/              ← PIT reconstruction, backtest, corporate-action adjustment
├── cockpit/            ← FastAPI ops console (read + step rerun)
├── notebooks/          ← exploration + validation
├── tests/              ← 7 smoke tests
└── data/alpha_signal.db
```

## Where to learn more

| You want to... | Read |
|----------------|------|
| Where I am right now, what's next | [HANDOFF.md](HANDOFF.md) |
| See every doc available | [docs/README.md](docs/README.md) |
| Understand how the system fits together | [docs/architecture.md](docs/architecture.md) |
| Data sources, PIT/historical access, gotchas | [docs/reference/data-playbook.md](docs/reference/data-playbook.md) ⚠ READ BEFORE FETCHING |
| Understand a factor's formula | [docs/reference/signals.md](docs/reference/signals.md) |
| Add a new signal or source | [docs/runbooks/](docs/runbooks/) |
| Know why we chose SQLite/Python/PIT-strict adjustment/etc. | [docs/decisions/](docs/decisions/) |
| What's planned next | [docs/plans/](docs/plans/) |

## Status (high level)

- ✅ Foundation, data migration, signals, scoring, output — **DONE**
- ✅ Daily cron at 03:30 UTC: bhavcopy + RSS + insider + bulk-deals + macro + nselib backfills; Tickertape on monthly cron
- ✅ **PIT reconstruction harness** ([tools/reconstruct_pit.py](tools/reconstruct_pit.py)) — replays any historical snapshot with no future-event leakage. 23 signals, ~216s for a full reconstruction
- ✅ **PIT-strict corporate-action adjustment** (2026-05-06) — splits/bonuses/dividends compose at signal-compute time, not at ingest. See [ADR 0010](docs/decisions/0010-pit-strict-corporate-action-adjustment.md)
- ✅ **Cockpit ops console** at `:3000` — read-mostly with one write endpoint (rerun a failed pipeline step). See [ADR 0008](docs/decisions/0008-cockpit-write-surface.md)
- ✅ Smoke tests — [tests/test_smoke.py](tests/test_smoke.py); 7 tests covering imports, dry-run, critical-step config, flow overview, rerun guardrails, upsert preservation
- ✅ Parallel run + cutover — **2026-05-01**: v2 replaced v1 on the 03:30 UTC cron slot; v1 stays installed for rollback only

**In flight** (see [HANDOFF.md](HANDOFF.md) for the live list and [docs/plans/](docs/plans/) for the spec):
- F-track (factor depth, plan 0005): 42 → ~100 factors, then upgrade scoring from `weight × signal` summation to a real factor model with IC-stability weighting + orthogonalization + mean-variance portfolio construction. Next concrete step: F1.1 — Screener Premium ingest.
- D-track (intelligence): D15 → D17 (segment models, portfolio construction); D18 (XGBoost overlay) data-blocked until ≥6 months of accumulated PIT snapshots.
- 2 of 42 factors not READY by design: `sentiment_7d` (PARTIAL — needs FinBERT, F1.4) and `screener_final_composite` (PROPOSED — F3 deliverable).

## Relationship to v1

v1 (`~/alpha-signal/`) is the original pipeline. It is **still installed for rollback**, but v2 owns the 03:30 UTC cron slot since 2026-05-01. v2 was designed as a clean rebuild with proper engineering practices — see [ADR 0007](docs/decisions/0007-fresh-rebuild-v2.md) for context.

**Do not modify v1 from this folder.** The shared venv (`~/alpha-signal/venv/`) is the only thing v2 borrows.
