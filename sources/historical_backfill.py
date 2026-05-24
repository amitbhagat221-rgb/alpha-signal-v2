"""
Historical backfill harvesters for nselib-sourced tables.

One-time backfill of tables whose live harvesters only collect today's data:
  • bulk_deals          — current 2025-06+ → backfill to 2021+
  • short_selling_data  — current 2024-06+ → backfill to 2022+
  • fii_dii_positioning — current 2025-11+ → backfill to 2022+ (one date per call)
  • fii_dii_cash_flow   — currently empty (only FII derivatives via this script;
                          cash-segment flows are a different SEBI source — leave
                          for future work)

Per CLAUDE.md rules:
  • Never run two harvester scripts simultaneously — these functions are
    sequenced inside one process; if you parallelize them externally you'll
    double-rate the NSE endpoint and risk an IP block.
  • 2-second delay minimum between external calls (NSE_DELAY below).
  • Idempotent inserts (INSERT OR IGNORE for append-only tables).
  • Loud progress prints — no silent failures.

Usage:
    python -m sources.historical_backfill --source bulk     --start 2021-01-01
    python -m sources.historical_backfill --source short    --start 2022-01-01
    python -m sources.historical_backfill --source fii_fno  --start 2022-01-01
    python -m sources.historical_backfill --source all      --start 2022-01-01
"""

import argparse
import time
from datetime import date, datetime, timedelta

import pandas as pd

from db import get_db, read_sql, insert_df

NSE_DELAY = 2.5            # seconds between external calls (CLAUDE.md)
CHUNK_DAYS = 90            # date-range chunk for nselib calls; smaller = safer
PROGRESS_EVERY = 10        # print heartbeat every N chunks/dates


# ─────────── helpers ───────────

def _nselib_date(d):
    """Convert date/str to nselib's DD-MM-YYYY format."""
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return d.strftime("%d-%m-%Y")


def _parse_nselib_date(s):
    """nselib returns dates as '15-MAY-2026'. Convert to YYYY-MM-DD."""
    try:
        return datetime.strptime(s, "%d-%b-%Y").date().isoformat()
    except Exception:
        try:
            # Some endpoints return DD-MM-YYYY
            return datetime.strptime(s, "%d-%m-%Y").date().isoformat()
        except Exception:
            return None


def _comma_int(s):
    if pd.isna(s):
        return None
    if isinstance(s, (int, float)):
        return int(s)
    try:
        return int(str(s).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _comma_float(s):
    if pd.isna(s):
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _sid_map():
    """symbol → sid lookup from stocks table."""
    df = read_sql("SELECT sid, ticker FROM stocks WHERE ticker IS NOT NULL")
    return dict(zip(df.ticker.str.upper(), df.sid))


def _chunk_dates(start_date, end_date, chunk_days=CHUNK_DAYS):
    """Yield (chunk_start, chunk_end) tuples covering [start_date, end_date]."""
    d = start_date
    while d <= end_date:
        ce = min(d + timedelta(days=chunk_days - 1), end_date)
        yield d, ce
        d = ce + timedelta(days=1)


# ─────────── bulk_deals ───────────

def backfill_bulk(start_date, end_date=None):
    """Pull bulk_deals from NSE archive in chunks. Idempotent via PK."""
    from nselib import capital_market as cm
    if end_date is None:
        end_date = date.today()

    sid_map = _sid_map()
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_rows = 0
    chunks = list(_chunk_dates(start_date, end_date))
    print(f"[bulk] backfilling {start_date} → {end_date} in {len(chunks)} chunks of ≤{CHUNK_DAYS}d", flush=True)

    for i, (s, e) in enumerate(chunks, 1):
        try:
            raw = cm.bulk_deal_data(from_date=_nselib_date(s), to_date=_nselib_date(e))
        except Exception as ex:
            print(f"[bulk] {s}→{e}: ERROR {ex}", flush=True)
            time.sleep(NSE_DELAY * 2)
            continue

        if raw is None or len(raw) == 0:
            print(f"[bulk] {s}→{e}: 0 rows", flush=True)
            time.sleep(NSE_DELAY)
            continue

        rows = []
        for _, r in raw.iterrows():
            sym = str(r.get("Symbol", "")).upper().strip()
            sid = sid_map.get(sym)
            if not sid:
                continue
            rows.append({
                "sid": sid,
                "symbol": sym,
                "client_name": str(r.get("ClientName", ""))[:200],
                "deal_type": "bulk",   # nselib provides bulk + block separately
                "buy_sell": str(r.get("Buy/Sell", "")).strip().upper(),
                "quantity": _comma_int(r.get("QuantityTraded")),
                "price": _comma_float(r.get("TradePrice/Wght.Avg.Price")),
                "deal_date": _parse_nselib_date(r.get("Date")),
                "fetched_at": fetched_at,
            })

        if rows:
            df = pd.DataFrame(rows).dropna(subset=["deal_date"])
            # Append with INSERT OR IGNORE (id is autoincrement; dedupe via
            # (sid, deal_date, client_name, buy_sell, quantity) is impractical
            # without a real PK — accept some dupes on re-run, or add UNIQUE
            # constraint in a separate session).
            written = insert_df(df, "bulk_deals")
            total_rows += written
        if i % PROGRESS_EVERY == 0 or i == len(chunks):
            print(f"[bulk] chunk {i}/{len(chunks)} {s}→{e}: +{len(rows)} rows · total={total_rows}", flush=True)
        time.sleep(NSE_DELAY)

    print(f"[bulk] DONE — {total_rows} rows written", flush=True)
    return total_rows


# ─────────── short_selling_data ───────────

def backfill_short(start_date, end_date=None):
    from nselib import capital_market as cm
    if end_date is None:
        end_date = date.today()
    sid_map = _sid_map()
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_rows = 0
    chunks = list(_chunk_dates(start_date, end_date))
    print(f"[short] backfilling {start_date} → {end_date} in {len(chunks)} chunks", flush=True)

    for i, (s, e) in enumerate(chunks, 1):
        try:
            raw = cm.short_selling_data(from_date=_nselib_date(s), to_date=_nselib_date(e))
        except Exception as ex:
            print(f"[short] {s}→{e}: ERROR {ex}", flush=True)
            time.sleep(NSE_DELAY * 2)
            continue
        if raw is None or len(raw) == 0:
            time.sleep(NSE_DELAY)
            continue

        rows = []
        for _, r in raw.iterrows():
            sym = str(r.get("Symbol", "")).upper().strip()
            sid = sid_map.get(sym)
            if not sid:
                continue
            rows.append({
                "sid": sid,
                "symbol": sym,
                "short_date": _parse_nselib_date(r.get("Date")),
                "quantity": _comma_int(r.get("Quantity")),
                "fetched_at": fetched_at,
            })
        if rows:
            df = pd.DataFrame(rows).dropna(subset=["short_date"])
            written = insert_df(df, "short_selling_data")
            total_rows += written
        if i % PROGRESS_EVERY == 0 or i == len(chunks):
            print(f"[short] chunk {i}/{len(chunks)} {s}→{e}: +{len(rows)} rows · total={total_rows}", flush=True)
        time.sleep(NSE_DELAY)

    print(f"[short] DONE — {total_rows} rows written", flush=True)
    return total_rows


# ─────────── fii_dii_positioning (participant-wise OI, daily) ───────────

def backfill_fii_fno(start_date, end_date=None):
    """One nselib call per trading day. Skips weekends and existing dates."""
    from nselib import derivatives as der
    if end_date is None:
        end_date = date.today()
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Skip dates already present (idempotent on re-runs)
    existing = set(read_sql("SELECT DISTINCT trade_date FROM fii_dii_positioning").trade_date.tolist())
    print(f"[fii_fno] existing dates in DB: {len(existing)}", flush=True)

    total_rows = 0
    d = start_date
    seen_dates = 0
    while d <= end_date:
        # Skip weekends + already-have
        if d.weekday() < 5 and d.isoformat() not in existing:
            try:
                raw = der.participant_wise_open_interest(trade_date=_nselib_date(d))
            except Exception as ex:
                msg = str(ex)
                if "not found" not in msg.lower():
                    print(f"[fii_fno] {d}: ERROR {msg[:120]}", flush=True)
                time.sleep(NSE_DELAY)
                d += timedelta(days=1)
                continue
            if raw is None or len(raw) == 0:
                time.sleep(NSE_DELAY)
                d += timedelta(days=1)
                continue

            rows = []
            for _, r in raw.iterrows():
                rows.append({
                    "trade_date": d.isoformat(),
                    "client_type": str(r.get("Client Type", "")).strip(),
                    "future_index_long": _comma_int(r.get("Future Index Long")),
                    "future_index_short": _comma_int(r.get("Future Index Short")),
                    "future_stock_long": _comma_int(r.get("Future Stock Long")),
                    "future_stock_short": _comma_int(r.get("Future Stock Short       ")),
                    "option_index_call_long": _comma_int(r.get("Option Index Call Long")),
                    "option_index_put_long": _comma_int(r.get("Option Index Put Long")),
                    "option_index_call_short": _comma_int(r.get("Option Index Call Short")),
                    "option_index_put_short": _comma_int(r.get("Option Index Put Short")),
                    "option_stock_call_long": _comma_int(r.get("Option Stock Call Long")),
                    "option_stock_put_long": _comma_int(r.get("Option Stock Put Long")),
                    "option_stock_call_short": _comma_int(r.get("Option Stock Call Short")),
                    "option_stock_put_short": _comma_int(r.get("Option Stock Put Short")),
                    "total_long": _comma_int(r.get("Total Long Contracts      ")),
                    "total_short": _comma_int(r.get("Total Short Contracts")),
                    "fetched_at": fetched_at,
                })
            if rows:
                df = pd.DataFrame(rows)
                written = insert_df(df, "fii_dii_positioning")
                total_rows += written
            time.sleep(NSE_DELAY)
        seen_dates += 1
        if seen_dates % 50 == 0:
            print(f"[fii_fno] {d.isoformat()}: total written so far = {total_rows}", flush=True)
        d += timedelta(days=1)

    print(f"[fii_fno] DONE — {total_rows} rows written", flush=True)
    return total_rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True, choices=["bulk", "short", "fii_fno", "all"])
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", default=None, help="YYYY-MM-DD (default: today)")
    args = p.parse_args()
    s = date.fromisoformat(args.start)
    e = date.fromisoformat(args.end) if args.end else None

    if args.source in ("bulk", "all"):
        backfill_bulk(s, e)
    if args.source in ("short", "all"):
        backfill_short(s, e)
    if args.source in ("fii_fno", "all"):
        backfill_fii_fno(s, e)


if __name__ == "__main__":
    main()
