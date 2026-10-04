"""
Alpha Signal v2 — Gate 3: cross-source reconciliation (plan 0018 §4).

A feed can pass every transport, shape and range check and still be wrong in
meaning — the forecast_history.price "PT" that was really the year-ahead close
(ADR 0045). The only defence is to compare it with an independent source:

  prices        NSE bhavcopy close (stock_prices, source='bhavcopy') vs Yahoo's
                UNADJUSTED close on the same date, for 20 random LARGE/MID stocks.
                Agree = within 0.5 %. PASS ≥ 90 % agree · WARN ≥ 70 % · else FAIL.
  fundamentals  every Tickertape statement column a factor reads (FUND_FIELDS: revenue,
                operating expenses, profit, cash flows, dividends, equity, share count)
                vs the Screener line item that must hold the same quantity
                (fundamentals_screener), on the latest period both hold, for up to
                200 stocks per field; the feed's status is its weakest field's. The two define revenue slightly differently
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


# Tickertape column ↔ the Screener line item that must hold the same quantity:
# (table, column, Screener period_type, line item or items summed, scale). Every
# statement column a factor reads is here, because a column can be full, fresh and
# in range and still hold the wrong thing — `interest` was operating expenses and
# `depreciation` was dividends paid for months while only revenue was compared.
FUND_FIELDS = [
    ("quarterly_income", "revenue", "quarterly", ("Sales",), 1.0),
    ("quarterly_income", "operating_expenses", "quarterly", ("Expenses",), 1.0),
    ("quarterly_income", "pbt", "quarterly", ("Profit before tax",), 1.0),
    ("quarterly_income", "net_income", "quarterly", ("Net profit",), 1.0),
    ("annual_cash_flow", "operating_cash_flow", "annual", ("Cash from Operating Activity",), 1.0),
    ("annual_cash_flow", "investing_cash_flow", "annual", ("Cash from Investing Activity",), 1.0),
    ("annual_cash_flow", "financing_cash_flow", "annual", ("Cash from Financing Activity",), 1.0),
    # not dividends_paid: Tickertape holds cash paid in the year, Screener the dividend declared
    # for it (39% agree within 5%) — a timing difference, not a mapping; no factor reads the column
    ("annual_balance_sheet", "total_equity", "annual", ("Equity Share Capital", "Reserves", "Non controlling int"), 1.0),
    ("annual_balance_sheet", "shares_outstanding", "annual", ("No. of Equity Shares",), 1e-7),
]


def reconcile_field(table, column, period_type, items, scale, sample=FUND_SAMPLE):
    """One Tickertape column against its Screener line item(s) on the latest period both
    hold, for up to `sample` stocks → (n, share agreeing within FUND_TOL, worst)."""
    from signals._fundamentals import prefer_consolidated
    basis = ", reporting" if table == "quarterly_income" else ""
    tt = prefer_consolidated(read_sql(f"SELECT sid, end_date AS period_end, {column} AS ours{basis} FROM {table} "
                                      f"WHERE {column} IS NOT NULL AND {column} != 0"))
    sc = read_sql(f"""SELECT sid, period_end, SUM(value) AS theirs, COUNT(*) AS k FROM fundamentals_screener
                      WHERE period_type = ? AND line_item IN ({','.join('?' * len(items))}) AND value IS NOT NULL
                      GROUP BY sid, period_end""", params=[period_type, *items])
    sc = sc[sc["k"] >= min(2, len(items))]            # a sum needs its main parts (minority interest is optional)
    m = tt.merge(sc, on=["sid", "period_end"])
    if not m.empty:
        m = m.sort_values("period_end").groupby("sid").tail(1)
        m = m.sample(min(sample, len(m)), random_state=int(date.today().strftime("%Y%m%d")))
    return agreement([(r.sid, abs(float(r.ours)), abs(float(r.theirs)) * scale) for r in m.itertuples(index=False)], FUND_TOL)


def reconcile_fundamentals(sample=FUND_SAMPLE):
    """Every FUND_FIELDS column against Screener. The feed's status is its WORST field's."""
    fields, worst_field = {}, None
    for table, column, period_type, items, scale in FUND_FIELDS:
        n, share, worst = reconcile_field(table, column, period_type, items, scale, sample)
        status = verdict_of(share, n, FUND_PASS, FUND_WARN)
        fields[f"{table}.{column}"] = {"status": status, "compared": n, "agree_share": round(share, 3),
                                       "against": "screener " + " + ".join(items),
                                       "worst": [(k, o, t, round(x, 4)) for k, o, t, x in worst]}
        rank = ("PASS", "WARN", "FAIL").index(status)
        if worst_field is None or (rank, -share) > worst_field[0]:
            worst_field = ((rank, -share), f"{table}.{column}")
    w = fields[worst_field[1]]
    return {"feed": "tickertape_fundamentals", "status": w["status"], "n": w["compared"], "share": w["agree_share"],
            "detail": {"check": "fundamentals", "against": f"{w['against']} ({worst_field[1]}, the weakest of {len(fields)} fields)",
                       "tolerance": FUND_TOL, "compared": w["compared"], "agree_share": w["agree_share"],
                       "worst": w["worst"], "fields": {k: (v["status"], v["agree_share"], v["compared"]) for k, v in fields.items()}}}


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
