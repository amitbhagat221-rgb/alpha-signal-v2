# HANDOFF
Updated: 2026-06-13 | Branch: master (1 commit this session → pushed) | HEAD: `ce1fa1c` + this handoff commit on top

## Left off
Shipped 3 things off the now-sid-complete BSE event stream: (1) the **PEAD date-swap** ([signals/pead.py](signals/pead.py) — drift now anchors to the real `bse_announcements` `Result` `dt_tm`, 85.5% match) which re-backtested **still all-DROP** (real dates were necessary not sufficient — the binding constraint is the consensus-EPS *surprise*, not the date); (2) the **daily keep-current wiring** (`bse_announcements --days 7` → `sources.scrip_master` into run_daily_forward.sh + registered in `config.RAW_TABLES`/`STALENESS_OVERRIDES`, both FRESH); and (3) a **brand-new validated factor `governance_resignation`** ([signals/governance_events.py](signals/governance_events.py)) — senior/auditor-resignation density, **MID t=−3.82 KEEP** (negative sign, forensic), fully registered + reconstructed but **NOT yet wired**.

## Pick up here
1. **Deliberate weight review for `governance_resignation`** (MID t=−3.82 KEEP, unwired) — orthogonality-check its PIT column in `daily_snapshots_pit` vs `piotroski`/`forensic`(m_score)/`pledge_quality`, then decide a negative-weight MID penalty per [signal-weights.md](docs/reference/signal-weights.md) (never mechanical) → [config.py](config.py) `SIGNAL_WEIGHTS` + [scoring/screener.py](scoring/screener.py) `_load_signals` if wired.
2. **Credit-rating directional factor** — richest BSE family (14.5K events/1,480 sids) but direction is **PDF-locked** (headline is LODR boilerplate; `downgrad` only 88/14,510). Needs a PDF/text-extraction layer or skip; density-only sign is ambiguous.
3. **Next-3 #1c transcript look-ahead** — replace [sources/transcripts_pull.py](sources/transcripts_pull.py) `doc_date` month-proxy with the real `bse_announcements` `dt_tm` (same pattern as the PEAD swap just shipped).

## Watch out
- `reconstruct_pit.PIT_COLUMNS` is the **write-emit filter** — a new factor merged into `base` but missing from `PIT_COLUMNS` writes **all-NULL silently** (`with_signal=0`). Cost a debug cycle on `governance_resignation`. A new PIT factor needs: dispatch **+ `PIT_COLUMNS` + `_VALIDATION_RANGES` + `db._COLUMN_MIGRATIONS`** (+ BACKTEST_SIGNALS, SIGNAL_COLUMN_MAP, FACTOR_LINEAGE).
- `backtest_pit --signal` takes the **COLUMN name** (`pead_drift_60d`, `governance_resignation`), NOT the `reconstruct_pit --signal` group name (`pead`, `governance`). The old HANDOFF's "`--signal pead`" no-ops.
- `run_daily_forward.sh` is gitignored (`*.sh`) → the BSE cron wiring is **live-VM-only, not in the commit**; the registration (`config.RAW_TABLES` + `db.STALENESS_OVERRIDES`) IS committed. Cron runs 14:00 UTC daily.
- Only **monthly** anchors were reconstructed for pead + governance — weekly-anchor `pead_drift_60d`/`governance_resignation` rows in `daily_snapshots_pit` are stale/absent (inert; both monthly-cadence, but don't trust weekly rows).

## Active plan
No single plan doc — rides **Next-3 #1** ([ADR 0042](docs/decisions/0042-data-acquisition-build-not-buy.md), data-acquisition build-not-buy). Checklist **1a** = governance event factor (BUILT); **1b** = crypto Phase 0 (separate repo `~/crypto-convex`).
