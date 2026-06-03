"""
Alpha Signal v2 — Historical Universe Loader (multibagger cohort study, Phase 2b)

Reconstructs the TRUE historical NSE equity universe at chosen anchor dates from
the bhavcopy archive — INCLUDING names that have since delisted. This is the
survivorship-correction foundation: our `stock_prices`/`stocks` are current-
names-only, so the cohort study would be biased without this.

Source: `nselib.capital_market.bhav_copy_with_delivery(trade_date)` — the full
universe + close + delivery% for any trading day (confirmed back to 2023-04;
see memory: survivorship-universe-via-bhavcopy). Free, no paid feed.

Writes `historical_universe`: one row per (snapshot_date, symbol) with close,
delivery%, and the sid mapping (NULL = not in today's `stocks` → likely
delisted/never-tracked). The cohort tool joins anchor↔end snapshots by symbol:
present at both → forward return; present at anchor only → delisted (death).

Usage:
    python -m tools.build_historical_universe                 # default anchors + end
    python -m tools.build_historical_universe --dates 2023-04-03,2026-05-29
"""

import argparse
import io
import time
import zipfile
from datetime import date, timedelta

import pandas as pd
import requests

from db import get_db, read_sql

DELAY_SEC = 2.0
_MMM = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_NSE_SESSION = None
EQUITY_SERIES = {"EQ", "BE"}     # mainboard equity (SM = SME platform, excluded)
TRADING_DAY_LOOKBACK = 6         # step back up to N days to find a trading day

# Default: a few 2-4yr-forward anchors + a recent end reference.
DEFAULT_DATES = [
    "2022-08-01", "2023-04-03", "2023-10-03", "2024-04-01", "2026-05-29",
]


def _sid_map():
    df = read_sql("SELECT sid, ticker FROM stocks")
    return df.set_index("ticker")["sid"].to_dict()


def _nse_session():
    global _NSE_SESSION
    if _NSE_SESSION is None:
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AlphaSignal/2.0"})
        try:
            s.get("https://www.nseindia.com", timeout=15)
        except Exception:
            pass
        _NSE_SESSION = s
    return _NSE_SESSION


def _old_bhav(d):
    """Pre-2020 NSE archive bhavcopy (old format). Returns normalized df or None."""
    mmm = _MMM[d.month - 1]
    url = (f"https://archives.nseindia.com/content/historical/EQUITIES/"
           f"{d.year}/{mmm}/cm{d.day:02d}{mmm}{d.year}bhav.csv.zip")
    try:
        r = _nse_session().get(url, timeout=25)
        if r.status_code != 200 or len(r.content) < 200:
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        df = pd.read_csv(z.open(z.namelist()[0]))
        df.columns = [c.strip() for c in df.columns]
        df = df.rename(columns={"CLOSE": "CLOSE_PRICE"})  # old fmt: CLOSE not CLOSE_PRICE
        df["DELIV_PER"] = float("nan")                    # no delivery in old format
        return df
    except Exception:
        return None


def _fetch_bhavcopy(requested):
    """Nearest trading day ≤ requested. New-format (with delivery, 2020+) first,
    falls back to the pre-2020 archive (old format)."""
    from nselib import capital_market as cm
    d = date.fromisoformat(requested)
    for _ in range(TRADING_DAY_LOOKBACK + 1):
        try:
            df = cm.bhav_copy_with_delivery(trade_date=d.strftime("%d-%m-%Y"))
            if df is not None and len(df):
                return d.isoformat(), df
        except Exception:
            pass
        df = _old_bhav(d)          # pre-2020 archive
        if df is not None and len(df):
            return d.isoformat(), df
        d -= timedelta(days=1)
        time.sleep(DELAY_SEC * 0.5)
    return None, None


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return None


def build(dates):
    sid_map = _sid_map()
    total = 0
    for requested in dates:
        actual, df = _fetch_bhavcopy(requested)
        if df is None:
            print(f"  {requested}: ❌ no bhavcopy within {TRADING_DAY_LOOKBACK} days")
            time.sleep(DELAY_SEC)
            continue
        df.columns = [c.strip() for c in df.columns]
        df["SERIES"] = df["SERIES"].astype(str).str.strip()
        eq = df[df["SERIES"].isin(EQUITY_SERIES)]

        rows = []
        for _, r in eq.iterrows():
            sym = str(r["SYMBOL"]).strip()
            rows.append({
                "snapshot_date": actual,
                "requested_date": requested,
                "symbol": sym,
                "sid": sid_map.get(sym),
                "series": str(r["SERIES"]).strip(),
                "close": _num(r.get("CLOSE_PRICE")),
                "delivery_pct": _num(r.get("DELIV_PER")),
            })
        out = pd.DataFrame(rows)
        cols = ", ".join(out.columns)
        ph = ", ".join(["?"] * len(out.columns))
        with get_db() as conn:
            cur = conn.executemany(
                f"INSERT OR REPLACE INTO historical_universe ({cols}) VALUES ({ph})",
                out.values.tolist(),
            )
            n = cur.rowcount
        mapped = out["sid"].notna().sum()
        print(f"  {requested} → bhavcopy {actual}: {len(out)} EQ/BE symbols "
              f"({mapped} mapped to sid, {len(out) - mapped} unmapped/delisted) → {n} rows")
        total += n
        time.sleep(DELAY_SEC)
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dates", default=None,
                        help="Comma-separated ISO dates (anchors + end). Default: built-in set.")
    args = parser.parse_args()
    dates = args.dates.split(",") if args.dates else DEFAULT_DATES
    print(f"Historical universe — {len(dates)} dates: {dates}")
    n = build(dates)
    print(f"\nDone. {n} rows into historical_universe.")
    # Quick survivorship read
    summary = read_sql(
        "SELECT snapshot_date, COUNT(*) symbols, "
        "SUM(CASE WHEN sid IS NULL THEN 1 ELSE 0 END) unmapped "
        "FROM historical_universe GROUP BY snapshot_date ORDER BY snapshot_date"
    )
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
