"""
Alpha Signal v2 — NSE quarterly results XBRL: the income statement as filed (feed nse_results_xbrl).

`quarterly_income` (Tickertape) and the Screener quarterly rows both start in 2023, so no
quarterly signal (margin expansion, profit acceleration) could be tested before 2024-12
(plan 0025 task 5.1). The exchange filing has the same numbers back to ~2017 in XBRL.

SOURCE (unofficial — the public nseindia.com site's own backend; research 0005 A3):
    index   GET https://www.nseindia.com/api/corporates-financial-results
              params: index=equities, symbol=<NSE symbol>, period=Quarterly  (warm NSE session)
              response: [{fromDate, toDate, consolidated ('Consolidated'/'Non-Consolidated'),
                          cumulative, audited, bank, broadCastDate, filingDate, xbrl, seqNumber}]
              back to 2005 for old listings; XBRL links up to Dec-2024 (2025+ results moved to the
              integrated filing, which this module does not read)
    filing  GET <xbrl>  (nsearchives.nseindia.com, Ind AS taxonomy)

FILE SHAPE: facts are `<prefix:Element contextRef="X">value</…>`. The quarter is the context whose
DateOfStartOfReportingPeriod / DateOfEndOfReportingPeriod equal the index row's fromDate / toDate
(the year-to-date context is skipped). Values are in rupees; stored in ₹ crore. Banks (bank = 'Y')
use another taxonomy and are skipped.

PIT: `filed_at` = broadCastDate (else filingDate), the moment the market saw the result. A revised
filing is a new row with a later `filed_at`. Append-only (INSERT OR IGNORE).
Basis: per quarter the consolidated filing when one exists, else standalone (`basis`).

Usage:
    python -m sources.nse_results --smoke                         # 3 stocks, 2 quarters each, print, no write
    python -m sources.nse_results --sids SSWL,TIMETECHNO
    python -m sources.nse_results --universe --since 2017-04-01 --budget-min 180   # resumable
"""

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import runlog  # noqa: E402
from db import insert_df, read_sql  # noqa: E402
from hosts import HOSTS  # noqa: E402
from sources import _http  # noqa: E402

LABEL = "nse_results_xbrl"
INDEX_API = "https://www.nseindia.com/api/corporates-financial-results"
WARM_URL = "https://www.nseindia.com/"
HEADERS = {**HOSTS["nse"]["headers"],
           "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results"}
SMOKE = ["SSWL", "TIMETECHNO", "NETWEB"]
DONE_FILE = PROJECT_ROOT / "output" / "nse_results_done.txt"
FIELDS = {
    "revenue": ["RevenueFromOperations"],
    "other_income": ["OtherIncome"],
    "total_income": ["Income"],
    "finance_costs": ["FinanceCosts"],
    "depreciation": ["DepreciationDepletionAndAmortisationExpense"],
    "pbt_pre_exceptional": ["ProfitBeforeExceptionalItemsAndTax"],
    "exceptional": ["ExceptionalItemsBeforeTax"],
    "pbt": ["ProfitBeforeTax"],
    "tax": ["TaxExpense"],
    "pat": ["ProfitLossForPeriod"],
    "eps": ["BasicEarningsLossPerShareFromContinuingOperations",
            "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations"],
}
CRORE = 1e7
COLS = ["sid", "symbol", "period_start", "period_end", "basis", "filed_at", "audited", *FIELDS,
        "source_url", "fetched_at"]
_FACT = re.compile(r'<[\w-]+:(\w+)\b[^>]*contextRef="([^"]+)"[^>]*>([^<]*)<')


def _d(s, fmt="%d-%b-%Y"):
    try:
        return datetime.strptime(s.strip(), fmt).date().isoformat()
    except Exception:
        return None


def parse(text, start, end):
    """One quarter's figures from a results XBRL: {field: value} (₹ crore; EPS in ₹), or None
    when no context covers exactly [start, end]."""
    facts = _FACT.findall(text)
    span = {}
    for name, ctx, val in facts:
        if name in ("DateOfStartOfReportingPeriod", "DateOfEndOfReportingPeriod"):
            span.setdefault(ctx, {})[name] = val.strip()
    ctx = next((c for c, s in span.items() if s.get("DateOfStartOfReportingPeriod") == start
                and s.get("DateOfEndOfReportingPeriod") == end), None)
    if ctx is None:
        return None
    vals = {name: val.strip() for name, c, val in facts if c == ctx}
    out = {}
    for field, names in FIELDS.items():
        v = next((vals[n] for n in names if n in vals and vals[n] not in ("", "-")), None)
        try:
            v = float(v) if v is not None else None
        except ValueError:
            v = None
        out[field] = v if v is None or field == "eps" else v / CRORE
    return out if out.get("revenue") is not None or out.get("pat") is not None else None


def index(session, symbol):
    r = _http.polite_get(INDEX_API, session=session, timeout=60,
                         params={"index": "equities", "symbol": symbol, "period": "Quarterly"})
    rows = r.json()
    return rows if isinstance(rows, list) else rows.get("data", [])


def choose(rows, since, until):
    """Quarterly, non-cumulative, non-bank filings with an XBRL file in [since, until]; per quarter the
    consolidated filing if there is one, else standalone. Revisions (several filings per quarter
    and basis) are all kept."""
    keep = []
    for x in rows:
        end, start = _d(x.get("toDate") or ""), _d(x.get("fromDate") or "")
        url = x.get("xbrl") or ""
        if not (end and start and url.endswith(".xml")) or x.get("bank") == "Y":
            continue
        if x.get("cumulative", "").lower().startswith("cumulative") or not (since <= end <= until):
            continue
        basis = "consolidated" if x.get("consolidated") == "Consolidated" else "standalone"
        filed = x.get("broadCastDate") or x.get("filingDate") or ""
        filed_at = (_d(filed[:11]) or "") + (filed[11:].strip() and " " + filed[11:].strip())
        keep.append(dict(start=start, end=end, basis=basis, url=url, filed_at=filed_at.strip(),
                         audited=x.get("audited")))
    cons = {k["end"] for k in keep if k["basis"] == "consolidated"}
    return [k for k in keep if k["basis"] == "consolidated" or k["end"] not in cons]


def _stored(sid):
    df = read_sql("SELECT period_end, basis, filed_at FROM quarterly_results_nse WHERE sid = ?", [sid])
    return set(map(tuple, df.to_numpy()))


def harvest_stock(session, sid, symbol, since, until, skip_stored=True, limit=None, errors=None):
    filings = choose(index(session, symbol), since, until)
    if limit:
        filings = sorted(filings, key=lambda f: f["end"], reverse=True)[:limit]
    have = _stored(sid) if skip_stored else set()
    rows, now = [], datetime.utcnow().isoformat(timespec="seconds")
    for f in filings:
        if (f["end"], f["basis"], f["filed_at"]) in have:
            continue
        try:
            r = _http.polite_get(f["url"], timeout=60)
            vals = parse(r.content.decode("utf-8", "replace"), f["start"], f["end"])
        except Exception as e:                                  # visible in run_events, not a print
            runlog.item_error(LABEL, f"{sid} {f['url']}", e)
            if errors is not None:
                errors.append(f["url"])
            continue
        if vals is None:
            runlog.item_failed(LABEL, f"{sid} {f['url']}", "no context covers the quarter")
            continue
        rows.append(dict(sid=sid, symbol=symbol, period_start=f["start"], period_end=f["end"], basis=f["basis"],
                         filed_at=f["filed_at"], audited=f["audited"], **vals, source_url=f["url"], fetched_at=now))
    return rows


def _done():
    return set(DONE_FILE.read_text().split()) if DONE_FILE.exists() else set()


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--smoke", action="store_true", help="3 stocks, latest 2 quarters, print, no write")
    p.add_argument("--sids", help="comma-separated NSE symbols")
    p.add_argument("--universe", action="store_true", help="every stock (resumable via the done file)")
    p.add_argument("--since", default="2017-04-01")
    p.add_argument("--until", default=date.today().isoformat())
    p.add_argument("--budget-min", type=float, help="stop after this many minutes (rerun resumes)")
    a = p.parse_args()
    stocks = read_sql("SELECT sid, ticker FROM stocks WHERE ticker IS NOT NULL AND (sector IS NULL OR sector != 'Financials') "
                      "ORDER BY market_cap_cr DESC")
    by_sym = dict(zip(stocks["ticker"], stocks["sid"]))
    if a.smoke:
        items = SMOKE
    elif a.sids:
        items = [s.strip() for s in a.sids.split(",") if s.strip()]
    elif a.universe:
        done = _done()
        items = [s for s in stocks["ticker"] if s not in done]
    else:
        p.error("one of --smoke / --sids / --universe")
    session = _http.warm_session(WARM_URL, headers=HEADERS)

    if a.smoke:
        bad = []
        for sym in items:
            rows = harvest_stock(session, by_sym.get(sym, sym), sym, a.since, a.until, skip_stored=False, limit=2)
            print(f"\n{sym}: {len(rows)} quarters")
            for r in rows:
                print(f"  {r['period_end']} {r['basis']:12s} filed {r['filed_at']} rev {r['revenue']:.1f} "
                      f"pbt {r['pbt']} pat {r['pat']} eps {r['eps']}")
            if not rows:
                bad.append(sym)
        if bad:
            sys.exit(f"nse_results smoke: no quarters for {bad}")
        return

    out_of_time = _http.time_budget("nse", a.budget_min) if a.budget_min else (lambda: False)
    pending_done = []

    def fetch(sym):
        if out_of_time():
            return None
        errors = []
        rows = harvest_stock(session, by_sym.get(sym, sym), sym, a.since, a.until, errors=errors)
        if a.universe and not errors:
            pending_done.append(sym)
        return rows

    def write(rows):
        n = insert_df(pd.DataFrame(rows)[COLS], "quarterly_results_nse", lock_retries=5) if rows else 0
        if pending_done:
            with DONE_FILE.open("a") as f:
                f.write("".join(f"{s}\n" for s in pending_done))
            pending_done.clear()
        return n

    print(f"nse_results: {len(items)} stocks, quarters {a.since} → {a.until}"
          + (f", budget {a.budget_min:.0f} min" if a.budget_min else ""))
    _http.run_harvester(items, fetch, write, flush_every=10, label=LABEL)


if __name__ == "__main__":
    main()
