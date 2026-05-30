# Alpha Signal v2 — Full System Setup & Context

> **Purpose of this document.** This is a complete, self-contained description of
> everything built in the Alpha Signal v2 project, written so that an external
> AI assistant (or a new collaborator) can read it cold and give informed advice
> on any sub-topic. It defines all jargon, states what is *proven* vs *aspirational*,
> and is honest about what does and does not work. Nothing here assumes prior
> knowledge of the codebase.
>
> Last compiled: 2026-05-29. If code and this doc disagree, the code wins —
> regenerate this file.

---

## 1. One-paragraph summary

Alpha Signal v2 is a **daily stock-intelligence engine for Indian retail equity
investors**, built and run by a single person (Amit Bhagat) on one Oracle Cloud
Ubuntu VM. Every morning it ingests market + fundamental + news data for ~2,448
Indian stocks, computes a few dozen quantitative "factors," ranks stocks **within
their market-cap tier**, writes the rankings to a database, generates AI-written
one-page "dossiers" for the top names, and emails a digest. A web "cockpit"
(FastAPI) lets the owner inspect every step. It is a **research/intelligence
system, not a deployed fund** — no live capital is managed by it yet, and (see
§12) its stock-ranking skill is **not yet statistically proven** on live data.

---

## 2. Owner, environment, and hard constraints

- **Owner / sole operator:** Amit Bhagat, Bengaluru, India. Retail investor + builder.
- **Goal (stated 2026-05-29):** eventually **trade his own capital** off these signals.
- **Hardware:** one Oracle Cloud Ubuntu VM (always-on).
- **Stack:** Python (no web framework beyond FastAPI for the cockpit), **SQLite**
  single-file database, plain functions + a Python config dict. Deliberately
  **no Prefect/Airflow, no ORM, no base classes, no YAML** (see ADR 0002, 0004).
- **Two parallel installs on the same box:**
  - `~/alpha-signal/` = **v1**, the *original* system. Kept only for rollback.
    Owns the shared Python virtualenv and the credentials. **Never modified.**
  - `~/alpha-signal-v2/` = **v2**, this system. Owns the live 03:30 cron since 2026-05-01.
- **Credentials** live only in v1's `run_pipeline.sh` as `export` lines; v2 imports
  them read-only at runtime (`eval "$(grep '^export ' .../run_pipeline.sh)"`).
  No secrets are stored in v2 code.
- **External-API etiquette (hard rules):** ≥2 s between calls to any source;
  never run two harvesters at once (doubles request rate → IP-ban risk);
  smoke-test with 3 stocks before any full run.

---

## 3. The investable universe and "tiers"

- **2,448 stocks** total (NSE-listed Indian equities; **ETFs excluded** by design).
- Each stock is assigned a **`cap_tier`** (market-cap bucket) *before* any ranking.
  This is the single most important structural rule: **stocks are only ever ranked
  against others in the same tier**, never across tiers. A large-cap is never
  compared to a small-cap.
- Current tier counts:
  | Tier  | Definition (rough)          | Count |
  |-------|-----------------------------|-------|
  | LARGE | Top 100 by market cap       | 100   |
  | MID   | Ranks 101–250               | 150   |
  | SMALL | 251+ (minus MICRO)          | 1,601 |
  | MICRO | Carved out of SMALL (ADR 0026) | 597 |
- **MICRO** stocks are *classified but never recommended* — too illiquid, data-thin,
  and trivially manipulable. They are excluded from all picks/dossiers/emails.
- **Liquidity floors (ADTV = average daily traded value, ₹ crore):** LARGE ≥10,
  MID ≥5, SMALL ≥1. Below the floor → not investable.
- **Financial-sector stocks** (banks, NBFCs) are meant to route through a separate
  "financial sub-model" rather than the generic screener (see §11) — though that
  routing is not yet live.
- **Tickertape SIDs ≠ NSE tickers.** The project's internal stock IDs ("SIDs") come
  from Tickertape and differ from NSE symbols (e.g. `REDY`, not `DRRD`). All joins
  use SIDs.

---

## 4. Data flow (the daily pipeline)

```
03:30 IST cron → pipeline.py runs ~40 steps in order →
   FETCH (prices, fundamentals, news, insider, bulk deals, analyst, macro, MF) →
   COMPUTE SIGNALS (each factor module writes its own *_scores table) →
   QUALITY GATE + REGIME (risk overlays) →
   SCREENER (rank within tier, write daily_picks) →
   PICK OUTCOMES (track realized forward returns of past picks) →
   OUTPUT (snapshot → AI dossiers → email) →
   BACKGROUND (news AI-enrichment, regulatory classify, broker recos, banking metrics)
```

- **Orchestrator:** [pipeline.py](pipeline.py). Reads a single list, `PIPELINE_STEPS`,
  in [config.py](config.py) — the one source of truth. Each step is a dict:
  `{name, module, function, critical, table, source, data_freq, frequency}`.
- **`critical: True`** steps (bhavcopy price fetch, quality_gate, screener) stop the
  pipeline on failure. Everything else is non-blocking.
- **`frequency`** gates how often a step runs: `daily` always; `weekly` = Sundays;
  `monthly` = the 1st; `quarterly` = 1st of Jan/Apr/Jul/Oct. So the daily cron
  only executes the steps due that day.
- **Heavy/slow steps run AFTER the email** (news AI-enrichment, regulatory
  classifier capped at 500/run, the 8-hour Moneycontrol broker scrape, the
  monthly banking-metrics scrape) so a slow background job can never delay the
  morning digest. This was a real 2026-05-25 incident: a classifier ran 1.5 h at
  the top of the pipeline and blocked everything downstream.
- Every step logs a row to `pipeline_log` (status, rows affected, duration, error).

---

## 5. Data sources (what's ingested, and from where)

All fetchers live in `sources/`. Key inputs:

| Domain | Source | Table(s) | Cadence |
|---|---|---|---|
| Daily prices | NSE Bhavcopy archives (primary) + yfinance `.NS`/`.BO` gap-fill | `stock_prices` | daily |
| Fundamentals (income/BS/CF) | Tickertape API | `quarterly_income`, `annual_balance_sheet`, `annual_cash_flow` | monthly |
| Fundamentals (deep ratios) | **Screener.in Premium** scrape (2,123 stocks, ~681K rows) | `fundamentals_screener` | weekly |
| Analyst price targets | **yfinance** (current PT) + Tickertape (forecast history) | `analyst_consensus`, `forecast_history`, `analyst_consensus_snapshots` | daily / monthly |
| Shareholding (promoter, pledge, FII/DII) | Tickertape | `shareholding` | monthly |
| Insider trades | NSE PIT API | `insider_trades` | daily |
| Bulk/block deals | NSE archives | `bulk_deals` | daily |
| News | 8 RSS feeds | `news_articles` (+ AI-enriched `news_enriched`, `news_briefs`) | daily |
| Regulatory events | Google News + RBI + PIB | `regulatory_events` → AI-classified `regulatory_signals` | daily |
| Macro | yfinance (20 tickers) + data.gov.in + FRED | `macro_history` | daily/weekly |
| Volatility regime | yfinance `^INDIAVIX` | `vix_history` | daily |
| Banking-specific ratios | **Screener.in** bank pages (GNPA/NNPA/NII/etc.) | `banking_metrics` (158 banks+NBFCs) | monthly |
| Mutual funds | AMFI NAV file + ETMoney holdings scrape | `mf_*` tables | daily/weekly/monthly |
| Broker recommendations | Moneycontrol HTML (12 s/req, ~8 h full run) | `broker_recommendations` | weekly |

**Key data-hygiene rules learned the hard way:**
- `INSERT OR IGNORE` for append-only tables (insider, bulk deals, news);
  `INSERT OR REPLACE` for snapshot tables (analyst consensus, regime, signals).
- **Analyst price targets are *episodic*, not daily.** Sell-side analysts revise
  quarterly at best. Storing a daily PT history is "phantom precision" and once
  caused a real bug where the day's *last price* masqueraded as a price target.
  Three PT tables with three deliberately different rhythms: `analyst_consensus`
  (daily live view), `analyst_consensus_snapshots` (monthly, for backtests),
  `forecast_history` (year-end). (ADRs 0018, 0020.)
- `forecast_history.price` from Tickertape is **contaminated** — its "price-target"
  rows are actually the current close. Verified 2026-05-23; do not trust that column.

---

## 6. Factors / signals (the quantitative core)

A **factor** (a.k.a. signal) is a single number per stock meant to predict future
relative return — e.g. "earnings yield," "Piotroski quality score," "promoter
buying." Each factor is one module in `signals/`, writes its own `*_scores`
table, and is registered for backtesting.

- **~42 factors are computed daily** (READMEs say 42; the registry is growing toward
  a target of ~50, ultimately 100). Groups:
  - **Value:** earnings yield, book-to-price, 52-week-range position, FCF yield.
  - **Quality:** Piotroski F-score, Sloan accruals (CF + BS), earnings persistence,
    earnings beat rate, ROIC, ROIIC, interest coverage.
  - **Forensic / accounting-quality:** Beneish M-score, Altman Z-score, DSO/DIO
    change YoY, SG&A-to-revenue change, goodwill-to-assets, asset tangibility,
    debt structure, working-capital intensity, cash-conversion-cycle.
  - **Capital allocation / growth:** capex-to-depreciation, FCF margin, sales-growth
    relative to sector, revenue coefficient-of-variation, inventory turnover.
  - **Ownership / flow:** promoter signal (buying + pledge), smart-money (bulk-deal
    + delivery), insider signal, share-count momentum.
  - **Sentiment / external:** news sentiment, consensus (analyst PT upside +
    EPS growth + revisions), macro sector signal, regulatory signal.
- **Two-tier factor registry** (in [db.py](db.py): `BACKTEST_SIGNALS` + `FACTOR_LIBRARY`,
  ADR 0017):
  - A factor is computed and **PIT-backtested** the moment it ships.
  - If it clears a statistical bar (|t-stat| ≥ 1.5 in at least one tier) it becomes
    eligible for the **production scoring weights**.
  - If it doesn't clear the bar, it stays in the **FACTOR_LIBRARY** — computed and
    tracked but not used in live scoring. "100 factors, all backtested; only the
    validated ones touch the model."
- **State as of now:** 23 of ~50 planned factors are PIT-reconstructable; the live
  production screener uses only **8 factors** (LARGE 6, MID 6, SMALL 7); ~9 more
  validated factors sit "on the bench" awaiting wiring.

### What "PIT" means and why it matters
**PIT = point-in-time.** A backtest is only honest if, on each historical date, it
uses *only data that was actually knowable then* — prices adjusted for splits as of
that day, fundamentals lagged by realistic filing delays (60 days quarterly, 75 days
annual). The project enforces PIT strictly (ADR 0010): corporate-action adjustment
happens at *compute* time, not ingest time. `tools/reconstruct_pit.py` rebuilds the
historical factor panel; there is a **36-month PIT archive** to backtest against.

---

## 7. The scoring model (how stocks get ranked)

Located in `scoring/`. Three pieces:

1. **`quality_gate.py` (SMALL caps only).** A hard filter + penalty system before
   ranking. Hard-excludes Piotroski ≤1 or Altman-Z <0.5 (bankruptcy risk).
   Applies capped penalties for chronic losses, negative 3-yr FCF, >50% promoter
   pledge, weak Piotroski, Altman grey zone, Beneish manipulation flag. Then a
   "quality composite" (weighted Piotroski / CFO-EBITDA / Beneish / Altman / pledge / FCF).
2. **`regime.py` (VIX regime overlay).** Reads India VIX and classifies the market
   into CALM / NORMAL / CAUTION / CRISIS, which shifts how capital is notionally
   tilted across tiers (e.g. CRISIS → 70% LARGE, 10% SMALL). 3-day hysteresis to
   avoid whipsaw.
3. **`screener.py` (the ranker).** For each tier, combines the tier's factors using
   **per-tier weights**, producing a score, then ranks. Writes `daily_picks`
   (the **full ranked universe** per day — ~1,688 rows/day, not just the top names;
   the email selects the top 5 per tier from it).

### Production weights (`SIGNAL_WEIGHTS` in config.py)
Hand-set from the original "C13b" validation, weighted by t-stat tier
(t≥2.5 → 1.0×, 1.5–2.5 → 0.5×, etc.). Examples:
- **LARGE:** consensus 0.40, earnings_yield 0.20, accruals 0.15, piotroski 0.10, momentum 0.05, book_to_price 0.10.
- **MID:** accruals 0.30, piotroski 0.20, consensus 0.15, book_to_price 0.20, earnings_yield 0.10, promoter 0.05.
- **SMALL:** promoter 0.25, earnings_yield 0.20, piotroski 0.15, book_to_price 0.15, smart_money 0.10, accruals 0.10, momentum 0.05.

### Two experimental weight variants (ADR 0028, not yet live)
Generated by `tools/optimize_weights.py` from the PIT IC backtest:
- **`SIGNAL_WEIGHTS_RETURN`** — weight ∝ |t-stat| (maximise raw return signal).
- **`SIGNAL_WEIGHTS_SHARPE`** — weight ∝ ICIR = information-coefficient information-ratio
  (maximise consistency of the signal).
Both are **print-only / cockpit-only** — they are computed and shown side-by-side on
a `/model/variants` page but do **not** write `daily_picks`. Promotion to production
is deliberately deferred pending a 30-day side-by-side track and orthogonalization.
Both lean heavily on `pt_upside` (analyst PT upside, t=7–9) and `eps_growth` (t≈5) —
whose t-stats are **suspected partly artifactual** (see §12).

---

## 8. Outputs

- **`daily_picks`** table — the full ranked universe per date.
- **AI dossiers** (`output/dossier.py`, Claude API) — a one-page thesis per top pick:
  thesis / bull / bear / catalysts / risks. **Hard rule:** narrative LLM fields
  **must not contain raw numbers** (price targets, percentages, multiples) — LLMs
  hallucinate plausible-but-wrong figures. Numbers live only in structured fields
  (`target_price`, `stop_loss`). A validator rejects dossiers that violate this;
  calendar tokens like "Q1 FY25" are allowed. (This rule exists because of a real
  2026-05-22 hallucination: "16.5% downside at ₹1038" when the math was −8.5%.)
- **Email digest** (`output/email_sender.py`, Gmail SMTP) — sent daily.
- **Cockpit** (`cockpit/` FastAPI app on port 3000; ops split on 3001) — a read-only
  (mostly) web console. Pages: `/model`, `/model/variants`, `/model/outcomes`
  (live equity curve), `/portfolio`, `/news`, `/sectors`, `/mutual-funds`,
  `/signals`, `/system` (health), `/stock/<sid>`, `/sql` console, `/explorer`,
  `/flow`, `/command`, `/morning-brief`. Heavily cached (per-page disk pickles
  with TTLs) after a cold-restart perf rewrite (140× on `/system`).

---

## 9. The database

- **One SQLite file:** `data/alpha_signal.db`, **~2.0 GB**, **~80 tables**.
  (Note: the README still says "51 tables / 320 MB" — stale; the DB has grown.)
- Table families: raw data (`stock_prices`, `quarterly_income`, …), one `*_scores`
  table per factor, output tables (`daily_picks`, `daily_snapshots`, `daily_changes`),
  observability (`pipeline_log`, `universe_eligibility`, `signal_lineage`),
  validation (`pick_outcomes`, `pit_replay_snapshots`), MF tables (`mf_*`),
  sector tables (`sector_briefs`, `sector_force_breakdown`, `sector_metadata`),
  and paper-trading tables (`paper_positions`, `paper_trades`, `paper_nav_history` —
  **currently empty**, scaffolding only).

---

## 10. Scheduling (cron) and observability

**Cron jobs (v2):**
- `03:30 IST` daily — main pipeline (`run_pipeline.sh`).
- `19:07 on the 1st` — monthly Tickertape fundamentals refresh (~4 h run).
- `14:00` daily — `run_daily_forward.sh` (forward-return tracking).
- `15:00` daily — `freshness_watchdog` (alerts on stale tables/files).
- `04:00 UTC` daily — `health_report --email --push` (the daily health email).
- `04:30 on the 1st` — monthly analyst-PT snapshot.

**Observability philosophy (ADR 0019): "silent failures are the enemy."**
- Producers must **raise** on missing env vars or zero output — never write placeholders.
- The **freshness watchdog** covers both DB tables *and* file outputs
  (`config.FILE_OUTPUTS`) — added after a dossier producer failed silently for weeks.
- A daily health email at 04:00 UTC + an URGENT phone push (via ntfy.sh) on any
  CRITICAL. One source of truth: `tools/health_report.py`.
- **Per-stock data lineage** (ADR 0027): `signal_lineage` table + `FACTOR_LINEAGE`
  map so any factor value can be traced to its source columns.
- **PIT replay validator** (ADR 0025): each day freezes its inputs+outputs as a
  regression-test anchor; scoring/signal changes are replayed against frozen days.

---

## 11. The financial sub-model (banks & NBFCs) — in progress

Generic equity factors (P/E, accruals, etc.) don't work for banks — they need
banking-specific metrics (gross/net NPA, net interest income, cost of funds,
CASA, capital adequacy). Track 2.2:
- Source decision **flipped to Screener.in** (Tickertape carries no banking ratios) — ADR 0030.
- Scope = **158 Banks + NBFCs**; the other 91 financials (AMCs, insurers,
  capital-markets) stay on the main screener.
- `banking_metrics` table (28 cols) backfilled: Banks 41/41 (100% coverage on
  GNPA/NNPA/NII/etc.); NBFCs have a **big GNPA gap** (only 20/100 publish quarterly
  NPA in standard form) — a fallback source (RBI XBRL / annual-report scrape) is the
  next priority.
- `signals/financial_signal.py` scores them (40% asset-quality + 30% profitability +
  15% capital + 15% efficiency, renormalised over available components). **Print-only**
  — the screener does **not** yet route financials through it.
- **Critical finding (2026-05-29):** the composite **failed** its backtest gate
  (t = −0.75 / −1.30 / −0.34). The diagnostic revealed *why* and it's important:
  the predictive **sign of NPA flips by tier** — for LARGE/MID, high NPA predicted
  *higher* future return (distressed-recovery / mean-reversion, t=+2.4/+4.2); for
  SMALL, high NPA predicted *lower* return (quality compounds, t=−3.1). The composite
  assumed "lower NPA is always better," inverting the large-cap signal. This is also
  a textbook **overfitting warning sign** — a factor whose direction depends on the
  subsample. Open decision: tier-aware sign recalibration vs. splitting into two
  named sub-signals ("quality" for SMALL, "recovery" for LARGE/MID).

---

## 12. Validation — the honest state (READ THIS BEFORE TRUSTING THE PICKS)

This is the most important section for anyone advising on strategy.

**The backtest t-stats are in-sample and selection-biased.** Every "t=7–9" figure
comes from regressions on the *same* 36-month PIT panel used to *choose* the factors.
That is circular — it measures fit, not out-of-sample skill. `pt_upside` (the
biggest weight in both experimental variants) is explicitly flagged in the docs as
"real alpha or artifact?" and carries a history of price-target data contamination.

**Live out-of-sample evidence is thin; the signal is promising in MID, unproven
overall.** A `pick_outcomes` table tracks the realized forward return of every past
pick vs its benchmark. The correct way to read it is **per-date Spearman IC**
(correlate score vs forward return *within* each date, then average) — NOT a single
pooled correlation across all dates (which mixes day-to-day market swings into the
cross-sectional signal and was an early mistake in this analysis).

Proper per-date IC at the 20-day horizon (the model's design horizon):

| Tier | mean per-date IC | ICIR | dates positive |
|---|---|---|---|
| LARGE | −0.005 | −0.19 | ~4/9 — no skill |
| MID | **+0.076** | **+1.02** | 8/9 — promising |
| SMALL | +0.017 | +0.97 | 7/9 — weak but consistent |

(At the 5-day horizon everything is noise/negative — expected; the model isn't built
for a 1-week hold.) A mean IC of +0.076 with ICIR ≈ 1.0 in MID is a genuinely
respectable number for a real quant signal — this tier is a live candidate, not a
flatline.

**But it is not yet proven, for one specific reason:** live picks span only ~6 weeks
(2026-04-09 → 2026-05-23) and the 9 "dates" are heavily **overlapping** 20-day windows
→ effectively **~2 independent periods**. MID's positive average is driven almost
entirely by the tightly-clustered early-May dates (one observation counted ~8 times);
the single most-independent date, 2026-04-09, is *negative* for all three tiers. The
non-overlapping decile gate (`tools/validate_rank_skill.py`) confirms this: on the 2
independent windows MID is only +0.12pp, LARGE −1.03pp, SMALL +0.39pp — none
distinguishable from zero yet.

Also note a beta caveat on the raw basket returns: the headline "LARGE top-10 beat
NIFTY by +2.69pp" is mostly **beta, not alpha** — in the same window the LARGE
*bottom* bucket (rank 50+) also beat NIFTY by +3.21pp, i.e. the whole equal-weighted
tier beat the cap-weighted index in an up-market. Basket-vs-index outperformance ≠
ranking skill.

**The strong test — walk-forward OOS on 35 months of PIT history (`tools/walk_forward.py`).**
Rather than wait ~6 months for live data, this fits factor weights on months 1..N
(both sign and magnitude derived only from the training window) and tests the
composite's IC on the unseen month N+1, rolling forward over the 35 monthly v1 PIT
snapshots (2023-04 → 2026-02). Monthly spacing ≈ the 20-day return horizon, so test
periods barely overlap — this also sidesteps the overlapping-window artifact. With
min_train=12 that's ~23 genuinely out-of-sample periods per tier (vs 2 live). Result,
stable across expanding / rolling-18m / longer-train configurations:

| Tier | OOS mean IC | ICIR | t | 95% CI (mean IC) | % months + | Verdict |
|---|---|---|---|---|---|---|
| LARGE | ≈ 0 (−0.02 to +0.01) | ~0 | <\|1\| | straddles 0 | ~50% | **no OOS skill** |
| MID | ≈ 0 (−0.01 to +0.01) | ~0 | <\|0.5\| | straddles 0 | ~50% | **no OOS skill** |
| SMALL | **+0.034 to +0.047** | +0.45–0.60 | **+2.1 to +2.5** | **strictly > 0** | 71–82% | **VALIDATED** |

This **overturns the live read**: the live data (≈2 overlapping periods) made MID
look promising (+0.076), but over 23 non-overlapping OOS months MID shows nothing —
that live number was the overlapping-window / regime artifact. The tier with genuine,
robust, out-of-sample predictive power is **SMALL**. Two more findings fall out:
- **Equal-weight ≈ IC-weighted; best-single is worse.** Combining the production
  factors helps, but *optimizing* the weights beyond equal-weighting (with learned
  signs) adds nothing OOS. This is direct evidence **against** the elaborate
  `optimize_weights` / RETURN / SHARPE variant machinery.
- **`pt_upside` and `eps_growth` cannot be tested here at all** — they are absent
  from the 35-month panel (analyst PT is episodic, snapshotted only since 2026). The
  two factors that dominate the in-sample variant weights have *zero* OOS validation.

**Net assessment:** the engineering, data discipline, PIT rigor, and observability
are genuinely strong and unusually honest. On predictive skill: **SMALL-cap stock
selection is validated out-of-sample** (IC ≈ 0.04, t ≈ 2.2, gross of costs) using an
equal-weighted composite of the production factors. **LARGE and MID are not validated**
and show ~zero OOS skill. The in-sample t=7–9 figures (esp. `pt_upside`) remain
unproven and partly suspect. Caveat before trading SMALL: IC ≈ 0.04 is real but
modest and **gross** — SMALL carries 150 bps round-trip costs and liquidity limits,
so the next step is turning this IC into a net-of-cost, turnover-aware portfolio return
before sizing capital.

**The validation gate (`tools/validate_rank_skill.py`).** The agreed go/no-go test
before deploying any capital: per-tier **top-decile-minus-bottom-decile** forward-return
spread, computed on **non-overlapping** windows, with a 95% confidence band. It will
**not** declare a tier "PROVEN" until the spread is reliably positive over **≥6
independent periods** (roughly 4–5 more months of accumulation). Current verdict for
every tier: **NOT enough data — do not deploy capital yet.**

**Net assessment:** the engineering, data discipline, PIT rigor, and observability
are genuinely strong and unusually honest. The *predictive* claim — that the model
can pick winning stocks — is **unproven** and the limited live evidence is consistent
with "no stock-selection skill yet, only market beta."

---

## 13. The mutual-fund research module (separate product surface)

A self-contained MF research section (research-only, not part of stock scoring):
- **14,364 schemes** from AMFI; defaults to an **investable-only** cut (~8,492) with
  a "show all" toggle (ADR 0029).
- Daily NAV refresh, monthly metrics (returns/risk/rolling-returns/category stats),
  and **scraped portfolio holdings for 3,959 schemes** (via ETMoney).
- Cockpit pages: `/mutual-funds`, fund detail with a Holdings tab, fund compare.
- Note a structural invariant: one ETMoney URL maps to ~2.6 AMFI scheme codes via a
  shared `etm_id` (1→N), which the holdings writes must preserve.
This MF data is arguably the most **differentiated, non-alpha-dependent asset** in
the project (its value doesn't depend on stock-ranking skill).

---

## 14. Key architectural decisions (ADR index)

ADRs live in `docs/decisions/` (write-once, ≤30 lines each). The load-bearing ones:
- **0004** — no base classes / no YAML (plain functions + config dict).
- **0005** — tier-aware scoring (rank within cap tier only).
- **0007** — fresh v2 rebuild, v1 kept for rollback.
- **0010** — PIT-strict corporate-action adjustment at compute time.
- **0017** — two-tier factor registry (`BACKTEST_SIGNALS` + `FACTOR_LIBRARY`).
- **0019 / 0023 / 0024 / 0025 / 0027** — the observability stack (sensors, health
  center, eligibility registry, PIT replay, lineage).
- **0020** — PT data model v2: sell-side PT = yfinance only, LLM fields narrative-only.
- **0021** — pick-eligibility gate (weight ≥0.50 + ≥60 price rows + ≥50% fundamental coverage).
- **0022** — per-factor backtest cadence with Newey-West standard errors.
- **0026** — MICRO carved out as a 4th tier.
- **0028** — two weight variants (RETURN, SHARPE), promotion deferred.
- **0030** — banking metrics sourced from Screener.in, scoped to 158 banks+NBFCs.

---

## 15. Document & process conventions (so advice fits the workflow)

- **3 files always in head:** `README.md`, `CLAUDE.md` (rules for working here),
  `HANDOFF.md` (current state: "Left off / Pick up here / Watch out").
- **3 folders:** `docs/plans/` (what's being built; `0000-checklist.md` is the master
  view), `docs/decisions/` (ADRs), `docs/reference/` (how things work).
- **Session protocol:** `/catchup` (read state) → work → `/handoff` (update state, file
  ADRs, commit). Skipping `/handoff` is cited as the biggest source of context loss.
- **A knowledge graph** (graphify) indexes the codebase (~1,792 nodes) for navigation;
  frozen on a 2026-05-23 snapshot.

---

## 16. What's genuinely good, what's weak, and the open questions

**Strong:**
- PIT discipline, corporate-action correctness, and a real 36-month historical panel.
- Observability: silent-failure prevention, health email + push, lineage, PIT replay.
- Honesty: the project's own docs admit the ranking isn't validated yet.
- The MF holdings dataset and the dossier/narrative layer as standalone product assets.

**Validated (new, 2026-05-29):**
- **SMALL-cap selection has genuine out-of-sample skill.** Walk-forward over 35
  months of PIT history (§12, `tools/walk_forward.py`): OOS IC ≈ 0.04, t ≈ 2.2, 95%
  CI > 0, positive in 71–82% of 23 unseen months. Non-circular. Equal-weight is as
  good as any optimized weighting.

**Weak / unproven:**
- **LARGE and MID show ~zero OOS skill** (walk-forward). The live "MID +0.076" was an
  overlapping-window artifact and did not survive 23 non-overlapping OOS months.
- **Weight optimization adds nothing OOS** — equal-weight ties IC-weighting; the
  RETURN/SHARPE variant machinery is not justified by evidence.
- **`pt_upside` / `eps_growth` have zero OOS validation** — absent from the historical
  panel; their in-sample t=7–9 cannot be confirmed.
- t-stats are in-sample and selection-biased; `pt_upside`'s edge is suspect.
- A factor (`financial_signal`) whose sign flips by tier — overfitting risk.
- Over-engineered relative to validated edge: ~80 tables, 40 pipeline steps, two
  weight optimizers, MICRO tier, MF scraper — all wrapped around a core that hasn't
  cleared the predictive bar.
- Single VM, single SQLite file (now 2 GB) — fine for research, a scaling ceiling later.

**Open questions the owner is actively weighing:**
- NBFC GNPA fallback source (RBI XBRL vs annual-report scrape).
- Whether to promote a weight variant to production, and on what gate.
- Whether `pt_upside`'s t=7–9 is real (re-test after ≥3 monthly snapshots, ~Aug 2026).
- For deploying real capital: should it be the *picks* (unproven), a cheap
  equal-weight beta tilt (the only effect visible so far), or a productized
  data/research service (note: selling stock advice in India requires **SEBI RIA
  registration** — a hard regulatory constraint).

---

## 17. Mini-glossary

- **Factor / signal** — one predictive number per stock.
- **Tier / cap_tier** — market-cap bucket (LARGE/MID/SMALL/MICRO); ranking is always within-tier.
- **PIT (point-in-time)** — using only data knowable on the historical date being tested.
- **t-stat** — statistical significance of a factor's return relationship; |t|≥1.5/2.0 are the project's bars.
- **IC / ICIR** — information coefficient (rank-correlation of factor to forward return) / its information ratio (mean ÷ vol).
- **Decile spread** — return of best-ranked 10% minus worst-ranked 10%; the honest test of ranking skill.
- **ADTV** — average daily traded value (₹ crore); a liquidity floor.
- **SID** — the project's internal Tickertape-sourced stock ID (≠ NSE ticker).
- **GNPA / NNPA / NII / CASA / CAR** — banking metrics: gross/net non-performing assets, net interest income, current+savings deposit ratio, capital adequacy ratio.
- **NBFC** — non-banking financial company.
- **Dossier** — the AI-written one-page thesis per top pick.
- **Cockpit** — the FastAPI web console for inspecting the system.
- **Quality gate** — pre-ranking filter/penalty applied to small caps.
- **Regime** — VIX-based market state (CALM/NORMAL/CAUTION/CRISIS) that tilts tier allocation.
- **SEBI RIA** — Securities and Exchange Board of India Registered Investment Adviser; required to sell stock advice for money in India.

---

*To use this file: paste it as context to any AI assistant, then ask your specific
question (e.g. "given this setup, how should I prove the small-cap factor works?"
or "critique my data sources" or "how would I turn this into a SEBI-compliant
product?"). It is intentionally self-contained.*
