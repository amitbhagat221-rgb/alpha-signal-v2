# HANDOFF
Updated: 2026-06-09 | Branch: master (1 unpushed after the handoff commit) | HEAD: `ce05456` docs(crypto): convex cockpit plan 0009 + data-source map

## Left off
Built the **BSE scrip↔ISIN↔sid crosswalk** ([sources/scrip_master.py](sources/scrip_master.py)) off the Upstox instrument master — the BSE backfill **finished** (2.48M filings, 2018→present) and is now **sid-populated** (1.32M filings / 2,197 universe names, incl. **81,750 dated `Result` earnings-announcement events** across 2,179 names), so PEAD finally has real announcement dates. Also this session (all committed `3c4fa01`/`739adaf`/`ce05456`): scoped + accepted a **separate crypto convex/lottery-ticket cockpit** (plan 0009), plus earlier-today's DLM managerial-ability + financial-mgmt lens + gate-6 UHS fix + HRP prototype.

## Pick up here
1. **PEAD date-swap** — in [signals/pead.py](signals/pead.py) (~line 44) replace `ANNOUNCE_LAG_DAYS=45` (the `period_end+45d` proxy that failed to replicate) with the real `dt_tm` of the matching `bse_announcements` `category='Result'` row per (sid, quarter) → re-backtest `python -m tools.backtest_pit --signal pead`. The 81,750 dated events are ready.
2. **Wire 3 keep-current daily steps** into `run_daily_forward.sh`: `bse_announcements --days 7` → `sources.scrip_master` (re-run = refresh + sid-backfill of new rows) → register both in `config.RAW_TABLES` + freshness watchdog (the unregistered-cron silent-failure landmine).
3. **Crypto Phase 0** (when greenlit, [docs/plans/0009-crypto-convex-cockpit.md](docs/plans/0009-crypto-convex-cockpit.md)) — the validate-before-build kill-gate: right-tail base rates / ex-ante separability / can-the-top-be-called, vs buy-hold-ETH (~$0 + $79 CMC one-shot).

## Watch out
- `scrip_master` reaches **90% of universe by design** — the ~10% gap is NSE-only names (never appear in `bse_announcements`) + 22 delisted/renamed (RELINFRA/AKZOINDIA). 53% of *all* filings carry a sid (the universe generates the bulk; long-tail BSE scrips don't). Not a bug.
- Upstox master is the **live** universe → re-run `scrip_master` after each daily forward-harvest or new rows stay sid-NULL. The rohittihiro `ListOfScrips.csv` delisted supplement **404'd** (wrong branch/path) — non-fatal (adds no universe sid); fix the URL later for the survivorship tail.
- PEAD event dates: `category='Result'` (203K rows) is the clean SUE-event source; some also sit under `category='Board Meeting'` subcat `Financial Results`/`Outcome of Board Meeting` — decide which to treat as the announcement. `dt_tm` is the look-ahead-safe time.
- Crypto is a **separate product** (own repo + venv + DB) — do NOT add ccxt/web3/solana-py/sanpy to v1's shared venv.

## Active plan
- Equity: BSE event stream → PEAD/governance factors — no plan doc; rides Next-3 #1 ([ADR 0042](docs/decisions/0042-data-acquisition-build-not-buy.md)). Crosswalk done; PEAD date-swap next.
- Crypto: [docs/plans/0009-crypto-convex-cockpit.md](docs/plans/0009-crypto-convex-cockpit.md) — accepted; Phase 0 (validation kill-gate) next.
