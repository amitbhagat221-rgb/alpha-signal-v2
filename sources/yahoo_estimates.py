"""
Alpha Signal v2 — Yahoo EPS estimates → analyst_estimates (plan 0018, research 0005 A4).

Two reads per stock, both through the host door (pace("yahoo"), one paced block each):

  history   get_earnings_dates: per earnings report, the EPS estimate, the reported
            EPS and the surprise — ~2007+ for large caps, ~2015+ for covered small
            caps. The missing SUE numerator of PEAD (memory pead_needs_announce_dates).
            available_at = the report time. Whether Yahoo froze each estimate at the
            report (not back-revised) is UNVERIFIED → label 'pit_unverified' until a
            check against our own forward snapshots clears it.
  trend     earningsTrend (one quoteSummary module): EPS now and 7/30/60/90 days
            ago, revisions up/down over 7/30 days, low/high/avg, analyst count, per
            Yahoo period (0q, +1q, 0y, +1y). available_at = fetch time — honest PIT by
            construction; weekly snapshots build our own revision history.

Writes are versioned (plan 0017 `estimates` rule): a changed value is a new row, an
unchanged one only moves last_seen_at.

Usage:
    python -m sources.yahoo_estimates --history --tiers LARGE,MID,SMALL   # backfill
    python -m sources.yahoo_estimates --trend --covered                    # weekly
    python -m sources.yahoo_estimates --history --reported-days 21        # weekly: fresh reports only
    python -m sources.yahoo_estimates --history --sid RELI --trend        # smoke
    --budget-min N stops cleanly after N minutes (resumable: stocks already fetched today are skipped)
"""

import argparse
import math
from datetime import datetime, timezone

import pandas as pd

import runlog
from db import get_db, read_sql
from sources import _http

SOURCE_HIST = "yahoo_calendar"
SOURCE_TREND = "yahoo_trend"
TREND_COLS = {  # yfinance frame → metric
    "eps_trend": {"current": "eps_trend_now", "7daysAgo": "eps_trend_7d", "30daysAgo": "eps_trend_30d",
                  "60daysAgo": "eps_trend_60d", "90daysAgo": "eps_trend_90d"},
    "eps_revisions": {"upLast7days": "eps_rev_up_7d", "upLast30days": "eps_rev_up_30d",
                      "downLast7Days": "eps_rev_down_7d", "downLast30days": "eps_rev_down_30d"},
    "earnings_estimate": {"avg": "eps_est_avg", "low": "eps_est_low", "high": "eps_est_high",
                          "numberOfAnalysts": "eps_est_n_analysts", "yearAgoEps": "eps_year_ago"},
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


# ─────────────────────────────── fetch ───────────────────────────────

def history_rows(sid, ed, now):
    """get_earnings_dates frame → rows (metric, target_period=report date)."""
    rows = []
    if ed is None or len(ed) == 0:
        return rows
    for ts, r in ed.iterrows():
        when = pd.Timestamp(ts)
        when_utc = (when.tz_convert("UTC") if when.tzinfo else when.tz_localize("UTC")).isoformat()
        future = when_utc > now
        period = when.date().isoformat()
        for col, metric in (("EPS Estimate", "eps_estimate"), ("Reported EPS", "eps_actual"),
                            ("Surprise(%)", "eps_surprise_pct")):
            v = _num(r.get(col))
            if v is None:
                continue
            # an upcoming report's estimate is known NOW; a past one is dated at the report
            avail = now if future else when_utc
            label = "upcoming" if future else ("pit_unverified" if metric == "eps_estimate" else "reported")
            rows.append((sid, metric, period, SOURCE_HIST, v, label, avail))
    return rows


def trend_rows(sid, frames, now):
    rows = []
    for attr, cols in TREND_COLS.items():
        df = frames.get(attr)
        if df is None or len(df) == 0:
            continue
        for period, r in df.iterrows():
            for col, metric in cols.items():
                v = _num(r.get(col))
                if v is not None:
                    rows.append((sid, metric, f"yf:{period}", SOURCE_TREND, v, None, now))
    return rows


def fetch_one(sid, ticker, history=True, trend=True):
    import yfinance as yf
    t = yf.Ticker(f"{ticker}.NS")
    now, rows = _now(), []
    if history:
        with _http.pace("yahoo"):
            ed = t.get_earnings_dates(limit=100)
        rows += history_rows(sid, ed, now)
    if trend:
        with _http.pace("yahoo"):                  # one quoteSummary response serves all three views
            frames = {attr: getattr(t, attr) for attr in TREND_COLS}
        rows += trend_rows(sid, frames, now)
    return rows


# ─────────────────────────────── versioned write ───────────────────────────────

def write_versioned(rows):
    """Plan 0017 versioned rule: unchanged value → bump last_seen_at on the latest
    version; changed / new → insert a new version. Returns new versions written."""
    if not rows:
        return 0
    df = pd.DataFrame(rows, columns=["sid", "metric", "target_period", "source", "value", "label", "available_at"])
    # microseconds: fetched_at is part of the key — a changed value written in the same
    # second as the previous version must not collide and be silently ignored
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    sids = sorted(set(df["sid"]))
    ph = ",".join("?" * len(sids))
    latest = read_sql(f"""SELECT sid, metric, target_period, source, value, fetched_at FROM analyst_estimates a
                          WHERE sid IN ({ph}) AND fetched_at = (SELECT MAX(fetched_at) FROM analyst_estimates b
                            WHERE b.sid = a.sid AND b.metric = a.metric AND b.target_period = a.target_period
                              AND b.source = a.source)""", params=sids)
    last = {(r.sid, r.metric, r.target_period, r.source): (r.value, r.fetched_at) for r in latest.itertuples()}
    new, seen = [], []
    for r in df.itertuples(index=False):
        k = (r.sid, r.metric, r.target_period, r.source)
        prev = last.get(k)
        if prev is not None and prev[0] is not None and r.value is not None and abs(prev[0] - r.value) < 1e-9:
            seen.append((now, *k, prev[1]))
        else:
            new.append((r.sid, r.metric, r.target_period, r.source, r.value, r.label, r.available_at, now, now))
    with get_db() as conn:
        if new:
            conn.executemany("INSERT OR IGNORE INTO analyst_estimates (sid, metric, target_period, source, value, "
                             "label, available_at, fetched_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?)", new)
        if seen:
            conn.executemany("UPDATE analyst_estimates SET last_seen_at = ? WHERE sid = ? AND metric = ? "
                             "AND target_period = ? AND source = ? AND fetched_at = ?", seen)
    runlog.count_write("analyst_estimates", len(new))
    return len(new)


# ─────────────────────────────── targets ───────────────────────────────

def targets(tiers=None, sid=None, covered=False, reported_days=None, skip_today=None):
    where, params = ["s.ticker IS NOT NULL"], []
    if sid:
        where.append("s.sid = ?")
        params.append(sid)
    elif tiers:
        where.append(f"s.cap_tier IN ({','.join('?' * len(tiers))})")
        params += list(tiers)
    if covered:
        where.append("s.sid IN (SELECT sid FROM analyst_consensus WHERE total_analysts >= 1)")
    if reported_days:
        where.append("s.sid IN (SELECT sid FROM earnings_calendar WHERE date BETWEEN date('now', ?) AND date('now'))")
        params.append(f"-{int(reported_days)} days")
    if skip_today:                              # resumable backfill: skip stocks fetched today
        where.append("s.sid NOT IN (SELECT sid FROM analyst_estimates WHERE source = ? AND last_seen_at >= date('now'))")
        params.append(skip_today)
    return read_sql(f"SELECT s.sid, s.ticker FROM stocks s WHERE {' AND '.join(where)} "
                    f"ORDER BY CASE s.cap_tier WHEN 'LARGE' THEN 0 WHEN 'MID' THEN 1 ELSE 2 END, s.ticker", params=params)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Yahoo EPS estimates → analyst_estimates (plan 0018)")
    ap.add_argument("--history", action="store_true", help="per-report estimate vs actual")
    ap.add_argument("--trend", action="store_true", help="EPS trend / revisions snapshot")
    ap.add_argument("--tiers", default="LARGE,MID,SMALL")
    ap.add_argument("--sid")
    ap.add_argument("--covered", action="store_true", help="only stocks with analyst coverage")
    ap.add_argument("--reported-days", type=int, help="only stocks with results in the last N days")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--budget-min", type=float, help="stop cleanly after N minutes (resumable)")
    a = ap.parse_args(argv)
    if not (a.history or a.trend):
        ap.error("choose --history and/or --trend")
    skip = None if a.sid else (SOURCE_HIST if a.history and not a.trend else SOURCE_TREND if a.trend and not a.history else None)
    tg = targets(a.tiers.split(","), a.sid, a.covered, a.reported_days, skip_today=skip)
    if a.limit:
        tg = tg.head(a.limit)
    out_of_time = _http.time_budget("yahoo", a.budget_min) if a.budget_min else (lambda: False)
    items = []
    for row in tg.itertuples(index=False):
        items.append((row.sid, row.ticker))
    print(f"Yahoo estimates: {len(items)} stocks (history={a.history}, trend={a.trend})", flush=True)
    if not items:
        return 0

    def fetch(item):
        if out_of_time():
            return None
        return fetch_one(item[0], item[1], a.history, a.trend)

    n_ok, n_err, n_written = _http.run_harvester(items, fetch, write_versioned, flush_every=50,
                                                 label="yahoo estimates")
    if out_of_time():
        runlog.note("yahoo estimates stopped at its time budget — rerun to resume", "WARN")
        print("  stopped at the time budget — rerun the same command to resume", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
