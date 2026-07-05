# HANDOFF
Updated: 2026-07-05 (PM) | Branch: master (36 unpushed) | HEAD: `2be758b` docs: registry re-baseline diff

## Left off
Ran the full audit-driven human-task wave (5 background agents). Landed:
- **fwd_return landmine FIXED + full registry re-baseline** (`528df71`, `2be758b`, [rebaseline-2026-07-05.md](docs/reference/rebaseline-2026-07-05.md)). Anchor-proximity guard (entry+exit price within ~5 trading days of the intended date, else NULL). Pre-2023 NULL-rate 0.5%→~50% — ~40-50% of old forward returns were fabricated (`searchsorted` grabbed the first later price, sometimes years off). Re-baseline PERSISTED to `pit_ic_by_tier_v2` (verified vs pre-snapshot CSV).
- **Banded rebalancing iter-2** (`6c4b218`, `0bb91e0`, [ADR 0046](docs/decisions/0046-banded-rebalancing.md)): debounce-3 + partial re-size, net Sharpe −0.84→**+0.11**, turnover 14.6%→6.2%/day. Now the config default.
- **Batch API classifier** (`b10a6bd`): async two-phase Message Batches, pipeline step 58min→seconds, backlog 43→13d at ½ cost.
- **Screener auth fixed + full refresh** (fresh through `period_end 2026-06-30`) + 8-hourly keep-alive cron + fortnightly flock-guarded refresh cron.
- **LARGE-tier factor trio** built+backtested (low_vol/st_reversal/asset_growth) — NONE wire, all → FACTOR_LIBRARY.
- **Tickertape forecastsHistory probe** — upstream float-then-freeze defect confirmed, permanently dead for PT.

## Pick up here
1. **Re-baseline promotion review** (evidence-only so far, SIGNAL_WEIGHTS untouched): decide on the factors whose deep-history t-stats deflated but live edge holds — `pledge_quality` SMALL (5.90→1.76, left BY-FDR), `promoter_qoq` SMALL (2.62→0.47, weight 0.19!), `governance_resignation` MID (−3.82→−1.55), `consensus` LARGE (2.82→1.62). None auto-un-wired (signs preserved + healthy recent IC). Read rebaseline-2026-07-05.md.
2. **Financial routing (item c) — NOT actioned yet.** Evidence says keep generic (sub-model IC t=0.73). Still TODO: fix the MID-Financials eligibility bug (they vanished from daily_picks post-ADR-0045 — `universe_eligibility` wrongly marks Financials eligible for accruals/piotroski; mirror `lineage.py` sector_exclusions), correct the CLAUDE.md routing rule, write the ADR.
3. **LARGE-tier (item a)** — trio failed; next candidate is announcement-window CAR (earnings surprise, BSE dates + bhavcopy in-house). LARGE confirmed hollow (consensus now 1.62 dominant).
4. **Layer-2 correctness check (logged this session):** build "replicate each wired factor's t-stat a 2nd way, alarm on disagreement" — would have caught both pt_upside AND this landmine. Highest-value guardrail.
5. Morning-after: `python -m tools.health_report` after tonight's 03:30 UTC pipeline.

## Watch out
- **Cockpit NOT restarted** (per rule) — mf.py `sort="percentile"` default + banded book changes live in code, old process serves until `alpha-cockpit.service` restart.
- **Banded is now the default rebalance mode + partial re-size** — `portfolio_weights` books ≤2026-07-04 are daily, 2026-07-05 iter-1 (one book), ≥2026-07-05 PM iter-2. `portfolio_nav`/`portfolio_outcomes` comparisons must not span these regime changes. Book still net-of-cost marginal (+0.11 Sharpe, in-sample 61d).
- **`backtest_pit` does not bump `computed_at` on replace** — re-baselined rows show old May timestamps despite new values (verified correct via pre-snapshot CSV diff). Registry-age monitoring can't rely on that column.
- `run_daily_forward.sh` + crontab changes are gitignored/crontab-only (flock guards, keep-alive cron, fortnightly Screener cron, monthly backtest cron) — invisible to `git log`.
- `factor_decay` flags 5 wired pairs DECAYED (accruals L/M/S, book_to_price S, promoter S) — recent drift, separate from the re-baseline, watch-list only.
- **pt_upside re-entry** gated ~2027-05 (≥12 clean `analyst_consensus_snapshots`), [ADR 0045].

## Active plan
docs/plans/0002-100-factors-and-model.md. Plan 0010 (audit remediation) DONE. Human-task wave DONE except items (a) LARGE CAR factor, (c) financial eligibility fix, (e) MF externals.
