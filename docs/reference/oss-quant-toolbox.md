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

---

# Round 3 — gap-targeted sweep (2026-06-08)

**Method:** 4 parallel web-research agents, one per open gap (BSE-`sid` crosswalk · earnings dates+consensus · forensic data · newer Indian-quant repos). **None of these were live-probed** — a BSE backfill harvester held our IP during the sweep, so everything below is README/PyPI/arXiv-sourced and carries a **verify-on-install** flag. Skepticism is deliberately high; negatives are reported as findings.

## ⭐⭐ A. The BSE `sid` crosswalk — directly unblocks HANDOFF pickup #1

The job: fill `bse_announcements.sid` (NULL today). **The universal join key is ISIN.** `stocks` has NSE tickers, not ISIN, so we need BSE-scrip-code → ISIN → NSE-symbol. Two broker instrument masters give **all three keys in one CDN file** (served off the broker's own CDN, *not* the BSE/NSE backends — so they're harvester-safe).

### `Upstox` instrument master (CDN static file) — JACKPOT
- **Gives:** one row per (exchange, instrument) with `isin` + `exchange` + `trading_symbol` + `exchange_token`. Group rows by `isin` → the **BSE row's `exchange_token` IS the BSE scrip code** (e.g. 500209), the **NSE row's `trading_symbol` is the NSE ticker**. All three keys, one file.
- **URLs (harvester-safe, `assets.upstox.com` CDN, no auth, daily-refreshed):** `…/market-quote/instruments/exchange/complete.json.gz` (both exchanges) · `…/BSE.json.gz` · `…/complete.csv.gz` (CSV deprecated — prefer JSON).
- **Maps to:** fills `bse_announcements.sid` → unblocks event-time PEAD + transcript look-ahead.
- **Confidence:** HIGH (cleanest single-source crosswalk, avoids the forbidden backends).
- **Verify-on-install:** gunzip; confirm Infosys ISIN → BSE row `exchange_token=500209` + NSE row `trading_symbol=INFY`; **spot-check that `exchange_token`==BSE scrip code on a few B-group/delisted names** (it's the documented convention, but confirm before trusting wholesale). Upstox is the *live* universe → won't carry delisted names (see next).

### `rohittihiro/BhavCopy_Equity_Database` → `ListOfScrips.csv` — survivorship supplement
- **Gives (verified header):** `Security Code, Security Id, Security Name, Status, Group, Face Value, ISIN No, Industry, Instrument` — **includes Delisted/Suspended rows.** A frozen snapshot of BSE's own ListOfScrips, checked into GitHub (raw URL, no backend hit).
- **Maps to:** recovers the **delisted/suspended** BSE names that the live Upstox file drops — exactly the survivorship-complete tail of our firehose (back to 2018).
- **Confidence:** MEDIUM — stale (~8 commits, no auto-refresh) so it misses recent listings, but scrip↔ISIN pairs are durable. Use as supplement, not primary.

### Dhan detailed scrip master — clean alternate
- `https://images.dhan.co/api-data/api-scrip-master-detailed.csv` (CDN) carries `EXCH_ID` + `ISIN` + `SEM_TRADING_SYMBOL` + `SEM_SMST_SECURITY_ID`. Same group-by-ISIN recipe as Upstox; `SEM_SMST_SECURITY_ID` for BSE rows should be the scrip code (docs don't state it explicitly → verify). MEDIUM-HIGH; clean fallback.

### Myth killed + don't-run
- **Zerodha Kite `instruments.csv` has NO ISIN** — requested-but-unshipped since 2017 (`tradingsymbol`+`exchange`+`exchange_token` only). It cannot self-bridge to ISIN; do not build on the assumption it carries one.
- **`rehanhaider/stocky`** is conceptually exactly this crosswalk (ISIN-keyed SQLite of BSE/NSE/Zerodha/Yahoo symbols) but **abandoned (2021) and builds the map by hitting the BSE/NSE backends** — mine its ISIN-join logic, don't run it.
- `jugaad-data` / `nsepython` / `BseIndiaApi` confirm EQUITY_L + bhavcopy carry ISIN, but all route through the forbidden backends — deferred until the harvester finishes.

## B. Earnings dates + consensus (the PEAD prerequisites) — mostly a negative result

### The dates we already own
- **Key finding: our own BSE event stream is the best free announce-date source.** `bse_announcements` (`AnnSubCategoryGetData`, survivorship-complete to 2018) already carries Board-Meeting / Financial-Results intimations — **parse the results category out of the stream we have rather than adding a redundant scraper.** This is the event-time PEAD date source; no new dependency needed.
- **Forward calendar:** `earnings.thecore.in/upcoming` — free, drawn from filed board-meeting intimations, ~1,000 names. **No API/CSV** (scrape the HTML); only ~8 quarters of history. Good for a forward widget, useless for deep backfill.
- **Deferred (hit backends — don't run now):** `jugaad-data` `NSELive.corporate_announcements()`, `BennyThadikaran/BseIndiaApi` `announcements()`, `BuildAlgos/screener-scraper` (despite the name, pulls `api.bseindia.com`) — all redundant with our own stream anyway.

### Free India consensus estimates — **there isn't one for the small/mid tail**
- **Trendlyne Forecaster** is the richest India-native consensus (EPS/revenue/PAT + an explicit EPS-surprise view) — **but it's PRO/paywalled**, no public API. The only real path to a true consensus surprise, if PEAD ever justifies the spend (paid scrape).
- **FMP free = US-only.** **Finnhub free = US-only** (confirms *why* our memory's "Finnhub dead end" — it's geography, not coverage). **Alpha Vantage** doesn't meaningfully cover Indian estimates. All disqualified for free India consensus.
- **`Sampad-Hegde/Bharat-SM-Data`** (MoneyControl+Tickertape scraper, active v4.0.1) and the screener.in scrapers expose *actuals only* — no consensus/estimates. **Net:** pair our in-house BSE dates with Tickertape forecasts (already integrated) for large/mid; accept that the thin small-cap tail has **no reliable free consensus** — this is the real reason core PEAD didn't replicate, and it won't without paid estimates.

## C. Forensic layer — standalone-vs-consolidated, headcount, managerial ability

### `VishwaGauravIn/screener-scraper-pro` — the standalone/consolidated toggle
- **Gives:** screener.in scrape where the URL path selects the basis — `…/company/X/` = **standalone**, `…/company/X/consolidated/` = **consolidated**. Returns P&L / balance-sheet / cash-flow / ratios, ~11yr annual. Accepts BSE/NSE codes.
- **Maps to:** the **REXP standalone-vs-consolidated revenue/profit divergence flag** (HANDOFF / Next-3 #4 deferred detector). Hits screener.in, not the BSE/NSE backends — OK under the harvester rule, but obey the 2s-delay.
- **Confidence:** HIGH for the toggle. **Skeptic's caveat:** the divergence is only computable where a company files BOTH bases — many small-caps show only one → the flag is NULL (not zero) for a chunk of the universe; don't treat missing as "no divergence."

### Employee headcount — the genuinely hard gap (be skeptical)
- **No clean free structured multi-year headcount feed exists for the Indian small/mid universe.** It legally exists (Companies Act §197(12) + Rule 5(1): "number of permanent employees on the rolls" in every Board's Report, FY2015+) but lives as **unstructured PDF text**, not a queryable field.
- **Best path:** extract headcount from annual-report PDFs via our existing report pipeline (regex/LLM). **Backstop:** AmbitionBox employee-count *bands* (`mratanusarkar/Dataset-Indian-Companies` ships a CSV) — current snapshot only, fuzzy name→sid match. **EPFO/LinkedIn = dead ends** (no free company-level API / biased non-headcount).
- **Pragmatic fallback for the Dechow non-financial-divergence term:** use **employee-benefit-expense growth** (already in our P&L, fully populated) as the divergence denominator instead of headcount — defensible proxy, no new data, no sparsity.

### Demerjian-Lev-McVay managerial ability — build it (no shortcut exists)
- **No India MA dataset and no full DLM replication repo exist** (Demerjian's published scores are US-Compustat only — use purely as a logic-validation benchmark). Build = DEA frontier → Tobit residual:
  - **`NibuTake/PyDEA` (PyPI `Pyfrontier`)** — `EnvelopeDEA(frontier=CRS/VRS, orient=in)`, pure-Python, **freshest (v1.1.1, Dec 2025)**. Stage-1 efficiency frontier within `cap_tier`×sector. (Alt: `araith/pyDEA`, more mature, lower activity.)
  - **`jamesdj/tobit`** — censored regression for stage-2 (efficiency on size/share/FCF/age/segments → residual = managerial ability). Small but math is simple.
  - **Recipe:** F1000Research 2025 paper applies DLM to **150 NSE firms 2014-2023** with the exact input set (inventory, AR, AP, COGS, net revenue, net income) — the India-localized spec to follow.

## D. F&O depth below ~2024 — the one lever a fundamentals floor can't pull

### `dhan-oss/DhanHQ-py` — ⭐ best find for this gap
- **Gives:** official Dhan client with a dedicated **expired-options historical endpoint** — OHLC + **rolling IV, OI, volume** for *expired* F&O contracts, addressed by ATM±strike offset (no dead-security-ID resolution needed), ~5yr minute-level. **Actively maintained (v2.2.0, Apr 2026, ~162★).**
- **Maps to:** pushes the F&O/IV-greeks/microstructure floor **below 2024** — directly the lever HANDOFF flags that a 2018 *fundamentals* floor cannot provide. Free with a Dhan account; per-user OAuth (sanctioned, unlikely to IP-block — different profile from our scrapers).
- **Confidence:** HIGH. Probe how far back expiries actually reach before committing.

### Supporting cast
- **`upstox/upstox-python`** — V3 historical (minutes from Jan-2022, daily from **Jan-2000**) + a separate **Expired Historical Candle** endpoint. Cross-check expiry depth against Dhan, keep whichever goes older.
- **`marketcalls/openalgo`** — self-hosted unified API over **30+ Indian brokers** + L5 depth (v2.0.1.2, May-2026, ~2,000★, AGPL-3.0). Front Dhan/Upstox with this so the broker stays swappable.
- **`marketcalls/openchart`** — no-auth NSE+NFO intraday/EOD, but young (~57★, undocumented depth). Spot-checks only, not a primary deep-history source.

## E. Financial-NLP — the number-hallucination guardrail + forensic NLP

### `nlpaueb/finer` (FiNER) + `pegasi-ai/shield` (FRED) — pair, targets the HALC bug class
- **FiNER** — financial **numeric-entity recognition**: tags numeric tokens by what they represent (the correct tag depends on context, not the digits); ships the numeric-pseudo-token trick + SEC-BERT. Maps directly to our **"no raw numbers in narrative fields"** rule — number-grounding / "is this a real PT vs `lastPrice`" typing.
- **FRED / `pegasi-ai/shield`** (arXiv:2507.20930, Jul-2025) — detects *and edits* ungrounded numeric spans given a context, with a user-defined error taxonomy; small fine-tuned models (Phi-4-mini beats o3 on their bench → cheap gate). The ML upgrade to the regex check in `output/dossier.py`; the **2026-05-22 "16.5% downside at ₹1038" HALC bug is exactly its target case**. Verify weights/license release before integrating.

### India-native + relation extraction
- **`kdave/FineTuned_Finbert`** + **`kdave/Indian_Financial_News`** (HF) — FinBERT fine-tuned on ~27K **Indian** financial-news articles. India-calibrated sentiment head vs generic ProsusAI. GPT-labeled → weak supervision, validate before prod. (v2 alternatives: `Aadhil-rog/finbert-indian-sentiment-v2`.)
- **`kwanhui/FinRelExtract`** + REFinD benchmark — financial **relation extraction** (ORG–ORG, PERSON–TITLE, ORG–MONEY) from filings; complements the BSE event stream (resignations, pledges, related-party links). Reference-grade, not a maintained lib.

## F. Backtest rigor — multiple-testing correction (extends the Round-2 Deflated-Sharpe work)
- **`esvhd/pypbo`** — clean focused **PBO (CSCV — combinatorial-symmetric CV)** + Deflated/Probabilistic Sharpe. Directly addresses the **ADR-0017 trials problem**: every new factor is another trial against the fixed 36-period archive, and a |t|≥1.5 gate doesn't correct for the count. Smallest dependency surface — easiest rigor tool to drop in.
- **`bcosm/backtester-mcp`** — core robustness suite = PBO + Deflated Sharpe + bootstrap CI + walk-forward + a **JSON manifest audit trail** (fits our silent-failure-averse philosophy). Lift the robustness module, not the whole MCP server.
- **`polakowo/vectorbt`** — its **Splitter** has purged+embargoed k-fold and combinatorial CV as first-class objects (López de Prado leakage controls). Mind free-vs-`vectorbt.pro` feature-gating — may just want the Splitter pattern reimplemented.

## G. Survivorship / external factor benchmarks
- **`rkohli3/india-famafrench`** + the **IIM-Ahmedabad IFFM data library** (faculty.iima.ac.in/iffm) — externally-published NSE Fama-French + momentum factor returns with documented survivorship/look-ahead handling. An independent benchmark to **diff our own factor returns against** (a guard against our own construction bugs).
- **`yfiua/index-constituents`** — PIT **NIFTY-50 constituents back to 2008** (Wayback/MediaWiki-reconstructed). Cross-check for our bhavcopy-reconstructed survivorship universe ([[survivorship-universe-via-bhavcopy]]). NIFTY-50-centric + some Wayback noise → validation cross-check, not primary.

## Round-3 adoption priority
1. **Upstox instrument master** → fill `bse_announcements.sid` (the gate on PEAD/look-ahead wiring). Harvester-safe CDN file, verify-on-install. **Do this when the backfill finishes.** Supplement with `ListOfScrips.csv` for delisted names.
2. **Parse results dates out of our own `bse_announcements`** (not a new scraper) → event-time PEAD. Free, in-house, already survivorship-complete.
3. **`esvhd/pypbo` PBO/CSCV** → trials-adjusted overfitting probability beside the existing Deflated Sharpe (ADR-0017 honesty). ~small, generic.
4. **`screener-scraper-pro`** → standalone-vs-consolidated divergence flag (REXP detector); pair the Dechow term with **employee-benefit-expense growth** (no headcount data needed).
5. **FiNER + FRED** → ML number-grounding guardrail for dossiers (HALC bug class).
6. **DhanHQ-py expired-options** → the only lever for the sub-2024 F&O/IV floor; needs a Dhan account — evaluate when the F&O track is picked up.

> **Honest status:** of Round 3, **zero are live-verified here** (the harvester held the IP) — every claim is a README/docs hypothesis. The single highest-leverage, lowest-risk item is the **Upstox crosswalk** (it unblocks the #1 board item and is a static CDN download). The single most important *negative* is **no free programmatic India consensus** — PEAD's missing half stays paid-only.
