# HANDOFF
Updated: 2026-07-05 (PM) | Branch: master (44 unpushed) | HEAD: `ea62185` docs: bank human-task wave outcomes

## Left off
Ran the audit-driven human-task wave via 5 background agents; the big one is the `fwd_return`
anchor-proximity landmine fix + full factor-registry re-baseline on clean data ([ADR 0047](docs/decisions/0047-fwd-return-anchor-proximity-guard.md)),
which showed `pledge_quality` SMALL (5.90→1.76) was a pre-2023 contamination artifact while
`delivery_anomaly_z` SMALL strengthened (4.76→7.78) as the sole wired multiple-testing survivor.
`SIGNAL_WEIGHTS` left untouched — deflated factors kept their sign + healthy live IC, so it's a
promotion-review decision, not an auto-un-wire.

## Pick up here
1. **Financial eligibility regression (LIVE, do first)** — 27 MID Financials vanished from
   `daily_picks` post-[ADR 0045]; mark Financials INELIGIBLE for `accruals`/`piotroski` in
   `universe_eligibility` (mirror `lineage.py` sector_exclusions), fix the CLAUDE.md routing rule,
   file the "keep generic" ADR (sub-model IC t=0.73). [scoring/screener.py, lineage.py]
2. **Re-baseline promotion review** — decide weights for `pledge_quality` S (0.11), `promoter_qoq`
   S (0.19), `governance_resignation` M, `consensus` L per [rebaseline-2026-07-05.md](docs/reference/rebaseline-2026-07-05.md). [config.py SIGNAL_WEIGHTS]
3. **LARGE-tier factor build** — announcement-window CAR (BSE `Result` dates + bhavcopy); trio
   failed, LARGE hollow (consensus 1.62). [tools/reconstruct_pit.py, signals/]

## Watch out
- **Banded is now default + partial re-size** — `portfolio_weights` books ≤07-04 daily, 07-05
  AM one iter-1 book, ≥07-05 PM iter-2; don't span these in `portfolio_nav`/`portfolio_outcomes`.
  Book is net-cost marginal (+0.11 Sharpe, in-sample 61d), turnover 6.2%/day (misses <5%; next
  lever = EMA-smooth `final_score`, screener-touching).
- **`backtest_pit` doesn't bump `computed_at` on replace** — re-baselined rows show old May
  timestamps despite new values (verified via pre-snapshot CSV). Don't trust that column for age.
- Cockpit not restarted; Screener cookie keep-alive (8h) + fortnightly Screener refresh +
  monthly `backtest_pit` crons are crontab-only, invisible to git.
- `factor_decay` flags 5 wired pairs DECAYED (accruals L/M/S, book_to_price S, promoter S) —
  recent drift, separate from the re-baseline, watch-list only.

## Active plan
docs/plans/0002-100-factors-and-model.md (Phase 3.3d Barra wiring + post-re-baseline promotion review). Plan 0010 (audit remediation) DONE.
