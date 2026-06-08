# Open-Source Quant Toolbox — GitHub gems for Alpha Signal v2

**Compiled:** 2026-06-08 (WebSearch sweep + the BSE-API discovery that prompted it).
**Why:** open-source GitHub is an underrated source of *both* data-access libraries and
analysis tooling for an Indian-equity quant model. This is a curated, mapped-to-our-gaps
shortlist — not exhaustive. Confidence noted per item; "verify on install" = surfaced by
search, not yet probed here.

> **Rule of thumb:** prefer a maintained library's *known-good endpoint recipe* over
> reverse-engineering (the BSE `AnnSubCategoryGetData` param set came straight from
> `BseIndiaApi` and saved hours). But vendor-wrap libraries rot — pin versions, and keep
> our own thin fetchers so a library breakage doesn't take the pipeline down.

---

## Tier 1 — directly unblocks a current gap

### `jugaad-data` (jugaad-py/jugaad-data) — deep historical NSE/BSE bhavcopy + RBI ⭐
- **Gives:** historical stock/index/**derivatives** bhavcopy from the *new* NSE site, plus RBI economic data, with built-in caching. Future-proof (uses the live site, unlike the deprecated `nsepy`).
- **Maps to:** the **2018-floor price backfill**. Our `nselib` delivery-bhavcopy *floors at ~2022* (probed: 2018/2016 → "Data not found"). jugaad-data is the candidate to extend `stock_prices` (and the survivorship panel) back to 2018 — the binding dependency for credit_beta's backtest window + every deepened backtest.
- **Caveat:** delivery% availability in deep history is uncertain → verify on install; pair with `corporate_actions` backfill (raw bhavcopy is NOT split-adjusted — see data-playbook NSE Bhavcopy gotcha #4).
- **Confidence:** high it exists + is maintained; depth to 2018 = verify on install.

### `BseIndiaApi` (BennyThadikaran/BseIndiaApi) — the BSE backend recipe ⭐
- **Gives:** the exact, working param sets for BSE's unofficial JSON API (announcements, quotes, corporate actions). **We already used its `AnnSubCategoryGetData` recipe** to build `sources/bse_announcements.py`.
- **Maps to:** the BSE event-stream harvester (shipped). Also documents other BSE endpoints (corp actions, results) worth mining.
- **Confidence:** verified — its recipe works live from this VM.

### `pysentiment2` + full Loughran-McDonald dictionary — NLP lexicon upgrade
- **Gives:** the **full ~2,300-word LM finance lexicon** (negative/positive/uncertainty/litigious/strong-modal/weak-modal), vs our hand-curated ~270-word subset in `signals/nlp_scores.py`.
- **Maps to:** directly fixes **NLP doubt #6** (curated-subset crudeness). Drop-in richer tone/uncertainty on the transcript corpus; adds the **litigious** + **modal** categories we don't have.
- **Confidence:** high (LM dictionary is the finance-research standard).

### `FinBERT` (ProsusAI/finBERT) + `rj694/earnings-sentiment` — transformer tone cross-check
- **Gives:** BERT fine-tuned on financial text → sentence-level financial sentiment. The `earnings-sentiment` repo is a reference pipeline doing **LM + FinBERT on earnings calls** (finds LM↔FinBERT agreement r≈0.81).
- **Maps to:** a model-based cross-check on our lexicon tone (transcripts). Catches sarcasm/negation the bag-of-words LM misses. Heavier (GPU-ish), so a periodic batch, not daily.
- **Confidence:** high it works; cost/benefit on CPU = evaluate.

---

## Tier 2 — analysis tooling (don't reinvent)

### `alphalens-reloaded` (stefan-jansen) — factor performance tear-sheets
- **Gives:** standard factor analysis — quantile returns, **IC / IC-decay**, turnover, by-group (sector) breakdown, full tear-sheets. The maintained fork of quantopian/alphalens.
- **Maps to:** *augments* our custom `tools/backtest_pit.py`. We already compute IC/t-stat/Newey-West; alphalens adds turnover, IC-decay curves, quantile monotonicity, and publication-grade plots for `/model`. Good cross-check that our hand-rolled stats agree with the reference implementation (a guard against our own bugs).
- **Confidence:** high.

### `Riskfolio-Lib` / `PyPortfolioOpt` — portfolio construction
- **Gives:** mean-variance, risk-parity, HRP, CVaR, Black-Litterman, constraints.
- **Maps to:** **Track 2 (Portfolio)** — turning ranked picks into a weighted, risk-aware book (currently the weakest-built track).
- **Confidence:** high.

### `empyrical` / `pyfolio-reloaded` — performance & risk metrics
- **Gives:** Sharpe/Sortino/max-DD/tail-ratio + portfolio tear-sheets (battle-tested formulas).
- **Maps to:** `pick_outcomes` / backtest reporting + the MF metrics module — replace any hand-rolled ratio with the reference impl.
- **Confidence:** high.

### Microsoft `qlib` — AI quant platform + ready factor sets
- **Gives:** an end-to-end AI-quant framework; notably the **Alpha158 / Alpha360** engineered-factor libraries (price/volume factor definitions) and a backtest/model layer.
- **Maps to:** a *source of factor ideas* (Alpha158 formulas we haven't built) + a reference architecture. Heavy to adopt wholesale; mine it for factor definitions rather than swallow the framework.
- **Confidence:** medium (large, opinionated; cherry-pick).

---

## Tier 3 — data platforms / broker APIs (deeper or alternative data)

### Indian broker APIs — free historical incl. **options** (the F&O/microstructure floor)
- **Zerodha Kite Connect:** as of 2025, **historical data bundled free** with the base Connect subscription — up to **~10 years intraday** incl. active options contracts. *Caveat:* the free "Personal" API tier reportedly excludes market data; the historical bundle is on the paid Connect plan. **Verify the exact tier.**
- **Angel One SmartAPI:** free, Python SDK, **historical data incl. NFO futures**.
- **Maps to:** the **F&O / IV / microstructure factor floor (~2024 today)**. A broker historical API could push intraday + options history *deeper* than our `fno_bhav` — the one lever that helps the families a 2018 *fundamentals* floor does NOT (see factor-impact analysis). Needs a broker account + key.
- **Confidence:** medium — free-tier boundaries shift; verify before relying.

### `OpenBB` (OpenBB-finance/OpenBB) — open data platform, ~100 connectors
- **Gives:** a "connect once, consume everywhere" layer over ~100 sources (equity/options/macro/fixed-income/alt), Pydantic-standardised, Python + REST + MCP.
- **Maps to:** a *meta-connector* + a catalog of free data routes we might be scraping by hand. Worth mining its provider list for India-reachable free sources; possibly an MCP surface for the cockpit. Don't adopt wholesale — cherry-pick connectors.
- **Confidence:** high it exists; India-coverage depth = verify.

---

## Already in our stack (for completeness)
`yfinance` (prices/macro) · `nselib` (bulk deals, insider, bhavcopy ≥2022, corp actions) · `bsedata`-style BSE access · Screener.in / Tickertape scrapers · `mfapi.in` (MF NAV). See `data-playbook.md` Source Catalog.

---

## Suggested adoption order (cheapest, highest-leverage first)
1. **`pysentiment2` full LM** → richer transcript tone (one import; fixes NLP doubt #6). ½ day.
2. **`jugaad-data`** → backfill `stock_prices` to 2018 (the dependency behind credit_beta's window + every deepened backtest). Verify delivery-% depth.
3. **`alphalens-reloaded`** → cross-check `backtest_pit` + better `/model` tear-sheets. Low risk.
4. **Broker API (Kite/SmartAPI)** → evaluate deeper F&O/options history (the one floor the 2018 plan can't lower). Needs an account.
5. **Riskfolio-Lib** → when Track 2 portfolio construction is picked up.

> **Note on this list:** items are surfaced by web search + domain knowledge; only `BseIndiaApi`
> (used live) is fully verified here. Treat depth/free-tier/India-coverage claims as
> hypotheses to confirm on install, exactly like the paid-vendor research in
> `pit-data-sources-research.md`.

---

# Round 2 — deeper + lateral finds (2026-06-08)

## ⭐⭐ Paid-grade data that's quietly free (VERIFIED LIVE from the VM)

### SEC EDGAR XBRL API — free as-filed, restatement-vintage PIT fundamentals for Indian ADRs
- **Verified:** `GET https://data.sec.gov/api/xbrl/companyfacts/CIK{10-digit}.json` (no key, 10 req/s, UA must carry a contact email). Infosys (CIK 1067491) → **300 IFRS-full concepts, FY 2018→2025, as-filed**.
- **Why it's huge:** Indian **ADRs** (Infosys, Wipro, ICICI Bank, HDFC Bank, Dr Reddy's, WNS, MakeMyTrip, Azure Power, Sify, Yatra…) file **20-F** with full IFRS XBRL. EDGAR keeps **every filing's as-filed values + the filing-date history** → this is the **restatement-vintage, point-in-time, survivorship-complete** fundamentals layer the paid-vendor research (`pit-data-sources-research.md`) said was an "enterprise quote" — **free** for the ~15-20 cross-listed large caps. Perfect PIT ground-truth to *calibrate/validate* our Screener-sourced (latest-restated) fundamentals against.
- **Maps to:** Gap 3 (PIT fundamentals) for the ADR subset; a "look-ahead audit" benchmark for the whole pipeline.
- **Confidence:** verified.

### TradingView screener API — ~13,000 free fundamental+technical fields, whole India universe
- **Verified:** `POST https://scanner.tradingview.com/india/scan` (no auth) → **8,430 NSE+BSE stocks** with P/E-TTM, ROE, D/E, margins, market cap in one call. Libraries: `tradingview-screener` (shner-elmo), `tvscreener` (claims 13,000+ fields, any timeframe, no login).
- **Maps to:** a **free cross-check / redundancy layer** for Screener.in + Tickertape fundamentals (catches their scrape bugs), plus fields we don't currently pull (analyst recs, many ratios, technicals). Not PIT (latest snapshot), so a *current-state* source, not a backtest source.
- **Caveat / ToS:** unofficial backend, same brittleness + personal-use posture as the BSE feed. Verify field set + rate limits.
- **Confidence:** verified live.

## ⭐ Tooling that fixes our STATED weaknesses

### Deflated Sharpe Ratio + Combinatorial Purged CV (López de Prado) — the multiple-testing fix
- **Gives:** the **Deflated Sharpe Ratio** (Bailey–López de Prado 2014) corrects a Sharpe/t-stat **for selection bias under multiple testing** + non-normal returns — i.e. penalises a "KEEP" that's just the lucky tail of N trials. **Combinatorial Purged CV** produces a *distribution* of backtest t-stats (multiple paths) instead of one point estimate, with purging+embargo to kill look-ahead.
- **Maps to:** **directly addresses doubt #13** (we test ~150 (factor×tier) hypotheses at |t|≥2 with no correction → ~7 false KEEPs expected). A DSR / haircut on every `pit_ic_by_tier_v2` t-stat, and purged-CV paths on the promotion gate, would make the whole library tier honest. The highest-rigour upgrade available.
- **Source:** `mlfinlab` (Hudson & Thames — core went paid, but purged-CV/DSR are widely re-implemented: `RiskLabAI`, `mlfinpy`, standalone gists; the DSR is ~30 lines).
- **Confidence:** high (canonical method).

### `linearmodels` + `arch` (Kevin Sheppard) — rigorous panel + bootstrap inference
- **Gives:** `linearmodels` = proper **Fama-MacBeth** + panel regressions with clustered/Driscoll-Kraay SEs (we already do FM by hand in `sector_tilt_validation`); `arch` = bootstrap, **Model Confidence Set**, GARCH.
- **Maps to:** harden every t-stat/IC with reference-grade SEs + bootstrap CIs; the MCS picks the genuinely-best factor from a set without data-snooping.
- **Confidence:** high.

## Creative / India-native ALTERNATIVE data (alpha-oriented)

### AmbitionBox / Glassdoor employee reviews → India-native management-quality signal
- **Gives:** employee ratings (overall, **culture, work-life, management**, recommend-%) per company — AmbitionBox is India-native (InfoEdge/Naukri), deep coverage of listed firms.
- **Maps to:** a *novel* input to the **Management-scorecard credibility pillar** (currently hand-set + the weakest pillar). Employee-sentiment-on-management is a documented soft governance/culture signal, and it's hard for rivals to source. No official API → scrape (ToS-light, public reviews).
- **Confidence:** medium (signal real; scraping + sid-mapping is the work).

### Google Trends (`pytrends`) + Wikipedia pageviews → retail-attention factor
- **Gives:** search interest (`pytrends`, unofficial) + Wikipedia pageviews (official API, since 2015) per company/ticker.
- **Maps to:** a **retail-attention factor** — academically validated *for India specifically* (search spikes → short-horizon excess return that **reverses next week** → a tradeable attention/reversal signal, esp. small/mid-cap). Free.
- **Confidence:** medium-high (India-validated in literature).

### GDELT 2.0 → free global event/tone knowledge graph
- **Gives:** worldwide news events + tone + themes, free (API + BigQuery), India-filterable. "Information supply" half (vs Trends/Wikipedia "information demand").
- **Maps to:** augments the RSS news/sentiment pipeline with a far broader, dated, structured event feed; macro/sector theme detection.
- **Confidence:** medium (breadth real; India entity-linkage is the work).

### `FinBERT-FLS` (yiyanghkust) → forward-looking-statement classifier
- **Gives:** a BERT model that classifies **forward-looking statements** in financial text.
- **Maps to:** upgrades our **regex-based `forward_looking_intensity` (#36)** to a model-based detector, and is the natural extractor for the **promise-vs-delivery** guidance signal on transcripts.
- **Confidence:** high.

## Round-2 adoption priority
1. **SEC EDGAR ADR pull** — free PIT ground-truth; tiny (≤20 CIKs), no key → a look-ahead *audit* of our fundamentals. ½ day, verified.
2. **Deflated Sharpe Ratio** on `pit_ic_by_tier_v2` — ~30 lines, makes every verdict honest about multiple testing. Highest rigour-per-line.
3. **TradingView screener** — free current-state fundamental cross-check (catches Screener/Tickertape scrape bugs).
4. **Google Trends / Wikipedia attention factor** — a genuinely new, India-validated factor family.
5. **AmbitionBox** management signal + **FinBERT-FLS** — when the Management/NLP pillars get their next pass.
