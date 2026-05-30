"""
Alpha Signal v2 — Banking Metrics (Phase 2.2a-ii)

Per-bank/NBFC quarterly + annual regulatory disclosures scraped from
Screener.in stock pages. ADR 0030 makes this the primary source; Tickertape
does not expose banking-specific ratios via Bharat_sm_data.

Scope: 158 Banks (41) + NBFCs (117). The other 91 "Financials" (AMC,
Insurance, Capital Markets) use the main screener — they don't fit the
NIM/GNPA lens.

What we scrape per stock (HTML #quarters / #profit-loss / #balance-sheet):

  Income (quarterly + annual):
    Revenue               → interest_earned          (banks: interest income)
    Interest              → interest_expended        (banks: cost of funds)
    Financing Profit      → net_interest_income      (= NII)
    Financing Margin %    → nim_pct                  (NIM directly!)
    Other Income          → other_income
    Net Profit            → net_profit

  Asset Quality (quarterly only):
    Gross NPA %           → gross_npa_pct
    Net NPA %             → net_npa_pct

  Balance sheet (annual):
    Equity Capital, Reserves → book_value_per_share (computed from shares)
    Deposits              → deposits
    Borrowing             → borrowings

  Computed:
    cost_of_funds_pct  = 4 × interest_expended / (deposits + borrowings)  [annualized]
    adj_book_per_share = book_value − gross_npa_pct/100 × book_value
                         (no PCR available — pessimistic zero-recovery
                         assumption; refine in Phase 2.2c when RBI lands)

Not scraped (Plan 2.2c — RBI fallback gated on coverage report):
    CASA %, PCR %, CAR %, CRAR %, Slippage %, Credit cost %, Provisions

Reuses sources/screener_pull infra:
  - ~/.cache/screener_cookie.json auth
  - Rate-limit policy (2.5–4 s between stocks, jittered)
  - SID → ticker mapping from stocks.ticker

Usage:
    python -m sources.banking_metrics --sid HDBK              # one bank
    python -m sources.banking_metrics --sid HDBK --dry-run    # parse, don't write
    python -m sources.banking_metrics --industry Banks         # all 41 banks
    python -m sources.banking_metrics --industry NBFCs         # all 117 NBFCs
    python -m sources.banking_metrics --universe              # all 158
    python -m sources.banking_metrics --limit 5               # smoke test
"""

import argparse
import re
import sys
import random
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, upsert_df
from sources.screener_pull import (
    make_session,
    check_auth,
    COMPANY_CONSOLIDATED_URL,
    COMPANY_URL,
    DELAY_BETWEEN_STOCKS,
    BACKOFF_ON_429,
)

# Universe filter — banks + NBFCs only. AMC, Insurance, Capital Markets stay
# on the main screener (different valuation primitives, ADR 0030).
BANKING_INDUSTRIES = ("Banks", "NBFCs / Finance")

# Map HTML row label → banking_metrics column. Mirror labels appear in both
# #quarters (quarterly cadence) and #profit-loss (annual cadence) — same map
# works for both. Asset Quality (GNPA/NNPA) is quarterly-only.
#
# Notes from 2026-05-29 HDBK probe:
# - "Financing Profit" is Revenue - Interest - Expenses (op profit), NOT NII.
#   We map it to pre_provision_op_profit and compute true NII ourselves as
#   interest_earned - interest_expended.
# - "Financing Margin %" is op margin (Financing Profit / Revenue), NOT NIM.
#   We drop it and compute NIM = NII / advances × 4 in derive step.
# - HDBK consolidated page has BLANK Gross NPA / Net NPA cells; standalone
#   has them filled. Banks publish NPA on standalone (banking-entity) basis.
#   fetch_one() tries standalone FIRST.
INCOME_ROW_MAP = {
    "Revenue":            "interest_earned",
    "Interest":           "interest_expended",
    "Financing Profit":   "pre_provision_op_profit",
    "Other Income":       "other_income",
    "Net Profit":         "net_profit",
    "Gross NPA %":        "gross_npa_pct",
    "Net NPA %":          "net_npa_pct",
}

# Balance sheet (annual only) row label → column
BALANCE_SHEET_ROW_MAP = {
    "Equity Capital":     "_equity_capital",   # not stored; used to derive BVPS
    "Reserves":           "_reserves",         # not stored; used to derive BVPS
    "Deposits":           "deposits",
    "Borrowing":          "borrowings",
}


def _parse_period(label: str) -> tuple[str, str] | None:
    """Convert Screener period header to (period_end YYYY-MM-DD, period_type).

    Quarterly labels look like 'Mar 2024', 'Jun 2024'. Annual labels are
    'Mar 2024' too — but the section determines which it is, so we just
    parse the date and let the caller tag period_type.

    Returns None for headers that aren't dates (e.g. the blank corner cell
    or 'Raw PDF' link rows).
    """
    m = re.match(r"\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})\s*$", label)
    if not m:
        return None
    mon, year = m.group(1), int(m.group(2))
    months = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,
              "Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
    month = months[mon]
    # Screener reports period END — Mar 2024 = quarter ending Mar 31 2024.
    # Use month-end day. (For simplicity, hardcode month-end.)
    if month in (1, 3, 5, 7, 8, 10, 12):
        day = 31
    elif month in (4, 6, 9, 11):
        day = 30
    else:
        # Feb — 28 unless leap. Banks file Feb-end so check leap.
        day = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
    return f"{year:04d}-{month:02d}-{day:02d}"


def _parse_number(text: str) -> float | None:
    """Parse a Screener cell value. Handles ₹ commas, '%', '+', NULL/empty."""
    if not text:
        return None
    s = text.strip().replace(",", "").replace("%", "").replace("₹", "")
    if s in ("", "-", "—"):
        return None
    # Screener sometimes uses parentheses for negatives
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def _parse_section_table(soup, section_id: str, row_map: dict, period_type: str):
    """Extract a section's table as a list of {period_end, period_type, **fields}.

    Section structure:
      <section id="...">
        <h2>...</h2>
        <table class="data-table ...">
          <thead><tr><th></th><th>Mar 2023</th> ...</tr></thead>
          <tbody>
            <tr><td>Revenue+</td><td>47,548</td> ...</tr>
            <tr><td>Interest</td><td>22,606</td> ...</tr>
            ...

    Row labels sometimes carry a trailing '+' marker (expandable rows in
    the UI) which we strip. Match is exact after the strip.
    """
    section = soup.find(id=section_id)
    if not section:
        return []
    table = section.find("table")
    if not table:
        return []

    # Headers — list of period labels; first cell is blank.
    header_cells = table.find("thead").find_all("th") if table.find("thead") else table.find_all("tr")[0].find_all("th")
    period_labels = [th.get_text(strip=True) for th in header_cells]
    # Drop first (blank) column. Some Screener tables also append a "TTM"
    # column for some sections — keep it as None period_end so the parser
    # skips it.
    period_ends = []
    for lab in period_labels[1:]:
        pe = _parse_period(lab)
        period_ends.append(pe)

    # Build a row dict per period
    rows_by_period: dict[str, dict] = {pe: {"period_end": pe, "period_type": period_type}
                                        for pe in period_ends if pe}

    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        label = cells[0].get_text(strip=True).rstrip("+").strip()
        if label not in row_map:
            continue
        col = row_map[label]
        for i, cell in enumerate(cells[1:]):
            if i >= len(period_ends) or period_ends[i] is None:
                continue
            val = _parse_number(cell.get_text(strip=True))
            rows_by_period[period_ends[i]][col] = val

    return list(rows_by_period.values())


def parse_bank_page(html: str, sid: str) -> pd.DataFrame:
    """Parse a Screener.in stock page HTML into long-form banking_metrics rows.

    Returns a DataFrame with one row per (sid, period_end, period_type),
    columns matching the banking_metrics schema (NULLs for unscraped fields).
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    quarterly = _parse_section_table(soup, "quarters", INCOME_ROW_MAP, "quarterly")
    annual    = _parse_section_table(soup, "profit-loss", INCOME_ROW_MAP, "annual")
    balance   = _parse_section_table(soup, "balance-sheet", BALANCE_SHEET_ROW_MAP, "annual")

    # Merge balance-sheet rows into the annual income rows by period_end.
    annual_by_pe = {r["period_end"]: r for r in annual}
    for br in balance:
        pe = br["period_end"]
        if pe in annual_by_pe:
            annual_by_pe[pe].update({k: v for k, v in br.items()
                                     if k not in ("period_end", "period_type")})
        else:
            annual_by_pe[pe] = br

    # Compute BVPS from equity_capital (face value × shares) + reserves.
    # Screener "Equity Capital" is in Cr at face value (₹1 or ₹10 typically),
    # not number of shares. We need shares outstanding to convert. Use the
    # stocks table for shares_outstanding (latest snapshot).
    # If we don't have shares, leave BVPS NULL.
    for r in annual_by_pe.values():
        eq = r.pop("_equity_capital", None)
        rs = r.pop("_reserves", None)
        if eq is not None and rs is not None:
            # Total book value in Cr; per share computed later when we know shares
            r["_book_value_cr"] = float(eq) + float(rs)

    rows = quarterly + list(annual_by_pe.values())
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["sid"] = sid

    # Compute Net Interest Income = Interest Earned - Interest Expended.
    # (We don't read Screener's "Financing Profit" as NII — it has expenses
    # subtracted; see INCOME_ROW_MAP note.)
    def _nii(row):
        ie = row.get("interest_earned")
        ix = row.get("interest_expended")
        if ie is None or ix is None or pd.isna(ie) or pd.isna(ix):
            return None
        return round(float(ie) - float(ix), 3)
    df["net_interest_income"] = df.apply(_nii, axis=1)

    # Derive cost_of_funds_pct = annualized rate on deposits + borrowings.
    # COF works for ANNUAL rows (we have deposits + borrowings + interest
    # expended all at the same period). Quarterly rows don't have deposits
    # in this scrape — we'd need to ffill from the latest annual row. Defer
    # to Phase 2.2b signal layer.
    def _cof(row):
        if row.get("period_type") != "annual":
            return None
        ie = row.get("interest_expended")
        dep = row.get("deposits")
        bor = row.get("borrowings")
        if ie is None or pd.isna(ie):
            return None
        funds = (dep or 0) + (bor or 0)
        if funds <= 0:
            return None
        return round(100.0 * float(ie) / funds, 3)
    df["cost_of_funds_pct"] = df.apply(_cof, axis=1)

    # Stamp source + fetched_at
    df["source"] = "screener_in"
    df["fetched_at"] = datetime.now().isoformat(timespec="seconds")

    return df


def _derive_bvps_and_adj_book(df: pd.DataFrame, shares_outstanding: float | None):
    """Convert _book_value_cr (₹ Cr) → book_value_per_share + adj_book_per_share.

    BVPS = book_value_cr × 10^7 / shares_outstanding  (Cr → ₹ then / shares)
    AdjBook = BVPS × (1 − gross_npa_pct/100)
              [pessimistic — assumes zero NPA recovery; refine in 2.2c]
    """
    if shares_outstanding is None or shares_outstanding <= 0:
        df["book_value_per_share"] = None
        df["adj_book_per_share"] = None
        df.drop(columns=[c for c in ("_book_value_cr",) if c in df.columns],
                inplace=True, errors="ignore")
        return df

    def _bvps(bv_cr):
        if bv_cr is None or pd.isna(bv_cr):
            return None
        return round(float(bv_cr) * 1e7 / shares_outstanding, 4)

    if "_book_value_cr" in df.columns:
        df["book_value_per_share"] = df["_book_value_cr"].map(_bvps)
        df.drop(columns=["_book_value_cr"], inplace=True)
    else:
        df["book_value_per_share"] = None

    def _adjbook(row):
        bvps = row.get("book_value_per_share")
        gnpa = row.get("gross_npa_pct")
        if bvps is None or pd.isna(bvps):
            return None
        if gnpa is None or pd.isna(gnpa):
            return bvps  # no NPA data → no adjustment
        return round(float(bvps) * (1.0 - float(gnpa) / 100.0), 4)
    df["adj_book_per_share"] = df.apply(_adjbook, axis=1)
    return df


def _get_shares(sid: str) -> float | None:
    """Latest shares outstanding from fundamentals_screener (Screener.in Excel).

    The 'No. of Equity Shares' line item is in raw share count (not Cr).
    Read the most recent annual snapshot.
    """
    try:
        row = read_sql(
            "SELECT value FROM fundamentals_screener "
            "WHERE sid = ? AND line_item = 'No. of Equity Shares' "
            "ORDER BY period_end DESC LIMIT 1",
            params=[sid],
        )
        if row.empty:
            return None
        v = row.iloc[0]["value"]
        return float(v) if v and not pd.isna(v) else None
    except Exception:
        return None


def fetch_one(session, sid: str, ticker: str, dry_run: bool = False) -> tuple[str, int, str]:
    """Scrape + parse + write one bank. Returns (sid, rows_written, status).

    Order: standalone FIRST, consolidated FALLBACK. Banks publish asset
    quality (GNPA/NNPA) on the standalone banking entity, not consolidated
    (HDFC Bank's consolidated page leaves these cells empty). Some NBFCs
    only publish consolidated — hence the fallback.
    """
    last_err = None
    for view, url in (
        ("standalone",   COMPANY_URL.format(ticker=ticker)),
        ("consolidated", COMPANY_CONSOLIDATED_URL.format(ticker=ticker)),
    ):
        try:
            r = session.get(url, timeout=15, allow_redirects=False)
        except Exception as e:
            last_err = f"{view}: {type(e).__name__}: {e}"
            continue
        if r.status_code == 429:
            print(f"  ⚠ 429 rate-limited; sleeping {BACKOFF_ON_429}s")
            time.sleep(BACKOFF_ON_429)
            continue
        if r.status_code in (301, 302) or r.status_code == 404:
            last_err = f"{view}: HTTP {r.status_code}"
            continue
        if r.status_code != 200:
            last_err = f"{view}: HTTP {r.status_code}"
            continue
        # Parse
        df = parse_bank_page(r.text, sid)
        if df.empty:
            last_err = f"{view}: parsed 0 rows"
            continue
        # Plan 0007 Phase 2 — Identity Gate. The Screener.in URL is keyed by
        # ticker; if a redirect (rebrand, delisting, ticker recycling) makes
        # the response page about a different company, the H1 won't contain
        # the stock name. Route the parsed rows to banking_metrics_quarantine
        # instead of the live table.
        try:
            from validators.identity_check import verify_identity, quarantine_row, record_verdict
            name_row = read_sql("SELECT name FROM stocks WHERE sid=?", params=[sid])
            expected_name = name_row.iloc[0]["name"] if not name_row.empty else None
            v = verify_identity(sid, r.text, source="screener_in",
                                expected_name=expected_name)
            if v.status == "WRONG_ENTITY":
                # Quarantine + skip live write. Try the next view (consolidated)
                # in case standalone got redirected.
                for _, row in df.iterrows():
                    quarantine_row(
                        source_table="banking_metrics",
                        row=row.to_dict(), sid=sid, datum_class="banking_metric",
                        verdict=v,
                    )
                last_err = f"{view}: identity_gate WRONG_ENTITY ({v.reason})"
                continue
            elif v.status == "PASS":
                record_verdict(
                    sid=sid, source_table="banking_metrics",
                    source_key=f'{{"sid":"{sid}","view":"{view}"}}',
                    datum_class="banking_metric", verdict=v,
                )
        except Exception as e:
            # Never let an identity-gate exception block the write — log + carry on.
            import sys
            print(f"  ⚠ identity_check failed for {sid}: {e}", file=sys.stderr)
        shares = _get_shares(sid)
        df = _derive_bvps_and_adj_book(df, shares)

        # Plan 0007 Phase 3 — Plausibility Gate on banking metrics.
        # GNPA > 35% / NNPA > 15% / CAR < 5% are almost-certainly parse errors
        # (consolidated/standalone mix-up, decimal-place shift). Hard-out-of-
        # range rows route to banking_metrics_quarantine before write.
        try:
            from validators.plausibility import verify_plausibility, route_on_plausibility
            keep_idx = []
            for ix, parsed_row in df.iterrows():
                row_dict = parsed_row.to_dict()
                quarantined_this_row = False
                for col, datum_class in (
                    ("gross_npa_pct", "bank_gnpa_pct"),
                    ("net_npa_pct",   "bank_nnpa_pct"),
                    ("nim_pct",       "bank_nim_pct"),
                    ("car_pct",       "bank_car_pct"),
                    ("roa_pct",       "bank_roa_pct"),
                ):
                    val = row_dict.get(col)
                    if val is None:
                        continue
                    pv = verify_plausibility(datum_class, value=val, segment="*")
                    if pv.status == "OUT_OF_RANGE_HARD":
                        route_on_plausibility(
                            pv, source_table="banking_metrics",
                            row=row_dict, sid=sid, datum_class=datum_class,
                        )
                        quarantined_this_row = True
                        break  # don't double-quarantine the same row
                if not quarantined_this_row:
                    keep_idx.append(ix)
            if len(keep_idx) < len(df):
                df = df.loc[keep_idx]
                if df.empty:
                    last_err = f"{view}: all rows quarantined by plausibility gate"
                    continue
        except Exception as e:
            import sys
            print(f"  ⚠ plausibility gate failed for {sid}: {e}", file=sys.stderr)

        # Drop helper columns + align to schema
        schema_cols = [
            "sid", "period_end", "period_type",
            "interest_earned", "interest_expended", "net_interest_income",
            "other_income", "provisions", "pre_provision_op_profit", "net_profit",
            "gross_npa_pct", "net_npa_pct", "pcr_pct", "slippage_pct", "credit_cost_pct",
            "advances", "deposits", "borrowings", "book_value_per_share",
            "casa_pct", "car_pct", "crar_pct",
            "nim_pct", "roa_pct", "cost_of_funds_pct", "adj_book_per_share",
            "source", "fetched_at",
        ]
        # Add missing columns as None so upsert_df has them all
        for c in schema_cols:
            if c not in df.columns:
                df[c] = None
        df = df[schema_cols]

        if dry_run:
            print(f"  ✓ {sid} ({ticker}, {view}) — {len(df)} rows parsed (dry-run, not written)")
            return sid, len(df), "DRY_RUN"

        n = upsert_df(df, "banking_metrics")
        return sid, n, view

    return sid, 0, f"ALL_FAIL: {last_err}"


def _resolve_universe(args) -> pd.DataFrame:
    """Return DataFrame of (sid, ticker, industry) to scrape."""
    if args.sid:
        return read_sql(
            "SELECT sid, ticker, industry FROM stocks WHERE sid = ?",
            params=[args.sid.upper()],
        )
    where_clauses = ["industry IN ({})".format(",".join("?" * len(BANKING_INDUSTRIES)))]
    params: list = list(BANKING_INDUSTRIES)
    if args.industry:
        ind = args.industry.strip()
        # Allow shorthand
        if ind.lower() in ("banks", "bank"):
            ind = "Banks"
        elif ind.lower() in ("nbfc", "nbfcs"):
            ind = "NBFCs / Finance"
        where_clauses = ["industry = ?"]
        params = [ind]
    df = read_sql(
        f"SELECT sid, ticker, industry FROM stocks WHERE {' AND '.join(where_clauses)} "
        f"AND ticker IS NOT NULL ORDER BY cap_tier, sid",
        params=params,
    )
    if args.limit:
        df = df.head(args.limit)
    return df


def compute_universe():
    """PIPELINE_STEPS entry point — scrape full Banks + NBFCs universe.

    Wraps main(--universe) for the monthly cron. Returns the row count so
    the pipeline runner can log rows_affected (same contract as other
    compute() functions in sources/).
    """
    class _A:
        sid = None
        industry = None
        universe = True
        limit = None
        dry_run = False
    args = _A()

    targets = _resolve_universe(args)
    if targets.empty:
        print("⚠ no Bank/NBFC universe to scrape")
        return 0

    session = make_session()
    ok, detail = check_auth(session)
    if not ok:
        raise PermissionError(f"Screener.in auth: {detail}")

    rows_total = 0
    for i, row in targets.reset_index(drop=True).iterrows():
        sid, ticker = row["sid"], row["ticker"]
        try:
            _, n, status = fetch_one(session, sid, ticker, dry_run=False)
            rows_total += n
            if i % 20 == 0:
                print(f"  [{i+1}/{len(targets)}] {sid} → {n} rows ({status})")
        except Exception as e:
            print(f"  ✗ {sid}: {type(e).__name__}: {e}")
        if i < len(targets) - 1:
            time.sleep(random.uniform(*DELAY_BETWEEN_STOCKS))
    print(f"✓ banking_metrics: {rows_total:,} rows across {len(targets)} stocks")
    return rows_total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sid", help="Scrape one stock by SID")
    parser.add_argument("--industry", help="Banks / NBFCs (case-insensitive shorthand)")
    parser.add_argument("--universe", action="store_true",
                        help="Scrape all Banks + NBFCs")
    parser.add_argument("--limit", type=int, help="Cap to first N stocks")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse + report row counts; do not write")
    args = parser.parse_args()

    if not (args.sid or args.industry or args.universe):
        parser.error("specify --sid, --industry, or --universe")

    targets = _resolve_universe(args)
    if targets.empty:
        print("⚠ no stocks matched filters")
        return

    session = make_session()
    ok, detail = check_auth(session)
    if not ok:
        print(f"✗ Screener.in auth: {detail}")
        print("  Try: python -m sources.screener_pull --login")
        sys.exit(2)
    print(f"✓ auth: {detail}")

    print(f"\n→ scraping {len(targets)} stocks ({targets['industry'].value_counts().to_dict()})")

    rows_total = 0
    errors = []
    started = time.time()
    for i, row in targets.reset_index(drop=True).iterrows():
        sid, ticker = row["sid"], row["ticker"]
        try:
            sid, n, status = fetch_one(session, sid, ticker, dry_run=args.dry_run)
            rows_total += n
            print(f"  [{i+1:3d}/{len(targets)}] {sid:6s} ({ticker:14s}) → {n:3d} rows ({status})")
            if status.startswith("ALL_FAIL"):
                errors.append((sid, status))
        except Exception as e:
            print(f"  [{i+1:3d}/{len(targets)}] {sid:6s} ✗ {type(e).__name__}: {e}")
            errors.append((sid, str(e)))
        # Rate-limit jitter
        if i < len(targets) - 1:
            delay = random.uniform(*DELAY_BETWEEN_STOCKS)
            time.sleep(delay)

    elapsed = time.time() - started
    print(f"\n{'═' * 60}")
    print(f"✓ {rows_total:,} rows; {len(targets) - len(errors)}/{len(targets)} stocks OK")
    print(f"  elapsed: {elapsed/60:.1f} min")
    if errors:
        print(f"  errors: {len(errors)}")
        for sid, err in errors[:10]:
            print(f"    {sid}: {err}")


if __name__ == "__main__":
    main()
