"""
Alpha Signal v2 — Macro Market Data (yfinance)

Fetches 3yr daily history for 20 market-based macro indicators:
- Nifty sectoral indices (12)
- Commodities (5: crude, gold, copper, aluminium, silver)
- FX (1: USD/INR)
- Rates (1: US 10Y yield)
- Volatility (1: India VIX)

Stores in macro_history table. Also populates macro_indicator_meta.

Usage:
    python -m sources.macro_yfinance                  # backfill 3yr
    python -m sources.macro_yfinance --days 30        # last 30 days only
    python -m sources.macro_yfinance --dry-run        # show what would be fetched
"""

import argparse
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from db import get_db, upsert_df, insert_df, read_sql
from sources import _http

# Ticker registry: indicator_id → (yf_ticker, name, category, unit)
TICKERS = {
    # Sectoral indices
    "nifty50":          ("^NSEI",       "Nifty 50",         "coincident", "index"),
    "bank_nifty":       ("^NSEBANK",    "Bank Nifty",       "coincident", "index"),
    "nifty_it":         ("^CNXIT",      "Nifty IT",         "coincident", "index"),
    "nifty_metal":      ("^CNXMETAL",   "Nifty Metal",      "coincident", "index"),
    "nifty_realty":     ("^CNXREALTY",   "Nifty Realty",     "coincident", "index"),
    "nifty_pharma":     ("^CNXPHARMA",  "Nifty Pharma",     "coincident", "index"),
    "nifty_auto":       ("^CNXAUTO",    "Nifty Auto",       "coincident", "index"),
    "nifty_fmcg":       ("^CNXFMCG",    "Nifty FMCG",       "coincident", "index"),
    "nifty_energy":     ("^CNXENERGY",  "Nifty Energy",     "coincident", "index"),
    "nifty_infra":      ("^CNXINFRA",   "Nifty Infra",      "coincident", "index"),
    "nifty_psubank":    ("^CNXPSUBANK", "Nifty PSU Bank",   "coincident", "index"),
    "nifty_media":      ("^CNXMEDIA",   "Nifty Media",      "coincident", "index"),
    # Volatility
    "india_vix":        ("^INDIAVIX",   "India VIX",        "leading",    "index"),
    # Commodities
    "brent_crude":      ("BZ=F",        "Brent Crude",      "leading",    "usd"),
    "gold":             ("GC=F",        "Gold",             "leading",    "usd"),
    "copper":           ("HG=F",        "Copper",           "leading",    "usd"),
    "aluminium":        ("ALI=F",       "Aluminium (LME)",  "leading",    "usd"),
    "silver":           ("SI=F",        "Silver",           "leading",    "usd"),
    # FX
    "usdinr":           ("USDINR=X",    "USD/INR",          "coincident", "inr"),
    # Rates
    "us_10y":           ("^TNX",        "US 10Y Yield",     "leading",    "percent"),
    # India rates / credit (§3.2.7). NSE-listed ETFs are the only free *daily*
    # India-rates source reachable from this VM — FBIL/CCIL/RBI are Angular/403-
    # walled, FRED is monthly + times out, Investing.com/Stooq IP-block datacenters.
    # Daily *returns* (auto_adjust=True → total return) feed macro_betas:
    #   gsec10_etf  → rate_beta   (ETF rises when the 10Y yield falls; sign-fixed there)
    #   aaa_psu_etf → credit leg  (paired vs gilt into credit_excess_idx below)
    "gsec10_etf":       ("SETF10GILT.NS", "India 10Y G-Sec (SBI Gilt ETF)",  "leading", "inr"),
    "aaa_psu_etf":      ("EBBETF0430.NS",  "AAA-PSU bond (Bharat Bond ETF)",  "leading", "inr"),
}


def _populate_meta():
    """Insert/update macro_indicator_meta for all yfinance tickers."""
    rows = []
    for ind_id, (ticker, name, category, unit) in TICKERS.items():
        rows.append({
            "indicator_id": ind_id,
            "name": name,
            "source": "yfinance",
            "source_ref": ticker,
            "category": category,
            "frequency": "daily",
            "unit": unit,
            "description": f"{name} — daily from yfinance ({ticker})",
        })
    df = pd.DataFrame(rows)
    with get_db() as conn:
        upsert_df(df, "macro_indicator_meta", conn=conn)
    return len(rows)


def _fetch_all(start_date, end_date):
    """Daily close for every TICKERS entry in ONE batched yf.download (was one
    download + 0.5s sleep per ticker). Returns {indicator_id: DataFrame}; a
    ticker with no data maps to an empty frame. The batch's date index is the
    union across exchanges, so each series drops its NaN (non-trading) rows —
    leaving exactly what a single-ticker download returned."""
    symbols = [t for t, _, _, _ in TICKERS.values()]
    try:
        with _http.pace("yahoo"):
            data = yf.download(symbols, start=start_date, end=end_date, progress=False,
                               auto_adjust=True, group_by="ticker", threads=False)
    except Exception as e:
        print(f"  Error fetching batch: {e}")
        return {ind_id: pd.DataFrame() for ind_id in TICKERS}

    out = {}
    for ind_id, (ticker, _, category, unit) in TICKERS.items():
        if data.empty or ticker not in data.columns.get_level_values(0):
            out[ind_id] = pd.DataFrame()
            continue
        close = data[ticker]["Close"].dropna()
        out[ind_id] = pd.DataFrame({
            "indicator_id": ind_id,
            "date": close.index.strftime("%Y-%m-%d"),
            "value": close.values,
            "source": "yfinance",
            "category": category,
            "unit": unit,
        })
    return out


def _compute_changes(df):
    """Compute YoY and MoM changes for a single indicator's time series."""
    if df.empty or len(df) < 2:
        return df

    df = df.sort_values("date").copy()
    vals = df["value"].values

    # MoM: vs 22 trading days ago (~1 month)
    mom = pd.Series(vals).pct_change(periods=min(22, len(vals) - 1)) * 100
    df["mom_change"] = mom.values

    # YoY: vs 252 trading days ago (~1 year)
    if len(vals) > 252:
        yoy = pd.Series(vals).pct_change(periods=252) * 100
        df["yoy_change"] = yoy.values

    return df


def backfill(days=None, dry_run=False):
    """Fetch macro market data and store in macro_history."""
    if days:
        start = (date.today() - timedelta(days=days)).isoformat()
    else:
        start = (date.today() - timedelta(days=3 * 365 + 30)).isoformat()
    end = date.today().isoformat()

    print(f"Macro yfinance backfill: {start} to {end}")
    print(f"Tickers: {len(TICKERS)}")

    if dry_run:
        for ind_id, (ticker, name, _, _) in TICKERS.items():
            print(f"  {ind_id:20s} {ticker:15s} {name}")
        print("\nDry run — not fetching.")
        return 0

    # Populate metadata
    _populate_meta()
    print("Metadata: populated")

    total_rows = 0
    fetched = _fetch_all(start, end)
    for i, (ind_id, (ticker, name, _, _)) in enumerate(TICKERS.items(), 1):
        print(f"  [{i:2d}/{len(TICKERS)}] {ind_id:20s} {ticker:12s} ", end="", flush=True)

        df = fetched[ind_id]
        if df.empty:
            print("— no data")
            continue

        df = _compute_changes(df)

        upsert_df(df, "macro_history")
        total_rows += len(df)
        print(f"— {len(df)} rows")

    print(f"\nTotal: {total_rows} rows in macro_history")
    if total_rows == 0:
        # One batched call now feeds all tickers — an all-empty result is a
        # yfinance outage/block, not a quiet market (daily runs return 68-114).
        raise RuntimeError(f"macro_yfinance: 0 rows for all {len(TICKERS)} tickers {start}→{end}")

    # Mirror india_vix into vix_history so regime.py + diff_engine read fresh data.
    # vix_history is the historical contract; macro_history is the firehose.
    vix_rows = _sync_vix_history()
    if vix_rows:
        print(f"Mirrored {vix_rows} rows into vix_history")

    # Derive the India credit series from the two bond ETFs (full-history recompute).
    cs_rows = _compute_credit_spread()
    if cs_rows:
        print(f"Derived credit_excess_idx: {cs_rows} rows (AAA-PSU − gilt excess index)")

    return total_rows


def _sync_vix_history():
    """Copy india_vix rows from macro_history into vix_history (idempotent)."""
    df = read_sql(
        "SELECT date, value AS vix FROM macro_history "
        "WHERE indicator_id='india_vix' AND value IS NOT NULL "
        "ORDER BY date"
    )
    if df.empty:
        return 0
    return upsert_df(df, "vix_history")


def _compute_credit_spread():
    """Derive the daily India credit series `credit_excess_idx` from the two ETFs.

    credit factor return = ret(AAA-PSU bond ETF) − ret(10Y gilt ETF)
      → AAA-PSU *excess* return over a duration-comparable sovereign. Positive when
        credit spreads TIGHTEN (risk-on credit); negative when they widen (stress —
        e.g. the Mar-2020 NBFC/credit blowout). Stored as a base-100 cumulative
        index so the beta machinery (which takes pct_change of the stored level)
        recovers the daily credit-factor return directly.

    CAVEAT: Bharat Bond is target-maturity, so its duration drifts below the 10Y
    gilt over time → the spread carries a residual duration tilt. credit_beta must
    be orthogonalised vs rate_beta before use. (No free/daily constant-maturity AAA
    index ETF exists; FBIL's true AAA-over-G-Sec spread is the authoritative upgrade
    once we can reach it.) Always recomputed from full history — idempotent.
    """
    g = read_sql("SELECT date, value FROM macro_history WHERE indicator_id='gsec10_etf' "
                 "AND value IS NOT NULL ORDER BY date")
    c = read_sql("SELECT date, value FROM macro_history WHERE indicator_id='aaa_psu_etf' "
                 "AND value IS NOT NULL ORDER BY date")
    if g.empty or c.empty:
        return 0
    m = g.merge(c, on="date", suffixes=("_g", "_c")).sort_values("date")
    m["ret"] = m["value_c"].pct_change() - m["value_g"].pct_change()
    m = m.dropna(subset=["ret"])
    if m.empty:
        return 0
    idx = 100.0 * (1.0 + m["ret"]).cumprod()
    out = pd.DataFrame({
        "indicator_id": "credit_excess_idx",
        "date": m["date"].values,
        "value": idx.values,
        "source": "derived",
        "category": "leading",
        "unit": "index",
    })
    out = _compute_changes(out)
    meta = pd.DataFrame([{
        "indicator_id": "credit_excess_idx",
        "name": "India AAA-PSU credit excess index",
        "source": "derived",
        "source_ref": "EBBETF0430.NS − SETF10GILT.NS (daily excess return, base100)",
        "category": "leading",
        "frequency": "daily",
        "unit": "index",
        "description": ("Cumulative AAA-PSU-over-gilt excess-return index (Bharat Bond − "
                        "SBI 10Y Gilt). Daily return = India credit factor; rises when "
                        "credit spreads tighten. Duration-tilt caveat — orthogonalise vs "
                        "rate_beta. §3.2.7."),
    }])
    with get_db() as conn:
        upsert_df(meta, "macro_indicator_meta", conn=conn)
    return upsert_df(out, "macro_history")


def compute(dry_run=False):
    """Pipeline entry point — daily refresh (last 7 days)."""
    return backfill(days=7, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, help="Fetch last N days (default: 3yr)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    backfill(days=args.days, dry_run=args.dry_run)
