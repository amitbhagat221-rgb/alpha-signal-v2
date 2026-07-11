# HANDOFF
Updated: 2026-07-11 (PM) | Branch: master | HEAD: `e01619f` feat(factor): max_lottery_21d + PIT helper + backtest — library (plan 0012 C4)

## Left off
Two parallel Sonnet tranches finished today. **Plan 0012** (execution-layer + factor builds,
10/10 tasks, 0 BLOCKED): `expected_return.py` gained a tax line — finding: neither operating
mode (as-operated or monthly-cadence) reaches the 1yr LTCG threshold under current turnover
assumptions, which revises the roadmap's "tax favors slower cadence" framing (true for the
compounder engine, not yet for this factor book); the 36-cell cadence/EMA sweep found no cell
clears the WS1.1 bar, but EMA halflife=10 comes close with a large net_ann improvement (+19-21%
vs today's +2.0%); `eps_revision_yoy`/`value_composite` wired zero-weight into `_load_signals`
with swap-vs-stack evidence; `residual_momentum_12_1`/`max_lottery_21d` built + backtested
(`max_lottery_21d` SMALL t=-3.47 is the strongest result of the whole batch). **Plan 0013**
(event-study infra + in-house event factors, 6/6, 0 BLOCKED — ran concurrently in a separate
session): `tools/event_study.py` generalizes the wired `announcement_car` CAR machinery for
future event-time factors; demerger/buyback drift studies both came back NULL (no sleeve, no
capital). **Cross-cutting finding (plan 0012 A3) that matters for BOTH plans' shared blocker,
WS2.8:** `historical_universe` has only 9 sparse (~annual) snapshots total, 2018-2026 — even
the "true universe" reconstruction lacks the price density to backtest delisted names at the
live panel's cadence, so fixing WS2.8 needs a full price-history backfill project (~1,381
delisted symbols), not just pointing `reconstruct_pit.py` at `historical_universe`.

## Pick up here
1. **Three human gates from Plan 0012 (decisions only, no code):**
   a. **B2 cadence sweep** — no cell clears the WS1.1 bar (≤1.5%/day, gap≤4pp, corr≥0.90);
      decide whether to widen the grid / relax the bar, or adopt EMA halflife=10 anyway for its
      net_ann improvement despite missing the strict turnover target.
   b. **C1/C2 promotion review** — `eps_revision_yoy` (p_BY=1.00, weak) and `value_composite`
      (p_BY=0.36; swap-vs-stack evidence favors it over `book_to_price` in SMALL, ρ=0.71,
      t=3.32 vs 1.88) are computed/zero-weight; decide wire/skip for each.
   c. **A1 WS1.4 verdict** — rank-IC localizes in LARGE (t=1.78) but is opposite-signed in MID
      (t=-3.40); decide whether to prototype conviction sizing (likely tier-specific if built).
2. **Plan 0013's D7 gate** — both event studies NULL; no action needed unless revisiting the
   demerger effective-date framing or the buyback tender-vs-open-market split (both unstarted
   follow-up hypotheses, not started).
3. **WS2.8 survivorship fix is a bigger lift than the roadmap assumed** (see Left off) — scope
   a price-backfill project before attempting the `historical_universe` intersection; this is
   the shared blocker for Engine 2 (compounder) cohort validation per the D12 research findings.

## Watch out
- **New crontab entry** (plan 0012 B3, crontab-only, invisible to git): monthly
  `expected_return` snapshot, 1st of month 05:00 UTC — check `crontab -l`, not `git log`.
- **`_load_signals()` now computes 2 extra zero-weight columns** (`eps_revision_yoy`,
  `value_composite`) — harmless (`SIGNAL_WEIGHTS` untouched), don't be surprised seeing them.
- **2 new `daily_snapshots_pit` columns** (`residual_momentum_12_1`, `max_lottery_21d`) added
  via additive `ALTER TABLE` — no backward-compat concern.
- **New table `event_calendar`** (plan 0013) — append-only; its PK can't dedupe buyback rows
  via SQLite alone (`tools/build_event_calendar.py` pre-filters in Python before insert). Don't
  write a new populator against the raw PK without the same guard.
- **`tools/event_study.py` is now available** for the next event-time factor (index-rebalance,
  lock-up expiry, open-offers, …) — reuse `event_car`/`car_summary`/`drift_curve` as-is.

## Active plan
[docs/plans/0011-roadmap-to-90.md](docs/plans/0011-roadmap-to-90.md) — active master plan.
Plan 0012 DONE (this entry). Plan 0013 DONE (same day, separate session).
