# Architecture Decision Records (ADRs)

One file per decision, **write-once**: when a decision changes, a new ADR supersedes it and the old
one gets a single `Status:` line pointing forward (body untouched). File name `NNNN-kebab-title.md`,
numbers never reused. Template: Context · Decision · Alternatives considered · Consequences.

Read part (a) to know what is true **now**; use part (b) to find any ADR by number.

## (a) Current decision per topic

| Topic | Live ADR(s) | What holds today |
|---|---|---|
| Stack & process | [0001](0001-sqlite-over-csv.md) · [0002](0002-no-prefect.md) · [0004](0004-no-base-classes-no-yaml.md) · [0007](0007-fresh-rebuild-v2.md) · [0031](0031-duckdb-read-replica.md) | One SQLite DB, plain-Python `pipeline.py` over `config.PIPELINE_STEPS`, plain functions + config dict, v2 separate from v1; DuckDB only as a derived read replica |
| Doc & plan numbering | [0016](0016-plan-numbering-fresh-start.md) (+ [0015](0015-track-numbering-and-rename.md) for old Track labels) | Chronological plan numbers; plan 0011's WS workstreams replaced the Track 1/2/3 labels ([0009](0009-factor-track-parallel-to-d-track.md) is historical) |
| Prices & PIT correctness | [0003](0003-bhavcopy-over-yfinance.md) · [0010](0010-pit-strict-corporate-action-adjustment.md) · [0012](0012-pit-archive-refresh-on-signal-fix.md) · [0047](0047-fwd-return-anchor-proximity-guard.md) | Bhavcopy closes; corporate actions composed at compute time; refresh the v2 PIT archive when a signal changes; forward returns need an anchor within about 5 trading days |
| Data model & acquisition | [0011](0011-long-format-for-new-fundamentals-tables.md) · [0042](0042-data-acquisition-build-not-buy.md) · [0034](0034-fno-oi-data-model.md) · [0035](0035-fno-iv-derived-from-bhav.md) | Long format for new fundamentals tables; build from public endpoints, 2018 floor; F&O from `fno_bhav_copy`, IV/Greeks derived in-house |
| Analyst PT data | [0018](0018-pt-data-model-episodic-cadence.md) → [0020](0020-pt-data-model-v2-sell-side-only-llm-narrative-only.md) → [0045](0045-pull-pt-upside-lookahead.md) · [0037](0037-per-stock-uhs-and-pt-plausibility.md) | PTs are episodic: yfinance `analyst_consensus` daily view + monthly `analyst_consensus_snapshots`; `forecast_history` price is look-ahead, never used; `pt_upside` out of the weights until about 2027-05; stored PTs over 3× or under 0.33× the close are nulled |
| Ranking structure | [0005](0005-tier-aware-scoring.md) · [0026](0026-micro-tier-carve-out.md) · [0021](0021-pick-eligibility-gate.md) → [0024](0024-per-signal-eligibility-and-per-stock-integrity.md) | Rank only within cap tier; MICRO classified but never picked; pick gate = `eligible_coverage` plus weight and price-row floors |
| Financials | [0048](0048-financials-rank-generic-not-submodel.md) | Generic screener; `accruals` + `piotroski` INELIGIBLE for Financials; `financial_signal_scores` display-only ([0030](../_archive/decisions/0030-banking-metrics-screener-first.md), [0032](../_archive/decisions/0032-tier-direction-flip-split-signal.md) archived) |
| Factor promotion gate | [0017](0017-factor-library-two-tier-registry.md) · [0022](0022-per-factor-backtest-cadence-newey-west.md) · [0036](0036-horizon-resolved-factor-evaluation.md) → [0038](0038-horizon-resolved-promotion-gate.md) · [0043](0043-multiple-testing-aware-factor-significance.md) | Every factor registered and backtested at its own cadence with Newey-West errors; net-of-cost horizon gate; multiple-testing haircut (\|t\|≥2.5 is necessary, not sufficient); weights stay a human decision |
| Production weights | [0049](0049-honest-weight-rederivation.md) · [0050](0050-wire-announcement-car.md) · [0041](0041-sector-tilt-backtest-gated-small-only.md) | Weights re-derived on clean data under five rules; `announcement_car` wired LARGE+SMALL; sector tilt backtest-gated ([0028](../_archive/decisions/0028-two-variant-factor-model.md) variants archived) |
| Trust & observability | [0019](0019-observability-sensor-surface-alert.md) · [0023](0023-health-center-cockpit-as-single-window.md) · [0024](0024-per-signal-eligibility-and-per-stock-integrity.md) · [0025](0025-pit-replay-validator.md) · [0027](0027-per-stock-data-lineage.md) · [0033](0033-trust-pipeline-uhs.md) · [0037](0037-per-stock-uhs-and-pt-plausibility.md) · [0059](0059-health-five-questions-one-issue-list.md) · [0060](0060-a-check-must-be-able-to-fail.md) · [0061](0061-retire-uhs-and-dead-gates.md) | Sensor → sanity → surface → alert; every check answers one of five questions and all surfaces render one issue list; cockpit Health Center is the single window; every check proves it can fire; two write-time gates (identity, plausibility), the per-pick number is factor coverage (UHS retired); lineage registry; PIT-replay pre-push gate |
| Portfolio construction | [0044](0044-hrp-over-mean-variance-portfolio.md) · [0046](0046-banded-rebalancing.md) | HRP, no µ input; banded rebalancing (enter top-5, exit below rank 8) |
| Multibagger | [0039](0039-multibagger-funnel-regime-dominated.md) → [0040](0040-multibagger-holding-not-selection.md) | Separate screen, out of `daily_picks`; selection is closed, the product is a holding/conviction monitor on a gated pool |
| Cockpit & UX | [0008](0008-cockpit-write-surface.md) · [0013](0013-industry-not-sector-as-drill-unit.md) · [0014](0014-llm-sourced-competitive-landscape.md) · [0029](0029-mf-investable-only-default.md) | Guarded write surface (step rerun); industry is the drill unit; LLM competitive landscape; MF view defaults to investable-only |
| LLM classification | [0006](0006-classifier-status-tracking.md) | Regulatory classifier state lives on `regulatory_events.classifier_status` |
| Strategy (plan 0011) | [0051](0051-roadmap-to-90-decisions-d1-d12.md) | D1–D12 standing rules with pre-committed evidence bars. This reads like a plan; it is the decision register for plan 0011 |

## (b) Complete index

Status key: **A** accepted · **P→N** partly superseded by N · **S→N** superseded by N · **M→N** moot after N · **H** historical.

| # | Title | Status |
|---|---|---|
| 0001 | [SQLite over CSV files](0001-sqlite-over-csv.md) | A |
| 0002 | [No Prefect, plain Python orchestrator](0002-no-prefect.md) | A |
| 0003 | [NSE Bhavcopy over yfinance for prices](0003-bhavcopy-over-yfinance.md) | A |
| 0004 | [No base classes, no YAML](0004-no-base-classes-no-yaml.md) | A |
| 0005 | [Tier-aware scoring](0005-tier-aware-scoring.md) | A |
| 0006 | [Classifier status tracking](0006-classifier-status-tracking.md) | A |
| 0007 | [Fresh rebuild as v2](0007-fresh-rebuild-v2.md) | A |
| 0008 | [Cockpit as a write-side surface](0008-cockpit-write-surface.md) | A |
| 0009 | [Track 3 parallel to Track 2](0009-factor-track-parallel-to-d-track.md) | H (old D-/F-track naming) |
| 0010 | [PIT-strict corporate-action adjustment](0010-pit-strict-corporate-action-adjustment.md) | A |
| 0011 | [Long format for new fundamentals tables](0011-long-format-for-new-fundamentals-tables.md) | A |
| 0012 | [PIT archive refresh on signal fix](0012-pit-archive-refresh-on-signal-fix.md) | A |
| 0013 | [Industry, not GICS sector, as drill unit](0013-industry-not-sector-as-drill-unit.md) | A |
| 0014 | [LLM-sourced competitive landscape](0014-llm-sourced-competitive-landscape.md) | A |
| 0015 | [Track numbering and rename](0015-track-numbering-and-rename.md) | P→0016; Track labels H |
| 0016 | [Plan numbering fresh start](0016-plan-numbering-fresh-start.md) | A |
| 0017 | [Two-tier factor registry](0017-factor-library-two-tier-registry.md) | A |
| 0018 | [PT data model: episodic, three-table](0018-pt-data-model-episodic-cadence.md) | P→0020, 0045 |
| 0019 | [Observability: sensor + sanity + surface + alert](0019-observability-sensor-surface-alert.md) | P→0023, 0033 |
| 0020 | [PT data model v2: sell-side only, LLM narrative-only](0020-pt-data-model-v2-sell-side-only-llm-narrative-only.md) | A |
| 0021 | [Pick eligibility gate](0021-pick-eligibility-gate.md) | P→0024 |
| 0022 | [Per-factor backtest cadence + Newey-West](0022-per-factor-backtest-cadence-newey-west.md) | A |
| 0023 | [Health Center: cockpit as single window](0023-health-center-cockpit-as-single-window.md) | A |
| 0024 | [Per-signal eligibility + per-stock integrity](0024-per-signal-eligibility-and-per-stock-integrity.md) | A |
| 0025 | [PIT replay validator](0025-pit-replay-validator.md) | A |
| 0026 | [MICRO tier carve-out](0026-micro-tier-carve-out.md) | A |
| 0027 | [Per-stock data lineage](0027-per-stock-data-lineage.md) | A |
| 0028 | [Two-variant factor model (archived)](../_archive/decisions/0028-two-variant-factor-model.md) | S→0049 |
| 0029 | [MF investable-only default](0029-mf-investable-only-default.md) | A |
| 0030 | [Banking metrics: Screener.in first (archived)](../_archive/decisions/0030-banking-metrics-screener-first.md) | M→0048 |
| 0031 | [DuckDB read replica](0031-duckdb-read-replica.md) | A |
| 0032 | [Tier direction-flip split signal (archived)](../_archive/decisions/0032-tier-direction-flip-split-signal.md) | M→0048 |
| 0033 | [Trust Pipeline + UHS](0033-trust-pipeline-uhs.md) | S→0061 (gates 1–2 remain) |
| 0034 | [F&O OI data model](0034-fno-oi-data-model.md) | A |
| 0035 | [F&O IV derived from bhavcopy](0035-fno-iv-derived-from-bhav.md) | A |
| 0036 | [Horizon-resolved factor evaluation](0036-horizon-resolved-factor-evaluation.md) | A (gate part realized by 0038) |
| 0037 | [Per-stock UHS + PT plausibility](0037-per-stock-uhs-and-pt-plausibility.md) | S→0061 (PT plausibility sweep remains) |
| 0038 | [Horizon-resolved promotion gate](0038-horizon-resolved-promotion-gate.md) | A |
| 0039 | [Multibagger funnel, regime-dominated](0039-multibagger-funnel-regime-dominated.md) | A (extended by 0040) |
| 0040 | [Multibagger: holding, not selection](0040-multibagger-holding-not-selection.md) | A |
| 0041 | [Sector tilt: backtest-gated](0041-sector-tilt-backtest-gated-small-only.md) | A |
| 0042 | [Data acquisition: build, not buy](0042-data-acquisition-build-not-buy.md) | A |
| 0043 | [Multiple-testing-aware significance](0043-multiple-testing-aware-factor-significance.md) | A |
| 0044 | [HRP over mean-variance](0044-hrp-over-mean-variance-portfolio.md) | A |
| 0045 | [Pull pt_upside (look-ahead) + smart_money](0045-pull-pt-upside-lookahead.md) | A |
| 0046 | [Banded rebalancing](0046-banded-rebalancing.md) | A |
| 0047 | [Forward-return anchor-proximity guard](0047-fwd-return-anchor-proximity-guard.md) | A |
| 0048 | [Financials rank generic, not sub-model](0048-financials-rank-generic-not-submodel.md) | A |
| 0049 | [Honest weight re-derivation](0049-honest-weight-rederivation.md) | A |
| 0050 | [Wire announcement_car](0050-wire-announcement-car.md) | A |
| 0051 | [Roadmap-to-90 decisions D1–D12](0051-roadmap-to-90-decisions-d1-d12.md) | A (decision register for plan 0011) |
| 0052 | [Seven building blocks: one as-of dataflow graph](0052-seven-building-blocks.md) | P→0053 (plan 0015) |
| 0053 | [Lag is declared; a lagged read sees the previous run](0053-declared-lag-not-cadence-lag.md) | A (partly supersedes 0052) |
| 0054 | [Tables grow with concepts, not things](0054-tables-grow-with-concepts.md) | A (plan 0017) |
| 0055 | [Data supply: feeds, canaries, run log](0055-data-supply-feeds-canaries-runlog.md) | A (plan 0018) |
| 0056 | [LLM work runs on a local subscription worker through a validated queue](0056-llm-work-local-worker-queue.md) | A (plan 0016) |
| 0057 | [The agent org: roles are a registry, desk work is a task kind, memos are documents](0057-agent-org-roles-on-the-queue.md) | A (plan 0019) |
| 0058 | [The CEO's interface to the org: tune behaviour, never permissions](0058-ceo-interface-tune-behaviour-not-permissions.md) | A (plan 0019) |
| 0059 | [Health is five questions and one issue list](0059-health-five-questions-one-issue-list.md) | A |
| 0060 | [A daily check must be able to fail, and prove it](0060-a-check-must-be-able-to-fail.md) | A |
| 0061 | [Retire the UHS trust score and the dead gates; the data behind a pick is its factor coverage](0061-retire-uhs-and-dead-gates.md) | A (supersedes 0033, 0037) |
| 0062 | [Factor audit: the inputs are corrected as one model change](0062-factor-audit-fixes-one-model-change.md) | A (plan 0020) |
| 0063 | [Production weights re-set on the corrected evidence](0063-weights-on-corrected-evidence.md) | A (supersedes the weight table of 0049 / 0050) |
| 0064 | [A factor with no value counts as neutral; a result print is found wherever it is filed](0064-missing-factor-is-neutral.md) | A (amends the scoring rule of 0024 / 0048) |
