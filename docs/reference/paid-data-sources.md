# Paid Data Sources — ₹5,000/month Budget Playbook

> Stack-ranked paid Indian-equity data subscriptions that fit a ~₹5,000/month
> data budget. Includes the Screener Premium scrape pattern (no official API).
> Companion to [api-endpoints.md](api-endpoints.md) (free sources) and
> [paid_data_sources](../../) memory entry it was extracted from.
>
> **Last reviewed:** 2026-05-03 — after the nselib discovery dropped marginal
> value of paid sources sharply. Re-evaluate quarterly.

---

## Tier 1 — High conviction, fits the budget

### Zerodha Kite Connect — ₹500/month

**Only sub if you already have a Zerodha trading account** (single login, no friction).

**What unlocks:**
- Real-time + 5+ years historical OHLCV across all segments (equity, F&O, MCX, currency)
- WebSocket streaming for live data
- Order placement API (eventual automation)
- Instrument master (3,000+ instruments)
- F&O OI, Greeks (computed by exchange)

**Why it's the best single pick:**
- Only ₹500/mo for a real, supported, stable API
- Same login as user's existing trading account
- Replaces 3-4 fragile sources (yfinance for prices, manual options data, etc.)
- No rate-limit anxiety like NSE direct
- Properly split-adjusted historical (no Adj-Close vs raw issues)

**Caveat:** SEBI requires static IP for API trading. Oracle VM has one ✅.

---

### Screener.in Premium — ₹420/month (₹5,000/year)

**Important: NO official API.** Premium gives:
- Excel/CSV export of any custom screen
- Bulk download of fundamentals for 5,000+ stocks
- 10+ years quarterly data per stock (Tickertape only has 10 quarters)
- Better small-cap coverage (Tickertape skips many)
- Custom screening with 100+ ratios

**The practical scrape pattern (what to actually code):**

```python
import requests, pandas as pd, io

s = requests.Session()
# 1. Login (one-time, save cookies to ~/.cache/screener_cookie.json)
s.post(
    "https://www.screener.in/login/",
    data={"username": "...", "password": "..."}
)

# 2. Excel export endpoint (Premium only)
xls = s.get("https://www.screener.in/api/company/RELI/export/")

# 3. Parse with pandas
df = pd.read_excel(io.BytesIO(xls.content))
```

**Tools:** [`screenerpy`](https://github.com/) wraps this; or DIY with
`requests` + `openpyxl`.

**Risk:** technically TOS-gray; data is the same that's web-visible anyway,
Premium just makes BULK access easy.

**Free alternative:** Screener exposes most data on each stock's HTML page.
Scrape public pages for free with rate limits — gets ~90% of Premium, slower.

**Why pay:** speed (one Excel export → 5K-stock fundamentals) and saved
screens / custom alerts.

---

### Combined Tier 1: ₹920/mo. Leaves ~₹4,080/mo reserve.

---

## Tier 2 — Worth considering, budget-permitting

### EODHD India Fundamentals — $20-60/month (~₹1,700-5,000)

**What unlocks:**
- 30+ year historical fundamentals for 5,000+ Indian stocks
- **Cleanest filing-date-aware API** (knows when each filing was disclosed → solves PIT cleanly)
- Income / balance sheet / cash flow for full universe with restatements
- Same data quality as Bloomberg/Refinitiv at 1/100 the cost

**Why consider:** if serious about backtest fidelity, this is the cleanest source.
Tickertape gives 10 quarters; EODHD gives 30 years.

**Trade-off:** most expensive in our budget. Recommended pattern: occasional
one-month sub when extending v2 PIT history past 2023.

---

### Trendlyne — ~₹500/month

**What unlocks:**
- Curated insider trading data (cleaner than NSE PIT)
- Historical bulk/block deals with date range (Plan B if nselib breaks)
- DII/FII deep cuts
- Pre-built screeners

**Why consider:** backup for data we now get free via nselib + extra curated cuts.
Lower priority than Zerodha + Screener.

---

## Tier 3 — Skip unless specific need

| Source | Cost | Why skip |
|---|---|---|
| AlphaVantage Premium | $50/mo (~₹4,200) | Indian coverage patchy; not best $50 spend |
| TrueData | ₹500-2,000/mo | Tick + Greeks — only matters for options/HFT |
| Sensibull / Opstra | ₹500-1,500/mo | Options analytics; we'd compute these from Kite raw |
| Tijori Finance | ₹500-1,500/mo | Indian small/mid cap — niche but powerful for D15 |
| Bharat-SM-Data Premium | varies | Effectively duplicates Tickertape |
| Refinitiv / Bloomberg | $$$$ | Way out of budget |
| FactSet | $$$$ | Way out of budget |
| Stockedge Premium | ~₹500/mo | Decent but Trendlyne wins on data |

---

## Sensibull — special note

**Sensibull does NOT sell a public retail API.** Their commercial offering is B2B
(brokers embed their analytics into their own platforms; Zerodha is one such
integration partner — that's how you see Sensibull *inside* Kite).

**What Sensibull's analytics layer adds on top of raw NSE/Kite data:**
- Max pain calculation
- OI buildup classification (long buildup vs short buildup vs unwinding)
- Strategy P&L visualizer (multi-leg)
- IV percentile vs 1y history
- Dispersion screens

**Verdict:** every one of these is computable from raw Kite option chain data.
We'd want to compute them ourselves anyway to keep PIT history. **Skip Sensibull.**

---

## Recommended allocation (₹5,000/mo)

```
Zerodha Kite Connect       ₹500   (proper data API + future trading)
Screener.in Premium        ₹420   (deep fundamentals, scrape pattern)
Trendlyne                  ₹500   (curated alt sources, optional)
                           ─────
Recurring:                 ₹1,420
Reserve:                   ₹3,580 — for occasional EODHD bursts, Tijori
                                    when Q-by-Q deep dives needed
```

---

## Decision tree — "do I need to pay for X right now?"

1. Need historical OHLCV with proper splits? → **Zerodha** (₹500/mo)
2. Need 5,000+ small-caps not in Tickertape? → **Screener Premium** (₹420/mo)
3. Need 30y filing-date-clean fundamentals for backtest? → **EODHD** ($20/mo for one month)
4. Need historical insider/bulk beyond what nselib gives? → **Trendlyne** (₹500/mo)
5. Need options Greeks / IV surface? → **TrueData** or Zerodha
6. Anything else? → Try free first; nselib + mfapi.in + Tickertape covers ~80%.

---

## Update protocol

After every paid-source evaluation or trial:
1. Add probe results to the table above
2. Note marginal value vs the free stack — paid is only worth it if it unblocks a *category* not covered free
3. Re-rank quarterly. Free sources improve faster than paid ones for niche markets like Indian equities.

---

## Cross-references

- [api-endpoints.md](api-endpoints.md) — free Tier A/B/C catalog
- [data-playbook.md](data-playbook.md) — PIT strategy, reconstruction patterns
- [docs/plans/0005-100-factors-and-model.md](../plans/0005-100-factors-and-model.md) — Phase A1 (Screener) and A3 (Kite) implementation
