# ADR 0042 — Data acquisition: build-not-buy from public endpoints; 2018 history floor

**Status:** accepted · **Date:** 2026-06-08

## Context
The benched factor families (PEAD, credit_beta, financial sub-model) and the NLP
look-ahead/survivorship doubts all reduce to *data depth + point-in-time integrity*, not
modelling. A money-no-object `deep-research` sweep (`docs/reference/pit-data-sources-research.md`,
108 agents) priced the "ideal" sources (CMIE Prowess, LSEG I/B/E/S/Worldscope, Bloomberg) as
enterprise quotes — and, decisively, **none sold to an individual without a live terminal**, with
every global vendor's depth claim carrying an India caveat (I/B/E/S India pre-2011 "very limited";
Worldscope India-depth refuted 0-3).

## Decision
1. **Build, don't buy.** Acquire the missing data from public/unofficial endpoints we operate
   ourselves, mirroring the existing yfinance/Screener/nselib pattern. Keystone: the **BSE
   corporate-announcement event stream** (`AnnSubCategoryGetData`, free, timestamped,
   survivorship-complete to 2018, delisted included) — one harvester seeds PEAD announce-dates,
   the transcript look-ahead fix, and net-new credit-rating / pledge / resignation / governance
   factor families. Verified-free PIT extras: **SEC-EDGAR** 20-F XBRL for Indian ADRs (as-filed,
   restatement-vintage), **TradingView** screener (~13k fields), **FIMMDA** credit spreads.
2. **2018 history floor** (user-approved). 2018 captures the IL&FS credit cycle + the bank-NPA
   peak-to-trough — exactly the regimes that bench credit_beta and the financial sub-model. The
   big lift is 2022→2018 (≈triples the panel); 2018→2013 is marginal at much higher data cost.
   *Caveat:* the floor applies to fundamental/macro/event families; F&O/IV (~2024) and
   delivery-microstructure (~2022) are capped by their own free-data limits, unchanged.
3. **Paid only as backfill accelerant**, never as a blocker — forward PIT (consensus snapshots,
   as-filed filings, transcripts) already accrues for free; a vendor only buys *historical* vintages.

## Consequences
- New `bse_announcements` table + `sources/bse_announcements.py`; `sid` join deferred to a static
  BSE-scrip-master ↔ ISIN ↔ ticker map.
- ToS: public-disclosure content is free for personal research; license the *real-time feed* before
  any commercial redistribution (noted in `data-playbook.md`).
- Curated OSS leverage list in `docs/reference/oss-quant-toolbox.md` (jugaad-data for 2018 prices,
  pysentiment2 full LM, Deflated Sharpe Ratio for the multiple-testing exposure).
