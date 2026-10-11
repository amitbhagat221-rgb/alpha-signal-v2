"""
Alpha Signal v2 — Automated MF holdings ingest via ETMoney public site.

Phase 4c automated path. The user requested holdings for all schemes;
manual CSV ingest at `sources/mf_holdings.py` is still supported, but this
module replaces "deferred to v2" with a real working scraper.

Why ETMoney:
  - Published sitemap (`mf-regular-schemes-portfolio-details-sitemap.xml`)
    enumerates 1,475 portfolio-detail URLs deterministically — no per-AMC
    discovery needed
  - Holdings data is SERVER-RENDERED in static HTML (no JS evaluation
    required) — clean BeautifulSoup parse
  - Each holding row carries the equity name + ETMoney's internal stockId
    (mappable to our stocks.sid via a separate name match)
  - Reasonable ToS posture (public catalog page, no auth, polite scraping)
  - Single source covers ~60% of our scored MF universe (the actionable
    top-AUM funds; the long tail of 8K+ tiny inactive schemes can be
    skipped — they wouldn't show up in research workflows anyway)

Matching AMFI scheme_code → ETMoney URL:
  - ETMoney slug = lowercased + hyphen-joined scheme name with words
    "plan" and most "scheme" stripped
  - We normalise both and do best-substring match
  - Stored in `mf_scheme_master.etm_slug` + `.etm_id` for direct re-fetch

Usage:
    python -m sources.mf_holdings_scrape --build-map       # build AMFI ↔ ETMoney mapping
    python -m sources.mf_holdings_scrape --scrape          # scrape all mapped schemes
    python -m sources.mf_holdings_scrape --limit 50        # smoke test
    python -m sources.mf_holdings_scrape --scheme 122639   # single scheme
    python -m sources.mf_holdings_scrape --scrape --recheck-days 14 --max-minutes 15   # = the daily step
"""

import argparse
import re
import sys
import time
from datetime import datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup


from db import get_db, read_sql
import runlog
from sources import _http

# ── Rate-limit policy ──
# ETMoney is a free aggregator. They tolerate steady-state polite traffic but
# rate-limit aggressive scrapers. The host door keeps calls ≥2.5 s apart
# (hosts.HOSTS["etmoney"], ~24 req/min steady state, browser headers); on top:
TIMEOUT = 20
CHUNK_SIZE = 100         # request count between long pauses
CHUNK_PAUSE = 30         # seconds to pause between chunks (lets any soft-limit reset)
MAX_RETRIES = 3
BACKOFF_BASE = 5         # 5s, 15s, 45s on retries
ERROR_PAUSE_THRESHOLD = 5  # consecutive errors → long pause
ERROR_PAUSE_SECONDS = 300  # 5 min if we hit rate-limit territory


def _get(url, timeout):
    """One ETMoney GET through the host door: raw Response, no door retry
    (fetch_holdings runs its own backoff ladder)."""
    return _http.polite_request("GET", url, check=False, retries=0, timeout=timeout)

SITEMAPS = [
    "https://www.etmoney.com/mf-schemes-sitemap.xml",
    "https://www.etmoney.com/mf-regular-schemes-sitemap.xml",
]
PORTFOLIO_SITEMAP = "https://www.etmoney.com/mf-regular-schemes-portfolio-details-sitemap.xml"
# The Direct-plan sitemap answers a 199-byte 403 on some calls and 200 on the next
# (2026-10-10); one miss used to drop every Direct page from the mapping silently.
SITEMAP_TRIES = 3

# Daily rotation (2026-10-10). The old monthly step re-fetched only the top 100 funds
# by composite_score: the other ~2,200 stayed frozen at the 2026-05-28 bulk scrape and
# funds launched since (no score yet, never mapped) were never fetched at all. Now every
# run maps new schemes, then visits the least-recently-checked funds until the host
# budget runs out; a fund is due again RECHECK_DAYS after its last check. ~2,300 non-debt
# pages / 14 days ≈ 165 a day ≈ 8 min. Debt funds are skipped: ETMoney lists no stock
# table for them (17 of 2,408 ever returned one).
RECHECK_DAYS = 14


def _ensure_columns():
    """Add etm_slug / etm_id / etm_checked_at columns to mf_scheme_master if absent."""
    with get_db() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(mf_scheme_master)").fetchall()]
        if "etm_slug" not in cols:
            conn.execute("ALTER TABLE mf_scheme_master ADD COLUMN etm_slug TEXT")
            print("  Added etm_slug column")
        if "etm_id" not in cols:
            conn.execute("ALTER TABLE mf_scheme_master ADD COLUMN etm_id INTEGER")
            print("  Added etm_id column")
        if "etm_checked_at" not in cols:
            conn.execute("ALTER TABLE mf_scheme_master ADD COLUMN etm_checked_at TEXT")
            print("  Added etm_checked_at column")


# ─────────────────────── Mapping: AMFI ↔ ETMoney ───────────────────────


_STOP_TOKENS = {
    "fund", "plan", "option", "scheme", "mutual", "the",
    "an", "a", "of", "for", "and", "or",
    "formerly", "known", "as",
    "income", "distribution", "cum", "capital", "withdrawal", "payout",
    "reinvestment",
}
_PLAN_TOKENS = {"direct", "regular"}
_OPTION_TOKENS = {"growth", "idcw", "dividend"}


def _normalise(s: str) -> str:
    """Aggressive normalise for name matching: lowercase, alphanumeric only."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _normalise_etm_slug(slug: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (slug or "").lower())


def _identity_seq(s: str) -> list[str]:
    """Identity tokens in name order — fund-name signature WITHOUT plan/option indicators.
    'SBI CONTRA FUND - DIRECT PLAN - GROWTH' → [sbi, contra]
    'sbi-contra-direct-plan-growth' → [sbi, contra]
    Both sides match by 'who is this fund' rather than 'which variant'.
    'Fund of Funds' reads as ETMoney's 'fof'; dotted acronyms join (T.I.G.E.R. → tiger)."""
    s = (s or "").lower()
    s = re.sub(r"\bfunds?\s+of\s+funds?\b", "fof", s)
    s = re.sub(r"\b(?:[a-z]\.){2,}[a-z]?\b", lambda m: m.group(0).replace(".", ""), s)
    return [
        t for t in re.findall(r"[a-z0-9]+", s)
        if t not in _STOP_TOKENS
        and t not in _PLAN_TOKENS
        and t not in _OPTION_TOKENS
        and len(t) > 1
    ]


def _identity_tokens(s: str) -> set[str]:
    return set(_identity_seq(s))


def _identity_keys(s: str) -> set:
    """The keys two names must share to be the same fund: the token SET (word order
    differs between AMFI and ETMoney) and the tokens run together ('flexi cap' =
    'flexicap', 'mid cap' = 'midcap'). Empty for a name with < 2 identity tokens."""
    seq = _identity_seq(s)
    return {frozenset(seq), "".join(seq)} if len(seq) >= 2 else set()


def _plan_marker(s: str) -> str | None:
    """Returns 'direct' / 'regular' / None based on tokens."""
    raw = set(re.findall(r"[a-z0-9]+", (s or "").lower()))
    if "direct" in raw:
        return "direct"
    if "regular" in raw:
        return "regular"
    return None


def fetch_etm_sitemap_urls() -> dict[str, tuple[str, int]]:
    """Pull all MF detail URLs from ETMoney sitemaps. Returns {normalised_slug: (slug, etm_id)}."""
    out: dict[str, tuple[str, int]] = {}
    for url in SITEMAPS:
        print(f"  Fetching {url}…")
        for _ in range(SITEMAP_TRIES):
            r = _get(url, timeout=30)
            if r.status_code == 200:
                break
        if r.status_code != 200:
            runlog.item_failed("etmoney sitemap", url, f"HTTP {r.status_code} on {SITEMAP_TRIES} tries",
                               symptom="A")
            continue
        matches = re.findall(
            r"<loc>https://www\.etmoney\.com/mutual-funds/([^/<]+)/(\d+)</loc>",
            r.text,
        )
        for slug, etm_id in matches:
            norm = _normalise_etm_slug(slug)
            out[norm] = (slug, int(etm_id))
        print(f"    {len(matches)} URLs (cumulative unique: {len(out)})")
    if not out:
        raise RuntimeError("no ETMoney sitemap could be read — cannot map schemes")
    return out


def _etm_index(etm: dict[str, tuple[str, int]]) -> dict:
    """{identity key: [(slug, etm_id, plan), …]} over every sitemap URL (see _identity_keys);
    plan is 'direct' / 'regular' / None from the slug."""
    index: dict = {}
    for slug, etm_id in etm.values():
        for key in _identity_keys(slug):
            index.setdefault(key, []).append((slug, etm_id, _plan_marker(slug)))
    return index


def _match(amfi_name: str, index: dict, plan: str | None = None) -> tuple[str, int] | None:
    """(etm_slug, etm_id) of the ETMoney page for one AMFI scheme, or None.

    The names must be the SAME fund: equal identity-token sets, or equal once the
    spaces go. The old rule — ETMoney tokens ⊆ AMFI tokens, longest first — mapped a
    fund to any page whose name was a subset of its own: Canara Robeco Flexi Cap →
    canara-robeco-income ('income' is a stop token), LIC MF Nifty Next 50 → the Nifty
    50 fund, every closed-end 'Series N' → the open-ended fund, a PSU-bond index fund
    → a Nifty 50 page (audit 2026-10-10). No page is better than another fund's.
    A parenthetical is tried both kept ('UTI Focused Fund (30 stocks)') and dropped
    ('… (erstwhile Bluechip Fund)').

    Holdings are identical across plans, so the plan only picks between equal
    candidates: `plan` (mf_scheme_master.plan_type — scheme_name no longer carries
    it) or a Direct/Regular word in the name; unmarked → Regular (bare slug).
    """
    keys = _identity_keys(amfi_name) | _identity_keys(re.sub(r"\([^)]*\)", " ", amfi_name or ""))
    cands = [c for k in keys for c in index.get(k, [])]
    if not cands:
        return None
    want = (plan or "").lower() if (plan or "").upper() in ("DIRECT", "REGULAR") else None
    want = want or _plan_marker(amfi_name) or "regular"
    for slug, etm_id, slug_plan in sorted(cands):
        if slug_plan == want or (want == "regular" and slug_plan is None):
            return slug, etm_id
    return min(cands)[:2]


def build_mapping(dry_run: bool = False, only_unmapped: bool = False) -> int:
    """Match every active AMFI scheme to its ETMoney page (`_match`) and store it
    in mf_scheme_master.etm_slug / etm_id. `only_unmapped` (the daily path) maps
    just the schemes without one — new launches, names a past sitemap miss left
    behind. A full run also CLEARS a mapping the rule no longer supports, and when
    a scheme's page changes to a different fund (or to none), the holdings taken
    from the old page move to mf_holdings_quarantine and the scheme is re-checked
    first on the next scrape.
    """
    _ensure_columns()
    print("Fetching ETMoney sitemaps…")
    etm = fetch_etm_sitemap_urls()
    print(f"\nTotal ETMoney MF URLs: {len(etm)}")
    index = _etm_index(etm)

    schemes = read_sql(f"""
        SELECT scheme_code, scheme_name, plan_type, etm_slug
        FROM mf_scheme_master
        WHERE active = 1
          AND (data_quality IS NULL OR data_quality = 'TRUSTED')
          {"AND etm_id IS NULL" if only_unmapped else ""}
    """)
    print(f"Active TRUSTED AMFI schemes{' without a mapping' if only_unmapped else ''}: {len(schemes)}")

    updates = []        # (etm_slug, etm_id, scheme_code); slug/id None = clear
    moved_fund = []     # scheme_codes whose page is now a different fund, or none
    for row in schemes.itertuples(index=False):
        hit = _match(row.scheme_name, index, row.plan_type)
        old = row.etm_slug if isinstance(row.etm_slug, str) else None
        if (hit[0] if hit else None) == old:
            continue
        updates.append((hit[0] if hit else None, hit[1] if hit else None, row.scheme_code))
        if old and not (hit and _identity_keys(hit[0]) & _identity_keys(old)):
            moved_fund.append(row.scheme_code)

    moved = set(moved_fund)
    n_new = sum(1 for u in updates if u[0] and u[2] not in moved)
    n_cleared = sum(1 for u in updates if u[0] is None)
    print(f"\nMatching results: {len(schemes) - len(updates)} unchanged · {n_new} newly mapped / same-fund "
          f"slug updates · {len(moved_fund)} moved to another fund or none ({n_cleared} cleared)")

    if dry_run:
        print("--dry-run: not saving.")
        return 0

    with get_db() as conn:
        conn.executemany(
            "UPDATE mf_scheme_master SET etm_slug = ?, etm_id = ?, etm_checked_at = NULL WHERE scheme_code = ?",
            updates,
        )
        n_q = _quarantine_holdings(conn, moved_fund, "etm mapping pointed at another fund's page")
    print(f"\nWrote {len(updates)} mapping changes; {n_q} holding rows quarantined")
    return len(updates)


def _quarantine_holdings(conn, scheme_codes: list[str], reason: str, after: str | None = None) -> int:
    """Move the mf_holdings / mf_sector_allocation rows of `scheme_codes` (only those
    dated after `after`, if given) into the quarantine twins. Returns holding rows moved."""
    n = 0
    for i in range(0, len(scheme_codes), 500):
        chunk = scheme_codes[i:i + 500]
        marks = ",".join("?" * len(chunk)) + ")" + (" AND as_of_date > ?" if after else "")
        args = [*chunk, after] if after else chunk
        for table, cols in (
            ("mf_holdings", "scheme_code, as_of_date, holding_rank, instrument_type, sid, isin, "
                            "instrument_name, sector, pct_of_aum, market_value_cr"),
            ("mf_sector_allocation", "scheme_code, as_of_date, sector, pct_of_aum"),
        ):
            cur = conn.execute(
                f"""INSERT OR REPLACE INTO {table}_quarantine ({cols}, _q_failed_gate, _q_reason, _q_quarantined_at)
                    SELECT {cols}, 'etm_mapping', ?, datetime('now') FROM {table} WHERE scheme_code IN ({marks}""",
                [reason, *args],
            )
            if table == "mf_holdings":
                n += cur.rowcount
            conn.execute(f"DELETE FROM {table} WHERE scheme_code IN ({marks}", args)
    return n


# ─────────────────────── Holdings page parser ───────────────────────


def _parse_holdings_page(html: str) -> tuple[list[dict], list[dict], str | None]:
    """Parse an ETMoney `/portfolio-details/<id>` page.

    Holdings table structure (richer than the main detail page):
        <table class="table">
            <thead>
                <tr><th>Stocks</th><th>Sectors</th><th>% of holding</th><th>Value</th>...
            <tbody>
                <tr>
                    <td class="company-name"><a href="/stocks/hdfc-bank-ltd/2705">HDFC Bank Ltd.</a></td>
                    <td>Financial</td>
                    <td>7.94 %</td>
                    <td>₹4,932 Cr</td>
                    ...

    Sector allocation comes from a different section labeled "Sector
    Allocation" with `<div class="holding-list">` rows or another table.

    Returns ([{rank, instrument_name, pct_of_aum, sector, market_value_cr, etm_stock_id}],
             [{sector, pct_of_aum}], as_of_date).
    """
    soup = BeautifulSoup(html, "html.parser")
    holdings: list[dict] = []
    sectors_per_holding: dict[str, float] = {}   # sector → cumulative pct from holdings
    sectors: list[dict] = []
    as_of = None

    # ── Holdings table: look for <table> with "Stocks" + "% of holding" headers ──
    for table in soup.find_all("table"):
        head = table.find("thead")
        if not head:
            continue
        headers = [th.get_text(strip=True).lower() for th in head.find_all("th")]
        if not any("stock" in h for h in headers) or not any("% of" in h or "holding" in h for h in headers):
            continue
        # Header indices
        try:
            idx_stock  = next(i for i, h in enumerate(headers) if "stock" in h)
            idx_sector = next((i for i, h in enumerate(headers) if "sector" in h), None)
            idx_pct    = next(i for i, h in enumerate(headers) if "% of" in h or "% holding" in h or "% holdings" in h)
            idx_value  = next((i for i, h in enumerate(headers) if h in ("value", "₹ value", "value (cr)")), None)
        except StopIteration:
            continue
        body = table.find("tbody")
        if not body:
            continue
        for rank, tr in enumerate(body.find_all("tr"), 1):
            cells = tr.find_all("td")
            if len(cells) <= max(idx_stock, idx_pct):
                continue
            stock_cell = cells[idx_stock]
            stock_name = stock_cell.get_text(" ", strip=True)
            if not stock_name:
                continue
            pct_text = cells[idx_pct].get_text(strip=True)
            try:
                pct = float(re.sub(r"[^\d.\-]", "", pct_text))
            except ValueError:
                continue
            sector = cells[idx_sector].get_text(strip=True) if idx_sector is not None and len(cells) > idx_sector else None
            mv_cr = None
            if idx_value is not None and len(cells) > idx_value:
                val_text = cells[idx_value].get_text(strip=True)
                try:
                    mv_cr = float(re.sub(r"[^\d.]", "", val_text))
                except ValueError:
                    pass
            etm_stock_id = None
            link = stock_cell.find("a", href=re.compile(r"^/stocks/[^/]+/\d+$"))
            if link:
                m = re.search(r"/stocks/[^/]+/(\d+)$", link["href"])
                if m:
                    etm_stock_id = int(m.group(1))
            holdings.append({
                "rank":            rank,
                "instrument_name": stock_name,
                "pct_of_aum":      pct,
                "sector":          sector,
                "market_value_cr": mv_cr,
                "etm_stock_id":    etm_stock_id,
            })
            # Aggregate sector exposure from per-holding sector tag
            if sector:
                sectors_per_holding[sector] = sectors_per_holding.get(sector, 0) + pct
        if holdings:
            break

    # Sector allocation: derive purely from the per-holding sector column.
    # Explicit "Sector Allocation" block search was attempted first but ETMoney's
    # page often places a holdings table immediately after that label, which the
    # naive find_next() pattern matched as the wrong block (giving stock names
    # instead of sectors). Per-holding aggregation is more robust and the per-row
    # sector tag is always present on equity funds.
    if sectors_per_holding:
        sectors = [{"sector": s, "pct_of_aum": round(p, 2)}
                   for s, p in sorted(sectors_per_holding.items(), key=lambda x: -x[1])]

    # ── Disclosure date ──
    # ETMoney writes "as on Sep 30, 2026" (month first) in the section headers; the
    # day-first pattern alone never matched it, so every row carried the scrape date.
    # "as on" first: the AMC blurb says "AUM … as of March 31, 2026".
    date_pat = r"\s+(\d{1,2}\s+[A-Za-z]+,?\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})"
    m = re.search(r"as\s+on" + date_pat, html, re.I) or re.search(r"as\s+of" + date_pat, html, re.I)
    if m:
        for fmt in ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y"):
            try:
                as_of = datetime.strptime(re.sub(r",", "", m.group(1)), fmt).date().isoformat()
                break
            except ValueError:
                continue

    return holdings, sectors, as_of


class RateLimited(Exception):
    """Raised when we suspect ETMoney is rate-limiting us."""


def fetch_holdings(etm_slug: str, etm_id: int) -> tuple[list[dict], list[dict], str | None]:
    """GET the portfolio-details URL with retry + exponential backoff.

    Raises RateLimited on suspected blocks (HTTP 429 / 503 / very-short HTML).
    Returns ([], [], None) on legit empty responses (404, valid but no holdings).
    """
    url = f"https://www.etmoney.com/mutual-funds/{etm_slug}/portfolio-details/{etm_id}"
    last_err: str | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = _get(url, timeout=TIMEOUT)
            if r.status_code == 200:
                # ETMoney sometimes returns 200 with a "blocked" page (~5KB).
                # Real holdings pages are >100KB.
                if len(r.text) < 10_000:
                    raise RateLimited(f"200 but only {len(r.text)} bytes — suspected soft-block")
                return _parse_holdings_page(r.text)
            if r.status_code == 404:
                return [], [], None
            if r.status_code in (429, 503):
                raise RateLimited(f"HTTP {r.status_code}")
            last_err = f"HTTP {r.status_code}"
        except requests.exceptions.Timeout:
            last_err = "Timeout"
        except requests.exceptions.RequestException as e:
            last_err = str(e)[:60]
        # Exponential backoff before retry
        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF_BASE * (3 ** attempt))
    # Non-rate-limit failure (e.g. real server error or DNS) — return empty
    return [], [], None


# ─────────────────────── Batch ingest ───────────────────────


def write_portfolio(sibling_codes: list[str], as_of_date: str, holdings: list[dict], sectors: list[dict],
                    name_to_sid: dict, portfolio_dated: bool = True) -> tuple[int, int]:
    """Write one fund's portfolio for every sibling AMFI scheme_code (Direct/Regular and
    payout options share it) — the one write path for every holdings route. holdings:
    [{rank, instrument_name, pct_of_aum, sector, market_value_cr, instrument_type?}]
    (instrument_type defaults to EQUITY); sectors: [{sector, pct_of_aum}]. Returns
    (holding rows, sector rows) written."""
    all_holdings_rows = []
    all_sector_rows = []
    for sc in sibling_codes:
        for h in holdings:
            # Match each holding to our stocks.sid by name (best-effort).
            sid = name_to_sid.get(_normalise(h["instrument_name"]))
            all_holdings_rows.append((
                sc, as_of_date, h["rank"],
                h.get("instrument_type") or "EQUITY",
                sid, None,                      # no per-holding ISIN on either page
                h["instrument_name"],
                h.get("sector"),
                h["pct_of_aum"],
                h.get("market_value_cr"),
            ))
        for sec in sectors:
            all_sector_rows.append((sc, as_of_date, sec["sector"], sec["pct_of_aum"]))

    with get_db() as conn:
        # Rows dated after the page's own portfolio date are scrape-date stamps (the
        # date never parsed before 2026-10-10); left in place they outrank it.
        if portfolio_dated:
            _quarantine_holdings(conn, sibling_codes, "stamped with the scrape date, not the portfolio date",
                                 after=as_of_date)
        # Replace this portfolio date whole: a re-check of the same month with
        # fewer holdings must not leave the old tail ranks behind.
        for sc in sibling_codes:
            conn.execute(
                "DELETE FROM mf_holdings WHERE scheme_code=? AND as_of_date=?",
                (sc, as_of_date),
            )
            conn.execute(
                "DELETE FROM mf_sector_allocation WHERE scheme_code=? AND as_of_date=?",
                (sc, as_of_date),
            )
        conn.executemany(
            """INSERT OR REPLACE INTO mf_holdings
               (scheme_code, as_of_date, holding_rank, instrument_type,
                sid, isin, instrument_name, sector, pct_of_aum, market_value_cr)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            all_holdings_rows,
        )
        if all_sector_rows:
            conn.executemany(
                """INSERT OR REPLACE INTO mf_sector_allocation
                   (scheme_code, as_of_date, sector, pct_of_aum) VALUES (?,?,?,?)""",
                all_sector_rows,
            )
    return len(all_holdings_rows), len(all_sector_rows)


def _mark_checked(scheme_codes: list[str]) -> None:
    """Stamp mf_scheme_master.etm_checked_at — the rotation order for the next run."""
    if scheme_codes:
        with get_db() as conn:
            conn.executemany(
                "UPDATE mf_scheme_master SET etm_checked_at = datetime('now') WHERE scheme_code = ?",
                [(sc,) for sc in scheme_codes],
            )


def scrape(limit: int | None = None, scheme: str | None = None, dry_run: bool = False,
           recheck_days: int = 0, max_minutes: float | None = None, without_groww: bool = False) -> int:
    """Scrape ETMoney holdings for mapped non-debt schemes, least-recently-checked
    first: never-checked first of all, funds with no holdings at all ahead of the rest (new
    launches have no composite_score and would otherwise wait out the whole backlog), then
    by composite_score. Returns funds written.

    recheck_days > 0 skips funds checked within that many days; max_minutes stops
    the run when the time is up (the rest continue next run); without_groww keeps to
    funds the Groww route (the primary) has no page for.
    """
    where = ["sm.etm_id IS NOT NULL", "sm.active = 1", "(sm.data_quality IS NULL OR sm.data_quality = 'TRUSTED')",
             "COALESCE(sm.category_norm, '') NOT LIKE 'Debt%'"]
    params: list = []
    if scheme:
        where = ["sm.scheme_code = ?"]
        params = [scheme]
    elif without_groww:
        where.append("COALESCE(sm.groww_slug, '') = ''")
    having = ""
    if recheck_days > 0:
        having = (f"HAVING MAX(sm.etm_checked_at IS NULL) = 1 "
                  f"OR MIN(sm.etm_checked_at) < datetime('now', '-{int(recheck_days)} days')")

    # Dedupe by etm_id — many AMFI scheme variants share the same ETMoney URL
    # (Direct + Regular + plan variants all have identical underlying holdings, so
    # we only need to fetch once per etm_id and propagate to siblings).
    schemes = read_sql(
        f"""SELECT sm.etm_id,
                   GROUP_CONCAT(DISTINCT sm.scheme_code) AS sibling_codes,
                   MIN(sm.etm_slug)             AS etm_slug,
                   MIN(sm.scheme_name)          AS scheme_name
            FROM mf_scheme_master sm
            LEFT JOIN mf_metrics m ON sm.scheme_code = m.scheme_code
            WHERE {' AND '.join(where)}
            GROUP BY sm.etm_id
            {having}
            ORDER BY MAX(sm.etm_checked_at IS NULL) DESC,
                     MIN(EXISTS (SELECT 1 FROM mf_holdings h WHERE h.scheme_code = sm.scheme_code)),
                     MIN(sm.etm_checked_at), MAX(m.composite_score) DESC NULLS LAST""",
        params=params,
    )
    if limit:
        schemes = schemes.head(limit)

    n_total_amfi_codes = sum(len(r.split(",")) for r in schemes["sibling_codes"])
    print(f"Target: {len(schemes)} distinct ETMoney URLs covering {n_total_amfi_codes} AMFI schemes")
    if dry_run:
        print("--dry-run: not scraping.")
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.time()
    n_ok = 0
    n_no_data = 0
    n_err = 0
    n_holdings_rows = 0
    n_sector_rows = 0

    # Build sid lookup once — map (etm_stock_id, instrument_name) to our sid.
    # We only have stockId in ETMoney's namespace; map by name normalisation
    # against stocks.name.
    stocks = read_sql("SELECT sid, name, ticker FROM stocks")
    name_to_sid = {_normalise(r["name"]): r["sid"] for _, r in stocks.iterrows()}

    consecutive_errors = 0
    over_budget = _http.time_budget("etmoney", max_minutes)

    for i, row in enumerate(schemes.itertuples(index=False), 1):
        if over_budget():
            print(f"  budget of {max_minutes} min reached after {i - 1} funds — "
                  f"rest continue next run (stalest-first)", flush=True)
            break
        sibling_codes = row.sibling_codes.split(",") if row.sibling_codes else []
        try:
            holdings, sectors, as_of = fetch_holdings(row.etm_slug, row.etm_id)
            consecutive_errors = 0
        except RateLimited as e:
            consecutive_errors += 1
            n_err += 1
            runlog.item_failed("etmoney holdings", row.etm_slug, f"rate limited: {e}", symptom="G")
            print(f"  [{i}] RATE-LIMITED ({e}) — pausing {ERROR_PAUSE_SECONDS}s before continuing", flush=True)
            time.sleep(ERROR_PAUSE_SECONDS if consecutive_errors >= ERROR_PAUSE_THRESHOLD else 60)
            continue
        except Exception as e:
            n_err += 1
            consecutive_errors += 1
            runlog.item_error("etmoney holdings", row.etm_slug, e)
            _mark_checked(sibling_codes)
            continue

        _mark_checked(sibling_codes)
        if not holdings:
            n_no_data += 1
            continue

        # Plan 0007 Phase 2 — Identity Gate. ETMoney URL slug must contain the
        # expected etm_slug (the mapping we built in mf_scheme_master). If the
        # response page has a different slug — possible if ETMoney redirects
        # closed schemes — the holdings belong to the WRONG fund.
        try:
            from validators.identity_check import verify_identity, quarantine_row, record_verdict
            # `as_of` (raw) carries the page url segment that fetch_holdings parsed.
            # Pass row.etm_slug as the expected_url_segment; verifier checks containment.
            page_id = f"etm_id={row.etm_id} slug={row.etm_slug}"
            v = verify_identity(
                row.scheme_name, page_id, source="etmoney",
                expected_url_segment=row.etm_slug,
            )
            if v.status == "WRONG_ENTITY":
                # Quarantine the holdings + sector rows for every sibling
                for sc in (row.sibling_codes.split(",") if row.sibling_codes else []):
                    for h in holdings:
                        quarantine_row(
                            source_table="mf_holdings",
                            row={
                                "scheme_code": sc,
                                "as_of_date": as_of or datetime.now().strftime("%Y-%m-%d"),
                                "holding_rank": h.get("rank"),
                                "instrument_type": "EQUITY",
                                "instrument_name": h.get("instrument_name"),
                                "sector": h.get("sector"),
                                "pct_of_aum": h.get("pct_of_aum"),
                                "market_value_cr": h.get("market_value_cr"),
                            },
                            sid=sc, datum_class="mf_holding",
                            verdict=v,
                        )
                n_no_data += 1  # treat as no_data from the caller's perspective
                continue
            elif v.status == "PASS":
                # Record verdict for the first sibling (covers the slug-level check)
                first_sib = (row.sibling_codes.split(",") if row.sibling_codes else [""])[0]
                if first_sib:
                    record_verdict(
                        sid=first_sib, source_table="mf_holdings",
                        source_key=f'{{"etm_id":{row.etm_id}}}',
                        datum_class="mf_holding", verdict=v,
                    )
        except Exception as e:
            import sys
            print(f"  ⚠ identity_check failed for etm_id={row.etm_id}: {e}", file=sys.stderr)

        as_of_date = as_of or datetime.now().strftime("%Y-%m-%d")

        n_h, n_s = write_portfolio(sibling_codes, as_of_date, holdings, sectors, name_to_sid,
                                   portfolio_dated=bool(as_of))
        n_holdings_rows += n_h
        n_sector_rows += n_s
        n_ok += 1

        if i % 25 == 0:
            elapsed = time.time() - t0
            rate = i / elapsed
            eta_min = (len(schemes) - i) / rate / 60 if rate > 0 else 0
            print(f"  [{i}/{len(schemes)}]  ok={n_ok} no_data={n_no_data} err={n_err}  "
                  f"holdings={n_holdings_rows} sectors={n_sector_rows}  "
                  f"rate={rate:.2f}/s  ETA={eta_min:.0f}min", flush=True)

        # Long pause between chunks — gives any rolling rate limit a chance to reset
        if i % CHUNK_SIZE == 0:
            print(f"  [chunk-pause {CHUNK_PAUSE}s after {i} requests]", flush=True)
            time.sleep(CHUNK_PAUSE)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed/60:.1f}min.")
    print(f"  schemes: {n_ok} ok · {n_no_data} no_data · {n_err} err")
    print(f"  rows:    {n_holdings_rows:,} holdings · {n_sector_rows:,} sector allocations")
    return n_ok


def compute(max_minutes=_http.HOST_BUDGET) -> int:
    """Daily pipeline step. Primary: the Groww route (sources.mf_holdings_groww). Fallback:
    for funds Groww has no page for, map schemes that have no ETMoney page yet, then
    re-check the funds due (RECHECK_DAYS), stalest first, until the host budget is spent.
    Returns funds written by both routes."""
    from sources import mf_holdings_groww
    n_groww = mf_holdings_groww.compute()
    status()
    try:
        build_mapping(only_unmapped=True)
    except RuntimeError as e:   # no sitemap readable — still refresh the funds already mapped
        runlog.item_failed("etmoney sitemap", "mapping", str(e), symptom="A")
    if max_minutes is _http.HOST_BUDGET:
        max_minutes = _http.host("etmoney")[1]["budget_min"]
    return n_groww + scrape(recheck_days=RECHECK_DAYS, max_minutes=max_minutes, without_groww=True)


def status() -> None:
    counts = read_sql("""
        SELECT
            COUNT(DISTINCT scheme_code) AS schemes_with_holdings,
            COUNT(*) AS total_rows,
            MIN(as_of_date) AS oldest,
            MAX(as_of_date) AS newest
        FROM mf_holdings
    """).iloc[0]
    print(f"mf_holdings status:")
    print(f"  schemes_with_holdings: {counts['schemes_with_holdings']}")
    print(f"  total_rows:            {counts['total_rows']}")
    print(f"  date_range:            {counts['oldest']} → {counts['newest']}")
    mapped = read_sql(
        "SELECT COUNT(*) FROM mf_scheme_master WHERE etm_id IS NOT NULL AND active=1"
    ).iloc[0, 0]
    print(f"  schemes mapped to ETMoney: {mapped}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--build-map", action="store_true", help="Build AMFI ↔ ETMoney mapping")
    p.add_argument("--scrape", action="store_true", help="Scrape holdings for mapped schemes")
    p.add_argument("--limit", type=int, help="Cap number of schemes scraped (smoke test)")
    p.add_argument("--scheme", help="Single scheme code (smoke test)")
    p.add_argument("--status", action="store_true", help="Report current ingest state")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only-unmapped", action="store_true",
                   help="--build-map: map only schemes without a page (leave existing mappings alone)")
    p.add_argument("--recheck-days", type=int, default=0,
                   help="Skip funds checked within N days (the pipeline uses RECHECK_DAYS)")
    p.add_argument("--max-minutes", type=float, help="Stop after N minutes (the pipeline uses the host budget)")
    args = p.parse_args()

    if args.status or (not args.build_map and not args.scrape and not args.scheme):
        status()
    if args.build_map:
        build_mapping(dry_run=args.dry_run, only_unmapped=args.only_unmapped)
    if args.scrape or args.scheme:
        scrape(limit=args.limit, scheme=args.scheme, dry_run=args.dry_run,
               recheck_days=args.recheck_days, max_minutes=args.max_minutes)
