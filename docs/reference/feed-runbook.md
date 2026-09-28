# Feed runbook

How to run, read and fix the data supply ([plan 0018](../plans/0018-data-supply-strategy.md)). The registry is `feeds.py`, the live view is the ops **Data Supply** page (`:3001/feeds`), and the verdicts also reach the 04:00 UTC health email.

## Daily loop (automatic)
| UTC | What | Where it lands |
|---|---|---|
| 02:45 | `run.sh canary`: a 1-item live probe per feed (T1 daily, T2 on Sundays), under the harvest lock | `feed_checks` table, `data/raw/<canary>/` |
| 03:30 | morning pipeline | `pipeline_log`, data tables |
| 04:00 | health report: feed verdicts next to pipeline and freshness | email, push, `/catchup` |

## Reading a verdict
Every non-PASS canary carries a **symptom class**. Start from the class, then the feed's history on the page (Feeds tab → click the row → gates, shape fingerprint, last error).

| Class | Means | First response |
|---|---|---|
| **A Blocked** | 403, connection reset, or an HTML page where data was expected | Check Referer and cookie warm-up, then `impersonate` in `hosts.py`. Never bypass a captcha or auth. |
| **B Moved** | 404, or 200-but-empty, or a row-count cliff | Look for the new endpoint: wrapper changelogs (nselib, NseIndiaApi, jugaad), exchange circulars, the `daily-reports` manifest. Probe the candidates. |
| **C Auth expired** | login page / 401 | Run the feed's re-login path (Screener: `python -m sources.screener_pull --login`). |
| **D Shape drift** | fields removed (FAIL) or added (WARN) vs the accepted baseline | See the procedure below. |
| **E Partial / zero** | rows below the floor, or a timeout | Holiday? Retry once. If it persists, use the next route. |
| **F Semantic drift** | plausible values that mean something else | Cross-check a second source; pull the field; audit PIT. |
| **G Quota / billing** | 429, "credit balance too low" | Wait within the host budget or switch executor. Never raise the request rate. |
| **H Orphan** | a live feed nothing schedules | Add a step or a `run.sh` job (the test blocks new ones). |

**Severity** follows the tier:
- **T1** pages CRITICAL immediately on D or C, and on the 2nd consecutive failure of any other class. A first transport blip is WARN.
- **T2** is always WARN.

## Procedures
**Shape drift (D).**
1. Compare `data/raw/<canary>/last_good.*.gz` with the newest `fail_*.gz`, and read the gate detail on the page.
2. Fix the parser in the feed module. The canary in `sources/canaries.py` uses the same constants.
3. Add the failing response as a test fixture.
4. Smoke test on 3 items.
5. Accept the new shape: `python -m tools.canary --accept <canary>`.
6. Add an `INCIDENTS` line in `feeds.py`.

**Run canaries by hand.** Always hold the lock, and never run two harvesters at once.
```bash
flock -n /tmp/alpha_signal_harvest.lock python -m tools.canary --feed nse_bhavcopy   # one feed
flock -n /tmp/alpha_signal_harvest.lock python -m tools.canary --tier T1             # all critical
python -m tools.canary --list                                                         # canaries + baselines
```

**Add a feed**, in this order:
1. Add a `FEEDS` entry with `status="candidate"` and the probe evidence.
2. Add a canary function to `sources/canaries.py`, and run it on 3 items.
3. Build the ingestor, schedule it (step or `run.sh` job), and set `status="probation"`.
4. After 10 green runs, set `status="production"`. The tier is derived automatically.

`tests/test_feeds.py` fails if any of these is missing:
- a module, source step or RAW table without a feed
- a production feed without a schedule
- a T1 feed without a fallback or serve-stale limit, or without a canary

**Close an incident.** Append `(date, feed, class, symptom, cause, fix, ref)` to `feeds.INCIDENTS`. It shows on the page's Known issues tab, and it is what the DQ agent reads first.

## Run log: where exactly did it fail?
Every step, cron job and manual `python -m sources.x` run has a `run_id`, and its events are in `run_events`.
```bash
python -m runlog runs --feed bse_announcements            # recent runs: status, errors, warnings, rows
python -m runlog events --feed bse_announcements --level ERROR --since 24h
python -m runlog events --run '<run_id>'                   # the whole run, in order
python -m runlog bundle bse_announcements                  # incident bundle (add --json for agents)
```
Each failure event carries:
- the **symptom class**
- **`location`**: the exact `file:line in function` where it broke (library frames skipped)
- **`detail.origin`**: the line in the feed's own module
- traceback frames
- for HTTP failures, the redacted status, URL and response snippet

`run_end` holds per-host request/status counts, retries, rows written per table, and the last lines the run printed.

The same data is available over HTTP from the ops app:
- `/api/feeds/<feed>/incident`
- `/api/runs?feed=`
- `/api/run-events?feed=&level=ERROR&since=24h`

This is what an outside agent (MCP, plan 0016) reads.

**Writing a new harvester:**
- Use `_http.run_harvester` and the door. Item errors, request failures and write counts are then logged automatically.
- With a custom loop, call `runlog.item_error(label, item, exc)` in the `except`, or `runlog.item_failed(label, item, message, symptom)` when an item fails without an exception.

## Raw landing zone
`data/raw/<canary>/` holds:
- `baseline.json`: the accepted shape
- `last_good.<ext>.gz`
- `fail_<timestamp>.<ext>.gz`

It keeps 30 days of failures under a 2 GB cap (plan 0018 D3). The last good response and the baseline are never pruned.

## Open items (2026-09-28)
- **transcripts: orphan (H).** It has no step or cron since 2026-06-07. Schedule it weekly.
- **scrip_master: dead fallback (B).** The ListOfScrips GitHub mirror returns 404; the Upstox primary is healthy.
- **15 of 17 T1 feeds are single-source** and serve stale data if the source dies. P3 builds the top 3 fallbacks: prices (full universe), Tickertape fundamentals, shareholding.
