"""
Alpha Signal v2 — Screener.in schedules pull (F1.2)

Fetches the per-stock JSON schedules that expand "+"-marked rows on Screener
company pages. The Excel export rolls these up; the schedules endpoint
breaks them out. New line items reach `fundamentals_screener` in the same
long format used by `screener_pull.py`.

What we pull (parent → sub-items, all annual):
  Other Liabilities → Trade Payables, Non-controlling int, Other liability items
  Borrowings        → Long Term Borrowings, Short Term Borrowings, Lease Liabilities
  Other Assets      → tax assets, sub-receivables (varies by company)
  Fixed Assets      → Land, Buildings, Plant & Machinery (varies by company)

Endpoint pattern (discovered from chart static JS, company.customisation.js):
  GET /api/company/{companyId}/schedules/?parent=<row>&section=<section>&consolidated

Period labels in the response are like "Mar 2025"; we parse to fiscal-end
ISO dates ("2025-03-31"). For non-March fiscal years (e.g. "Dec 2025") we use
end-of-month of the label month.

Reads:  ~/.cache/screener_cookie.json, stocks (sid → ticker), fundamentals_screener
Writes: fundamentals_screener (new line items), screener_pull_errors

Usage:
    python -m sources.screener_schedules --sid RELI            # one stock
    python -m sources.screener_schedules --tier LARGE          # one tier
    python -m sources.screener_schedules --universe            # all stocks
    python -m sources.screener_schedules --sid RELI --dry-run  # don't write

NEVER run concurrently with sources.screener_pull — same cookie, doubled
rate, easy way to trip Screener's bot detection.
"""

import argparse
import calendar
import random
import re
import time
from datetime import date
from typing import Iterable

import pandas as pd
import requests

from db import insert_df, read_sql, upsert_df
from sources.screener_pull import (
    COMPANY_CONSOLIDATED_URL,
    COMPANY_URL,
    DELAY_BETWEEN_STEPS,
    DELAY_BETWEEN_STOCKS,
    log_error,
    make_session,
)

API_SCHEDULES_URL = "https://www.screener.in/api/company/{cid}/schedules/"

# (parent, section, view) — what we ask for, per stock.
# 'consolidated' is preferred but falls back to standalone if unavailable.
SCHEDULES_TO_PULL = [
    ("Other Liabilities", "balance-sheet"),
    ("Borrowings",        "balance-sheet"),
    ("Other Assets",      "balance-sheet"),
    ("Fixed Assets",      "balance-sheet"),
]

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}


def discover_company_id(s: requests.Session, ticker: str) -> tuple[int, str] | None:
    """Return (companyId, view) for `ticker`. Tries consolidated then standalone.

    The companyId appears on the company page as data-url="/api/company/<id>/add/...".
    """
    for view, url_tmpl in (("consolidated", COMPANY_CONSOLIDATED_URL),
                           ("standalone",   COMPANY_URL)):
        url = url_tmpl.format(ticker=ticker)
        r = s.get(url, timeout=20)
        if r.status_code == 404:
            continue
        if r.status_code in (401, 403):
            raise PermissionError(f"{url} → HTTP {r.status_code} (cookie expired?)")
        if r.status_code != 200:
            continue
        m = re.search(r'/api/company/(\d+)/(?:add|chat|actions|schedules)/', r.text)
        if m:
            return int(m.group(1)), view
    return None


def _parse_period_label(label: str) -> str | None:
    """'Mar 2025' → '2025-03-31'. Returns None on malformed input."""
    parts = label.strip().split()
    if len(parts) != 2:
        return None
    mon_abbr, year_s = parts
    mon = MONTHS.get(mon_abbr.lower()[:3])
    if not mon:
        return None
    try:
        y = int(year_s)
    except ValueError:
        return None
    return date(y, mon, calendar.monthrange(y, mon)[1]).isoformat()


def _parse_value(v) -> float | None:
    """Screener returns numeric strings like '1,234' or '-456' or '' — coerce."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s or s in ("-", "—", "N/A", "NaN"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fetch_schedule(
    s: requests.Session, cid: int, parent: str, section: str, consolidated: bool,
) -> dict:
    """Hit /api/company/{cid}/schedules/. Returns parsed JSON dict.

    Raises requests.HTTPError on non-200, except 404 (returns {}).
    """
    params = {"parent": parent, "section": section}
    if consolidated:
        params["consolidated"] = ""
    url = API_SCHEDULES_URL.format(cid=cid)
    r = s.get(url, params=params, timeout=20,
              headers={"X-Requested-With": "XMLHttpRequest"})
    if r.status_code == 404:
        return {}
    if r.status_code in (401, 403):
        raise PermissionError(
            f"schedules GET returned HTTP {r.status_code} — cookie expired"
        )
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        return {}


def schedule_to_rows(
    sid: str, schedule_data: dict, period_type: str = "annual",
) -> list[dict]:
    """Flatten {line_item: {period_label: value}} → long-format rows."""
    rows = []
    for line_item, periods in schedule_data.items():
        if not isinstance(periods, dict):
            continue
        for label, raw in periods.items():
            iso = _parse_period_label(label)
            if not iso:
                continue
            val = _parse_value(raw)
            rows.append({
                "sid": sid,
                "period_end": iso,
                "period_type": period_type,
                "line_item": line_item.strip(),
                "value": val,
            })
    return rows


def pull_one(
    s: requests.Session, sid: str, ticker: str, dry_run: bool = False,
) -> int:
    """Pull all configured schedules for one stock. Returns rows written."""
    try:
        found = discover_company_id(s, ticker)
    except PermissionError:
        raise
    except Exception as e:
        log_error(sid, ticker, "fetch", f"company-id discovery: {type(e).__name__}: {e}")
        return 0
    if found is None:
        log_error(sid, ticker, "fetch", "company-id not found (404 on consolidated + standalone)")
        return 0
    cid, view = found
    consolidated = view == "consolidated"

    all_rows: list[dict] = []
    for parent, section in SCHEDULES_TO_PULL:
        time.sleep(random.uniform(*DELAY_BETWEEN_STEPS))
        try:
            data = fetch_schedule(s, cid, parent, section, consolidated)
        except PermissionError:
            raise
        except Exception as e:
            log_error(
                sid, ticker, "fetch",
                f"schedule {parent!r}/{section}: {type(e).__name__}: {e}",
            )
            continue
        all_rows.extend(schedule_to_rows(sid, data))

    if not all_rows:
        log_error(sid, ticker, "empty", "no schedule rows for any parent")
        return 0

    df = pd.DataFrame(all_rows).drop_duplicates(
        subset=["sid", "period_end", "period_type", "line_item"], keep="last",
    )
    if dry_run:
        return len(df)
    return upsert_df(df, "fundamentals_screener")


def get_targets(args) -> pd.DataFrame:
    if args.sid:
        return read_sql(
            "SELECT sid, ticker FROM stocks WHERE sid = ?", params=[args.sid]
        )
    if args.tier:
        return read_sql(
            "SELECT sid, ticker FROM stocks WHERE cap_tier = ? AND ticker IS NOT NULL "
            "ORDER BY market_cap_cr DESC",
            params=[args.tier],
        )
    if args.universe:
        return read_sql(
            "SELECT sid, ticker FROM stocks WHERE ticker IS NOT NULL "
            "ORDER BY market_cap_cr DESC"
        )
    return pd.DataFrame()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--sid", help="single stock SID")
    parser.add_argument("--tier", choices=["LARGE", "MID", "SMALL"])
    parser.add_argument("--universe", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch + parse but don't write")
    args = parser.parse_args()

    s = make_session()

    targets = get_targets(args)
    if targets.empty:
        parser.error("no targets — specify --sid, --tier, or --universe")

    print(f"targets: {len(targets)} stocks")
    total_rows = 0
    failures = 0
    for i, (sid, ticker) in enumerate(
        targets[["sid", "ticker"]].itertuples(index=False), 1,
    ):
        try:
            n = pull_one(s, sid, ticker, dry_run=args.dry_run)
            status = "✓" if n > 0 else "·"
            print(f"  [{i}/{len(targets)}] {status} {sid} ({ticker}): {n} rows")
            total_rows += n
            if n == 0:
                failures += 1
        except PermissionError as e:
            print(f"\nAUTH FAILURE on {sid} ({ticker}): {e}")
            print("→ Re-extract the cookie from your browser and retry.")
            return 2
        if i < len(targets):
            time.sleep(random.uniform(*DELAY_BETWEEN_STOCKS))

    print(f"\ntotal rows: {total_rows}  |  failures: {failures}/{len(targets)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
