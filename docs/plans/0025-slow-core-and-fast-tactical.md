# Plan 0025 — Two scores, two books: a slow core and a fast SMALL tactical book

Status: **active** (proposed and executed 2026-10-13; phases 1-4 done, 5.2 done, 5.1 harvesting, 6.1 gated on data; live changes merged 2026-10-13 on Amit's approval). Owner: Amit. Read-only research until Amit approves a verdict: no change to live weights, picks, the book, schema or cron.

## Why
Plan 0024, the winners post-mortem and research 0007 ([unified summary](../research/0007-long-horizon-unified.html)) agree on three points:
- The best slow book (+18.3 %/yr over the Smallcap 250, t 1.81) is not yet distinguishable from luck.
- The slow score under-weights momentum and lets fast signals make ranks flip.
- The −0.2 Beneish penalty punishes fast growers.

Amit 2026-10-13: *"while we work on finding slow scores keep fast score as well dont delete, we might create a tactical portfolio of small only that uses fast scores."*

So the work splits into **two scores and two books**. Neither replaces the other.

| | Slow core | Fast tactical |
|---|---|---|
| Score | new `slow_v2` (separate, research-only) | **today's live weights, unchanged** (`factors.SIGNAL_WEIGHTS`) |
| Tiers | SMALL, MID (LARGE = index) | SMALL only |
| Holding | 6–12 months, monthly review | weeks to ~3 months |
| Signals | momentum, value × quality, Piotroski | delivery anomaly z, announcement CAR, delivery %, sector tilt, residual momentum, Piotroski |
| Tax | mostly long-term (12.5 %) | mostly short-term (20 %): must clear it |

## Ground rules
1. **The fast score is preserved.** Live weights, `factors.FACTORS`, `pit.features_at`, the screener and `daily_picks` are not edited by this plan. `slow_v2` is a new research score in `tools/`, written to `data/lh/`, and never to the DB.
2. Every test pre-registers its features, rule and pass bar in the tool's docstring before it runs.
3. Headline t comes from non-overlapping subsamples (or the Britten-Jones–Neuberger–Nolte regression), never a Newey-West t on overlapping labels. Any best-of-many choice is judged with the deflated Sharpe ratio (DSR) and the probability of backtest overfitting (PBO).
4. Read-only DB (`file:…?mode=ro`); one long writer at a time; pick-changing work only on a worktree branch, after approval.

## To-do

### Phase 1 — this week: is anything there? (read-only)
- [x] **1.1 Luck tests on the 48 plan-0024 variants** (`tools/lh_luck.py`, new).
  - Input: `data/lh/book_monthly.parquet`.
  - DSR: effective N from the average correlation of the variants' monthly excess returns; skew and kurtosis of the chosen variant; effective T.
  - PBO: CSCV with S = 8 blocks.
  - Per tier, also the `slow_icw` grid.
  - Done when: DSR and PBO per tier are in `docs/studies/long-horizon-2026-10.md` (new section). ~1 day.
  - **Result 2026-10-13:** no tier passes. SMALL DSR(N_eff 13.3) 0.93, PBO 0.47, but the in-sample best beats the index out of sample in 90 % of splits and the median rule earns +8.5 %/yr → the edge, if any, is in the score, not the rule choice. MID: DSR 0.68, PBO 0.61. LARGE: DSR 0.78, PBO 0.39.
- [x] **1.2 Freeze the fast score as a named baseline** (docs only, no code change).
  - Record today's `SIGNAL_WEIGHTS` per tier, with the date and git hash, in this plan's notes as `fast_v1`.
  - Done when the snapshot is written below. 15 min.
- [x] **1.3 Pre-register `slow_v2`** in `tools/lh_slow_v2.py` (docstring first, then code).
  - Equal-weight within-tier percentile composite, so there is no fitted weight to overfit: `mom_6m` + `x_quality_value` (ROCE & book-to-price, from `tools/lh_growth.py`) + Piotroski.
  - Piotroski is the lite version back to 2019 and `piotroski_f` once it exists.
  - No delivery or event signals. LARGE is reported but not used.
  - Done when the docstring is committed before any result. ~½ day.

### Phase 2 — weeks 1–2: the slow core
- [x] **2.1 `slow_v2` horizon test.** IC at 63 / 126 / 252 by tier, with non-overlap t, top-decile excess vs tier median, sign by period (2020-22 / 2023-24 / 2025-26) and correlation with plan 0024's `slow_select`.
  - Bar: SMALL or MID non-overlap t ≥ 2.0 at 126 with the sign held in every period. ~1 day.
- [x] **2.2 Book on `slow_v2`** (reuse `tools/lh_book.py` with a new score source).
  - (a) The single pre-registered template: monthly · top 10 · sell below 30 · 3-month average · 12-month hold · tax deferral.
  - (b) The full 48 grid, for 1.1-style DSR / PBO.
  - Bar: (a) excess after costs and tax with non-overlap t ≥ 2.0, and DSR ≥ 0.95 on (b) with PBO ≤ 0.2.
  - Done when the verdict is in a new study `docs/studies/slow-v2-2026-10.md`. ~2–3 days.
- [x] **2.3 Forensic penalty re-test** (`tools/lh_forensic.py`, new).
  - Rebuild Beneish M and Altman Z from annual Screener 2016+ (150-day lag).
  - Flags vs fwd 63 / 126 / 252 within tier: median excess, beat-median rate, top-5 % / bottom-5 % rates, and the share of the top revenue-growth quintile flagged.
  - Done when there is a recommendation (keep / resize / review-flag) per flag and tier. ~2 days.
- [x] **2.5 slow_v3, momentum-centred** (2026-10-13 verdict: keep slow_v2. slow_v3 earns more — 2019+ SMALL +11.6 % vs +9.3 %, MID +8.4 % vs +5.7 % — but its 15-year small-proxy worst 12 months is −35 % (2015 momentum crash) against the −15 % bar; study §8) (Amit 2026-10-13 "yes go ahead"; `tools/lh_slow_v3.py`, pre-registered). 52-week position + 6-month + 12-month momentum (+ quality×value variant). Test 1: 15-year full-market book across 12 starts. Test 2: 2019+ against slow_v2. It replaces slow_v2 in the paper sleeve only if both pass.
- [x] **2.6 50/50 slow_v2 + slow_v3 blend** (2026-10-13 verdict: keep slow_v2. The blend beats slow_v2 in window A (SMALL +9.6 % vs +9.3 %, t 2.00, worst −13.2 %) but fails window B's −15 % bar (−21.3 %). slow_v2 itself scores −23.5 % there, so every option fails the Covid-era crash test.) (Amit 2026-10-13; `tools/lh_blend_v23.py`, pre-registered). Window A: starts 2022-06 … 2023-05, must beat slow_v2. Window B: starts 2019-12 … 2020-11, the crash test (≥ 10/12 starts, t ≥ 1.5, worst 12 months ≥ −15 %).
- [x] **2.4 Accruals re-test** (MID live weight −0.10). Long-history `cf_accruals` from Screener (NI − CFO) / assets, at 63 / 126 / 252, non-overlap t. Indian literature says the anomaly runs the wrong way. ~½ day.

### Phase 3 — weeks 1–3, in parallel: the fast SMALL tactical book
- [x] **3.1 Re-run names-per-tier SMALL at measured costs** (the existing follow-up).
  - `tools/names_per_tier.py` at 30.5 bps one-way instead of 150, plus 20 % STCG on gains (today it is pre-tax).
  - Plan 0025's question: does `fast_v1` SMALL top 10–20 earn after real costs **and** short-term tax?
  - ~1 day.
- [x] **3.2 Tactical book grid** (`tools/tactical_book.py`, new; ≤ 24 variants, pre-registered).
  - Review weekly or monthly; buy top N = 10 / 20; sell below 2N / 3N; minimum hold 0 / 1 month.
  - `fast_v1` scores, SMALL only, the same cost model and tax engine as `lh_book`.
  - Bar: net-of-cost-and-tax excess vs Smallcap 250 with non-overlap t ≥ 2.0, DSR ≥ 0.95, PBO ≤ 0.2, one-way turnover reported.
  - Done when there is a verdict in `docs/studies/tactical-small-2026-10.md`. ~3 days.
- [x] **3.3 Overlap check.** How often `fast_v1` and `slow_v2` hold the same SMALL names, and the correlation of the two books' monthly excess. Two books are only worth running if they differ. ~½ day.

### Phase 4 — weeks 3–5: thesis monitors (feed both books)
- [x] **4.1 Event studies on our own data** (`tools/event_study.py`, BSE 2018+ incl. delisted).
  - Events: directional rating downgrades, auditor resignations, CFO/KMP resignations, promoter block/bulk sells, pledge % rising (shareholding), and GSM/ASM entry once a list history is sourced.
  - For each: CAR at 63 / 126 within tier, false-alarm rate (share that beat the tier median), n.
  - Done when there is a monitor catalogue with India evidence. ~1–2 weeks.
- [~] **4.2 Review-not-sell replay** (not run 2026-10-13: 4.1 found no event above noise, so the replay would measure noise; reopen after 5.2 adds delisted names) on the slow template book and the tactical book. An alert opens a review; exit only if the score is also outside the hold band. Measure extra turnover and the return delta. ~1 week.

### Phase 5 — weeks 5–10: more history
- [~] **5.1 Quarterly results 2018+.** (2026-10-13: `sources/nse_results.py` built, feed `nse_results_xbrl` → probation, canary PASS, table `quarterly_results_nse`; universe harvest 2017-04 → 2024-12 queued behind the harvest lock, resumable via output/nse_results_done.txt)
  - Sourcing probe of BSE/NSE XBRL results, canary on 3 stocks first, then a `feeds.FEEDS` candidate entry (data-playbook first).
  - Then re-test `q_margin_chg`, `q_rev_accel` and `q_profit_accel` on 6+ years.
  - ~2–3 weeks.
- [x] **5.2 Price signals to the 1990s** (DONE to 2010 on 2026-10-13: T3 pos_52w t 6.33 / mom_6m 6.04 over 183 anchors incl. delisted, 4/4 periods; survivorship understated them; warnings still noise ex-ante — study §7) (2026-10-13: corporate actions from 2010 + legacy bhavcopy 2010-01 → 2018-02 running, `sources.nse --legacy`; Amit: concurrent with the Kite backfill is fine) from legacy bhavcopy incl. delisted names (`survivorship_universe_via_bhavcopy`): momentum, low vol, 52-week position; more independent windows, survivorship-free. ~2–3 weeks.

**Phases 1–3 results (2026-10-13): [study](../studies/slow-core-tactical-2026-10.md).**
- Slow core fails in every tier; `slow_v2` did not beat `slow_select` in the book.
- Fast SMALL tactical (walk-forward `fast_select`): +12.2 %/yr after costs and tax. Passes DSR (0.955) and PBO (0.10) but not t (1.64).
- Forensic cuts fail their test → review flags.
- Accruals: high accruals lag, most in SMALL.
- 4.1 thesis monitors: no event above noise (false alarms 44–57 %); 4.2 not run.
- Phase 5 needs new harvesters, which must wait until the Kite minute-bar backfill finishes (one harvester at a time).

### Phase 6 — a winner hunter (Amit 2026-10-13: "can our new model find stocks like netweb sswl?" → "yes please")
Every score catches the top-5 % six-month SMALL winners at about chance (slow_v2 top 20: 6.4 % vs 5 %).
`slow_v2` bought TIMETECHNO (rank 10, Jan 2024); SSWL reached only the top 4–10 %; Netweb was never in a top 400.
- [ ] **6.1 Winner-hunter test** (`tools/winner_hunter.py`, pre-registered 2026-10-13 in its docstring).
  - **Score:** equal-weight percentiles of 6-month momentum, 52-week position, quarterly core-profit acceleration, latest-quarter revenue growth and core-margin change. No value or quality component.
  - **Gate:** revenue growth > 0 and momentum > 0. ₹1 cr liquidity floor; trusts and Financials excluded.
  - **T1 (purpose):** top-20 hit rate ≥ 10 % (2× chance) with non-overlap t ≥ 2.
  - **T2:** the book across 12 starts, graded by ADR 0073.
  - **Decision:** T1 + B → a small hunter sleeve; T1 only → watchlist; neither → no hunter.
  - **Gated:** `python -m tools.winner_hunter check` must say READY: ≥ 70 % of SMALL+MID with ≥ 8 quarters 2017-04 → 2022-12 in `quarterly_results_nse` (task 5.1 harvest).

- [ ] **6.2 New listings** (Amit 2026-10-13, after ATHERENERG: Ather was invisible for its first 12 months; 13 % of the 529 missed doublers in [missed-winners-2019-2025.md](../studies/missed-winners-2019-2025.md) were new listings). Pre-registered spec, tool not written yet:
  - **Universe:** stocks listed < 12 months at the anchor (first price in `stock_prices`, 2010+), SMALL + MID, ₹1 cr floor.
  - **Score:** equal weight of the return since the first close after listing day 5 (skips the listing pop), position vs the high since listing, latest-quarter revenue growth (`quarterly_income` / `quarterly_results_nse`), and the sector's 6-month momentum.
  - **Tests:** (a) rank IC within the new-listing set at 63 / 126 sessions, non-overlap t; (b) a book: top 10 new listings, monthly, hold until month 12, then hand over to the normal tier rank. Judged across 12 starts vs the tier index, graded by ADR 0073.
  - **Decision:** grade B → the live model stops scoring missing momentum as 0.5 for stocks under 12 months and uses this score instead; else no change.
  - **Data:** 2010+ listings from the legacy bhavcopy; delisted IPOs included through `stock_prices_unlisted`.

### Phase 7 — asymmetric sleeves (Amit 2026-10-13, after the doubler study: [doubler-study-2026-10.md](../studies/doubler-study-2026-10.md))
- **Generic doubler model rejected:** logistic, test 2023-25, SMALL top-20 median excess +0.3 % vs the live model's +8.1 %.
- **Three targeted tests**, each pre-registered in its tool's docstring before running. Each is judged by the ADR 0073 grade plus an asymmetry bar: top-20 P(double) ≥ 2× base, P(halve) ≤ base, median excess ≥ 0.
- [x] **7.1 Policy-capex theme momentum** (2026-10-13, `tools/theme_momentum.py`, [study](../studies/asymmetric-sleeves-2026-10.md)). SMALL book grade **B** (+25.5 %/yr after costs + tax, t 2.82, 12/12 starts ≥ +22.5 %, worst 12 months −9.9 %), but the asymmetry bar fails by a hair (P(double) 1.99× base vs 2.0×; halve 1.6 % vs 2.5 %, median +18.7 %) → not a sleeve candidate by the letter; the pre-registration did not cover "B without asymmetry" → **D5**. Post-hoc: order-win intensity is the engine (without it +10.1 %); the gate adds nothing. MID: C.
  - Inputs: industry momentum, sector policy score (`sector_policy_pit`, 2020+), order-win intensity (BSE "Award of Order / Receipt of Order" filings in the last 6 months, 2018+), position in the 52-week range.
  - Exit when industry momentum or the stock's 52-week position breaks.
- [ ] **7.2 Turnarounds** (needs `quarterly_results_nse`).
  - Inputs: debt / assets falling two years running, latest-quarter profit turning positive or interest coverage crossing 1.5, a credible acquirer (BSE "Open Offer" / "Acquisition").
  - Price confirmation: 3-month momentum > 0.
- [x] **7.3 Mania exclusion screen** (2026-10-13, `tools/mania_screen.py`): **fails, no screen.** Penny / forensic momentum names halve 1.6–1.8× more often with lower medians but HIGHER means (+34–37 % vs +21 %): two-sided lotteries, an avoid list would cut the winners.
  - Flags: price momentum with no fundamental change (revenue and profit growth ≤ 0), penny / low float, a preferential-warrant issue in the last 12 months (BSE "Preferential Issue"), forensic flags.
  - Test: do excluded names halve more often and earn a lower median?

### Decisions for Amit (after phases 2–3)
- [ ] **D1** Slow core: if 2.2 passes → ADR + a worktree build of the monthly slow book; if not → SMALL/MID stay the index.
- [ ] **D2** Tactical SMALL: if 3.2 passes → ADR + paper-trade sizing; if not → keep `fast_v1` as the screen only.
- [ ] **D3** Capital split, only if D1 or D2 pass. Example shape: index core + slow satellite + small tactical sleeve.
- [ ] **D5** Theme book (7.1): paper-only forward test beside the SMALL sleeve, or nothing. Weigh: idea in-sample; order filings ~5× after 2023; mostly short-term gains; a new pre-registration would be needed for the ungated variant.
- [x] **D4 (merged live 2026-10-13, Amit: "approved")** Forensic score cut off (review flags); MID grade-B factors at half weight (ADR 0074); monthly `run.sh paper_sleeve` job + cron (2nd, 06:40 UTC). Cockpit caches cleared and both services restarted. Original item: Forensic penalty and accruals weight changes from 2.3 / 2.4 (these change live picks → worktree).

## Notes
- `fast_v1` snapshot (task 1.2), taken 2026-10-13 from `factors.SIGNAL_WEIGHTS` (HEAD 5599d9c, with `factors.py` carrying uncommitted edits, including the ADR 0071 `cons_beat_rate_4q` wiring):
  - SMALL: delivery_anomaly_z +0.24 · announcement_car +0.22 · piotroski +0.14 · residual_momentum_12_1 +0.14 · sector_tilt +0.14 · avg_delivery_pct_30d +0.12
  - MID: iv_skew_25d +0.20 · residual_momentum_12_1 +0.17 · cons_beat_rate_4q +0.15 · piotroski +0.15 · consensus +0.14 · accruals −0.10 · announcement_car +0.09
  - LARGE: announcement_car +0.35 · iv_skew_25d +0.25 · asset_growth_yoy −0.20 · forward_looking_intensity +0.20
  - Plus the forensic penalty (Beneish LIKELY −0.20 / POSSIBLE −0.10; Altman DISTRESS −0.20 / GREY −0.10), applied after the weighted score.

## Commit plan (approved and committed 2026-10-13, second session)
Executed as below, with five additions the staged-tree test run forced: `pit.py` whole (all its hunks are ADR 0071's `pit_cons_beat_rate_4q`); `feeds.py` without the plan 0017 `external_anchors` hunk; the `cons_beat_rate_4q` column in `schema.sql`; `quarterly_results_nse` kept as-is in `datamodel/reconcile.RETIRED`; the `paper_sleeve` line in `ops/crontab.txt`; and `signals/consensus_beat.py` no longer imports `db` (invariant 1; its CLI loads through `pit.load_raw`).
The working tree also carries uncommitted work from earlier sessions and from a parallel Kite session, so commit by explicit file list (never `git add .` / `-A`). Two commits.

**Commit 1, `feat(model): ADR 0071 MID consensus-beat wiring + plan 0024 long-horizon tools`** (the backlog plan 0025 builds on):
- `signals/consensus_beat.py`
- `docs/decisions/0071-consensus-beat-rate-wired-mid.md`
- `docs/plans/0024-long-horizon-model.md`
- `docs/studies/{long-horizon-2026-10.md, long-horizon-2026-10/, names-per-tier-2026-10.md, nonlinear-benchmark-2026-10.md, large-reaudit-2026-10-10.md}`
- `tools/{lh_book, lh_labels, lh_costs, lh_horizon, lh_slow_model, lh_verify_rederive, names_per_tier, nonlinear_benchmark, large_reaudit}.py`

**Commit 2, `feat(plan-0025): slow core + fast SMALL tactical; forensic cut off; MID grade-B factors (ADR 0074); paper sleeve; NSE results XBRL; 2010 price history; doubler study`:**
- **Code, mixed files staged whole** (they also carry ADR 0071's wiring): `factors.py`, `config.py`, `scoring/screener.py`, `alpha_mcp/research.py`, `run.sh`, `feeds.py`, `sources/canaries.py`, `tests/test_wired_factors.py`
- **New code:** `sources/nse_results.py`
- **New tools:** `tools/{lh_growth, lh_luck, lh_slow_v2, lh_slow_v3, lh_blend_v23, lh_tier_slow, lh_timing_luck, lh_fast2slow, lh_forensic, lh_relax_test, lh_liquidity_floor, lh_price_history, mid_reweight_0074, monitor_events, monitor_events_full, tactical_book, paper_sleeve, winner_hunter, missed_winners, doubler_study}.py`
- **`schema.sql` and `tables.py`:** stage ONLY the `quarterly_results_nse` additions; their other hunks are plan 0017 table retirements. Use HEAD + the new block via `git hash-object -w` / `git update-index --cacheinfo`.
- **Docs:**
  - decisions: `docs/decisions/{0073, 0074}-*.md`, `docs/decisions/README.md`
  - plans: `docs/plans/0025-*.md`, `docs/plans/0000-checklist.md`
  - research: `docs/research/0007-*` (prompt, findings, explainer.html, unified.html)
  - studies: `docs/studies/{slow-core-tactical-2026-10.md, winners-postmortem-2026-10.{md,html}, missed-winners-2019-2025.{md,csv}, doubler-study-2026-10.md, doubler-drivers-top40.md}`
  - reference: `docs/reference/signal-weights.md`
  - root: `HANDOFF.md`, `CLAUDE.md`

**Leave uncommitted (other work):**
- the Kite session: `sources/kite_bars.py`, `tests/test_kite_bars.py`
- plan 0017: `pit.py`, `db.py`, `datamodel/*`, `docs/plans/0017-*`, `tests/test_datamodel.py`, plus the schema / tables retirements
- cockpit / book / other sessions: `cockpit/*`, `tests/test_book_methods.py`, `tests/test_checks.py`, `tools/expected_return.py`, `backup_db.sh`
- not code: research 0006, `tools/session_classify*`, `anc.js`, `.archify/`, `output/*`

Then `git push origin master`.
