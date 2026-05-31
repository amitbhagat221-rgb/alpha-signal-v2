"""
Alpha Signal v2 — Tickertape Analyst + Forecast (HTML scrape)

Ports v1 scripts 25_analyst_harvester.py + 31_forecast_history_harvester.py
into a single v2 producer. Both v1 fetchers hit the same Tickertape company
page and parse the embedded __NEXT_DATA__ JSON; we do it once per stock and
write to *both* tables. Saves ~80 min vs running them separately.

Writes:
    analyst_consensus  — PK (sid). One row per stock with latest snapshot.
    forecast_history   — PK (sid, metric, date). Long format. Price/EPS/Revenue
                         estimates over time, drives the pt_revision/eps_revision
                         signals.

Reads:
    stocks.slug — the Tickertape slug, e.g. "stocks/reliance-industries-RELI".

Usage:
    python -m sources.tickertape_analyst              # full refresh, all sids
    python -m sources.tickertape_analyst --limit 3    # smoke test
    python -m sources.tickertape_analyst --dry-run
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import API
from db import read_sql, upsert_df

DELAY = API["tickertape_delay"]  # 2 seconds
TIMEOUT = 15
MAX_RETRIES = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def _fetch_next_data(slug):
    """GET tickertape.in/{slug} and return parsed __NEXT_DATA__ JSON, or None."""
    url = f"https://tickertape.in/{slug}"
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 404:
                return None
            if r.status_code != 200:
                if attempt < MAX_RETRIES:
                    time.sleep(2)
                    continue
                return None
            soup = BeautifulSoup(r.text, "html5lib")
            script = soup.find("script", attrs={"id": "__NEXT_DATA__"})
            if not script:
                return None
            return json.loads(script.contents[0].text)
        except (requests.exceptions.Timeout, requests.exceptions.RequestException):
            if attempt < MAX_RETRIES:
                time.sleep(2)
                continue
            return None
    return None


def _safe_growth_pct(hist: list) -> Optional[float]:
    """Recompute forward growth % from a forecastsHistory.{eps,revenue} array.

    Returns NULL when the base is too small or non-positive — Tickertape's own
    .change field divides into those bases and produces absurd ratios (DWNH
    eps_growth_pct = 306,231% surfaced by Plan 0007 Gate 2 backfill on
    2026-05-31). Caps the magnitude at the plausibility-gate hard range
    (-200..+500 for EPS, -90..+500 for revenue) so we never write a known-bad
    value even if Tickertape's `.value` field itself is malformed.
    """
    if not hist or len(hist) < 2:
        return None
    fwd = hist[-1].get("value")
    base = hist[-2].get("value")
    try:
        fwd = float(fwd) if fwd is not None else None
        base = float(base) if base is not None else None
    except (TypeError, ValueError):
        return None
    if fwd is None or base is None:
        return None
    if base <= 0.5:                       # turnaround / sign-flip — undefined
        return None
    growth = (fwd - base) / base * 100
    if growth < -200 or growth > 500:     # outside gate hard range
        return None
    return round(growth, 2)


def _extract_analyst_row(sid, data, fetched_at):
    """Flatten __NEXT_DATA__ into a single analyst_consensus row.

    Owns these fields in analyst_consensus:
      buy_pct, forward_eps, eps_growth_pct, forward_revenue, revenue_growth_pct
    Co-writes total_analysts (yfinance overwrites daily).
    Does NOT touch price_target — yfinance is the sole writer (see HANDOFF
    2026-05-22 — Tickertape's forecastsHistory.price[-1] was lastPrice, not
    a real PT, and contaminated the field for 20 days).
    """
    rec = {
        "sid": sid,
        "total_analysts": None,
        "buy_pct": None,
        "forward_eps": None,
        "eps_growth_pct": None,
        "forward_revenue": None,
        "revenue_growth_pct": None,
        "has_analyst_data": 0,
        "fetched_at": fetched_at,
    }
    try:
        pp = data.get("props", {}).get("pageProps", {})
        forecast = pp.get("securitySummary", {}).get("forecast", {}) or {}
        rec["total_analysts"] = forecast.get("totalReco")
        rec["buy_pct"] = forecast.get("percBuyReco")

        fh = pp.get("forecastsHistory", {}) or {}

        # NOTE: do NOT pull price_target from forecastsHistory.price[-1].
        # That entry is the "today" value (lastPrice masquerading as PT —
        # see HANDOFF 2026-05-22). yfinance is the sole writer of
        # analyst_consensus.price_target; Tickertape leaves it alone.
        # Year-end snapshots still flow to forecast_history (long format) via
        # _extract_forecast_rows below; backtest pulls from there.

        # NOTE: do NOT use Tickertape's `.change` field. Trust Backfill
        # 2026-05-31 surfaced 35 hard-fail rows (DWNH 306,231%, JSTL 696%,
        # TTCH -907%, PPL -457%, ...). Tickertape divides forward EPS by the
        # most-recent point in eps_hist regardless of whether that point is a
        # quarterly snapshot or a near-zero turnaround base. We recompute from
        # values, requiring a positive base ≥ ₹0.5 — anything below is a
        # turnaround case where percentage growth is mathematically undefined.
        eps_hist = fh.get("eps", [])
        if eps_hist:
            rec["forward_eps"] = eps_hist[-1].get("value")
            rec["eps_growth_pct"] = _safe_growth_pct(eps_hist)

        rev_hist = fh.get("revenue", [])
        if rev_hist:
            rec["forward_revenue"] = rev_hist[-1].get("value")
            rec["revenue_growth_pct"] = _safe_growth_pct(rev_hist)

        if rec["total_analysts"] or rec["forward_eps"]:
            rec["has_analyst_data"] = 1
    except Exception:
        pass
    return rec


def _extract_forecast_rows(sid, data, fetched_at):
    """Flatten __NEXT_DATA__ into long-format forecast_history rows.

    Tickertape's forecastsHistory.price array contains TWO kinds of entries:
      1. Historical year-end snapshots (Dec 27-28 of each year) — real
         analyst PT consensus at that point. Sparse: ~1 per stock per year.
      2. A "today" entry — date = page-load date, value = current lastPrice
         (NOT a real PT; it's just the intraday price). Fetched daily, this
         creates phantom daily PT rows that match close prices and break
         every downstream signal. See HANDOFF 2026-05-22.

    We keep (1) and drop (2). A "today" entry is anything dated within the
    last 90 days — real broker PT revisions get published quarterly at best,
    so a fresh entry from this week is the lastPrice contaminant, not new
    consensus.
    """
    from datetime import date as _date, timedelta as _timedelta
    cutoff = (_date.today() - _timedelta(days=90)).isoformat()
    rows = []
    try:
        fh = data.get("props", {}).get("pageProps", {}).get("forecastsHistory", {}) or {}
        for metric in ("price", "eps", "revenue"):
            for entry in fh.get(metric, []):
                raw_date = entry.get("date", "")
                d = raw_date[:10] if raw_date else None
                if not d:
                    continue
                # Drop the contaminating "today" entry for the price metric only.
                # eps/revenue are quarterly fundamentals — those can be recent.
                if metric == "price" and d >= cutoff:
                    continue
                rows.append({
                    "sid": sid,
                    "metric": metric,
                    "date": d,
                    "value": entry.get("value"),
                    "change": entry.get("change"),
                    "fetched_at": fetched_at,
                })
    except Exception:
        pass
    return rows


def compute(limit=None, dry_run=False):
    """Pipeline entry point — fetch analyst + forecast for all sids with a slug."""
    stocks = read_sql(
        "SELECT sid, slug FROM stocks WHERE slug IS NOT NULL AND slug LIKE 'stocks/%' ORDER BY sid"
    )
    if limit:
        stocks = stocks.head(limit)

    total = len(stocks)
    print(f"Tickertape Analyst+Forecast (HTML scrape): {total} stocks")

    if dry_run:
        print(f"  Estimated time: ~{total * DELAY / 60:.0f} min ({DELAY}s × {total} pages)")
        return 0

    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    analyst_rows = []
    forecast_rows = []
    no_data = 0
    errors = 0
    saved_analyst = 0
    saved_forecast = 0

    for i, (sid, slug) in enumerate(stocks.itertuples(index=False), 1):
        data = _fetch_next_data(slug)
        if data is None:
            errors += 1
        else:
            arow = _extract_analyst_row(sid, data, fetched_at)
            analyst_rows.append(arow)
            if not arow["has_analyst_data"]:
                no_data += 1
            forecast_rows.extend(_extract_forecast_rows(sid, data, fetched_at))

        if i % 200 == 0:
            # Mid-run checkpoint — flush what we have so a crash doesn't lose progress.
            if analyst_rows:
                upsert_df(pd.DataFrame(analyst_rows), "analyst_consensus")
                saved_analyst += len(analyst_rows)
                analyst_rows = []
            if forecast_rows:
                upsert_df(pd.DataFrame(forecast_rows), "forecast_history")
                saved_forecast += len(forecast_rows)
                forecast_rows = []
            print(f"  [{i}/{total}] {saved_analyst} analyst rows, {saved_forecast} forecast rows saved")

        time.sleep(DELAY)

    # Final flush.
    if analyst_rows:
        upsert_df(pd.DataFrame(analyst_rows), "analyst_consensus")
        saved_analyst += len(analyst_rows)
    if forecast_rows:
        upsert_df(pd.DataFrame(forecast_rows), "forecast_history")
        saved_forecast += len(forecast_rows)

    print(f"Done: {saved_analyst} analyst rows, {saved_forecast} forecast rows. "
          f"No coverage: {no_data}. Errors: {errors}.")
    # Return analyst-row count for pipeline_log (tracks the primary table).
    return saved_analyst


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Limit to first N stocks (smoke test)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(limit=args.limit, dry_run=args.dry_run)
