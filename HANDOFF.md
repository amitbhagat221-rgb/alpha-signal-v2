# HANDOFF
Updated: 2026-10-13 | Branch: master (0 unpushed; today's work UNCOMMITTED) | HEAD: 5599d9c fix(tests): news Markets test gets its own cockpit cache

## Left off
Plan 0025 ran end to end, and three changes are live in the shared tree on Amit's approval: the forensic score cut is off, MID has +5 grade-B factors (ADR 0074), and `run.sh paper_sleeve` + cron are added. The SMALL paper sleeve started 13 Oct. The doubler study (docs/studies/doubler-study-2026-10.md) found doubling is mostly beta + policy-capex themes, and a generic doubler model fails out of sample. Amit wants the quest continued with plan 0025 phase 7: theme momentum with BSE order wins, turnarounds, a mania exclusion screen.

## Pick up here
1. Ask Amit to approve the two-commit plan in docs/plans/0025-slow-core-and-fast-tactical.md ("Commit plan"). Commit by explicit file list only (Kite and plan 0017 work is uncommitted beside it), then push.
2. Build plan 0025 **7.1 policy-capex theme momentum** as a new pre-registered tool (pattern: tools/lh_slow_v3.py + tools/doubler_study.py).
   - Inputs: industry momentum, `sector_policy_pit`, order-win intensity from `bse_announcements` subcategory 'Award of Order / Receipt of Order' (9,454 filings since 2018), position_52w, plus an exit rule.
   - Judge: ADR 0073 grade across 12 starts, plus the asymmetry bar P(double) ≥ 2× base, P(halve) ≤ base, median excess ≥ 0.
   - Then 7.3 (mania exclusion); 7.2 waits for the quarterly data.
3. Background:
   - `python -m tools.winner_hunter check` (the harvest runs in the `run.sh backfill` windows); at READY run 6.1.
   - 2026-11-02: first paper-sleeve rebalance → output/paper_sleeve/latest.md.
   - Amit owes a choice: slow_v2 vs the 50/50 blend (study §9).

## Watch out
- AURUM's ×24 in labels is a special-dividend artifact (corporate_adjustments factor 0.012, 2020-12-23). Exclude or cap pure-dividend factors < 0.5 in any winner study.
- `stock_prices` now starts 2010-01-04. Delisted names (`stock_prices_unlisted`) have no corporate actions, so neutralise one-day jumps (tools/lh_price_history.py).
- Judge books on ≥ 20 names across 12 starts (CLAUDE.md). `fast_v1` is in-sample; use `fast_select`.
- The results harvest holds /tmp/alpha_signal_harvest.lock in backfill windows; the other backfill steps queue behind it.

## Active plan
docs/plans/0025-slow-core-and-fast-tactical.md (phase 7 next; 5.1 harvesting; 6.1 / 6.2 gated)
