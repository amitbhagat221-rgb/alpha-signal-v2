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
"""

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db, read_sql

# ── Rate-limit policy ──
# ETMoney is a free aggregator. They tolerate steady-state polite traffic but
# rate-limit aggressive scrapers. Empirical defaults:
DELAY = 2.5              # base delay between requests (~24 req/min steady state)
TIMEOUT = 20
CHUNK_SIZE = 100         # request count between long pauses
CHUNK_PAUSE = 30         # seconds to pause between chunks (lets any soft-limit reset)
MAX_RETRIES = 3
BACKOFF_BASE = 5         # 5s, 15s, 45s on retries
ERROR_PAUSE_THRESHOLD = 5  # consecutive errors → long pause
ERROR_PAUSE_SECONDS = 300  # 5 min if we hit rate-limit territory

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

SITEMAPS = [
    "https://www.etmoney.com/mf-schemes-sitemap.xml",
    "https://www.etmoney.com/mf-regular-schemes-sitemap.xml",
]
PORTFOLIO_SITEMAP = "https://www.etmoney.com/mf-regular-schemes-portfolio-details-sitemap.xml"


def _ensure_columns():
    """Add etm_slug / etm_id columns to mf_scheme_master if absent."""
    with get_db() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(mf_scheme_master)").fetchall()]
        if "etm_slug" not in cols:
            conn.execute("ALTER TABLE mf_scheme_master ADD COLUMN etm_slug TEXT")
            print("  Added etm_slug column")
        if "etm_id" not in cols:
            conn.execute("ALTER TABLE mf_scheme_master ADD COLUMN etm_id INTEGER")
            print("  Added etm_id column")


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


def _identity_tokens(s: str) -> set[str]:
    """Identity tokens — fund-name signature WITHOUT plan/option indicators.
    'SBI CONTRA FUND - DIRECT PLAN - GROWTH' → {sbi, contra}
    'sbi-contra-direct-plan-growth' → {sbi, contra}
    Both sides match by 'who is this fund' rather than 'which variant'."""
    raw = re.findall(r"[a-z0-9]+", (s or "").lower())
    return {
        t for t in raw
        if t not in _STOP_TOKENS
        and t not in _PLAN_TOKENS
        and t not in _OPTION_TOKENS
        and len(t) > 1
    }


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
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"    HTTP {r.status_code} — skipping")
            continue
        matches = re.findall(
            r"<loc>https://www\.etmoney\.com/mutual-funds/([^/<]+)/(\d+)</loc>",
            r.text,
        )
        for slug, etm_id in matches:
            norm = _normalise_etm_slug(slug)
            out[norm] = (slug, int(etm_id))
        print(f"    {len(matches)} URLs (cumulative unique: {len(out)})")
    return out


def build_mapping(dry_run: bool = False) -> int:
    """Match every AMFI scheme to its ETMoney URL.

    Strategy (in order):
      1. Exact normalised-name match (fast path for clean cases)
      2. Token-set match — ETMoney tokens ⊂ AMFI tokens (after stop-word filter).
         Handles the "fund/plan/option" word-order divergence that
         substring-matching missed (e.g. SBI Contra, HDFC ELSS).

    Stores result in mf_scheme_master.etm_slug / etm_id.
    """
    _ensure_columns()
    print("Fetching ETMoney sitemaps…")
    etm = fetch_etm_sitemap_urls()
    print(f"\nTotal ETMoney MF URLs: {len(etm)}")

    # Pre-tokenise ETM keys once; store (slug, etm_id, identity_tokens, plan).
    # Identity tokens strip plan/option markers so 'sbi-contra-direct-plan-growth'
    # and 'sbi-contra-fund' both yield {sbi, contra}; plan ('direct' or 'regular'
    # or None) tracked separately.
    etm_tokens: list[tuple[str, int, frozenset[str], str | None, int]] = []
    for norm, (slug, etm_id) in etm.items():
        toks = _identity_tokens(slug)
        if len(toks) >= 2:
            etm_tokens.append((slug, etm_id, frozenset(toks), _plan_marker(slug), len(toks)))
    # Sort by token-count desc so longest (most specific) ETM key wins;
    # within same length, prefer plan-bearing slugs (Direct over bare) so AMFI
    # Direct schemes pick the direct slug.
    etm_tokens.sort(key=lambda x: (x[4], 1 if x[3] else 0), reverse=True)

    schemes = read_sql("""
        SELECT scheme_code, scheme_name, plan_type, option_type
        FROM mf_scheme_master
        WHERE active = 1
          AND (data_quality IS NULL OR data_quality = 'TRUSTED')
    """)
    print(f"Active TRUSTED AMFI schemes: {len(schemes)}")

    matches = []
    n_exact = 0
    n_token = 0
    n_miss = 0

    for _, row in schemes.iterrows():
        scheme_code = row["scheme_code"]
        amfi_name = row["scheme_name"]
        amfi_norm = _normalise(amfi_name)

        slug_id = None

        # 1. Exact match on full normalised name
        if amfi_norm in etm:
            slug_id = etm[amfi_norm]
            n_exact += 1
        else:
            # 2. Identity-token subset (ETM identity ⊆ AMFI identity).
            #    Plan check: AMFI Direct prefers an ETM 'direct' slug; AMFI
            #    Regular prefers a bare slug (no plan token in ETM). If no
            #    plan-matched ETM exists, fall back to any subset match —
            #    holdings are identical across plans so it's still correct.
            amfi_toks = _identity_tokens(amfi_name)
            # Pre-2013 AMFI names lack 'Direct'/'Regular' — those are legacy
            # Regular plans, so default unmarked → 'regular'.
            amfi_plan = _plan_marker(amfi_name) or "regular"
            if amfi_toks:
                best_plan = None
                best_any = None
                for slug, etm_id, etm_toks, etm_plan, n_toks in etm_tokens:
                    if not (etm_toks <= amfi_toks):
                        continue
                    if best_any is None:
                        best_any = (slug, etm_id)
                    if etm_plan == amfi_plan and best_plan is None:
                        best_plan = (slug, etm_id)
                    # AMFI Regular ↔ ETM bare slug (no plan token)
                    if amfi_plan == "regular" and etm_plan is None and best_plan is None:
                        best_plan = (slug, etm_id)
                    if best_plan:
                        break
                slug_id = best_plan or best_any
                if slug_id:
                    n_token += 1

            if not slug_id:
                n_miss += 1

        if slug_id:
            matches.append((slug_id[0], slug_id[1], scheme_code))

    print(f"\nMatching results:")
    print(f"  exact:         {n_exact}")
    print(f"  token-subset:  {n_token}")
    print(f"  no match:      {n_miss}")
    print(f"  total mapped:  {len(matches)}")
    print(f"  distinct ETM URLs: {len(set((m[0], m[1]) for m in matches))}")

    if dry_run:
        print("--dry-run: not saving.")
        return 0

    with get_db() as conn:
        cur = conn.executemany(
            "UPDATE mf_scheme_master SET etm_slug = ?, etm_id = ? WHERE scheme_code = ?",
            matches,
        )
    print(f"\nWrote {len(matches)} mappings to mf_scheme_master.etm_slug / etm_id")
    return len(matches)


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
    m = re.search(r"(?:as\s+on|as\s+of|portfolio\s+as\s+on)\s+(\d{1,2}\s+\w+,?\s+\d{4})", html, re.I)
    if m:
        for fmt in ("%d %b %Y", "%d %B %Y"):
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
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
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


def scrape(limit: int | None = None, scheme: str | None = None,
           top_score_first: bool = True, dry_run: bool = False,
           skip_fresh_days: int = 0) -> int:
    """Scrape ETMoney holdings for all mapped schemes. Returns rows written.

    If skip_fresh_days > 0, skip etm_ids that already have any sibling with
    holdings newer than N days — useful for incremental runs after a remapping.
    """
    where = ["sm.etm_id IS NOT NULL", "sm.active = 1", "(sm.data_quality IS NULL OR sm.data_quality = 'TRUSTED')"]
    params: list = []
    if scheme:
        where = ["sm.scheme_code = ?"]
        params = [scheme]
    if skip_fresh_days > 0:
        where.append(
            f"NOT EXISTS (SELECT 1 FROM mf_holdings h "
            f"WHERE h.scheme_code = sm.scheme_code "
            f"AND h.as_of_date >= date('now','-{skip_fresh_days} days'))"
        )

    # Prioritise by composite_score so the most-researched funds are covered first.
    # Then dedupe by etm_id — many AMFI scheme variants share the same ETMoney URL
    # (Direct + Regular + plan variants all have identical underlying holdings, so
    # we only need to fetch once per etm_id and propagate to siblings).
    join_sql = "LEFT JOIN mf_metrics m ON sm.scheme_code = m.scheme_code" if top_score_first else ""
    order_sql = "ORDER BY MAX(m.composite_score) DESC NULLS LAST" if top_score_first else ""

    schemes = read_sql(
        f"""SELECT sm.etm_id,
                   GROUP_CONCAT(sm.scheme_code) AS sibling_codes,
                   MIN(sm.etm_slug)             AS etm_slug,
                   MIN(sm.scheme_name)          AS scheme_name
            FROM mf_scheme_master sm
            {join_sql}
            WHERE {' AND '.join(where)}
            GROUP BY sm.etm_id
            {order_sql}""",
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

    for i, row in enumerate(schemes.itertuples(index=False), 1):
        try:
            holdings, sectors, as_of = fetch_holdings(row.etm_slug, row.etm_id)
            consecutive_errors = 0
        except RateLimited as e:
            consecutive_errors += 1
            n_err += 1
            print(f"  [{i}] RATE-LIMITED ({e}) — pausing {ERROR_PAUSE_SECONDS}s before continuing", flush=True)
            time.sleep(ERROR_PAUSE_SECONDS if consecutive_errors >= ERROR_PAUSE_THRESHOLD else 60)
            continue
        except Exception as e:
            n_err += 1
            consecutive_errors += 1
            time.sleep(DELAY)
            continue

        if not holdings:
            n_no_data += 1
            time.sleep(DELAY)
            continue

        as_of_date = as_of or datetime.now().strftime("%Y-%m-%d")
        sibling_codes = row.sibling_codes.split(",") if row.sibling_codes else []

        # Match each holding to our stocks.sid by name (best-effort).
        # Build holdings_rows for EVERY sibling AMFI scheme_code (same underlying
        # fund holdings — Direct/Regular plans share portfolio).
        all_holdings_rows = []
        all_sector_rows = []
        for sc in sibling_codes:
            for h in holdings:
                sid = name_to_sid.get(_normalise(h["instrument_name"]))
                all_holdings_rows.append((
                    sc, as_of_date, h["rank"],
                    "EQUITY",                       # ETMoney portfolio-details = equity holdings
                    sid, None,                      # isin not in scrape
                    h["instrument_name"],
                    h.get("sector"),
                    h["pct_of_aum"],
                    h.get("market_value_cr"),
                ))
            for s in sectors:
                all_sector_rows.append((sc, as_of_date, s["sector"], s["pct_of_aum"]))

        with get_db() as conn:
            for sc in sibling_codes:
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

        n_holdings_rows += len(all_holdings_rows)
        n_sector_rows += len(all_sector_rows)
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
        else:
            time.sleep(DELAY)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed/60:.1f}min.")
    print(f"  schemes: {n_ok} ok · {n_no_data} no_data · {n_err} err")
    print(f"  rows:    {n_holdings_rows:,} holdings · {n_sector_rows:,} sector allocations")
    return n_ok


def compute() -> int:
    """PIPELINE_STEPS-friendly entry — incremental refresh."""
    status()
    # Re-fetch top-100 by score (monthly cadence is enough for AMFI-style 45d-lag data)
    return scrape(limit=100, top_score_first=True)


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
    p.add_argument("--skip-fresh-days", type=int, default=0,
                   help="Skip etm_ids whose holdings are newer than N days (incremental top-up)")
    args = p.parse_args()

    if args.status or (not args.build_map and not args.scrape and not args.scheme):
        status()
    if args.build_map:
        build_mapping(dry_run=args.dry_run)
    if args.scrape or args.scheme:
        scrape(limit=args.limit, scheme=args.scheme,
               dry_run=args.dry_run, skip_fresh_days=args.skip_fresh_days)
