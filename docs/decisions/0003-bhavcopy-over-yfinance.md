# 0003 — NSE Bhavcopy over yfinance for prices
**2026-04-09 · Accepted**

**Decision.** Primary OHLCV source is NSE bhavcopy (`archives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv`). yfinance kept only for India VIX (`^INDIAVIX`).

**Why.**
- yfinance prices are Yahoo's retro-adjusted view — wrong for PIT backtests
- yfinance lacks delivery % (delivered_qty / traded_qty), which is a real "informed accumulation" signal
- NSE publishes free daily — single source of truth for prices

**Trade-offs.**
- One day at a time → 3yr backfill ≈ 25 min
- Column names have leading spaces (`.str.strip()` after read)
- Format changed Apr 3 2026 — fetch raw from archives
- Need User-Agent spoofing + 2s delay
- Weekend/holiday gaps → fallback to prior 4 calendar days

**References.** `sources/nse.py` · `sources/nse_bulk.py` · full data details in [reference/data-playbook.md](../reference/data-playbook.md)
