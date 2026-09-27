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
from datetime import datetime
from typing import Optional

import pandas as pd
from bs4 import BeautifulSoup


from db import read_sql, upsert_df
from sources._http import host, polite_get, run_harvester

# Gap (2 s) and browser headers come from the host door: hosts.HOSTS["tickertape"].


def _fetch_next_data(slug):
    """GET tickertape.in/{slug} and return parsed __NEXT_DATA__ JSON.

    None on 404 (delisted / slug gone). Raises on transport/HTTP failure (after
    polite_get's retries) and when the page carries no __NEXT_DATA__ blob —
    run_harvester counts both as errors."""
    r = polite_get(f"https://tickertape.in/{slug}")
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "html5lib")
    script = soup.find("script", attrs={"id": "__NEXT_DATA__"})
    if not script:
        raise ValueError("page has no __NEXT_DATA__ script")
    return json.loads(script.contents[0].text)


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

    Both are unusable as PT history — (1) turned out to be the realized
    year-ahead close (ADR 0045) — so only the eps/revenue series are kept.
    """
    rows = []
    try:
        fh = data.get("props", {}).get("pageProps", {}).get("forecastsHistory", {}) or {}
        # "price" is NOT ingested: those rows are the realized year-ahead close,
        # not a PT (ADR 0045) — nothing may read them, so stop rewriting them.
        for metric in ("eps", "revenue"):
            for entry in fh.get(metric, []):
                raw_date = entry.get("date", "")
                d = raw_date[:10] if raw_date else None
                if not d:
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
        gap = host("tickertape")[1]["gap"]
        print(f"  Estimated time: ~{total * gap / 60:.0f} min ({gap}s × {total} pages)")
        return 0

    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    no_data = 0

    def fetch(item):
        nonlocal no_data
        sid, slug = item
        data = _fetch_next_data(slug)
        if data is None:
            return []
        arow = _extract_analyst_row(sid, data, fetched_at)
        if not arow["has_analyst_data"]:
            no_data += 1
        return ([("analyst_consensus", arow)]
                + [("forecast_history", f) for f in _extract_forecast_rows(sid, data, fetched_at)])

    def write(tagged):
        # One page feeds two tables; flush both, count the primary one.
        for table in ("analyst_consensus", "forecast_history"):
            rows = [r for t, r in tagged if t == table]
            if rows:
                upsert_df(pd.DataFrame(rows), table)
        return sum(1 for t, _ in tagged if t == "analyst_consensus")

    # RAISES if no page parsed at all (Tickertape block / page-shape change) —
    # the old loop reported SUCCESS with 0 rows in that case.
    _, n_err, saved_analyst = run_harvester(stocks.itertuples(index=False, name=None),
                                            fetch, write, label="tickertape analyst")
    print(f"Done: {saved_analyst} analyst rows. No coverage: {no_data}. Errors: {n_err}.")
    # Return analyst-row count for pipeline_log (tracks the primary table).
    return saved_analyst


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="Limit to first N stocks (smoke test)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(limit=args.limit, dry_run=args.dry_run)
