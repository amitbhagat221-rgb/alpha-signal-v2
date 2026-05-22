# Paid Data Sources — ₹5K/month budget

Stack-ranked paid subs that fit ~₹5K/mo. Companion to [api-endpoints.md](api-endpoints.md) (free).
Re-evaluate quarterly. Last review: 2026-05-03 (post-nselib discovery, which dropped paid marginal value sharply).

## Recommended allocation

```
Zerodha Kite Connect  ₹500   proper data API + future trading
Screener Premium      ₹420   deep fundamentals, 5K+ stocks
Trendlyne             ₹500   curated alt sources (optional)
                      ─────
Recurring             ₹1,420
Reserve               ₹3,580   for occasional EODHD bursts, Tijori
```

## Tier 1 — High conviction

### Zerodha Kite Connect — ₹500/mo

Sub only if you already have a Zerodha account (same login).

- Real-time + 5+ years OHLCV across all segments (equity, F&O, MCX, FX)
- WebSocket streaming, order placement, instrument master
- F&O OI + Greeks (exchange-computed)
- Properly split-adjusted history; no rate-limit anxiety; no Adj-Close vs raw ambiguity
- Replaces yfinance + manual options + 2–3 fragile feeds

Caveat: SEBI requires static IP for API trading — Oracle VM has one ✅.

### Screener Premium — ₹420/mo (₹5K/yr)

**No official API.** Premium gives Excel/CSV export per company + 10y quarterlies + 5K-stock bulk download + custom screens.

Practical pattern (login + Excel):

```python
import requests, pandas as pd, io
s = requests.Session()
s.post("https://www.screener.in/login/", data={"username":..., "password":...})
xls = s.get("https://www.screener.in/api/company/RELI/export/")
df = pd.read_excel(io.BytesIO(xls.content))
```

Library: [`screenerpy`](https://github.com/) wraps this. Or DIY with `requests` + `openpyxl`.

Risk: TOS-gray. Free alternative: scrape public HTML pages (~90% of Premium, slower, rate-limited).
Why pay: speed (one export → 5K-stock fundamentals) + saved screens + alerts.

## Tier 2 — Budget permitting

### EODHD India Fundamentals — $20-60/mo

- 30+ years historical fundamentals for 5K+ Indian stocks
- **Cleanest filing-date-aware API** — solves PIT cleanly
- Income/BS/CF with restatements

Recommended pattern: one-month bursts when extending PIT past 2023.

### Trendlyne — ₹500/mo

Curated insider data, historical bulk/block with date range (Plan B for nselib), DII/FII deep cuts, pre-built screeners. Lower priority than Kite + Screener.

## Tier 3 — Skip unless specific need

| Source | Cost | Why skip |
|---|---|---|
| AlphaVantage Premium | $50/mo | India coverage patchy |
| TrueData | ₹500-2K/mo | Tick + Greeks — only for options/HFT |
| Sensibull / Opstra | ₹500-1.5K/mo | We'd compute from Kite raw |
| Tijori Finance | ₹500-1.5K/mo | Niche but powerful for Track 2.2 |
| Bharat-SM-Data Premium | varies | Duplicates Tickertape |
| Stockedge Premium | ~₹500/mo | Trendlyne wins on data |
| Refinitiv / Bloomberg / FactSet | $$$$ | Out of budget |

## Sensibull — special note

Sensibull doesn't sell a public retail API; it's B2B (Zerodha embeds them inside Kite). Their analytics (max pain, OI buildup classification, multi-leg P&L, IV percentile, dispersion screens) are all computable from raw Kite option chain data. **Skip.**

## Decision tree

1. Need historical OHLCV with proper splits? → **Kite** (₹500/mo)
2. Need 5K+ small-caps not in Tickertape? → **Screener Premium** (₹420/mo)
3. Need 30y filing-date-clean fundamentals for backtest? → **EODHD** ($20 for one month)
4. Need insider/bulk beyond nselib? → **Trendlyne** (₹500/mo)
5. Need options Greeks / IV surface? → **TrueData** or Kite
6. Anything else? → Try free first. nselib + mfapi.in + Tickertape covers ~80%.

## Related

- [api-endpoints.md](api-endpoints.md) · [data-playbook.md](data-playbook.md) · [plans/0002-100-factors-and-model.md](../plans/0002-100-factors-and-model.md)
