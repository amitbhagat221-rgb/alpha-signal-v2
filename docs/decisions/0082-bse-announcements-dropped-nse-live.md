# ADR 0082 — BSE announcements route dropped; NSE is the live disclosure source; BSE table kept as history

**Status:** accepted 2026-10-19 (Amit: "drop BSE and swap with NSE", "yes add fraud/default as red flags").

## Decision
- **Feed `bse_announcements` is retired.** BSE's AnnSubCategoryGetData has answered HTTP 403 (Akamai WAF) to this server every day since 2026-10-13. The `run.sh forward` step, its canary and the table's freshness benchmark are removed; `forward` now takes `harvest_lock nse` only.
- **`bse_announcements` stays as frozen history** (2018-01-01 → 2026-10-12, 2.6 M rows): no `freq` / `stale_days` in `tables.TABLES`, so it never goes TABLE_STALE. `sources/bse_announcements.py` stays for a manual re-run if BSE lets us back in.
- **`nse_announcements` is production and T1** (it feeds the wired `announcement_car`), rows from 2026-10-09.
- **One reader for both:** `signals/announcements.py`. `sql()` is a subquery of every BSE row plus every NSE row in BSE's taxonomy (`config.NSE_BSE_EQUIVALENT`, first match wins, unmatched = NULL subcategory); an NSE row is dropped when BSE has the same sid and subcategory within 2 days. Every reader of `bse_announcements` goes through it.
- **Red flags gain `fraud` and `default`** (`config.MB_THESIS["red_flags"]`), the same rule live (`signals.multibagger.red_flag_events`) and in the backtest (`tools.mb_thesis.red_flags`).

## Why
- The governance, results and red-flag readers went blind on 2026-10-13 in the middle of the Q2 results season: `announcement_car` (wired L 0.35 / M 0.066 / S 0.22) had no new result dates.
- One mapping onto BSE's taxonomy keeps every existing filter (`RESULT_FILING_SQL`, the governance weights, the red-flag subcategories) unchanged, so no reader learns a second vocabulary.

## Mapping rules worth knowing
- NSE "Outcome of Board Meeting" whose subject says "submitted to the exchange, the financial results" → BSE category `Result` / `Financial Results`; other board outcomes → `Outcome of Board Meeting` (RESULT_FILING_SQL tests their text as before).
- A detailed NSE "Resignation" maps by the role it names (CFO, CMD, MD, CEO, Chairman, CS, director); "Cessation" → Cessation. Not mapped: the pointer row "Resignation of Director/KMP/SMP" (it would double-count), SMP and other-officer exits, "Change in Auditors" (NSE files rotations there; BSE's rare one weighs 3 in governance_resignation), "Appointment".
- Fraud: BSE files it under `General`; NSE "Fraud/Default/Arrest" and "Frauds/Default by employees" map to `General`. The kind needs "fraud" / "arrest" in the title and excludes the company as a victim (impersonation, cyber fraud, a bank reporting a borrower), clarifications and insurance recoveries.
- Default: BSE's event disclosures of loan / unlisted-debt default, or the same disclosure under `General`; the quarterly statement (often nil), "no default", "made good" and repayment intimations are excluded.

## Consequences
- Point-in-time history is unchanged: `governance_resignation`, `announcement_car`, `pead` columns are identical at 2022-06-30, 2024-12-31, 2026-09-30 and 2026-10-08. On 2026-10-19, 58 stocks' `announcement_car` changes (40 gain a reading) and 28 stocks' `governance_resignation`.
- Thesis backtest (arm B, 12 starts): top 30 excess +15.0 → +14.1 %/yr, t 2.27 → 2.21; top 10 +13.4 → +13.1 %/yr, t 1.71 → 1.60; grade C both. The new kinds remove distressed names, some of which later recovered.
- Pond names newly flagged on 2026-10-19: SERO (fraud, NSE), MTNL and ELTH (default), TIIN (fraud). None in the top 100 or the 30 candidates.
- The crontab is unchanged: BSE ran inside `run.sh forward`. The old `cron_bse_announcements` failure streak ages out of the health report within a few days.
- Credit-rating readers see NSE "Credit Rating*" rows as `Credit Rating`. The transcript GUID match (`sources/transcripts_pull`), `scrip_master`'s sid backfill and the datamodel mirror stay BSE-only by nature.
