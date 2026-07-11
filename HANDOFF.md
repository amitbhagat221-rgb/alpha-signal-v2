# HANDOFF
Updated: 2026-07-11 | Branch: master | HEAD: `8902849` study(event): buyback record-date price-move, in-house leg (plan 0013 B2)

## Left off
Ran [Plan 0013](docs/plans/0013-sonnet-tasks-event-infra-and-factors.md) (Sonnet tranche 2 —
event-study infra + in-house event factors) to completion: **6/6 tasks, 0 BLOCKED.**
`tools/event_study.py` generalizes the wired `announcement_car` CAR machinery to arbitrary
event-time windows (20/20 verify against `compute_announcement_car()`); `tools/sid_crosswalk.py`
found the crosswalk-coverage-lift hypothesis doesn't hold (`scrip_master` already backfills
`bse_announcements.sid`, so there's no separate freshness gap to close); the new
`event_calendar` table holds 112 demerger + 242 buyback events (both n≥30, in-house only). Both
B1 (demerger parent-drift) and B2 (buyback record-date move) came back **NULL per G2** — no
window clears mean CAR>0 & t≥1.5. B2's finding is the more interesting one: every window is
negative, and [-1,+1] is large AND highly significant (t=-12.2) — the buyback record-date
"entitlement premium" looks priced in ahead of time and stripped out at/right after the record
date, not paid out afterward. Full detail: [demerger-drift-2026-07.md](docs/studies/demerger-drift-2026-07.md),
[buyback-move-2026-07.md](docs/studies/buyback-move-2026-07.md), implementation notes under
Plan 0011 WS4.

## Pick up here
1. **Human gate (D7):** B1/B2 both NULL → no paper sleeve, no capital, nothing to wire. No
   action needed unless Amit wants to revisit the demerger *effective-date* framing (B1's most
   likely miss — announce-date ≠ scheme-effective-date) or split tender-vs-open-market buybacks
   before re-reading B2's drift curve — both are follow-up hypotheses, not started.
2. **§OUT items remain supervised-session-only** (do not start ad hoc): WS2.8 survivorship
   panel rewrite (`reconstruct_pit.py` intersecting `historical_universe` — blocks the
   compounder cohort study too), index-rebalance + IPO/lock-up-expiry factors (need external
   scrapes), buyback acceptance-ratio arb leg (needs PDF/Letter-of-Offer parsing).
3. **Plan 0012 (parallel session, Sonnet tranche 1) was still running at handoff time** — 9/11
   tasks landed (A1-A3, B1-B3, C1-C3), **C4 (`max_lottery_21d` build+backtest) was mid-flight**:
   uncommitted changes in `db.py`, `lineage.py`, `tools/backtest_pit.py`, `tools/reconstruct_pit.py`
   + untracked `signals/max_lottery.py` at handoff time — plan 0013 never touched these files
   (rule 9). Its own D1 close-out (checklist sync + a HANDOFF overwrite) had not run yet — check
   `git log` for whether it landed after this was written before trusting the "Watch out" section
   below as complete for 0012's scope.

## Watch out
- **New table `event_calendar`** (plan 0013 A3) — append-only, `INSERT OR IGNORE` only. Its
  DECIDED PK `(sid, event_type, announce_date)` can't dedupe buyback rows via SQLite alone
  (`announce_date` is always NULL for buybacks, and SQL treats NULL≠NULL in a UNIQUE index) —
  `tools/build_event_calendar.py` pre-filters in Python before insert so re-runs stay
  idempotent in practice. Don't rely on the raw PK for buyback dedup if writing a new populator.
- **`tools/event_study.py` is now available** for the next event-time factor (index-rebalance,
  lock-up expiry, open-offers, …) — `event_car`/`car_summary`/`drift_curve` are reusable as-is,
  no need to rebuild the CAR machinery again.
- **`tools/sid_crosswalk.scrip_cd_to_sid()` coverage lift is ~nil** (2,203 vs 2,202 raw-mapped)
  — don't expect it to meaningfully unblock a thin-sample event study; the real constraint is
  scrip_cd's absent from BSE/`scrip_master` entirely, not staleness.
- A parallel session may still be mid-flight on Plan 0012 — see Pick-up #3. Don't assume
  `db.py`/`lineage.py`/`tools/backtest_pit.py`/`tools/reconstruct_pit.py` are clean without
  checking `git status` first.

## Active plan
[docs/plans/0011-roadmap-to-90.md](docs/plans/0011-roadmap-to-90.md) is the active master plan.
Plan 0013 (this session) DONE. Plan 0012 (parallel session) near-done, see Pick-up #3.
