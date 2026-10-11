"""
Alpha Signal v2 — MF holdings from Groww's public fund pages (primary route, 2026-10-10).

Why Groww: the ETMoney scrape (sources/mf_holdings_scrape.py, now the fallback) misses
whole AMCs (Groww, Taurus, NJ, Shriram, JioBlackRock, Unifi), closed-end ELSS series and
suspended overseas funds, and reads only the stock table. Groww's server-rendered fund page
`groww.in/mutual-funds/{slug}` carries the full latest portfolio — equity, debt, cash, fund
units, weights summing to 100% — plus the fund's Direct-Growth AMFI scheme_code and ISIN, in
`__NEXT_DATA__`. robots.txt allows these pages and disallows `/v1/api/*`: use the pages, never
the JSON API. Groww's terms forbid copying content into a database; Amit accepted that risk
2026-10-10 (ETMoney carries the same one). Research: docs/reference/data-playbook.md.

Identity is exact, not by name: a page is written only when its scheme_code or ISIN belongs
to the fund it was fetched for. A fund = the active schemes sharing (amc, scheme_name) — every
plan and payout option of one portfolio.

Mapping: sitemap slugs are matched to fund names with the strict same-fund rule
(mf_holdings_scrape._match); a fund the sitemap lacks gets a slug guessed from its name
('{name}-direct-growth' — closed-end series and suspended overseas funds resolve that way).
The slug is only a candidate until its page passes the identity check; a 404 or a page for
another fund sets groww_slug = '' (no Groww page: the ETMoney fallback covers it).

Renamed funds keep Groww slugs from their old names, so each run also fetches any sitemap
page no fund has claimed and links it by the AMFI code on the page (`discover`).

Rotation: each run visits funds never checked first, funds with no holdings at all ahead of
the rest, then the least-recently-checked, until the host budget is spent; a fund is due
again RECHECK_DAYS after its last check (mf_scheme_master.groww_checked_at), or after
STALE_RECHECK_DAYS while its portfolio is older than the month-end AMCs must have published.

Usage:
    python -m sources.mf_holdings_groww --map                  # match sitemap slugs to funds
    python -m sources.mf_holdings_groww --discover             # link unclaimed sitemap pages by AMFI code
    python -m sources.mf_holdings_groww --scrape --limit 3     # smoke test
    python -m sources.mf_holdings_groww --scheme 151917        # one fund (any of its scheme codes)
    python -m sources.mf_holdings_groww --scrape --recheck-days 14 --max-minutes 20   # = the daily route
"""

import argparse
import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import runlog
from db import get_db, read_sql
from sources import _http
from sources.mf_holdings_scrape import (_etm_index, _match, _normalise, _normalise_etm_slug,
                                        write_portfolio)

SITEMAP = "https://groww.in/mf-sitemap.xml"
PAGE = "https://groww.in/mutual-funds/{slug}"
RECHECK_DAYS = 14
STALE_RECHECK_DAYS = 3       # a fund behind the month AMCs must have published is due sooner
NO_PAGE = ""                 # groww_slug value: Groww has no page for this fund
# Sitemap slugs that no active fund can claim (code not in mf_scheme_master, or a second page
# for a fund that already has one): {slug: {"reason", "checked"}}, retried after UNCLAIMED_RETRY_DAYS.
UNCLAIMED_FILE = Path(__file__).resolve().parent.parent / "output" / "groww_unclaimed_slugs.json"
UNCLAIMED_RETRY_DAYS = 30
IST = ZoneInfo("Asia/Kolkata")

# The funds a user can browse (cockpit/mf.py `investable`): trusted, not an ETF, NAV in the last 30 days.
FUND_ROWS_SQL = """
    SELECT sm.scheme_code, sm.amc, sm.scheme_name, sm.isin_growth, sm.isin_div,
           sm.groww_slug, sm.groww_checked_at,
           EXISTS (SELECT 1 FROM mf_holdings h WHERE h.scheme_code = sm.scheme_code) AS has_holdings,
           (SELECT MAX(h.as_of_date) FROM mf_holdings h WHERE h.scheme_code = sm.scheme_code) AS last_portfolio,
           (SELECT MAX(m.composite_score) FROM mf_metrics m WHERE m.scheme_code = sm.scheme_code) AS score
    FROM mf_scheme_master sm
    WHERE sm.active = 1 AND (sm.data_quality IS NULL OR sm.data_quality = 'TRUSTED')
      AND COALESCE(sm.category_norm, '') NOT LIKE 'ETF /%'
      AND EXISTS (SELECT 1 FROM mf_nav_history n WHERE n.scheme_code = sm.scheme_code
                  AND n.nav_date >= date('now', '-30 days'))
"""


def _ensure_columns():
    """Add groww_slug / groww_checked_at to mf_scheme_master if absent."""
    with get_db() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(mf_scheme_master)").fetchall()]
        for col in ("groww_slug", "groww_checked_at"):
            if col not in cols:
                conn.execute(f"ALTER TABLE mf_scheme_master ADD COLUMN {col} TEXT")
                print(f"  Added {col} column")


def funds(scheme: str | None = None) -> pd.DataFrame:
    """One row per fund: amc, scheme_name, codes, isins, slug, never_checked, last_checked,
    has_holdings (every sibling has some), score, last_portfolio (oldest sibling's latest
    portfolio date; None if any has none). `scheme`: just the fund holding that code."""
    rows = read_sql(FUND_ROWS_SQL)
    if scheme:
        hit = rows[rows["scheme_code"] == str(scheme)]
        rows = rows.merge(hit[["amc", "scheme_name"]].drop_duplicates(), on=["amc", "scheme_name"])
    if rows.empty:
        return pd.DataFrame(columns=["amc", "scheme_name", "codes", "isins", "slug", "never_checked",
                                     "last_checked", "has_holdings", "score", "last_portfolio"])
    out = []
    for (amc, name), g in rows.groupby(["amc", "scheme_name"], sort=False):
        slugs = g["groww_slug"].dropna()
        out.append({
            "amc": amc, "scheme_name": name, "codes": sorted(g["scheme_code"].astype(str)),
            "isins": {i for i in pd.concat([g["isin_growth"], g["isin_div"]]).dropna() if i},
            "slug": slugs.iloc[0] if not slugs.empty else None,
            "never_checked": bool(g["groww_checked_at"].isna().any()),
            # dropna first: pandas cannot min() text mixed with NaN (a fund half its plans checked)
            "last_checked": g["groww_checked_at"].dropna().min() if g["groww_checked_at"].notna().any() else None,
            "has_holdings": bool(g["has_holdings"].all()), "score": g["score"].max(),
            "last_portfolio": g["last_portfolio"].dropna().min() if g["last_portfolio"].notna().all() else None,
        })
    return pd.DataFrame(out)


def expected_portfolio(today: date | None = None) -> str:
    """The latest month-end whose portfolio every AMC must have published by `today`
    (SEBI: within 10 days of month end)."""
    today = today or date.today()
    end = today.replace(day=1) - timedelta(days=1)
    if today.day <= 10:
        end = end.replace(day=1) - timedelta(days=1)
    return end.isoformat()


def _guess_slug(name: str) -> str:
    """Groww's slug shape for a fund's Direct-Growth page, from the plan-free scheme name."""
    s = re.sub(r"\([^)]*\)", " ", (name or "").lower()).replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") + "-direct-growth"


def fetch_sitemap_slugs() -> list[str]:
    """Every fund-page slug in Groww's MF sitemap; raises when it cannot be read."""
    r = _http.polite_request("GET", SITEMAP, check=False, retries=2, timeout=30)
    slugs = [loc.rsplit("/", 1)[1] for loc in re.findall(r"<loc>([^<]+)</loc>", r.text if r is not None else "")
             if "/mutual-funds/" in loc and loc.endswith("-growth")]
    if not slugs:
        raise RuntimeError(f"Groww MF sitemap unreadable (HTTP {getattr(r, 'status_code', None)})")
    return slugs


def map_slugs(dry_run: bool = False, slugs: list[str] | None = None) -> int:
    """Give every fund without a groww_slug a candidate: its strict sitemap match, else a
    guessed slug. Returns funds mapped."""
    _ensure_columns()
    slugs = slugs or fetch_sitemap_slugs()
    index = _etm_index({_normalise_etm_slug(s): (s, i) for i, s in enumerate(slugs)})
    todo = funds()
    todo = todo[todo["slug"].isna()]
    updates, n_sitemap = [], 0
    for f in todo.itertuples(index=False):
        hit = _match(f.scheme_name, index, "DIRECT")
        n_sitemap += hit is not None
        slug = hit[0] if hit else _guess_slug(f.scheme_name)
        updates += [(slug, code) for code in f.codes]
    print(f"Groww sitemap: {len(slugs)} fund pages · {len(todo)} funds without a slug → "
          f"{n_sitemap} matched in the sitemap, {len(todo) - n_sitemap} guessed")
    if updates and not dry_run:
        with get_db() as conn:
            conn.executemany("UPDATE mf_scheme_master SET groww_slug = ?, groww_checked_at = NULL "
                             "WHERE scheme_code = ?", updates)
    return len(todo)


def _load_unclaimed() -> dict:
    try:
        return json.loads(UNCLAIMED_FILE.read_text())
    except (OSError, ValueError):
        return {}


def discover(slugs: list[str], max_minutes: float | None = None, name_to_sid: dict | None = None) -> int:
    """Fetch the sitemap pages no fund has claimed and link each to its fund by AMFI code.
    Renamed funds keep the slug of their old name (HDFC Flexi Cap = hdfc-equity-fund-…,
    Parag Parikh Flexi Cap = parag-parikh-long-term-value-fund-…), which neither the name
    rule nor a guess finds. A page claims only a fund with no working page (slug NULL or
    NO_PAGE); its portfolio is written on the spot. Returns funds linked."""
    claimed = set(read_sql("SELECT DISTINCT groww_slug FROM mf_scheme_master "
                           "WHERE COALESCE(groww_slug, '') != ''")["groww_slug"])
    unclaimed = _load_unclaimed()
    retry = (date.today() - timedelta(days=UNCLAIMED_RETRY_DAYS)).isoformat()
    todo = [sl for sl in slugs if sl not in claimed and unclaimed.get(sl, {}).get("checked", "") < retry]
    print(f"Groww discovery: {len(todo)} sitemap pages not linked to a fund")
    if not todo:
        return 0
    master = read_sql("SELECT scheme_code, amc, scheme_name, groww_slug FROM mf_scheme_master WHERE active = 1")
    master["scheme_code"] = master["scheme_code"].astype(str)
    if name_to_sid is None:
        name_to_sid = {_normalise(r["name"]): r["sid"] for _, r in read_sql("SELECT sid, name FROM stocks").iterrows()}
    over_budget = _http.time_budget("groww", max_minutes)
    n_linked = 0
    for slug in todo:
        if over_budget():
            print("  discovery budget reached — rest continue next run", flush=True)
            break
        r = _http.polite_request("GET", PAGE.format(slug=slug), check=False, timeout=30)
        if getattr(r, "status_code", None) != 200:
            unclaimed[slug] = {"reason": f"HTTP {getattr(r, 'status_code', None)}", "checked": date.today().isoformat()}
            continue
        try:
            codes, isin, holdings, sectors, as_of = parse_page(r.text)
        except Exception as e:
            runlog.item_error("groww fund page", slug, e)
            continue
        hit = master[master["scheme_code"].isin(codes)]
        if hit.empty:
            unclaimed[slug] = {"reason": f"scheme {sorted(codes)} not in mf_scheme_master", "checked": date.today().isoformat()}
            continue
        fund = master[(master["amc"] == hit["amc"].iloc[0]) & (master["scheme_name"] == hit["scheme_name"].iloc[0])]
        if fund["groww_slug"].fillna(NO_PAGE).ne(NO_PAGE).any():
            unclaimed[slug] = {"reason": f"fund already has page {fund['groww_slug'].dropna().iloc[0]}",
                               "checked": date.today().isoformat()}
            continue
        fund_codes = sorted(fund["scheme_code"])
        if holdings and as_of:
            write_portfolio(fund_codes, as_of, holdings, sectors, name_to_sid)
        _mark(fund_codes, slug)
        unclaimed.pop(slug, None)
        n_linked += 1
    UNCLAIMED_FILE.write_text(json.dumps(unclaimed, indent=1, sort_keys=True))
    print(f"Groww discovery: {n_linked} funds linked by AMFI code")
    return n_linked


def _ist_date(stamp: str) -> str:
    """Groww's portfolio_date is IST midnight in UTC ('2026-09-29T18:30:00.000Z') → '2026-09-30'."""
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(IST).date().isoformat()


def parse_page(html: str) -> tuple[set[str], str | None, list[dict], list[dict], str | None]:
    """(scheme codes, ISIN, holdings, sector allocation, portfolio date) from a fund page.
    Raises ValueError when the page has no fund data (shape drift, not a missing fund).

    A stock row's sector is Groww's; any other row carries its instrument kind in the sector
    column ('Treasury Bills', 'Net Payables') — Groww tags T-bills 'Financial'. Sector
    allocation is the stock rows only, as the ETMoney route always was."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    data = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("mfServerSideData") if m else None
    if not data:
        raise ValueError("no mfServerSideData in __NEXT_DATA__")
    codes = {str(c) for c in (data.get("scheme_code"), data.get("direct_scheme_code")) if c}
    rows = sorted((h for h in data.get("holdings") or [] if h.get("corpus_per") is not None),
                  key=lambda h: -h["corpus_per"])
    holdings, by_sector = [], {}
    for rank, h in enumerate(rows, 1):
        nature = (h.get("nature_name") or "OTHER").upper()
        equity = nature == "EQUITY"
        sector = h.get("sector_name") if equity else h.get("instrument_name")
        holdings.append({"rank": rank, "instrument_name": h.get("company_name") or h.get("instrument_name"),
                         "pct_of_aum": round(h["corpus_per"], 4), "sector": sector,
                         "market_value_cr": h.get("market_value"), "instrument_type": nature})
        if equity and sector:
            by_sector[sector] = by_sector.get(sector, 0) + h["corpus_per"]
    sectors = [{"sector": k, "pct_of_aum": round(v, 2)} for k, v in sorted(by_sector.items(), key=lambda x: -x[1])]
    dates = [h["portfolio_date"] for h in rows if h.get("portfolio_date")]
    return codes, data.get("isin"), holdings, sectors, (_ist_date(max(dates)) if dates else None)


def _mark(codes: list[str], slug: str | None = None) -> None:
    """Stamp groww_checked_at for a fund's codes; `slug` (e.g. NO_PAGE) replaces its slug too."""
    with get_db() as conn:
        if slug is None:
            conn.executemany("UPDATE mf_scheme_master SET groww_checked_at = datetime('now') WHERE scheme_code = ?",
                             [(c,) for c in codes])
        else:
            conn.executemany("UPDATE mf_scheme_master SET groww_slug = ?, groww_checked_at = datetime('now') "
                             "WHERE scheme_code = ?", [(slug, c) for c in codes])


def scrape(limit: int | None = None, scheme: str | None = None, recheck_days: int = 0,
           max_minutes: float | None = None, dry_run: bool = False) -> int:
    """Fetch the due funds' pages and write their portfolios. Returns funds written; raises
    when pages were fetched and every one failed."""
    _ensure_columns()
    todo = funds(scheme)
    todo = todo[todo["slug"].notna() & (todo["slug"] != NO_PAGE)]
    if recheck_days > 0 and not scheme:
        now = pd.Timestamp.now(tz="UTC")
        cutoff = (now - pd.Timedelta(days=recheck_days)).strftime("%Y-%m-%d %H:%M:%S")
        stale_cutoff = (now - pd.Timedelta(days=STALE_RECHECK_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        behind = todo["last_portfolio"].fillna("") < expected_portfolio()
        todo = todo[todo["never_checked"] | (todo["last_checked"] < cutoff)
                    | (behind & (todo["last_checked"] < stale_cutoff))]
    todo = todo.assign(_last=todo["last_checked"].fillna("")).sort_values(
        ["never_checked", "has_holdings", "_last", "score"], ascending=[False, True, True, False],
        na_position="last", kind="mergesort")
    if limit:
        todo = todo.head(limit)
    print(f"Groww: {len(todo)} funds due ({sum(len(c) for c in todo['codes'])} AMFI schemes)")
    if dry_run or todo.empty:
        return 0

    stocks = read_sql("SELECT sid, name FROM stocks")
    name_to_sid = {_normalise(r["name"]): r["sid"] for _, r in stocks.iterrows()}
    over_budget = _http.time_budget("groww", max_minutes)
    n_ok = n_none = n_wrong = n_empty = n_err = n_rows = 0
    for i, f in enumerate(todo.itertuples(index=False), 1):
        if over_budget():
            print(f"  budget of {max_minutes} min reached after {i - 1} funds — rest continue next run", flush=True)
            break
        r = _http.polite_request("GET", PAGE.format(slug=f.slug), check=False, timeout=30)
        status = getattr(r, "status_code", None)
        if status == 404:
            n_none += 1
            _mark(f.codes, NO_PAGE)
            continue
        if status != 200:
            n_err += 1
            runlog.item_failed("groww fund page", f.slug, f"HTTP {status}", symptom="A" if status == 403 else "B")
            _mark(f.codes)
            continue
        try:
            codes, isin, holdings, sectors, as_of = parse_page(r.text)
        except Exception as e:
            n_err += 1
            runlog.item_error("groww fund page", f.slug, e)
            _mark(f.codes)
            continue
        if not (codes & set(f.codes) or (isin and isin in f.isins)):
            # A guessed or name-matched slug that is really another fund's page.
            n_wrong += 1
            runlog.note(f"groww page {f.slug} is scheme {sorted(codes)}, not {f.scheme_name}", "WARN",
                        slug=f.slug, page_codes=sorted(codes), fund_codes=f.codes)
            _mark(f.codes, NO_PAGE)
            continue
        if not holdings or not as_of:
            n_empty += 1
            _mark(f.codes)
            continue
        n_h, _ = write_portfolio(f.codes, as_of, holdings, sectors, name_to_sid)
        _mark(f.codes)
        n_ok += 1
        n_rows += n_h
        if i % 25 == 0:
            print(f"  [{i}/{len(todo)}] ok={n_ok} no_page={n_none} wrong={n_wrong} empty={n_empty} err={n_err}",
                  flush=True)
    print(f"Groww done: {n_ok} written ({n_rows:,} rows) · {n_none} no page · {n_wrong} other fund's page · "
          f"{n_empty} empty · {n_err} errors")
    if n_err and not (n_ok or n_none or n_wrong or n_empty):
        raise RuntimeError(f"every Groww fund page failed ({n_err})")
    return n_ok


def compute(max_minutes=_http.HOST_BUDGET) -> int:
    """Daily route: map funds without a slug, link unclaimed sitemap pages by AMFI code, then
    fetch the due funds — all within one host budget."""
    if max_minutes is _http.HOST_BUDGET:
        max_minutes = _http.host("groww")[1]["budget_min"]
    t0 = time.monotonic()
    n = 0
    try:
        slugs = fetch_sitemap_slugs()
        map_slugs(slugs=slugs)
        n += discover(slugs, max_minutes=max_minutes)
    except RuntimeError as e:   # sitemap unreadable — still refresh the funds already mapped
        runlog.item_failed("groww sitemap", SITEMAP, str(e), symptom="B")
    left = max_minutes - (time.monotonic() - t0) / 60 if max_minutes else None
    if left is not None and left <= 0:
        return n
    return n + scrape(recheck_days=RECHECK_DAYS, max_minutes=left)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--map", action="store_true", help="Match sitemap slugs to funds without one")
    p.add_argument("--discover", action="store_true", help="Link unclaimed sitemap pages to funds by AMFI code")
    p.add_argument("--scrape", action="store_true", help="Fetch due funds' pages")
    p.add_argument("--scheme", help="One fund, by any of its AMFI scheme codes")
    p.add_argument("--limit", type=int, help="Cap funds fetched (smoke test)")
    p.add_argument("--recheck-days", type=int, default=0, help="Skip funds checked within N days")
    p.add_argument("--max-minutes", type=float, help="Stop after N minutes")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if a.map:
        map_slugs(dry_run=a.dry_run)
    if a.discover:
        discover(fetch_sitemap_slugs(), max_minutes=a.max_minutes)
    if a.scrape or a.scheme:
        scrape(limit=a.limit, scheme=a.scheme, recheck_days=a.recheck_days, max_minutes=a.max_minutes,
               dry_run=a.dry_run)
