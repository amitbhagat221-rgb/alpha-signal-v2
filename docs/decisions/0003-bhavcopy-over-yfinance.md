# 0003 — NSE Bhavcopy over yfinance for prices

**Status:** Accepted
**Date:** 2026-04-09
**Decided by:** Amit (with Claude Code)

## Context

v1 used `yfinance` (via `02_fetch_price_data.py`) as the primary OHLCV source. yfinance is convenient — `yf.download("RELIANCE.NS")` and you have prices.

However, during the data-source audit we noticed two problems with yfinance for Indian equities:

1. **Prices are Yahoo's adjusted view, not NSE official** — corporate actions/dividends are retroactively folded in. Acceptable for casual use, wrong for a system whose backtests need NSE-authoritative closes.
2. **No delivery percentage** — yfinance only has total volume. Delivery % (delivered_qty / traded_qty) is a meaningful "informed accumulation" signal which v1 was already fetching from NSE bhavcopy in a separate script (`16_smart_money.py`).

Meanwhile NSE publishes a daily bhavcopy CSV at `archives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv` containing OHLCV + delivery % + traded value + number of trades. v1 was already fetching it daily — we were paying for two sources and using only half of each.

## Decision

NSE Bhavcopy is the primary source for daily OHLCV.

```
sources/nse.py        → stock_prices  (open, high, low, close, volume,
                                       delivered_qty, delivery_pct,
                                       traded_value, num_trades)
```

yfinance is **kept** for India VIX (`^INDIAVIX`) — there's no equivalent NSE archive for VIX, and yfinance works fine for that one ticker.

## Alternatives considered

- **Stay with yfinance.** Rejected: missing delivery %, retro-adjusted prices, no rate-limit guarantees from a non-public API.
- **Tickertape OHLCV.** Tickertape exposes prices but they're derived from NSE anyway, with their own scraping fragility on top.
- **Paid data vendors.** Overkill for daily EOD. NSE gives us this for free.

## Consequences

**Easier:**
- NSE-official close prices (no adjustment ambiguity)
- Delivery % available for all stocks, all days — can be a signal everywhere, not just smart_money
- Volume quality signal: `delivery_pct > 50%` = informed accumulation
- Single source of truth for prices — one table (`stock_prices`), not 501 individual CSV files

**Harder:**
- Bhavcopy is one day at a time → backfill takes ~25 min for 3 years (vs yfinance's bulk download)
- Bhavcopy column names have leading spaces — must `.str.strip()` after read
- Bhavcopy format changed Apr 3, 2026 (simplified) — fetch raw from archives, not the new endpoint
- Need User-Agent spoofing + 2s delay between requests
- Weekend/holiday files don't exist — need fallback logic (try prior 4 calendar days)

**Will bite us if:**
- NSE changes the URL pattern (mitigation: small pinch of integration testing on the daily fetch)
- A holiday's bhavcopy never gets published (mitigation: skip-and-continue logic, alert if >2 consecutive missing days)

## References

- Source module: `sources/nse.py` (NOT YET BUILT — Phase D)
- Existing daily bhavcopy fetcher: `sources/nse_bulk.py` (already operational for bulk deals + delivery)
- Original strategy doc: [../_archive/2026-04-09-data-source-strategy.md](../_archive/2026-04-09-data-source-strategy.md)
