# HANDOFF
Updated: 2026-06-20 | Branch: master | HEAD: `da4bf40` (model-ID fix) + uncommitted Track C range-backfill on top

## Left off
Big multi-track session, all committed except the Track C backfill tool: (1) **HRP portfolio thread end-to-end** — sizing spine (`f549e35`) → realized-return harness (`3fbf2a3`) → risk-adjusted NAV (`f26ac3d`, [tools/portfolio_nav.py](tools/portfolio_nav.py)) showing **HRP Sharpe 0.83 vs eqw 0.20** (the risk-adjusted lens flips the raw-20d −0.10% read in HRP's favor); (2) **3.3b-3 within-group orthogonalization** (`5848bcb`) — Value is the most collinear group (ρ≤0.74); (3) **credit_beta fair-test → definitive DROP** — backfilled `stock_prices` to 2020-01 (+781,884 rows), 65 anchors incl. the 2020-22 stress regime, still no IC ([[credit_beta_benched_signal_not_data]]); (4) **fixed a 4-day CRITICAL** (`da4bf40`) — retired Sonnet model ID `claude-sonnet-4-20250514` → `claude-sonnet-4-6`. Health was 8 CRITICAL from the dead model ID (now fixed; next pipeline run clears it).

## Pick up here
1. **3.3d Barra-style risk model** (last unbuilt 3.3 piece — style+industry+specific attribution) OR **§3.2.3 microstructure** (3 intraday factors — blocked on Kite creds).
2. **Wire the small-cap quality gate (2.1) into `daily_picks`** — built but consumed nowhere (latent gap in the screener).
3. _Date-gated clocks (nothing to code): `validate_rank_skill` ~2026-07-06 · `pt_upside` re-verify ~2026-08-01 · 63d/126d book outcomes mature ~Jul/Sep (auto via the daily `portfolio_outcomes` step)._

## Watch out
- **`stock_prices` now reaches 2020-01** (was 2022-07), but only `macro_betas` + `fwd_return` were PIT-reconstructed for 2020-22. Other factors' PIT still starts later — run `reconstruct_pit --signal X --months N` to extend a specific factor into the new window. The backfill tool is `sources.nse --start YYYY-MM-DD --end YYYY-MM-DD` (archive reaches ~2020-01; older needs jugaad-data's legacy path).
- **`portfolio_weights` / `portfolio_outcomes` / `portfolio_nav` are ADVISORY** — no capital deployed; the §3.3c head-to-head gate (≥1.5% risk-adj, 18-24mo) is ~2027.
- **Cockpit persisted-cache survives restarts** (`data/.cockpit_cache/*.pkl`, 60s TTL): after deploying `cockpit/api.py` changes, a pre-edit pickle serves new template fields as Jinja Undefined (e.g. `+0.0%`) for up to 60s, then self-heals; delete the pkl to force-refresh.
- **`insider_trades` STALE ~49d** is the NSE disclosure lag (override 45d), not a code bug — it backfills as filings are disclosed.

## Active plan
docs/plans/0002-100-factors-and-model.md (Phase 3.3c — spine + harness + risk-adjusted NAV done; hard gate ~2027. 3.3b-3 done. 3.3d next.)
