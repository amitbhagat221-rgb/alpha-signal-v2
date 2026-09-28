"""
Alpha Signal v2 — Gate 3: cross-source reconciliation (plan 0018 §4).

A feed can pass every transport, shape and range check and still be wrong in
meaning — the forecast_history.price "PT" that was really the year-ahead close
(ADR 0045). The only defence is to compare it with an independent source:

  prices        NSE bhavcopy close (stock_prices, source='bhavcopy') vs Yahoo's
                UNADJUSTED close on the same date, for 20 random LARGE/MID stocks.
                Agree = within 0.5 %. PASS ≥ 90 % agree · WARN ≥ 70 % · else FAIL.
  fundamentals  Tickertape quarterly revenue (quarterly_income) vs Screener
                'Sales' (fundamentals_screener) on the latest quarter both hold,
                for up to 200 stocks. The two define revenue slightly differently
                (RELIANCE Jun-26: 3,16,018 vs 3,09,468 Cr, 2.1 %), so agree = within
                5 % — built to catch unit / period / company errors, not accounting
                nuance. PASS ≥ 80 % · WARN ≥ 60 % · else FAIL. DB-only.

One `feed_checks` row per check (check_kind 'reconcile', attributed to the feed
under test); checks/feeds.py turns a FAIL on a T1 feed into a CRITICAL.
Runs in `run.sh canary` after the canaries (same harvest lock).

    python -m tools.reconcile                  # both
    python -m tools.reconcile --only prices    # prices | fundamentals
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import runlog  # noqa: E402
from db import insert_df, read_sql  # noqa: E402

PRICE_TOL, PRICE_PASS, PRICE_WARN, PRICE_SAMPLE = 0.005, 0.90, 0.70, 20
FUND_TOL, FUND_PASS, FUND_WARN, FUND_SAMPLE = 0.05, 0.80, 0.60, 200


def verdict_of(share, n, pass_at, warn_at, min_n=5):
    if n < min_n:
        return "WARN"                          # too few comparable items to vouch for the feed
    return "PASS" if share >= pass_at else ("WARN" if share >= warn_at else "FAIL")


def agreement(pairs, tol):
    """pairs: [(key, ours, theirs)] → (n, share agreeing, 5 worst (key, ours, theirs, rel_diff))."""
    diffs = [(k, o, t, abs(o / t - 1)) for k, o, t in pairs if o and t and t > 0]
    if not diffs:
        return 0, 0.0, []
    ok = sum(d[3] <= tol for d in diffs)
    return len(diffs), ok / len(diffs), sorted(diffs, key=lambda d: -d[3])[:5]


def reconcile_prices(sample=PRICE_SAMPLE, seed=None):
    import yfinance as yf
    from sources import _http
    d = read_sql("SELECT MAX(date) AS d FROM stock_prices WHERE source = 'bhavcopy'").iloc[0]["d"]
    ours = read_sql("""SELECT p.sid, s.ticker, p.close FROM stock_prices p JOIN stocks s USING (sid)
                       WHERE p.date = ? AND p.source = 'bhavcopy' AND s.cap_tier IN ('LARGE', 'MID')
                         AND p.close > 0""", params=[d])
    pick = ours.sample(min(sample, len(ours)), random_state=seed if seed is not None else int(date.today().strftime("%Y%m%d")))
    day = pd.Timestamp(d)
    pairs = []
    for r in pick.itertuples(index=False):
        with _http.pace("yahoo"):
            h = yf.Ticker(f"{r.ticker}.NS").history(start=(day - timedelta(days=5)).date().isoformat(),
                                                   end=(day + timedelta(days=1)).date().isoformat(), auto_adjust=False)
        if h is None or h.empty:
            continue
        h.index = pd.to_datetime(h.index).tz_localize(None).normalize()
        if day in h.index:
            pairs.append((r.sid, float(r.close), float(h.loc[day, "Close"])))
    n, share, worst = agreement(pairs, PRICE_TOL)
    return {"feed": "nse_bhavcopy", "status": verdict_of(share, n, PRICE_PASS, PRICE_WARN), "n": n,
            "share": share, "detail": {"check": "prices", "date": d, "against": "yahoo unadjusted close",
                                        "tolerance": PRICE_TOL, "sampled": len(pick), "compared": n,
                                        "agree_share": round(share, 3),
                                        "worst": [(k, o, t, round(x, 4)) for k, o, t, x in worst]}}


def reconcile_fundamentals(sample=FUND_SAMPLE):
    tt = read_sql("SELECT sid, end_date AS period_end, revenue FROM quarterly_income WHERE revenue > 0")
    sc = read_sql("""SELECT sid, period_end, value FROM fundamentals_screener
                     WHERE line_item = 'Sales' AND period_type = 'quarterly' AND value > 0""")
    m = tt.merge(sc, on=["sid", "period_end"])
    if m.empty:
        latest = m
    else:
        latest = m.sort_values("period_end").groupby("sid").tail(1)
        latest = latest.sample(min(sample, len(latest)), random_state=int(date.today().strftime("%Y%m%d")))
    pairs = [(r.sid, float(r.revenue), float(r.value)) for r in latest.itertuples(index=False)]
    n, share, worst = agreement(pairs, FUND_TOL)
    return {"feed": "tickertape_fundamentals", "status": verdict_of(share, n, FUND_PASS, FUND_WARN), "n": n,
            "share": share, "detail": {"check": "fundamentals", "against": "screener quarterly Sales",
                                        "tolerance": FUND_TOL, "compared": n, "agree_share": round(share, 3),
                                        "worst": [(k, o, t, round(x, 4)) for k, o, t, x in worst]}}


def record(results, dry_run=False):
    now = datetime.now().isoformat(timespec="seconds")
    rows = [{"run_date": date.today().isoformat(), "feed": r["feed"], "check_kind": "reconcile",
             "route": r["detail"]["check"], "status": r["status"], "symptom": None if r["status"] == "PASS" else "F",
             "n_rows": r["n"], "detail": json.dumps(r["detail"], default=str), "checked_at": now} for r in results]
    if rows and not dry_run:
        insert_df(pd.DataFrame(rows), "feed_checks")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Gate 3 cross-source reconciliation (plan 0018)")
    ap.add_argument("--only", choices=["prices", "fundamentals"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    runlog.start("reconcile", module="tools.reconcile", adopt_env=True)
    results = []
    for name, fn in (("prices", reconcile_prices), ("fundamentals", reconcile_fundamentals)):
        if a.only and a.only != name:
            continue
        try:
            r = fn()
        except Exception as e:                        # noqa: BLE001 — recorded, never silent
            runlog.exception(e)
            r = {"feed": "nse_bhavcopy" if name == "prices" else "tickertape_fundamentals", "status": "WARN",
                 "n": 0, "share": 0.0, "detail": {"check": name, "error": f"{type(e).__name__}: {e}"}}
        results.append(r)
        print(f"  {r['status']:4} {name:12} {r['feed']:24} compared={r['n']:<4} agree={r['share']:.0%}  "
              f"worst={r['detail'].get('worst', [])[:2]}", flush=True)
        if r["status"] != "PASS":
            runlog.note(f"reconcile {name}: {r['status']} ({r['share']:.0%} agree of {r['n']})",
                        "ERROR" if r["status"] == "FAIL" else "WARN", **r["detail"])
    record(results, a.dry_run)
    runlog.end("SUCCESS", rows=len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
