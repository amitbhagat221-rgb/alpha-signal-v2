# HANDOFF
Updated: 2026-05-25 (extended marathon) | Branch: master (1 unpushed + 17 dirty) | HEAD: `2dfbd5f` fix(pipeline): reorder + cap + honor frequency

## Left off
Same-day megabatch: full Phase E PIT-replay validator (forward + 6 historical anchors + composite backfill + cockpit tile + pre-push hook + daily auto-freeze), MICRO tier carved out of SMALL (595 stocks, ADTV+quality+data composite, excluded from picks but signal calc retained), cockpit cold-restart perf rewrite (`/system` 28s → 0.2s, `/news` 2.4s → 0.05s, `/portfolio` 3.3s → 0.03s via new `_persisted_cache` decorator + disk pickles + parallel prewarm), health cleared 3 CRITICAL / 7 WARN → 0/0/16, news flagship UX revamp with 1242/1244 OG images. Broker_recos full backfill at 2,250/2,448 SIDs (3,300 rows, 92 no-slug); ETA ~1 hour remaining.

## Pick up here
1. **Confirm broker_recos finished + refresh consumers** — `tail -3 /tmp/broker_full.log` should show Done; then re-run [output/dossier.py](output/dossier.py) + [output/email_sender.py](output/email_sender.py) and bust the persisted caches via `python -c "from cockpit.api import get_model_overview; get_model_overview(_force=True)"` (or just `rm data/.cockpit_cache/*.pkl` and let the next prewarm rebuild).
2. **Phase F (93 → 95)** — Track 2.2 financial sub-model is the biggest remaining piece: ship [sources/banking_metrics.py](sources/banking_metrics.py) (RBI/banking data source, doesn't exist yet) + [signals/financial_signal.py](signals/financial_signal.py); plus per-stock data-lineage instrumentation across the signal modules.
3. **Promote candidate factors into SIGNAL_WEIGHTS** ([config.py:42](config.py#L42)) — `bulk_deal_signal SMALL` (t=2.56 weekly+NW), `delivery_anomaly_z SMALL` (t=4.11), `roic`/`fcf_yield`/`nwc_to_revenue`/`dso_change_yoy` all KEEP-verdict but not yet weighted. Last rebalance was 2026-05-23 — pick when to do the next.

## Watch out
- **MICRO is excluded from picks but NOT from signal computation** — all signal modules (piotroski, accruals, consensus, etc.) still process MICRO. Only the screener (`scoring/screener._load_signals`) filters them via `config.EXCLUDED_FROM_PICKS`. If a future consumer of `daily_picks` assumes the table covers the whole universe, it will now silently miss 595 stocks.
- **`stocks.cap_tier` is the source of truth for tier** — [cockpit/api.py get_stock_detail()](cockpit/api.py) used to merge `daily_picks.cap_tier` on top, resurrecting yesterday's tier for newly-reclassified stocks. Fixed today; if you add another consumer pulling `cap_tier`, prefer `stocks` over `daily_picks`.
- **`data/.cockpit_cache/*.pkl` survives systemd restarts** — speeds cold start 50-140× but means stale data persists until TTL or manual delete. After data changes that DON'T trigger the daily cron (manual SQL edits, hotfix backfills), `rm data/.cockpit_cache/*.pkl` to force fresh compute. Already in `.gitignore`.
- **`tools/pit_replay.py` historical freezes use the 4 composite signals now stored in `daily_snapshots_pit`** — if you add a new signal to `scoring/screener.SIGNAL_COLS`, you MUST also add it to PIT_COLUMNS in [reconstruct_pit.py:120](tools/reconstruct_pit.py#L120) + a `pit_<signal>()` helper + DEFAULT_SIGNALS, then re-run reconstruct against the 6 anchor dates AND re-freeze, or replay will silently use NaN.
- **Pre-push hook at [.git/hooks/pre-push](.git/hooks/pre-push) is local-only** (git doesn't version `.git/`). If you reclone or work from another machine, it's gone — re-create from the original copy or move it into a tracked `scripts/hooks/` dir.

## Active plan
[docs/plans/0005-data-confidence-to-95.md](docs/plans/0005-data-confidence-to-95.md) — Phase E shipped (90 → 93). Phase F next.
