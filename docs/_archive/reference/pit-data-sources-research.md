# PIT Data Sources — Deep Research (5 gaps, money-no-object)

**Source:** `deep-research` harness run · **Date:** 2026-06-08
**Scale:** 108 agents · 6 search angles · 25 sources fetched · 106 claims extracted → 25 verified → **21 confirmed / 4 killed**
**Question:** Best data sources to fill five PIT-integrity gaps in the automated Indian-equity quant factor model, where money is not a constraint (but always record pricing tier + access mechanism).

> **Read this caveat first.** Every *global* vendor's marquee strength was verified **for the product in general, not for India**. Independent evidence warns I/B/E/S India coverage pre-2011 is "very limited"; Worldscope's India-depth claim was **refuted 0-3**; Visible Alpha is global large/mid-cap tilted. Do **not** assume the headline history depths apply to the 2,448-stock Indian universe without a vendor-run India coverage report. Two gaps (4 line-items, 5 transcripts) rest on inference, not direct evidence — treat as hypotheses to validate.

---

## TL;DR

| Gap | #1 pick | Runner-up | Confidence | Key caveat |
|---|---|---|---|---|
| **1. PIT consensus estimates + earnings dates** | LSEG/Refinitiv I/B/E/S (+ separate *I/B/E/S Point-in-Time* product) | Visible Alpha (now S&P Global) | High | India coverage pre-2011 "very limited"; true PIT needs the separate PIT product, not the monthly Summary/Detail snapshot |
| **2. India rates + credit curves** | FBIL — RBI-recognised administrator; daily cubic-spline G-Sec par curve since 2018 | RBI DBIE / FIMMDA (pre-2018) + Refinitiv/Bloomberg (credit spreads) | High | Paid for timely/programmatic; free path is 7-day-lagged web-view only; series starts 2018 (no 2013 taper); does **not** publish corp credit curves |
| **3. Survivorship-free PIT fundamentals (15y+)** | **CMIE Prowess dx** — ~35–50k cos since 1990, API + Excel add-in | ACE Equity Nxt (Accord Fintech) | High | Survivorship is "no *deliberate* bias" (2-1 vote), not audited; vintage/restatement PIT layer **not** established |
| **4. NBFC/bank asset-quality history (10y+)** | CMIE Prowess (banking/NBFC DBs) | — (Capitaline/ACE/RBI produced no surviving claim) | Medium | Granular line-items (GNPA/NNPA/PCR/slippage/SMA/segmental NIM/CAR) **inferred** from general depth, not directly verified |
| **5. Machine-readable transcripts (timestamped, survivorship-complete)** | *None verified* — LSEG StreetEvents inferred by stack logic | Trendlyne / Screener (budget) | Low | **Zero surviving verified claims** — fully open |

**Best single India-native subscription:** CMIE Prowess (covers Gap 3 + 4; plausibly reaches Gap 1 estimates and Gap 5 concalls, unverified).
**Best 2-vendor combo:** LSEG/Refinitiv + CMIE Prowess — LSEG for global PIT machinery (Gaps 1+3, candidate 2, inferred 5); CMIE for the India-native depth/survivorship LSEG does *not* establish for India. Add **FBIL** as a cheap Gap-2 bolt-on regardless.

---

## Gap 1 — PIT consensus estimates + exact earnings-announcement dates

**#1: LSEG/Refinitiv I/B/E/S Estimates** — `confidence: high · vote 3-0`
Deepest consensus history (US 1976 / RoW 1987, 60k+ companies), explicitly positioned for back-testing. Carries **"Comparable Actuals adjusted to the consensus mean"** for clean beat/miss plus **Restated Actuals** — the exact actuals-vs-consensus pairing PEAD / earnings-surprise factors need. Programmatic via Datastream / RDP / WRDS.
- **Critical India caveat:** independent evidence notes I/B/E/S Indian coverage pre-2011 is "very limited"; the 1976/1987 depth does **not** extend to India. True PIT requires the separate **I/B/E/S Point-in-Time** product (daily from 2000, activation dates from 1980) — *not* the standard monthly Summary/Detail snapshot.
- Sources: [refinitiv.com/.../ibes-estimates](https://www.refinitiv.com/en/financial-data/company-data/ibes-estimates), [lseg.com/.../ibes-estimates](https://www.lseg.com/en/data-analytics/financial-data/company-data/ibes-estimates)

**Runner-up: Visible Alpha (now S&P Global)** — `confidence: high · vote 3-0`
Granular, line-item-level consensus with **revision timestamps** (when each estimate change occurred historically), well-stitched actuals-to-forecasts, VA Actuals delivered N days post-earnings (direct building block for surprise/PEAD). Three pipeline-native channels: **RESTful API, file feed via S3/SFTP, Snowflake share**. Actuals history to 2006.
- **India caveat:** ~7,000-company universe is global large/mid-cap tilted; NSE/BSE small/mid-cap breadth UNVERIFIED and likely thin. Product page now 301-redirects to S&P Global (acquisition in flux). Note: "Snowflake Time Travel" is **not** PIT evidence (it's a 90-day recovery feature) — genuine PIT comes from the revision-dated records.
- Sources: [visiblealpha.com/products/data-services](https://visiblealpha.com/products/data-services/), [Snowflake Marketplace listing](https://app.snowflake.com/marketplace/listings/Visible%20Alpha)

**India-native alternative:** `confidence: low — absence of confirming evidence`
ACE Equity (Accord Fintech), Trendlyne, Tijori carry India-native estimates and earnings dates, but **none of the verified evidence confirms a true PIT consensus history** (as-known-on-historical-date) with deep Indian coverage. ACE serves latest as-reported figures. **This is the single least-resolved gap** — global vendors have PIT machinery but thin India estimates; India-native vendors have coverage but unverified/likely-absent estimate vintages. Requires a direct vendor PoC.

---

## Gap 2 — Authoritative daily India rates + credit curves, deep history

**#1: FBIL (fbil.org.in)** — `confidence: high · vote 3-0`
The RBI-recognised official benchmark administrator (under Sec 45W; RBI/2022-23/142) and authoritative single source for India's short end and G-Sec curve. Publishes a **daily cubic-spline G-Sec Par Yield Curve** (clean as-published sovereign par yields by tenor — *not* an ETF total-return proxy) plus MIBOR, MIFOR, T-Bill Rate, CD curve, MIBOR-OIS (1M–5Y), STRIPS, ZCYC, SDL — on all Mumbai business days **since 31 March 2018**. Built from CCIL transaction-level G-Sec trades (min 15 trades + ₹75 cr face value threshold).
- **Access caveat:** timely/programmatic access is **PAID** (End-User ~₹50,000/yr valuation; ₹2,50,000/yr other; ₹10,00,000/yr international). The only free path is a **7-day-lagged, web-view-only** dataset — no documented free REST API/bulk feed.
- **Depth caveat:** history starts 2018 — does **not** natively cover the 2013 taper tantrum.
- Sources: [fbil.org.in](https://www.fbil.org.in/), [FBIL G-Sec/SDL valuation pricing PDF](https://www.fbil.org.in/uploads/Pricing_of_FBIL_G_Sec_Valuation_and_SDL_Valuation_benchmarks_c4832dcaaa.pdf)

**Runner-up + pre-2018 depth + credit spreads:** `confidence: low — inferred, not independently verified`
For deep history through the 2013 taper tantrum / 2018 IL&FS crisis (before FBIL's 2018 start) → **RBI DBIE / FIMMDA** for sovereign history. For **corporate-bond credit spreads by rating (AAA/AA/A) and tenor** — which FBIL does **not** publish → **Refinitiv / Bloomberg** India fixed-income curves. No verified claim confirmed a clean programmatic rating-by-tenor credit-spread feed from any India-native free source.
- Sources: [RBI DBIE](https://data.rbi.org.in/DBIE/)

---

## Gap 3 — Survivorship-free PIT Indian fundamentals (~15y+)

**#1: CMIE Prowess dx** — `confidence: high · company-count/history 3-0 · survivorship-free 2-1`
Strongest India-native deep-history candidate. Over **50,000 companies** (academic edition ~35,000) with financial + markets time series **since 1989/1990 (~35 yrs)**, explicitly survivorship-aware ("The database does not suffer any deliberate survival bias"; companies are not dropped after delisting), sourced from **MCA-filed audited statements**. Programmatic via **API + Excel Add-In + Query Builder** (potentially pipeline-native).
- **Caveat:** the survivorship claim is hedged ("no *deliberate* survival bias") — an assertion of no intentional dropping, **not** an audited guarantee of complete dead-company coverage with restatement vintages. Prowess typically serves as-reported figures; a true vintage/PIT restatement layer is **not** explicitly established. (Full Prowess: 107,084 cos incl. 5,531 listed + 101,553 unlisted as of Mar 2025.)
- Sources: [prowess.cmie.com](https://prowess.cmie.com/), [CMIE Prowess dx product](https://www.cmie.com/kommon/bin/sr.php?kall=wproducts&tabno=7010&prd=prowessdx), [IIMB library database list](https://library.iimb.ac.in/database/a-z)

**Runner-up: ACE Equity Nxt (Accord Fintech)** — `confidence: high · coverage/fields/datafeed 3-0 · access-mechanism 2-1`
**40,000 Indian companies** (7,000 listed + 33,000 private), **1,750 unique as-reported fields** with balance-sheet/P&L/cash-flow "directly linked to Annual report", Ind AS in annual + quarterly format.
- **Not pipeline-native:** delivered as a Windows/cloud-hosted desktop app with an Excel plug-in (auto-refresh) — no documented REST/JSON or bulk feed. Programmatic access requires the **separate "ACE Datafeed"** product (FTP + API, CSV/JSON), which however carries only shallow financials ("Latest 5 Years + 8 Qtr"), not the deep 1,750-field DB. As-reported, but no established restatement-vintage/PIT history.
- Sources: [accordfintech.com/ace-equity-nxt](https://www.accordfintech.com/ace-equity-nxt), [aceanalyser.com](http://www.aceanalyser.com/), [ACE market data feed](https://www.accordfintech.com/market-data-feed)

**Global alternative: LSEG Worldscope Fundamentals** — `confidence: high · capability/access 3-0 · India-depth REFUTED 0-3`
104,000+ companies / 120+ countries / 99% of global market cap, with a **dedicated Point-In-Time database** recording "the date a value was added or updated" and original + restated values where "original data is never overwritten" (US PIT from 1989, non-US from 1997). Fully pipeline-native: Datastream + LSEG Quantitative Analytics APIs (incl. cloud/Snowflake/S3) + SFTP/FTP bulk; the **DatastreamPy** Python package explicitly exposes Worldscope PIT data.
- **Two caveats:** (a) the claim that emerging-market (India) history reaches 25+ years was **REFUTED 0-3** — India depth NOT established; (b) PIT timestamping does **not** by itself prove a survivorship-free universe (distinct, undocumented property).
- Sources: [lseg.com/.../worldscope-fundamentals](https://www.lseg.com/en/data-analytics/financial-data/company-data/fundamentals-data/worldscope-fundamentals), [DatastreamPy on PyPI](https://pypi.org/project/DatastreamPy/)

---

## Gap 4 — Deep NBFC/bank asset-quality history (~10y+)

**#1: CMIE Prowess (banking/NBFC databases)** — `confidence: medium · Prowess depth 3-0 · line-items not directly verified`
Strongest verified India-native candidate by virtue of full-universe ~35–50k-company coverage since 1989/1990 and MCA-audited-statement sourcing — the natural source for GNPA/NNPA, provisioning, slippage, CAR across the bank+NBFC universe with depth.
- **Caveat:** no verified claim specifically confirmed the granular asset-quality **line items** (PCR, SMA/restructured book, segmental NIM) are present and consistent across the universe — this is **inferred** from general fundamentals depth, not directly evidenced. Confidence capped at medium pending a data-dictionary check.
- Runner-ups (Capitaline, ACE Equity, RBI DBIE banking stats, Refinitiv/Bloomberg) produced **no surviving Gap-4-specific verified claim**.
- Sources: [IIMB library](https://library.iimb.ac.in/database/a-z), [CMIE Prowess dx](https://www.cmie.com/kommon/bin/sr.php?kall=wproducts&tabno=7010&prd=prowessdx), [RBI Statistical Tables Relating to Banks](https://rbi.org.in/Scripts/AnnualPublications.aspx?head=Statistical+Tables+Relating+to+Banks+in+India)

---

## Gap 5 — Machine-readable Indian earnings-call transcripts (timestamped, survivorship-complete)

**No source conclusively verified.** `confidence: low · no surviving claim`
The full evaluation set — AlphaSense/Sentieo, Refinitiv StreetEvents transcripts, S&P Capital IQ Transcripts, FactSet CallStreet, Bloomberg, Trint/Rev ASR, and India-native Trendlyne/Tijori/Screener — produced **zero surviving verified claims**. The implied best path, **by inference only** from stack-consolidation logic (already buying LSEG for Gaps 1+3), is **Refinitiv/LSEG StreetEvents** for global-grade timestamped transcripts, with Trendlyne/Screener concalls as the budget alternative. Survivorship-completeness and exact-timestamp/API delivery for India remain **UNVERIFIED**. Treat as fully open.
- Candidate sources probed: [LSEG transcripts database](https://www.lseg.com/en/data-analytics/financial-data/company-data/events/earnings-transcripts-briefs/transcripts-database), [S&P Capital IQ Transcripts (IIMA PDF)](https://library.iima.ac.in/public/resource/SandP_Capital_IQ_Transcripts.pdf), [FactSet Events & Transcripts API](https://www.factset.com/marketplace/catalog/product/factset-events-and-transcripts-api)

---

## Single best integrated stack

`confidence: medium — synthesis of unanimous component claims; India-coverage gaps lower confidence`

- **(a) Highest-coverage single India-native subscription → CMIE Prowess.** Verified for Gap 3 (survivorship-aware deep fundamentals since 1990) and strongest candidate for Gap 4 (bank/NBFC asset quality), with plausible reach into Gap 1 (estimates) and Gap 5 (concalls) — both unverified.
- **(b) Best 2-vendor combo → LSEG/Refinitiv + CMIE Prowess.** LSEG covers Gap 1 (I/B/E/S beat/miss + deep history machinery, verified), Gap 3 (Worldscope PIT, verified), Gap 2 (India fixed-income curves, candidate), Gap 5 (StreetEvents, inferred). CMIE supplies the India-native depth/survivorship LSEG's evidence does **not** establish for India.
- **For Gap 2 specifically:** add **FBIL** (cheap, authoritative, paid feed) regardless of the main stack.

**Integration logic:** every global-vendor verified claim carries an explicit India-depth caveat (I/B/E/S India pre-2011 "very limited"; Worldscope India-depth REFUTED 0-3; VA global large-cap tilt), while CMIE Prowess is the only vendor with verified deep Indian coverage AND survivorship-awareness AND a programmatic API. No single vendor cleanly covers all five for India.

---

## Cross-cutting caveats

1. **India-depth is the pervasive weakness.** Every global-vendor strength was verified for the product *generally*, not India. I/B/E/S India pre-2011 "very limited"; Worldscope India-depth **refuted 0-3**; Visible Alpha global large/mid-cap tilted with unconfirmed NSE/BSE breadth.
2. **PIT ≠ survivorship-free.** Some sources document PIT timestamping (Worldscope add/update dates) without survivorship-free dead-company coverage, and vice versa (CMIE survivorship-aware but vintage/restatement PIT not established). The hard requirement needs **both** — not jointly verified for any single India source.
3. **Vendor-marketing sourcing.** Company counts and "99% of market cap" are self-reported. CMIE's survivorship claim is hedged ("no *deliberate* survival bias") — a 2-1 split, not an audited guarantee.
4. **Access nuances.** FBIL free path is 7-day-lagged web-view only (paid for timely/programmatic); ACE Equity Nxt's deep 1,750-field DB is desktop-only and its FTP/API datafeed carries only shallow 5yr/8qtr financials; CMIE/VA "APIs" retrieve predefined tabulations or need enterprise onboarding, not arbitrary public REST.
5. **Time-sensitivity.** Visible Alpha was acquired by S&P Global (product page redirects); packaging/pricing in flux.
6. **Two gaps are evidence-thin.** Gap 4 line-item granularity and Gap 5 (transcripts) have **no** directly verified source — recommendations are hypotheses to validate.
7. **Pricing.** Almost no concrete tiers verified except FBIL (₹50k–10L/yr). All global vendors (LSEG, S&P CapIQ, Bloomberg, Visible Alpha, FactSet) are "enterprise quote".

---

## Open questions (validate before buying)

1. Does **CMIE Prowess** (or ACE/Capitaline) actually carry granular bank/NBFC asset-quality line items — GNPA, NNPA, PCR, slippage, SMA/restructured book, segmental NIM, CAR — consistently across the full universe with 10y+ depth? *(Gap 4 inferred, not verified — needs a data-dictionary review or vendor sample extract.)*
2. Which vendor has clean, timestamped, survivorship-complete, machine-readable **Indian transcripts** with an API/feed? *(Gap 5 had zero surviving claims — StreetEvents, S&P CapIQ Transcripts, AlphaSense, Trendlyne/Screener all need direct probing for India coverage, exact timestamps, delisted-name inclusion.)*
3. Is there **any** source providing true PIT Indian **consensus estimates** (as-known-on-historical-date) with restatement vintages and deep small/mid-cap coverage? *(Least-resolved part of Gap 1.)*
4. For **Gap 2 pre-2018 history** (2013 taper, 2018 IL&FS) and corp-bond AAA/AA/A credit spreads by tenor — does RBI DBIE/FIMMDA offer bulk export, and do Refinitiv/Bloomberg/Nasdaq Data Link provide a clean programmatic India credit-curve feed with that depth?
5. Does **CMIE Prowess support a true vintage/as-first-reported (restatement-aware) PIT layer**, or only latest as-reported figures? *(Survivorship-aware verified; PIT-restatement integrity for un-look-ahead backtests not established.)*

---

## Refuted claims (killed in verification)

| Claim | Vote | Source |
|---|---|---|
| Worldscope EM/India history reaches 25+ years (≈2.5 decades, exceeding 15-yr target) | **0-3** | [lseg.com Worldscope](https://www.lseg.com/en/data-analytics/financial-data/company-data/fundamentals-data/worldscope-fundamentals) |
| Prowess IQ landing page discloses none of company count / history / PIT / survivorship / NBFC line-items / estimates / pricing | **0-3** | [prowess.cmie.com](https://prowess.cmie.com/) |
| Public ACE materials disclose nothing on PIT/as-reported, survivorship, history depth, or company count | **0-3** | [aceanalyser.com](http://www.aceanalyser.com/) |
| I/B/E/S via WRDS (from 1976) is *the* canonical PIT consensus dataset for Gap 1 | **1-2** | [IIMB library](https://library.iimb.ac.in/database/a-z) |

---

*Generated by the `deep-research` harness (108 agents, adversarial 3-vote verification). Confidence labels and vote tallies are preserved from the run. "Inferred" findings have no direct supporting claim and should be validated independently before any purchase decision.*
