# Alpha Signal v3 — Project Context for Claude Code

> AI-Native Daily Stock Intelligence for the Indian Retail Investor
> Owner: Amit Bhagat | Bengaluru | Oracle Cloud Ubuntu VM
> Version 3.0 | April 2026

---

## Critical Rules — Read Before Every Task

1. **Always activate venv first:** `source ~/alpha-signal/venv/bin/activate`
2. **Never run two harvester scripts simultaneously** — doubles request rate, risks IP block
3. **Never call `build_universe()`** — broken (KeyError: 'stock'). Always use `--resume` to load existing `universe.csv`
4. **Tickertape SIDs ≠ NSE tickers** — e.g. REDY not DRRD, BJFN not BJFIN, HDBK not HDFCBANK. Always use universe.csv SIDs
5. **Smoke test with 3 stocks** before any full run
6. **Checkpoint every 200 stocks** in any harvester. Resume via harvest_log.json
7. **2-second delay** between API calls minimum
8. **Credentials live in `run_pipeline.sh`** as `export` statements — not in `~/.bashrc`, never in code
9. **Smart quotes from copy-paste break shell scripts** — always retype quotes manually
10. **CSV checkpoints** don't exist until the 200-stock milestone; sanity checks must wait for that point
11. **pip installs:** always use `--break-system-packages` flag
12. **`cap_tier` must be assigned before any ranking operation** — never rank without knowing segment
13. **Never rank across tiers** — always `groupby('cap_tier').rank(pct=True)` for all factor percentile calculations
14. **Financial sector stocks route through `34_financial_model.py`** — never through main screener value/quality signals. D/E, P/E, Piotroski are meaningless for banks/NBFCs.
15. **Cyclical sector stocks** (Metals, Oil & Gas, Chemicals) must use cycle-normalized valuations, never raw P/E

---

## v3 Philosophy — Core Principles

1. Use what we have built. Never rebuild from scratch.
2. Baby steps. One validated signal at a time. No Mt. Everest jumps.
3. Data pipeline first. Complete data foundation before signal work.
4. Validate before adding complexity. Backtester must confirm IC before any signal is trusted.
5. AI at every layer. Not just the dossier — signals, weights, discovery, and self-improvement.
6. India-specific always. Emerging market research over US-centric papers.
7. Cost discipline. Rs 450/month now. Never add paid sources without proven ROI.
8. **Signals live in their natural market-cap habitat.** What fails universe-wide may work within a segment. Always test per-segment before discarding a signal.
9. **Quality is a gate in small caps, a signal in large caps.** The function of a factor changes with the universe it operates in.
10. **Transaction costs dictate signal choice.** Momentum only in liquid large/mid caps. Value only where mispricing persists — small caps. High-turnover signals belong in the large-cap sleeve only.

---

## v3 Architecture — Five Layers

| Layer | What it does | Current state | v3 target |
|-------|-------------|---------------|-----------|
| **Routing Layer** | Assign cap tier, route financials/cyclicals to sub-models | NEW — not yet built | `cap_tier` in universe.csv, routing logic in pipeline |
| Data Pipeline | Fetch, store, refresh all data sources | ~100% complete (A1-A5 done) | + banking metrics, VIX, 3yr prices, commodity prices |
| Signal Layer | Compute research-backed factors **within segment** | B1-B10 done (universe-wide) | Segment-specific factor sets, quality gate for small caps |
| Model Layer | Combine signals **per segment** into ranked predictions | Linear weighted scorecard, gut-feel weights | 3 segment models + financial sub-model + cyclical overlay |
| Output Layer | Construct portfolio, deliver ranked picks with explanation | Email + Streamlit + AI dossier | 40/30/30 + VIX overlay, SHAP dossier with tier attribution |

Each layer must be healthy before the next is added.

### v3 Segment Architecture

```
Universe (2,500 stocks)
    │
    ├── Tier Assignment (L/M/S by SEBI market cap rank)
    │     L = Nifty 100 (ranks 1-100)
    │     M = ranks 101-250
    │     S = ranks 251+
    │
    ├── Route: sector == "Financial Services"? → Financial Sub-Model (34)
    │
    ├── Route: sector in [Metals, Oil & Gas, Chemicals]? → Cyclical Overlay (35)
    │
    ├── LARGE CAP MODEL
    │     ├── Signals: Quality + Risk-adj Momentum + Low Volatility + Consensus
    │     ├── Rank within segment (groupby cap_tier)
    │     ├── ADTV filter: ≥ ₹10 Cr
    │     └── Select top 10-15
    │
    ├── MID CAP MODEL
    │     ├── Signals: Quality + Momentum (liquidity-filtered) + Consensus (where coverage exists)
    │     ├── Rank within segment
    │     ├── ADTV filter: ≥ ₹5 Cr
    │     └── Select top 10-15
    │
    ├── SMALL CAP MODEL
    │     ├── QUALITY GATE (hard exclusion — eliminate bottom 30-40%):
    │     │     • Net loss in 2+ of last 3 years
    │     │     • Cumulative 3-year negative free cash flow
    │     │     • Promoter pledge > 50%
    │     │     • Piotroski F-Score ≤ 3
    │     │     • Altman Z″-Score < 1.1 (emerging market distress)
    │     │     • SEBI GSM Stage IV+ / shell company
    │     ├── Signals (survivors only): Value/Earnings Yield + Promoter Buying + Quality composite (soft)
    │     ├── Rank within survivors
    │     ├── ADTV filter: ≥ ₹1 Cr
    │     └── Select top 10-15
    │
    └── PORTFOLIO CONSTRUCTION
          ├── Baseline weights: 40% Large / 30% Mid / 30% Small
          ├── VIX regime: >25 → 55/25/20 | <13 → 30/35/35
          ├── Sector cap: ≤5 stocks from any sector in final portfolio
          ├── Stock cap: ≤5% weight per stock
          └── Output: 30-50 stocks with tier + signal attribution
```

### Factor-Segment Evidence Map (from deep research April 2026)

| Factor | Large Cap | Mid Cap | Small Cap | Source |
|--------|-----------|---------|-----------|--------|
| Value (earnings yield, P/B) | Weak/Negative | Neutral | **Strong** (primary signal) | IIM-A FF library; own backtest t=2.64 |
| Quality (ROE, low leverage) | Signal (rank) | Signal (rank) | **Hard gate** (exclude junk) | Asness et al 2018; Marcellus +5.5% p.a. |
| Momentum (risk-adjusted) | **Strong** (10.7% p.a.) | Moderate (liq-filtered) | Reverses in illiquid stocks — DROP | Raju & Chandrasekaran 2019; Pacific-Basin FJ |
| Consensus / Earn revisions | **Strong** (dense coverage) | Moderate (5-8 analysts) | Sparse/absent — downweight to 0.2x | Own backtest t=3.47 |
| Promoter buying | Weak (low info asymmetry) | Moderate | **Strong** (high info asymmetry) | Brochet, Lee & Srinivasan (NYU Stern) |
| Low Volatility | **Strong** | Moderate | Negative excess returns — DROP | Joshipura & Peswani 2017 |
| Piotroski F-Score | Weak (t=0.33 universe-wide) | Gate + signal | **Hard gate** (F≤3 → exclude) | Walkshäusl 2020; own backtest |
| Smart Money (bulk deals) | Signal (bulk deals are large-cap phenomenon) | Moderate | Weak (low ADTV) | Own data |

### Rebalance Cadence by Segment

| Segment | Rebalance | Rationale | Est. round-trip cost |
|---------|-----------|-----------|---------------------|
| Large cap | Monthly | Low impact cost (24-32 bps), momentum is high-turnover | ~30 bps |
| Mid cap | Quarterly | Moderate impact (32-72 bps), balance turnover vs alpha | ~50 bps |
| Small cap | Semi-annual | High impact (72-222+ bps), value/quality are slow-moving | ~150 bps |

**STT floor: ~20 bps round-trip on all delivery trades (0.1% buy + 0.1% sell). This is unavoidable.**

---

## Project Layout

```
~/alpha-signal/
├── scripts/                    # Numbered pipeline scripts (00–37+)
│   ├── 00-11                   # Core pipeline: fetch, screen, sentiment, AI classify, dossier, email
│   ├── 14_macro_pulse.py       # 22 macro indicators, 27 sector scores
│   ├── 16_smart_money.py       # NSE bulk/block deals + delivery %
│   ├── 17_forensic_guard.py    # Beneish M-Score + Altman Z-Score
│   ├── 18_earnings_calendar.py # NSE event calendar
│   ├── 22_data_harvester.py    # Income, balance sheet, cash flow, shareholding
│   ├── 23_slug_mapper.py       # SID → Tickertape URL slug mapping
│   ├── 24_backtester.py        # 3 modes (PIT/proxy/recon) + --by-tier flag (v3)
│   ├── 25_analyst_harvester.py # Analyst consensus from __NEXT_DATA__
│   ├── 26_snapshot_archiver.py # Cumulative enriched CSV for backtesting
│   ├── 27_piotroski.py         # 9-factor F-Score
│   ├── 28_accruals.py          # Accruals quality + persistence
│   ├── 29_consensus_signal.py  # Analyst consensus signal
│   ├── 30_promoter_signal.py   # Promoter buying momentum
│   ├── 31_group_tagger.py      # Business group risk tagger
│   ├── 32_regime_module.py     # VIX regime + allocation shift (v3 — NEW)
│   ├── 33_quality_gate.py      # Small-cap hard quality gate (v3 — NEW)
│   ├── 34_financial_model.py   # Bank/NBFC sub-model (v3 — NEW)
│   ├── 35_cyclical_overlay.py  # Cycle-position-aware valuation (v3 — NEW)
│   ├── 36_segment_models.py    # 3 tier-specific scoring engines (v3 — NEW)
│   ├── 37_xgboost_segment.py   # Per-segment XGBoost + SHAP (v3 — NEW)
│   ├── tickertape_utils.py     # Reusable Tickertape client + all parsers
│   ├── page_methodology.py     # "How It Works" Streamlit page
│   ├── page_ai_assistant.py    # AI Assistant Streamlit page
│   ├── alpha_assistant_prompt.py # Full system prompt for AI Assistant
│   └── data_query_engine.py    # Data access functions
├── data/
│   ├── harvester/              # universe.csv (+ cap_tier, adtv_6m columns in v3)
│   ├── analyst/                # consensus.csv
│   ├── smart_money/            # bulk_30d.csv, delivery_30d.csv, smart_money_score.csv
│   ├── events/                 # earnings_calendar.csv
│   ├── snapshots/              # all_snapshots.csv, snapshot_YYYY-MM-DD.csv
│   ├── signals/                # piotroski.csv, accruals.csv, consensus.csv, promoter.csv
│   ├── backtest/               # signal_validation_report.csv, signal_validation_by_tier.csv (v3)
│   ├── banking/                # nim.csv, gnpa.csv, banking_scores.csv (v3 — NEW)
│   ├── cyclical/               # commodity_prices.csv, cycle_position.csv (v3 — NEW)
│   └── reference/              # business_groups.csv, gsm_list.csv (v3)
├── research_papers/
│   └── deliverables/           # full_research_report.md, research_changes_for_claude_code.md,
│                               # hierarchical_factor_model_research.md (v3)
├── config/
│   └── settings.py             # Centralised config + SEGMENT_CONFIG (v3)
├── venv/                       # Python virtual environment
├── run_pipeline.sh             # Cron orchestrator (9AM IST daily)
├── CLAUDE.md                   # This file
└── .git/                       # Private repo
```

---

## What's Already Built and LIVE

| Component | Status |
|-----------|--------|
| Oracle Cloud VM — 4 OCPU ARM, 24GB RAM, Ubuntu 24.04 | LIVE |
| Pipeline scripts 00-11 (fetch, screen, sentiment, AI classify, dossier, email) | LIVE |
| Forensic Guard — Beneish M-Score + Altman Z-Score (script 17, DEBUG=False) | LIVE |
| Macro Pulse — 22 macro indicators, 27 sector scores (script 14) | LIVE |
| Entity-matched news (11 RSS feeds, curated aliases, blocklist) | LIVE |
| AI routing — Haiku (bulk) + Sonnet (dossier), ~Rs 15/day | LIVE |
| Streamlit dashboard — 8 pages with sidebar nav | LIVE |
| "How It Works" page (page_methodology.py) | LIVE |
| AI Assistant page (page_ai_assistant.py) | LIVE |
| GitHub private repo + auto-backup via run_pipeline.sh | LIVE |
| Cron automation — 9AM IST daily, 10:30AM Saturday refresh | LIVE |
| NSE Smart Money Accumulator — 16_smart_money.py | LIVE |
| Earnings Calendar — 18_earnings_calendar.py | LIVE |
| Snapshot Archiver — 26_snapshot_archiver.py | LIVE |
| Piotroski F-Score — 27_piotroski.py, 1,978 stocks | LIVE |
| Accruals Quality + Persistence — 28_accruals.py, 2,426 stocks | LIVE |
| Analyst Consensus Signal — 29_consensus_signal.py, 2,398 stocks | LIVE |
| Promoter Buying Momentum — 30_promoter_signal.py, 2,438 stocks | LIVE |
| Business Group Risk Tagger — 31_group_tagger.py | LIVE |
| Signal Validation Backtester — 24_backtester.py, 3 modes | LIVE |

---

## Data Inventory — Harvested CSVs

| File | Location | Rows | Content | Status |
|------|----------|------|---------|--------|
| universe.csv | data/harvester/ | 2,500 | sid, name, ticker, sector, in_nifty500 | COMPLETE |
| quarterly_income.csv | data/harvester/ | 21,571 | Revenue, EPS, profit — 10 quarters | COMPLETE |
| annual_balancesheet.csv | data/harvester/ | 19,196 | Assets, equity, debt — 10 years | COMPLETE |
| annual_cashflow.csv | data/harvester/ | 19,155 | OCF, capex, FCF — 10 years | COMPLETE |
| slug_map.csv | data/harvester/ | 2,500 | sid → Tickertape URL slug | COMPLETE |
| shareholding.csv | data/harvester/ | 14,135 | Promoter%, FII%, MF%, DII% — 6 quarters | COMPLETE |
| consensus.csv | data/analyst/ | 2,439 | Price target, buy%, EPS, revenue forecasts | COMPLETE |
| errors.csv | data/harvester/ | ~60 | ETFs + micro-caps with no data | COMPLETE |
| bulk_30d.csv | data/smart_money/ | grows daily | Net bulk buy vol, repeat buyers | LIVE |
| delivery_30d.csv | data/smart_money/ | 2,448 | 30-day avg delivery% per stock | LIVE |
| smart_money_score.csv | data/smart_money/ | 2,464 | Combined smart money signal | LIVE |

### v3 Data Gaps (to be harvested)

| Data | Source | Priority | Session |
|------|--------|----------|---------|
| ~~Market cap + cap_tier for 2,500 stocks~~ | ~~yfinance `.info`~~ | ~~**P0**~~ | ✅ C12 DONE |
| ~~ADTV 6-month for 2,500 stocks~~ | ~~yfinance download~~ | ~~**P0**~~ | ✅ C12 DONE |
| India VIX daily (3yr+) | yfinance `^INDIAVIX` | **P1** | C13 |
| 3yr OHLCV for all 2,500 stocks | yfinance batch | **P1** | C13 |
| Banking metrics (NIM, GNPA, NNPA, PCR, CASA, ROA, PPOP) | Tickertape + quarterly results | **P2** | D15 |
| Commodity prices 7yr (Brent, HRC steel, LME aluminium) | yfinance (`BZ=F`, etc.) | **P2** | D16 |
| SEBI GSM/shell company list | NSE website | **P2** | D14 |
| Free-float shares | Tickertape or NSE | **P2** | D17 |

Total disk: ~14 MB current. Projected with 3yr prices: ~50 MB. All at ~/alpha-signal/data/

---

## Tickertape API — Two Tiers

**Tier 1: Bharat_sm_data library (sid-based)**
- `from Fundamentals.TickerTape import Tickertape`
- Functions: get_income_data(sid), get_balance_sheet_data(sid), get_cash_flow_data(sid), get_score_card(sid)

**Tier 2: __NEXT_DATA__ JSON scrape (slug-based)**
- Slug format: `stocks/reliance-industries-RELI` (no leading slash, sid appended)
- Slug discovery: GET `tickertape.in/stocks/{sid}` → follow HTTP redirect

**Confirmed __NEXT_DATA__ JSON paths (March 2026):**
| Data | Path | Notes |
|------|------|-------|
| Analyst consensus | props.pageProps.securitySummary.forecast | totalReco, percBuyReco |
| Price target history | props.pageProps.forecastsHistory.price | Array of {date, value} |
| EPS forecast | props.pageProps.forecastsHistory.eps | Array of {value, date, change} |
| Revenue forecast | props.pageProps.forecastsHistory.revenue | Array of {value, date, change} |
| Shareholding | props.pageProps.securitySummary.holdings.holdings | Quarterly entries |
| Key ratios | props.pageProps.securitySummary.keyRatios | Array of {backL, value} |
| Financial summary | props.pageProps.securitySummary.financialSummary | 5yr revenue/profit |
| Dividends | props.pageProps.securitySummary.dividends | past + upcoming arrays |
| Events | props.pageProps.securitySummary.events | Earnings, AGMs, announcements |
| AI summary | props.pageProps.securitySummary.aiSummary.summary | Text string |
| Ratings | props.pageProps.securitySummary.ratings | NULL without login session |

---

## Network — What Works vs Blocked (Oracle Cloud IP)

**Working:** tickertape.in, analyze.api.tickertape.in, archives.nseindia.com, yfinance (.NS)
**Blocked (403):** get_ticker() search, MoneyControl, www.nseindia.com main site

---

## Harvester Conventions

- Script naming: sequential numbers (`16_smart_money.py`, `17_forensic_guard.py`)
- CLI flags: `--resume`, `--refresh`, `--flag-only`, `--by-tier` (v3)
- Checkpoint: save CSV every 200 stocks
- Resume: read `harvest_log.json` for last completed index
- Error handling: log failures to errors.csv, skip and continue

---

## Phase A — Data Pipeline (Sessions 1-5) ✅ COMPLETE

**Goal:** Complete data pipeline. All sources harvested and refreshing on schedule.

| Session | Build | Status |
|---------|-------|--------|
| A1 | Cash flow harvester — 2,500 stocks | ✅ DONE |
| A2 | Slug mapper + shareholding harvester | ✅ DONE |
| A3 | Analyst consensus harvester | ✅ DONE |
| A4 | NSE smart money accumulator | ✅ DONE |
| A5 | Earnings calendar + snapshot archiver | ✅ DONE |

---

## Phase B — Signal Build (Sessions 6-10) ✅ COMPLETE

**Goal:** Add 5 research-backed signals. Each validated before next is built.

| Session | Signal | Status |
|---------|--------|--------|
| B6 | Piotroski F-Score | ✅ DONE — 27_piotroski.py |
| B7 | Accruals quality + persistence | ✅ DONE — 28_accruals.py |
| B8 | Smart money + Piotroski + Accruals integration | ✅ DONE — 08_integrate_sentiment.py v6 |
| B9 | Analyst consensus signal | ✅ DONE — 29_consensus_signal.py |
| B10 | Promoter buying momentum | ✅ DONE — 30_promoter_signal.py |

---

## Phase C — Validation + Tier Infrastructure (Sessions 11-13)

**Goal:** Validate signals. Build cap-tier infrastructure. Prove signals work per-segment.

| Session | Build | Success Criteria | Status |
|---------|-------|-----------------|--------|
| ~~C11~~ | ~~Backtester — IC per signal, t-stat, decay rate~~ | ~~>=3 signals with t-stat >= 2.5~~ | ✅ DONE |
| ~~C12~~ | ~~Tier infrastructure + within-segment ranking~~ | ~~All ranking operations use `groupby('cap_tier')`~~ | ✅ DONE |
| ~~C13~~ | ~~Segment-stratified backtest + VIX regime~~ | ~~≥1 signal per segment with t-stat ≥ 2.5 within segment~~ | ✅ DONE |

### Session C11 — Signal Validation Backtester ✅ DONE

**Results — Proxy mode (N=35 monthly periods):**

| Signal | Mean IC | t-stat | Verdict |
|--------|---------|--------|---------|
| consensus | +0.062 | **3.47** | **KEEP** — strongest signal (large/mid cap sleeve) |
| piotroski | +0.006 | 0.33 | Demoted universe-wide — **retest per-segment in C13** |
| accruals | -0.039 | -2.61 | INVERTED in India — **negative screen only** |
| promoter | -0.002 | -0.15 | Failed universe-wide — **retest in small-cap sleeve in C13** |

**Results — Recon mode (N=28-30 periods):**

| Signal | Mean IC | t-stat | Verdict |
|--------|---------|--------|---------|
| value_recon | +0.055 | **2.64** | **KEEP** — first validated fundamental signal (small-cap driver) |
| composite_recon | +0.036 | 1.83 | Weak — possible interaction effect |
| momentum_recon | +0.018 | 0.74 | Failed — **retest in large-cap sleeve only in C13** |
| quality_recon | -0.007 | -0.50 | Failed as signal — **repurpose as gate in small caps** |
| growth_recon | +0.006 | 0.34 | Failed — only 16 periods, needs more history |

**Key v3 insight:** Signals that "failed" on the unified universe are expected to show per-segment significance in C13. Value draws power from small caps; momentum should work in large caps; promoter buying should work in small caps where info asymmetry is highest.

### Session C12 — Tier Infrastructure + Within-Segment Ranking ✅ DONE

**Results (2026-04-03):**

| Component | Result |
|-----------|--------|
| LARGE cap tier | 100 stocks (market cap rank 1–100) |
| MID cap tier | 150 stocks (rank 101–250) |
| SMALL cap tier | 2,250 stocks (rank 251+) |
| Market cap coverage | 1,722 / 2,500 stocks (778 micro-caps not on yfinance) |
| ADTV coverage | 1,993 / 2,500 stocks |
| Median LARGE ADTV | ~₹1,200 Cr/day |
| Median MID ADTV | ~₹150 Cr/day |

**Build:**
1. Add `cap_tier` column to `universe.csv` (LARGE/MID/SMALL by SEBI market cap rank)
2. Add `adtv_6m` column (6-month average daily turnover value in ₹ Cr)
3. Modify `03_screener.py`: all `rank(pct=True)` → `groupby('cap_tier').rank(pct=True)`
4. Modify signal scripts (28, 29, 30, 16): within-segment percentile ranking
5. Modify `08_integrate_sentiment.py`: tier-aware confidence multipliers

**Confidence multipliers for integration (08):**

| Signal | Large | Mid | Small | Rationale |
|--------|-------|-----|-------|-----------|
| Consensus | 1.0x | 0.6x | 0.2x | Analyst coverage drops off a cliff |
| Value/EY | 0.5x | 0.8x | 1.0x | Value premium concentrates in small caps |
| Piotroski | 0.3x | 0.6x | Gate (not signal) | Quality gate in small caps per Asness |
| Smart Money | 1.0x | 0.8x | 0.3x | Bulk deals are large-cap phenomenon |
| Promoter | 0.4x | 0.8x | 1.0x | Info asymmetry highest in small caps |
| Momentum | 1.0x | 0.8x | 0.0x | Reverses in illiquid small caps — DROP |

**Files changed:** universe.csv, 03_screener.py, 28_accruals.py, 29_consensus_signal.py, 30_promoter_signal.py, 16_smart_money.py, 08_integrate_sentiment.py

### Session C13 — Segment-Stratified Backtest + VIX Regime ✅ DONE

**Files created/modified:**
- `scripts/24_backtester.py` — added `--by-tier` flag; cap_tier merged into proxy/pit/recon_df
- `scripts/33_regime_module.py` — NEW: India VIX fetch, CALM/NORMAL/CAUTION/CRISIS classification with hysteresis
- `data/backtest/signal_validation_by_tier.csv` — per-signal per-tier IC/ICIR/t-stat (N=35 proxy periods)
- `data/reference/india_vix.csv` — 734 trading days of India VIX (2023-04-03 to 2026-04-02)
- `data/reference/regime_state.json` — current regime + allocation weights
- `data/reference/regime_history.csv` — full daily regime history for backtester
- `run_pipeline.sh` — `33_regime_module.py --refresh` added before screener step

**C13 Results — Proxy mode (N=35 monthly periods, within-tier):**

| Signal | LARGE (t) | MID (t) | SMALL (t) | Verdict |
|--------|-----------|---------|-----------|---------|
| consensus | **3.52 ✓ KEEP** | 2.20 WEAK | 2.44 WEAK | Largest alpha in LARGE as expected |
| accruals | -2.06 DROP | -1.73 DROP | -2.34 DROP | Consistently INVERTED — use as negative screen only |
| piotroski | 1.16 DROP* | -0.21 DROP | 0.04 DROP | *Only 5 LARGE periods — need more history |
| promoter | 0.50 DROP | -0.55 DROP | -0.05 DROP | FAILS in proxy mode — retest with recon/history |

**Key findings vs hypotheses:**
- ✅ Consensus strong in LARGE (t=3.52) — hypothesis confirmed
- ⚠️ Consensus also WEAK-positive in MID+SMALL (not absent as expected — useful)
- ❌ Promoter failed to come alive in SMALL in proxy mode (CRITICAL: proxy projects current values; historical buying patterns need recon mode + more snapshot history)
- ✅ Accruals confirmed INVERTED in all tiers — use as negative exclusion screen always
- ⚠️ Piotroski inconclusive in proxy mode (5 periods LARGE, no in-sample data for PIT signals)

**Current regime (as of 2026-04-02):**
- VIX: 25.5 → CAUTION (since 2026-04-01, transitioned from NORMAL)
- Allocation: LARGE=55% | MID=25% | SMALL=20%
- Hysteresis worked: VIX crossed 25 on 2026-03-23/27/30 before confirming on 2026-04-01

**VIX regime thresholds:**
- VIX ≤ 13 (CALM): 30/35/35 (overweight mid+small)
- VIX 13-25 (NORMAL): 40/30/30 (baseline)
- VIX 25-35 (CAUTION): 55/25/20 (flight to large cap)
- VIX > 35 (CRISIS): 70/20/10 (maximum defensive)

Hysteresis: 3 consecutive days in new regime required before transition confirmed.

**Next steps (C14/D14):**
- Run `--recon --by-tier` when more snapshot history exists (6+ months) to validate promoter + piotroski in small caps
- D14: Small-cap quality gate — use `34_quality_gate.py` (33 is taken by regime_module)

### Session C13b — Full Historical Signal Reconstruction ✅ DONE

**Files created/modified:**
- `scripts/38_signal_reconstructor.py` — NEW: reconstructs 6 signals at 36 monthly eval dates with proper filing lags
- `scripts/26_snapshot_archiver.py` — ENHANCED: `archive_signal_snapshot()` for daily PIT accumulation
- `data/backtest/reconstructed_signals.csv` — 25,941 rows (35 periods × 658-846 stocks)
- `data/backtest/reconstructed_ic_by_tier.csv` — per-signal per-tier IC with t-stats
- `data/snapshots/signal_snapshots.csv` — NEW: cumulative daily signal snapshot (started 2026-04-03)

**C13b Results — 38_signal_reconstructor.py (full PIT reconstruction, 35 periods):**

| Signal | LARGE (t) | MID (t) | SMALL (t) | Verdict |
|--------|-----------|---------|-----------|---------|
| cf_accruals_ratio | 0.20 DROP | **3.17 ✓ KEEP** | 0.84 DROP | Sloan anomaly confirmed in MID |
| book_to_price | 0.79 DROP | 2.38 WEAK | **2.25 WEAK** | Value signal emerging |
| piotroski_f_score | 0.51 DROP | 2.20 WEAK | 1.55 WEAK | Only 18 periods (needs more) |
| earnings_yield | 1.57 WEAK | 0.99 DROP | 1.71 WEAK | Consistent direction across tiers |
| mom_12m_adj | -1.64 WEAK | 0.12 DROP | 1.07 DROP | INVERTED in LARGE — momentum fails here |
| mom_6m_adj | 0.00 DROP | 0.85 DROP | 0.75 DROP | No momentum signal found |
| promoter_qoq | 0.04 DROP | 0.81 DROP | 0.34 DROP | Only 13 periods — more history needed |

**C13b Results — --recon --by-tier (existing backtester, 28 periods):**

| Signal | LARGE (t) | MID (t) | SMALL (t) | Verdict |
|--------|-----------|---------|-----------|---------|
| value_recon | 1.08 DROP | 1.67 DROP | **3.17 ✓ KEEP** | Value premium confirmed in SMALL |
| momentum_recon | 0.19 DROP | 0.48 DROP | 0.49 DROP | No momentum signal found |
| quality_recon | -0.15 DROP | -0.65 DROP | -0.99 DROP | Quality as gate not signal confirmed |
| growth_recon | 0.51 DROP | -0.39 DROP | 0.00 DROP | No growth signal |

**Consolidated validated signals (as of 2026-04-03):**

| Signal | Source | Segment | t-stat | Status |
|--------|--------|---------|--------|--------|
| consensus | proxy | LARGE | 3.52 | ✓ KEEP — primary large-cap signal |
| value_recon (earnings yield) | recon | SMALL | 3.17 | ✓ KEEP — primary small-cap signal |
| cf_accruals (quality) | reconstructor | MID | 3.17 | ✓ KEEP — primary mid-cap quality screen |
| consensus | proxy | MID | 2.20 | ~ WEAK — secondary signal |
| consensus | proxy | SMALL | 2.44 | ~ WEAK — moderate use even in small |
| book_to_price | reconstructor | MID | 2.38 | ~ WEAK — complementary value signal |
| accruals (inverted) | proxy ALL tiers | ALL | -2.0 to -2.3 | INVERTED — use as negative screen only |

**Coverage note:** Only 847/2,500 stocks have price data (the rest haven't been downloaded yet). Running `38_signal_reconstructor.py` without `--no-download` will fetch remaining prices over 2-3 hours and provide better SMALL cap IC statistics.

**Signal snapshot accumulation:** `signal_snapshots.csv` started 2026-04-03 (day 1 of 130 needed for PIT IC testing). PIT-grade IC available approximately mid-August 2026.

**Script 38 CLI:**
```bash
python scripts/38_signal_reconstructor.py --no-download   # use cached prices
python scripts/38_signal_reconstructor.py                  # download all 2,500 prices first
python scripts/38_signal_reconstructor.py --smoke          # 3 dates, 200 stocks
python scripts/38_signal_reconstructor.py --signal value   # single signal only
```

---

## Phase D — Multi-Segment Model Build (Sessions 14-18)

**Goal:** Build the full hierarchical architecture. Three segment models + financial sub-model + cyclical overlay + portfolio construction.

| Session | Build | Output | Status |
|---------|-------|--------|--------|
| **D14** | **Small-cap quality gate** | 33_quality_gate.py, data/signals/quality_gate.csv | PENDING |
| **D15** | **Financial sub-model** | 34_financial_model.py, data/banking/ | PENDING |
| **D16** | **Cyclical overlay** | 35_cyclical_overlay.py, data/cyclical/ | PENDING |
| **D17** | **Segment models + portfolio construction** | 36_segment_models.py — REPLACES 03+08 as main engine | PENDING |
| **D18** | **XGBoost per segment + SHAP** | 37_xgboost_segment.py | PENDING (needs 6mo IC data) |

### Session D14 — Small-Cap Quality Gate

**Script:** `33_quality_gate.py`

**Hard exclusions (any one triggers removal):**
- Net loss in 2+ of last 3 fiscal years (from quarterly_income.csv)
- Cumulative 3-year negative free cash flow (from annual_cashflow.csv)
- Promoter pledge > 50% (from shareholding.csv)
- Piotroski F-Score ≤ 3 (from data/signals/piotroski.csv)
- Altman Z″-Score < 1.1 — emerging market formula: Z″ = 3.25 + 6.56(WC/TA) + 3.26(RE/TA) + 6.72(EBIT/TA) + 1.05(BV Equity/TL)
- SEBI GSM Stage IV+ or shell company listing (from reference/gsm_list.csv)

**Soft quality composite (for survivors, scored 0-1):**
- CFO/EBITDA conversion (20%)
- Piotroski F-Score (15%)
- Z″-Score (10%)
- Promoter pledge level (10%)
- Related party transactions % revenue (10%)
- Forensic ratios from Beneish components (35%)

**Expected impact:** Eliminate bottom 30-40% of small-cap universe. Marcellus evidence: +5.5% p.a. from forensic screening alone. Each F-Score point ≈ +4.93% one-year market-adjusted return.

**Gate validation metric:** Track 12-month survival rate of gated-out stocks. Target: >60% of excluded stocks should decline >30% or face adverse corporate action within 12 months.

### Session D15 — Financial Sub-Model

**Script:** `34_financial_model.py`

**Applies to:** All stocks where `sector == "Financial Services"` (Banks, NBFCs, Insurance, HFCs)

**Factor replacement map:**

| Standard factor | Financial replacement | Why |
|----------------|----------------------|-----|
| P/E | P/B + P/PPOP | Banks' earnings = lending spread - provisions. PPOP shows true operating power |
| ROE | **ROA** | Banks run 13-15x leverage. ROE misleads. ROA ≥ 1.0% = operationally sound |
| D/E | CAR (Capital Adequacy Ratio) | Leverage IS the business model. CAR measures regulatory headroom |
| Quality composite | GNPA%, NNPA%, PCR, Slippage ratio, Credit cost | Asset quality is THE quality metric for lenders |
| Moat/franchise | CASA ratio (banks) / Cost of Funds (NBFCs) | Low-cost deposits = durable competitive advantage |
| Growth | Loan book growth (capped — penalize >25%) | Aggressive lending precedes NPA crises |

**Adjusted Book Value:** `Adj_Book = Reported_BV − (GNPA × (1 − PCR/100))`
**Alpha signal:** P/B-ROE regression residual — stocks below the regression line are "cheap for quality"

**Benchmarks (2024):** ROA ≥1.0% good, NIM ≥3.0% good for banks, GNPA ≤3.0% acceptable (system GNPA = 2.8% Mar 2024), PCR ≥70% healthy, CASA ≥40% strong.

**NBFC sub-segments:** Gold loan (Muthoot, Manappuram: high NIM ~13-18%), Housing finance (low NIM ~2-3%, low credit cost), Microfinance (high risk, political sensitivity), Consumer NBFC (Bajaj Finance type).

### Session D16 — Cyclical Overlay

**Script:** `35_cyclical_overlay.py`

**Applies to:** Metals (steel, aluminium, copper), Oil & Gas (upstream, refining, marketing), Chemicals, Cement

**Normalization approach:** 7-year average (not 10 — India structural changes make 10yr unreliable: GST 2017, IND AS 2016-17, COVID)
- Metals: 7yr avg EBITDA/tonne × current capacity
- Oil upstream (ONGC, Oil India): regress operating income vs Brent crude
- Refining (BPCL, HPCL, IOC): 7yr avg Singapore complex GRM
- General cyclicals: 7yr avg EBITDA margin × current revenue

**Cycle position detector (4 indicators):**
1. Current EPS > 1.5× 7yr normalized average → PEAK territory
2. EBITDA margin > 1σ above 7yr mean → confirms peak
3. Commodity price > inflation-adjusted 7yr avg → macro confirmation
4. Rising industry capex + high margins → late cycle

**Valuation metric shift:**
- At troughs: weight P/B more heavily (earnings depressed, book value stable)
- At peaks: weight normalized EV/EBITDA (avoid low-P/E trap)
- Never use raw P/E for cyclicals

### Session D17 — Segment Models + Portfolio Construction

**Script:** `36_segment_models.py` — THIS REPLACES `03_screener.py` + `08_integrate_sentiment.py` as the main scoring engine

**Three scoring engines:**

**Large Cap (10-15 picks):**
```
score_L = w1*quality_pctile + w2*momentum_adj_pctile + w3*low_vol_pctile + w4*consensus_pctile
```
Weights: Quality 30%, Risk-adj Momentum 30%, Low Volatility 20%, Consensus 20%

**Mid Cap (10-15 picks):**
```
score_M = w1*quality_pctile + w2*momentum_liqfiltered_pctile + w3*consensus_pctile + w4*value_pctile
```
Weights: Quality 30%, Momentum 25%, Consensus 25%, Value 20%

**Small Cap (10-15 picks, after quality gate):**
```
score_S = w1*value_pctile + w2*promoter_pctile + w3*quality_composite_pctile
```
Weights: Value/EY 45%, Promoter buying 30%, Quality composite 25%

**All percentile ranks computed within segment** using `groupby('cap_tier').rank(pct=True)`.

**Portfolio construction:**
1. Select top-N from each segment
2. Apply segment weights: 40% L / 30% M / 30% S (adjusted by VIX regime from 32)
3. Within-segment weighting: score × free-float market cap (Nifty MQ50 methodology)
4. Cap at 5% per stock
5. Sector concentration cap: ≤5 stocks per sector in final portfolio
6. Financial stocks scored by 34_financial_model.py get allocated to their natural tier
7. Cyclical stocks carry cycle-position flag from 35_cyclical_overlay.py

### Session D18 — XGBoost Per Segment + SHAP

**Prerequisite:** 6+ months of segment-stratified IC data from C13 production runs.

**Script:** `37_xgboost_segment.py`

Train separate XGBoost models per tier:
- Features = tier-specific factor scores from D17
- Target = 20-day forward return quintile
- Walk-forward training: 24-month train, 6-month test
- SHAP values per stock → fed into AI dossier for explanation

---

## Phase E — Scale and Polish (Sessions 19+)

| Session | Build | Notes |
|---------|-------|-------|
| E19 | Multi-agent AI with segment-aware specialist agents | News, fundamentals, macro, smart money, signal agents |
| E20 | PEAD signal (mid-cap sleeve primarily) | Earnings surprise + 20-40 day drift |
| E21 | Continuous IC monitoring per segment, auto-retire signals | Monthly dashboard |
| E22 | Expand to full 2,500 active scoring | Currently ~500 in screener, scale to all |
| E23 | Zerodha Kite Connect — portfolio tracking | Rs 500/month, Phase E only |

---

## Financial Sub-Model — Detailed Reference

### Bank Quality Metrics (D15)

| Metric | Good | Caution | Bad | Source |
|--------|------|---------|-----|--------|
| ROA | ≥ 1.0% | 0.5-1.0% | < 0.5% | Quarterly results |
| NIM | ≥ 3.0% | 2.0-3.0% | < 2.0% | Quarterly results |
| GNPA % | ≤ 3.0% | 3.0-5.0% | > 5.0% | Quarterly results |
| NNPA % | ≤ 1.0% | 1.0-2.0% | > 2.0% | Quarterly results |
| PCR | ≥ 70% | 50-70% | < 50% | Quarterly results |
| CASA | ≥ 40% | 30-40% | < 30% | Quarterly results |
| CAR | ≥ 15% | 11.5-15% | < 11.5% (below RBI min) | Quarterly results |
| Credit Cost | ≤ 1.0% | 1.0-2.0% | > 2.0% | Derived |
| Slippage Ratio | ≤ 2.0% | 2.0-4.0% | > 4.0% | Quarterly results |

### NBFC Quality Metrics

| Metric | Good | Caution | Bad |
|--------|------|---------|-----|
| NIM | ≥ 6% | 3-6% | < 3% |
| GNPA | ≤ 4% | 4-6% | > 6% |
| D/E | ≤ 4x | 4-6x | > 6x |
| CRAR | ≥ 18% | 15-18% | < 15% |
| Cost of Funds | ≤ 8% | 8-10% | > 10% |

### Academic evidence:
- NIM has strongest positive influence on bank stock prices (β=0.583, p<0.001) — MDPI 2025
- Net NPA has significant negative effect (β=-0.251, p=0.002) — MDPI 2025
- CAR shows no meaningful direct impact on stock prices — use as risk filter, not alpha signal
- Loan book growth above 25% is a leading indicator of future NPA crisis (Indian evidence: 2004-08 boom → 2015-18 NPA crisis)

---

## Cyclical Overlay — Detailed Reference

### Sector → Commodity Mapping

| Sector | Key commodity | yfinance ticker | Normalization |
|--------|--------------|-----------------|---------------|
| Steel | HRC price | — (manual/free API) | 7yr avg EBITDA/tonne × capacity |
| Aluminium | LME Aluminium | `ALI=F` | 7yr avg EBITDA/tonne × capacity |
| Oil upstream | Brent Crude | `BZ=F` | Regression: OI = f(Brent) |
| Oil refining | Singapore GRM | — (manual) | 7yr avg GRM × throughput |
| Cement | — | — | 7yr avg EBITDA/tonne × capacity |
| Chemicals | — (diverse) | — | 7yr avg EBITDA margin × revenue |

### Cycle position action matrix

| Indicator | Trough | Mid-cycle | Peak |
|-----------|--------|-----------|------|
| Valuation metric | P/B dominant | Blend P/B + norm EV/EBITDA | Norm EV/EBITDA dominant |
| EPS vs 7yr avg | < 0.5x | 0.5-1.5x | > 1.5x |
| EBITDA margin | > 1σ below mean | Within 1σ | > 1σ above mean |
| Signal | **BUY value** | Hold | **Avoid low P/E trap** |

---

## Pre-Phase-C Fixes Applied (2026-03-31)

All 8 fixes applied before running backtester. Changes below are live in production.

| Fix | File | Change |
|-----|------|--------|
| 1 | 03_screener.py | Sector z-scores (MAD-based robust z → norm.cdf → 0-100) for value + quality |
| 2 | 03_screener.py | D/E score neutralised (=50) for Financial Services — debt is their product |
| 3 | 03_screener.py | P/E replaced with earnings yield (E/P = 1/PE) — negative EPS now penalised |
| 4 | 03_screener.py | 3M/6M/12M momentum skip-month (Jegadeesh-Titman) |
| 5 | 03_screener.py | Momentum neutralised for stocks with avg daily turnover < ₹25L |
| 6 | 24_backtester.py | Filing lag: 45 → 60 days |
| 7 | 08_integrate_sentiment.py | B-phase signal total capped at ±12 pts |
| 8 | 29_consensus_signal.py | buy_pct removed; weight redistributed |

---

## Research-Backed Changes Applied (2026-04-02)

9 changes from deep research (40+ academic papers). Applied in order.

| # | Signal | Change | Evidence |
|---|--------|--------|----------|
| 1 | Piotroski (27) | Expand FINANCIAL_SECTORS; threshold-based integration | Walkshäusl (2020) |
| 2 | Accruals (28) | Skip CF accruals for Financials; asymmetric integration (-4/+2) | Bansal & Ali (2021) |
| 3 | Earnings persistence (28) | Q4 surprises down-weighted 0.6x; loss-year dampener 0.5x | Balachandran et al. (2023) |
| 4 | Momentum (03) | Risk-adjusted: return/vol (Sharpe-like) for 6M + 12M | Chui et al. (2023) |
| 5 | Consensus (29) | pt_upside 15%; pt_revision 35%; eps_growth 35% | Indian analyst study (2024) |
| 6 | Promoter (30) | Asymmetric: selling dampened 30-50% | Brochet et al. (2017) |
| 7 | Integration (08) | Liquidity tier + sector concentration cap | Chui et al. (2023) |
| 8 | Group tagger (31) | 15 conglomerates mapped | Hindenburg-Adani episode |
| 9 | CLAUDE.md | All parameters documented | — |

---

## v3 Research Foundation (2026-04-03)

Deep research across 7 domains for hierarchical multi-segment architecture. Full report at `research_papers/deliverables/hierarchical_factor_model_research.md`.

### Key findings that shaped v3:
1. **Value premium is positive in small caps, zero in mid caps, NEGATIVE in large caps** — IIM Ahmedabad FF library
2. **Momentum earns 10.7% p.a. in Nifty 100 but REVERSES in illiquid small caps** — Raju & Chandrasekaran 2019
3. **Quality (QMJ) earns 0.92%/month (~11% p.a.) in India** — Jacob, Pradeep & Varma 2022 — nearly double US
4. **Controlling for quality more than doubles the size premium** across 24 international markets — Asness et al 2018
5. **Forensic screening alone adds ~5.5% p.a.** — Marcellus Investment Managers
6. **Promoter buying significant only in bottom tercile of FII ownership** (= small caps) — Brochet, Lee & Srinivasan
7. **NIM strongest predictor of bank stock prices (β=0.583)**, Net NPA significant negative (β=-0.251) — MDPI 2025
8. **Nifty500 Multicap MQ50 ranks within segment separately** — production-grade template for our architecture

---

## Validation Guardrails (v3 updated)

Recalibration cadence:
- Weekly: Rolling 4-week IC dashboard (automated, Streamlit page)
- Quarterly: Re-run reconstructor, adjust signal weights (±0.05 max per quarter)
- Semi-annual: Full architecture review, consider new signals/tiers
- Weight change cap: No signal weight changes by more than ±0.10 in a single recalibration
- Signal promotion: t-stat must exceed threshold for 2 consecutive quarters before promotion
- Signal demotion: t-stat must fall below threshold for 2 consecutive quarters before demotion

- **t-stat >= 2.5 within target segment** required for any signal to enter a segment model (not 3.0 — these aren't novel discoveries in new markets)
- **IC must be computed per segment.** Universe-wide IC is diagnostic only, not decisional.
- Walk-forward splits (no look-ahead bias)
- 30-day paper trading before live inclusion
- 3+ orthogonal signals for conviction within each segment
- Quality gate effectiveness: track 12-month survival rate of excluded stocks
- Monthly IC monitoring per segment via `24_backtester.py --by-tier`
- **Survivorship bias ~4.4% annually** — universe.csv is current listings only
- **Transaction costs by tier:** 30 bps (large), 50 bps (mid), 150 bps (small) — apply in backtester
- **Filing lag:** 60 days quarterly, 75 days Q4/annual
- Fama-MacBeth per segment (deferred until 12+ months per-segment IC data)

---

## Known Issues

| Issue | Fix |
|-------|-----|
| build_universe() broken (KeyError: 'stock') | Always use --resume |
| Venv not activated → ModuleNotFoundError | source ~/alpha-signal/venv/bin/activate |
| Smart quotes from paste | Retype quotes manually |
| Tickertape SIDs ≠ NSE tickers | Use universe.csv SIDs |
| Cache blocking harvest | Add --refresh with --resume |
| Parallel harvesting risks IP block | Never run two scrapers at once |
| run_pipeline.sh has plaintext credentials | Move to .env file (TODO) |
| data.gov.in API key not obtained | Not urgent, fallbacks working |
| cap_tier in universe.csv | ✅ Done — C12 (LARGE=100, MID=150, SMALL=2250) |
| **No banking-specific metrics harvested** | **Session D15** |
| **No 3yr OHLCV for full 2,500 universe** | **Session C13** |

---

## config/settings.py — Centralised Config Keys

| Config block | Key settings |
|-------------|-------------|
| `EMAIL_CONFIG` | SMTP credentials, recipient, subject prefix |
| `FORENSIC_CONFIG` | m_score thresholds, z_score thresholds, cache_max_age_days, skip_financial_sector |
| `SEGMENT_CONFIG` | cap_tier breakpoints, ADTV minimums per tier, VIX thresholds, allocation weights (v3 — NEW) |
| `FINANCIAL_CONFIG` | Bank/NBFC quality thresholds: ROA, NIM, GNPA, PCR, CASA benchmarks (v3 — NEW) |
| `CYCLICAL_CONFIG` | Sector→commodity mapping, normalization window (7yr), peak/trough detection thresholds (v3 — NEW) |
| `ZERODHA` | Stub — Phase E only |

---

## yfinance Gotchas for Indian .NS Stocks

- Field names differ from docs: "Accounts Receivable" not "Net Receivables"
- Typo in yfinance: "Investmentin Financial Assets" (no space)
- Beneish/Altman scores must be computed from raw financials
- `^INDIAVIX` works for India VIX daily data
- Batch download of 2,500 .NS tickers: use chunks of 50-100, 2-second delay, handle failures gracefully

---

## Test Commands

```bash
source ~/alpha-signal/venv/bin/activate
python -c "import pandas; print(pandas.__version__)"
wc -l data/harvester/universe.csv data/harvester/shareholding.csv data/analyst/consensus.csv
curl -I "https://archives.nseindia.com/content/equities/bulk.csv"
# v3 tier check:
python -c "import pandas as pd; df=pd.read_csv('data/harvester/universe.csv'); print(df['cap_tier'].value_counts())"
```

---

## Cost Plan

| Phase | Monthly | Key additions |
|-------|---------|--------------|
| Now (A-B complete) | Rs 450 | Claude API only — all data free |
| Phase C-D (v3 build) | Rs 450-700 | Possible Screener.in Pro if yfinance gaps |
| Phase E | Rs 950-1,200 | Zerodha Kite Rs 500/mo |

Philosophy: Free tier exhausted before any paid subscription is added.

---

## Success Metrics (v3 updated)

**After Phase C:** Tier infrastructure live, within-segment ranking operational, segment-stratified IC confirms ≥1 validated signal per tier
**After Phase D:** 3 segment models live, financial sub-model live, quality gate eliminating junk, portfolio construction producing 30-50 stock picks with tier attribution
**After Phase E:** XGBoost per segment, SHAP dossier, multi-agent AI, Zerodha integration

**Realistic target:** Top 30-50 picks (across 3 tiers) contain 3-5 stocks that 3x+ over 3 years. Consistently top 30% within each segment. Compound at 20-25% vs market 12-15%. Quality gate prevents >90% of catastrophic losses (stocks declining >50%).
