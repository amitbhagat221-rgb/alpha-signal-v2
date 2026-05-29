# 0030 — Banking metrics source: Screener.in stock page, not Tickertape

**Status:** Accepted
**Date:** 2026-05-29
**Supersedes (partially):** [Plan 0001 Open Question #3](../plans/0001-mother-plan.md) ("Tickertape-first; promote RBI to primary only if Tickertape gaps cost real signal")

## Context

Track 2.2 (Financial sub-model) needs per-bank-per-quarter ingestion of metrics the main screener can't produce: **NIM, CASA, GNPA, NNPA, PCR, CAR, Slippage, Credit cost, Cost of Funds**. These are bank-specific regulatory disclosures, not standard P&L items.

Plan 0001 §2.2 specified **Tickertape-first** as the source on the working assumption that Tickertape's structured ratios surface would carry them. Probe on 2026-05-29 disproved that.

### What Tickertape actually gives us

The `Bharat_sm_data.Fundamentals.TickerTape.get_key_ratios()` method scrapes `__NEXT_DATA__` from the stock page and returns `securityInfo.ratios`. For HDFC Bank (HDBK) the field set is:

```
risk, 3mAvgVol, 4wpct, 52wHigh, 52wLow, 52wpct, apef, beta, bps, divYield,
eps, etfLiq, inddy, indpb, indpe, lastPrice, marketCap, mrktCapRank, pb, pbr,
pe, roe, ttmPe, 12mVol, ...
```

Zero bank-specific fields. The income statement endpoint (`income-normal-annual`) uses the same generic schema (`incTrev / incOpe / incEbi / incNinc`) for banks and non-banks alike — no Net Interest Income, no Provisions, no Asset Quality breakdown.

The Tickertape *web UI* does show an Asset Quality widget on bank pages, but the data lives in a different API endpoint that the `Bharat_sm_data` library does not wrap. Reverse-engineering would mean discovering and maintaining a private endpoint contract — fragile.

### What Screener.in actually gives us

The stock page at `screener.in/company/<TICKER>/consolidated/` renders bank-aware tables. Direct probe on HDFCBANK (2026-05-29):

```
Gross NPA %      — quarterly column, 13 quarters of history
Net NPA %        — quarterly column, 13 quarters of history
Financing Profit — quarterly column (= Net Interest Income for banks)
Interest         — quarterly column (= Interest Expended for banks)
Deposits         — balance sheet row
Sales            — quarterly column (= Interest Earned for banks)
```

From these primitives we can derive **NIM** (Financing Profit / avg Advances), can use **GNPA % and NNPA %** directly, and can derive **Cost of Funds** approximations for NBFCs. **CASA, PCR, CAR** are not on the standard page and need a secondary source.

We already have:
- Screener.in credentials in `~/alpha-signal/run_pipeline.sh`
- A live `sources/screener_pull.py` with 681K rows in `fundamentals_screener`
- Proven retry/checkpoint/throttle infrastructure
- Universe-wide SID → Screener-ticker mapping working

Extending the existing pull to capture bank-specific tables is straightforward; building a new Tickertape banking endpoint is reverse-engineering work.

### Scope clarification

"Financials" in our taxonomy is **249 stocks** across 5 industries. Only 158 of those (Banks 41 + NBFCs 117) actually need the banking lens. The other 91 (AMC 27, Insurance 13, Capital Markets / Exchanges 51) have their own valuation primitives — AUM growth, VNB margin, persistency, transaction volume — and shouldn't get a `financial_signal` score that pretends NIM/GNPA matter for them.

## Decision

1. **Primary source: Screener.in** stock page (`/company/<TICKER>/consolidated/`). New module `sources/banking_metrics.py` — parses bank-aware tables on Screener.in for the 158 Banks + NBFCs only.

2. **Supplementary source: Tickertape** for fields Screener.in carries inconsistently (P/B, ROA, ROE already in our analyst_consensus / quarterly_income). No new Tickertape work for banking-specific ratios.

3. **Fallback source: RBI quarterly statements** — promote from "future" to "explicit fallback" for CASA, PCR, CAR, Slippage, Credit cost. Not built in Phase 2.2a; treat as known gap, add in Phase 2.2b if the empirical Phase-1 coverage shows it material.

4. **Scope of `financial_signal`**: **Banks + NBFCs only**. The other 91 Financials stocks stay routed through the main screener with the existing exclusions on Piotroski / accruals / sales growth (the "degenerate case" is honest for them — they at least get P/E, P/B, momentum, sentiment).

5. **Plan 0001 §2.2 Open Question #3 is closed** by this ADR. The new sequencing is:

   | Phase | Build | Cost |
   |---|---|---|
   | 2.2a | Screener.in bank-page parser → `banking_metrics` table → 158 SID backfill | ~1 session |
   | 2.2b | `signals/financial_signal.py` + routing in `scoring/screener.py` | ~1 session |
   | 2.2c | RBI fallback for CASA/PCR/CAR if material gap | gated on 2.2a coverage report |
   | 2.2d | Cockpit financial sub-model page + backtest validation | ~1 session |

## Consequences

**Good:**
- One source, one auth path, one infra pattern. We don't carry two competing scrapers.
- Reuses 681K-row `fundamentals_screener` discipline (validators, retry, checkpoint).
- Honest about which stocks the sub-model applies to.

**Bad:**
- Screener.in doesn't carry CASA, PCR, CAR on the standard page. These are core "moat" + "capital adequacy" fields. The Phase-2.2a coverage report will tell us if going without them is acceptable.
- Tickertape work already done for `analyst_consensus` / `quarterly_income` continues to carry banks but with the same generic schema — no banking-specific enrichment from there.
- We've now over-ruled Plan 0001 once on this question. If RBI also fails to fill the CASA/PCR/CAR gap, we'll need a third source (annual-report PDF parsing, IndianAPI.in, or paid Trendlyne). Set the bar at "if it's needed, ship a thin RBI scraper; don't fold that decision into 2.2a".

**Neutral / watch:**
- The Plan 0001 keystone formula `Adj_Book = BV − GNPA × (1 − PCR/100)` requires PCR. Without PCR from a source, we ship `Adj_Book_approx = BV − GNPA` (zero recovery assumption — pessimistic, defensible). Document this in `signals/financial_signal.py` when built.
- Academic evidence (MDPI 2025): **NIM β=+0.583** and **Net NPA β=−0.251** are the strongest predictors. We CAN get both from Screener.in. CAR is "no meaningful direct impact" — losing it as alpha is fine, only matters as a risk filter. So in practice the most important fields are all on Screener.in.

## References
- Plan 0001 §2.2 "Financial sub-model"
- `/home/ubuntu/alpha-signal/docs/financial_model_reference.md` (v1 53-line spec — preserved as authoritative for the factor map and benchmarks)
- Empirical probe 2026-05-29 (this session's HANDOFF will reference)
