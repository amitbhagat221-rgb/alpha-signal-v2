# HANDOFF
Updated: 2026-05-31 | Branch: master (0 unpushed) | HEAD: `df3c744` fix(identity-gate): name-aware MoneyControl verification + recover false quarantines

## Left off
Shipped the full feasible-now §3.2 build-out in one session — 18 new factors (4 F&O OI + 4 in-house Black-76 IV + 6 daily microstructure + 4 PEAD) — and put idle validated alpha to work: **5 factors now carry production weight** (`iv_skew_25d` MID, `pt_upside` L/M/S, `pledge_quality` + `delivery_anomaly_z` SMALL), each orthogonality-gated. Manual actions done: cockpit-ops restarted (`/system` funnel now 85, Phase E sector badges live) and the screener re-ran so today's `daily_picks` reflect the new weights.

## Pick up here
1. **§3.2.6 `industry_id` one-hot + §3.2.7 macro betas** — the last build-now §3.2 factors. Check `macro_history` for INR-forward / G-Sec / commodity series *first* (§3.2.7 may need new sources); `industry_id` is trivial. New `signals/` + `tools/reconstruct_pit.py` wiring.
2. **`pt_upside` artifact re-verify (due 2026-08)** — it's CAPPED in `config.SIGNAL_WEIGHTS` (0.16–0.25) pending this. Re-run `python -m tools.backtest_pit --signal pt_upside` once ≥3 fresh monthly `analyst_consensus_snapshots` exist; un-cap or pull based on whether t=7–9 holds on clean-PT periods.
3. **Kite activation** — user adds 5 Connect creds to `run_pipeline.sh` (see `docs/reference/kite-setup.md`), then `sources/kite_pull.py --check-auth` → `--instruments` → `--backfill-bars`, wire `fetch_kite_bars` into `PIPELINE_STEPS`. Starts the ~90d clock for the 3 held intraday §3.2.3 factors.

## Watch out
- **Long-running cockpit services cache the factor registry in memory + a 300s disk cache** (`get_factor_health` `@_persisted_cache`). Any future `BACKTEST_SIGNALS`/`SIGNAL_WEIGHTS` edit needs `sudo systemctl restart alpha-cockpit-ops` to show in `/system` — editing `db.py`/`config.py` alone won't (this is why it read 66 not 85 today).
- **`kyle_lambda` (t=4.24) and `corporate_action_density` (t=−3.67) are statistical KEEPs deliberately NOT promoted** (cost-coupled liquidity tilt / unclear mechanism). Don't let a future mechanical sweep wire them — see signal-weights.md "On the bench".
- **PEAD factors approximate announcement = period_end + 45d** (no real announce dates); don't treat `pead_drift_60d` / `earnings_surprise_std` as precise event-time, and don't re-attempt PEAD without an earnings-calendar feed (memory `pead_needs_announce_dates`).

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — Phase 3.2, **42/50 PIT-shipped**. §3.2.1✅ §3.2.2✅(8/8) §3.2.3 6/9 §3.2.5 4/6; §3.2.6+§3.2.7 next; §3.2.3-rest + §3.2.4 blocked on Kite/NLP (3.1c/3.1d).
