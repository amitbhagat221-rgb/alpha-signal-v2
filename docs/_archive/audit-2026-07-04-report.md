# Full-System Audit Report — 2026-07-04

Executed per [audit-prompt.md](audit-prompt.md) by 5 parallel independent auditors (read-only:
no DB writes, no external APIs, no file changes). Every finding below was grounded in a query
or file:line run on 2026-07-04 against `data/alpha_signal.db` (7.1 GB). Scores use the shared
rubric: 90–100 institutional-grade · 75–89 solid · 60–74 functional but material risks ·
40–59 significant weaknesses · <40 unreliable.

## Scorecard

| # | Dimension | Score | Band |
|---|---|---|---|
| 1 | Data adequacy, health & engineering | **66** | Functional, material risks |
| 2 | Model efficiency | **68** | Functional, material risks |
| 3 | Factor model | **54** | Significant weaknesses |
| 4 | Portfolio construction & results | **62** | Functional, material risks |
| 5 | Mutual-fund model | **46** | Significant weaknesses |
| | **FINAL (weighted)** | **58** | — |

Weighting: Data 25% · Factor 25% · Portfolio 20% · Efficiency 15% · MF 15% → 59.5,
minus ~2 for cross-dimension compounding (the pt_upside look-ahead contaminates the risk
decomposition, the SIGNAL_WEIGHTS derivation, and the sized book simultaneously) → **58**.

---

## THE headline finding (CRITICAL, resolves the "re-verify 2026-08" question — negatively)

**`pt_upside`'s backtest is look-ahead-contaminated.** The Tickertape `forecast_history`
metric='price' rows dated Dec-Y embed the **realized price at Dec-Y+1** — not a PT, not even
the current close. Reproduced evidence chain:
- `V(2024-12-27) / close(2025-12-29)`: median 1.007, 98.2% of 1,360 names within 10%. It is
  the year-ahead close (vs Dec-2024 close: median ratio 0.83).
- Per-anchor SMALL ICs ramp within each calendar year exactly as a shrinking-horizon
  future-price signal must: 0.27 (Jan-2025) → 0.85 (Dec-2025), then collapse to −0.04/−0.16
  when the stale row rolls (Jan–Mar 2026).
- The single anchor using genuine `analyst_consensus_snapshots` data (2026-05-01): **IC = 0.0009**.
- `rank corr(V24/close24, fwd 12m return) = 0.96`; placebo with year-older row = 0.14.

The t=7–9 that anchors the top weight in ALL THREE tiers (0.25/0.24/0.15) is an artifact of
future information. The 2026-05-23 cleanup caught the sibling (`pt_revision`) but left
`pit_pt_upside` (reconstruct_pit.py:1062) consuming metric='price'. The 3.3d risk decomp
already showed the SMALL book is a +3.10z levered bet on this factor. Honest current estimate
of pt_upside's true edge: ~zero. **Fix now, not 2026-08:** quarantine fh-price from
pit_pt_upside, rebuild the PIT column from snapshots only, re-run backtest + multiple_testing,
re-derive weights.

---

## 1. Data adequacy, health & engineering — 66/100

Top findings:
- **F1 HIGH — Survivorship-biased backtest panel.** `reconstruct_pit.py:2794` seeds every
  eval date from the CURRENT `stocks` table; `historical_universe` (1,381 non-current symbols,
  built for the multibagger study) is never referenced. All `pit_ic_by_tier_v2` t-stats are
  survivors-only; distress-loading factors (pledge_quality, governance, SMALL value) have the
  downside tail amputated.
- **F2 HIGH — `fundamentals_screener` 55 days stale, auth broken since 2026-07-01, and
  invisible to every alarm** (not in RAW_TABLES/PIPELINE_STEPS as a table → freshness N/A →
  never surfaced). ~25 daily signal steps recompute off frozen inputs and stamp fresh
  snapshot_dates. The exact "hides for a month" failure class — 55 days on the clock.
- **F3 HIGH — pt_upside PIT inputs** (see headline; independently flagged by this auditor too).
- **F4 MED-HIGH — Freshness date-column blind spots**: `as_of_date`/`brief_date`/`change_date`
  not in DATE_COLS (db.py:1047) → mf_metrics, mf_holdings, news_briefs, daily_changes
  permanently unalarmed despite registered cadences.
- **F5 MED — Alarm fatigue live**: `uhs_calibration_log` CRITICAL + URGENT email daily for
  ~a month, ignored; the table is also still in EXPECTED_EMPTY_TABLES with 11,718 rows.
- **F6 MED — email_sender swallows all send failures** and returns success (violates the
  producers-must-raise rule; the exact HALC failure shape).
- Also: PIT panel forward-extension is manual and ragged (latest anchor: 0/2448 non-NULL for
  most factors); no flock on harvesters; 90 future-dated MF NAV rows.

Verified clean: secrets, cron `cd` hygiene, upsert column-safety, forecast_history ≤90d
filter, backups (VACUUM→integrity→gzip→rclone), the watchdog catching real incidents.

## 2. Model efficiency — 68/100

- Daily pipeline 1h47m for 72 steps; **~80% is two steps** (classify_regulatory 54% — feeds
  only narrative, zero weighted alpha; fetch_yf_analyst 26% — refetches the 96%-no-coverage
  SMALL tier daily). The alpha path (signals→screener→picks→dossier→email) is ~4 minutes.
- **F1 HIGH — Duplicate monthly Tickertape scrape**: `fetch_analyst` + `fetch_forecast` both
  call the same function; pipeline.py has no dedup (config comment claims it does). Proven in
  pipeline_log: 6,964s + 6,777s on 2026-07-01. Violates the no-double-harvest rule from inside
  the orchestrator.
- **F2 HIGH — classify_regulatory**: sequential per-item LLM loop, permanently saturated
  (6.5K backlog, drains ~46 more days), no content dedup (same story classified 3×), no Batch
  API, cost model assumed 20% Haiku-pass — actual 75%.
- **F4 MED — 18 `*_scores` tables computed daily from ANNUAL data with zero consumers**
  (~1.2M rows; roic_scores appends 1,502 identical rows/day).
- **F5 MED — weight registry stale**: `pit_ic_by_tier_v2` refreshed only by hand (6 anchors
  behind); no scheduled backtest run; uneven anchor windows across factors.
- **Reproducibility: PASS** — pt_upside t reproduced read-only (8.02/9.54/9.93 fresh vs
  7.15/8.40/9.14 stored; delta = 6 accrued anchors). The old "t=16" is documented as
  data-corruption-inflated; don't cite it. Single-factor re-tests reuse the PIT archive in
  ~10s — the strongest part of the system. (Note: reproducible ≠ valid; see headline.)

## 3. Factor model — 54/100

- **F1 CRITICAL** — the pt_upside look-ahead (headline above).
- **F2 HIGH — registry drift**: 38 signals in limbo (registered, neither wired nor in
  FACTOR_LIBRARY); KEEP-grade candidates invisible to promotion (`value_composite` SMALL
  t=3.65; `eps_revision_yoy` 2.53; `earnings_persistence` 2.78); the verify_factor_library
  tool ADR 0017 promised doesn't exist.
- **F3 HIGH — LARGE tier has no wired factor that survives honest scrutiny**: consensus 0.35
  fails the haircut (and MID consensus is wired + against current-lens t=−1.16), pt_upside
  0.25 is the artifact, the rest are |t|≤0.9 diversifiers. `smart_money` SMALL 0.05 with
  best-ever t=1.06 (n=6) breaches the ≥1.5 rule outright.
- **F4 MED — no decay monitor**: governance_resignation wired 2026-06-14 exactly as its
  yearly IC hit −0.002 (monotonic decay from −0.081 in 2022).
- **F5 MED — wired object ≠ backtested object** for accruals (4-part composite deployed;
  only cf_accruals_ratio validated).
- **Post-audit robust core: `delivery_anomaly_z` SMALL + a diluted `pledge_quality` SMALL** —
  not the documented three. Validated wired alpha lives almost entirely in SMALL
  microstructure/ownership.
- Gap map (data already in-house): **low-vol/idio-vol/BAB (biggest absent canonical factor)**,
  short-term reversal, asset growth (CMA), announcement-window CAR (the sanctioned PEAD
  path), MAX/lottery, gross profitability (in library, never backtested — one command away).
- Machinery praised: HLZ/BY-FDR haircut math verified correct; horizon-resolved marginals;
  restraint on contrarian-sign KEEPs.

## 4. Portfolio construction & results — 62/100

- **F1 HIGH — Everything is GROSS.** `paper_portfolio.py` (the only cost-aware sim) has never
  run: 0 rows. Measured one-way turnover **18.5%/day** (~2.7 of 15 names replaced daily) ≈
  31bps/day at the system's own cost assumptions — vs measured gross pick edge of
  **+0.017% per 20d**. Net of Indian costs, the book as measured is negative-alpha; only
  SMALL (+2.6pp/20d) plausibly survives costs.
- **F2 HIGH — Financial-sector routing does NOT hold**: `financial_signal_scores` computed
  daily, consumed nowhere; Financials ranked by generic weights; today's book 26.9% Financials.
- **F3 HIGH — the HANDOFF headline "HRP Sharpe 0.83 vs eqw 0.20" is irreproducible**
  (today's rerun: 1.45/1.18; truncated-to-commit-date: 1.44/0.76) and statistically
  meaningless at n=46d. Raw stored head-to-head: both books trail tier-blended NIFTY by
  ~3pp/20d.
- **F4 MED-HIGH — HRP overweights the tiers with no skill**: 44.9% LARGE (decile spread
  −2.45pp) vs 23.7% SMALL (+2.22pp, the only tier with evidence).
- **F5 MED — stored books violate their own caps silently** (2026-05-20/21: 12.63% names,
  36.84% sector; `run()` stores regardless of `stock_cap_ok=False`).
- **F6 MED — stale-signal leakage**: "latest snapshot per sid" with no staleness cutoff
  (today's #1 LARGE pick carries a 2-month-frozen piotroski score).
- Highest-leverage fix: **banded/hysteresis rebalancing** (trade only on top-8 exit or >2pp
  drift) — cutting turnover ~10× is worth more than any factor improvement. Second: tier
  risk budgets toward SMALL.
- Credit: within-tier discipline holds end-to-end; ADVISORY/no-capital gate culture is real;
  validate_rank_skill's non-overlap correction is honest.

## 5. Mutual-fund model — 46/100

- **F1/F2 HIGH — the composite score is an unvalidated hand-tuned heuristic whose dominant
  input (0–50 of 100 pts) is cross-category trailing 3Y CAGR** — by design it converts fund
  quality into recent asset-class beta; the default cockpit sort is a performance-chase list.
  No MF backtest tool exists; forward validation impossible yet (4 snapshots).
- **F3 HIGH — zero cost data**: expense_ratio/aum/benchmark/inception NULL for all 14,403
  schemes; the enrichment stub never ran; no exit_load column anywhere.
- **F4 MED-HIGH — live bug**: `sharpe_1y` fabricated for 467 schemes (`ret_1y or 0` at
  mf_metrics.py:163; the 3Y branch guards correctly).
- **F5 MED-HIGH — consistency component is survivorship + selection biased** (2026 AMFI
  master ∩ 3,443-scheme Growth-only backfill as the historical comparison set).
- Also: benchmark proxy is price-weighted, current-constituent, price-return (claims
  cap-weighted TRI-comparable); up-to-4× plan/option duplicates in category pools; 329 IDCW
  schemes scored on payout-depressed NAV; "Debt/Income (legacy)" bucket holds 33% of master.
- **Built-but-unused gem**: `mf_holdings.sid` maps 90% of 280,969 holding rows to the equity
  universe — the exact join for equity-book overlap — and nothing consumes it.
- Credit: the data layer (8.3M NAV rows, quality classifier, splice-cleaning, quarantines,
  watchdog coverage) is genuinely good.

---

## Top 5 cross-cutting findings (by money/trust at risk)

1. **pt_upside look-ahead (CRITICAL)** — top weight in all tiers validated on future prices;
   fix = quarantine fh-price → rebuild PIT → re-run haircut → re-weight. Everything downstream
   (weights, risk decomp, book tilt) inherits it.
2. **All results are gross while turnover is lethal** — 18.5%/day one-way vs +0.017%/20d gross
   edge; the cost sim has never run. Fix = banded rebalancing + run paper_portfolio backfill.
3. **fundamentals_screener: 55d stale, auth dead, invisible to alarms** — ~25 signals silently
   frozen. Fix = one-line RAW_TABLES registration + auth repair.
4. **Survivorship-biased backtest panel** — the fix table (`historical_universe`) sits unused
   in the same DB. Fix = intersect eval-date frames; report per-factor exposure where dead
   names lack fundamentals.
5. **LARGE tier is noise-ranked** — no wired LARGE factor survives scrutiny; presented with
   the same confidence as SMALL. Fix = shrink/gate LARGE until a validated factor exists
   (low-vol is the cheapest candidate).

## Illusory-edge watchlist

- `pt_upside` t=7–9 (look-ahead artifact; true edge ~0)
- "HRP Sharpe 0.83 vs 0.20" (irreproducible, n=46d noise)
- `pledge_quality` t=5.90 (blends n=11–72 pre-2024-11 regime with n≈1,500 after at IC≈0.02)
- LARGE-tier skill generally (decile spread −2.45pp; 40% of weight on |t|≤0.9)
- `governance_resignation` (real 2022-23 edge, now decayed to ~0)
- MF composite score (unvalidated 3Y-CAGR chase)
- Any signal-weight justified by the stale "t=16" claim (documented as corruption-inflated)

## Fastest wins (≤1 day each)

1. Register `fundamentals_screener` in RAW_TABLES + fix Screener auth (closes finding #3).
2. Fix `sharpe_1y or-0` bug (1 line, kills 467 fabricated values).
3. Dedup the double Tickertape monthly step (saves ~1.9h + halves WAF risk).
4. Add `as_of_date`/`brief_date`/`change_date` to DATE_COLS; WARN on "registered but
   latest_date=None".
5. Raise on email send failure; fix/mute the month-old uhs_calibration CRITICAL (alarm fatigue).
6. Cap-violation guard before `portfolio_weights` store.
7. Backtest `gross_profitability` (registered, data ready, never run).
8. Build `tools/verify_factor_library.py` (registry partition check, promised by ADR 0017).

## Could not verify (all auditors)

- Whether Tickertape's *current* forecastsHistory API still serves future-embedded values
  (no external calls allowed) — the stored PIT table is contaminated either way.
- v1-archive (`daily_snapshots_pit_v1`) survivorship provenance and the v1↔v2
  pledge_quality contradiction (0.66 vs 5.90).
- Why the committed HRP headline is irreproducible (no snapshot/lineage to arbitrate).
- True LLM spend (no cost ledger exists).
- fetch_broker_recos 15.5h Sunday internals; live raise-on-zero behavior of each fetcher.

## Final verdict — 58/100

The *process* layer (PIT archive, HLZ haircut, promotion gates, advisory-only discipline,
observability breadth, backups) is well above solo-operator norm and is the reason no real
money has been hurt. The *conclusions* layer is where the risk lives: the flagship factor is
invalid, results are gross-only against lethal turnover, the backtest universe is survivors-
only, and the alarm system's two worst holes sit exactly under the most valuable inputs. The
system's own tools found most of this first — the audit's job was mostly to force the
confrontation. Fix findings 1–3 and rerun the haircut, and the honest score likely lands in
the low 70s.
