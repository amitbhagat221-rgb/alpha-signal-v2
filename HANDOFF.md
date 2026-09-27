# HANDOFF
Updated: 2026-09-27 | Branch: master (113 unpushed) | HEAD: d400a20 chore: retire run_pipeline.sh/run_tickertape_monthly.sh (run.sh jobs)

## Left off
Plan 0015 (ADR 0052) is fully shipped. Master is deployed, the cockpit services were restarted at about 09:47 UTC, and the crontab now calls `run.sh <job>` (the old crontab and wrapper scripts are in `backups/plan15-deploy/`). The full offline pipeline gate, old code against new on identical DB copies, differed only as intended: the PSP/PST close range and trading-day email returns. The next 03:30 UTC run is the first production run of the derived order, the host door, post-step checks and `pit.features_at`.

## Pick up here
1. Check the 2026-09-28 run:
   - `tail -200 output/pipeline.log`: look for "Running the DERIVED order" and any `[GRAPH] … undeclared` or `post-check:` lines.
   - `output/graph_shadow/2026-09-28_undeclared.json` must be `{}`. Otherwise add the table to that step's `reads` in `config.py`.
2. Decide the MICRO fix. `stocks.market_cap_cr` is in rupees, never refreshed, and NULL for 726 stocks, so `tools/classify_micro_tier.py`'s "< ₹500 Cr" rule only fires on NULLs. Using `scoring/segment.py`'s crore cap instead would move 54 stocks SMALL→MICRO and 47 MICRO→SMALL.
3. Run `/architecture-review` (`.claude/commands/architecture-review.md`), then take the next work from its ranked list. Also re-extract the Screener `sessionid` into `~/.cache/screener_cookie.json`: it has been dead since about August (see `output/screener_keepalive.log`).

## Watch out
- The first `segment_tiers` run is 2026-10-01 (monthly). It re-tiers 24 stocks (±10% hysteresis) before the screener, so LARGE/MID/SMALL picks shift that day by design.
- The first Sunday `refresh_pit_panel` step on prod takes about 35 min after the email. The 15:00 watchdog may heal it sooner, since the panel shows as OUTDATED at 88 days.
- A step whose declared output stays OUTDATED is now logged FAILED and is not retried (`pipeline._post_check`). `signal_insider`, `news_brief` and `compute_sector_dossiers` already fail this way while LLM credits are empty; `fetch_broker_recos` can too.
- Flip `config.PIPELINE["derived_order"] = False` to fall back to the list order instantly.
- `sources/news_classifier.py` still hard-codes its model id, because another session has uncommitted edits in that file. The value matches `hosts.HOSTS` (tested).

## Active plan
docs/plans/0015-first-principles-architecture.md (implemented; follow-ups above). Master plan: docs/plans/0011-roadmap-to-90.md
