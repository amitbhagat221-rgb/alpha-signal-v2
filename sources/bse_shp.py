"""
Alpha Signal v2 — BSE shareholding-pattern XBRL: the NAMED holders of each stock.

`shareholding` (Tickertape) holds category percentages only. The exchange filing also
names every holder above 1% — promoters, mutual-fund schemes, FPIs, individuals — and
that is what a "who owns this, and who just bought" view needs. This module writes
those names into `shareholding_holders`, one row per holder per filing.

SOURCE (unofficial — the public bseindia.com site's own backend; research 0005 A2):
    index   GET https://api.bseindia.com/BseIndiaAPI/api/Corp_Shareholding_ng/w
              params: scripcode, flag=0, indtype=''
              headers: browser UA + Referer, and NO Origin (Origin returns an
                       1814-byte error shell)
              response: {"Table": [{sQtrName, D (broadcast time), EndDate, IsXBRL,
                                    XBRLAttachment}, ...]}  newest first, back to 2001
    filing  GET https://www.bseindia.com + XBRLAttachment
              .xml  (XBRL, Jun-2016 → mid-2025)   .html (inline XBRL, mid-2025 →)

FILE SHAPE (same in the 2016, 2020, 2022 and 2025 taxonomies): a named holder is a
typed-dimension member `<key>` (e.g. `MutualFundsOrUTI_Context15`). The context
`D_<key>` carries the text facts (NameOfTheShareholder, TypeOfPromoterShareholding);
the context `<key>` carries the numbers (NumberOfShares, the percentage). A member
flagged "Category" is a sub-total of a category (Clearing Members, HUF…), not a holder,
and is skipped.

PIT: `filed_at` is the BSE broadcast time. A revised filing for the same quarter is a
new set of rows with a later `filed_at`; read the latest `filed_at` at or before the
as-of date. Append-only (INSERT OR IGNORE).

Coverage: stocks with a BSE scrip code (2,199 of 2,448). NSE-only names are not covered.

Usage:
    python -m sources.bse_shp --smoke                       # 3 stocks, latest filing, no write
    python -m sources.bse_shp --sids RELI,GRAI --quarters 4
    python -m sources.bse_shp --due --budget-min 180        # stocks missing the latest quarter (cron)
    python -m sources.bse_shp --universe --quarters 2       # stocks holding fewer than 2 quarters
    python -m sources.bse_shp --universe --quarters 0 --budget-min 300   # full history, largest first,
                                                            # resumable (output/bse_shp_backfill_done.txt)
"""

import argparse
import gzip
import html
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from db import insert_df, read_sql
from hosts import HOSTS
import runlog
from sources import _http

INDEX_API = "https://api.bseindia.com/BseIndiaAPI/api/Corp_Shareholding_ng/w"
FILE_BASE = "https://www.bseindia.com"
WARM_URL = "https://www.bseindia.com/"
# The index 1814-byte-error-shells any request that carries an Origin header.
INDEX_HEADERS = {k: v for k, v in HOSTS["bse_api"]["headers"].items() if k != "Origin"}
SMOKE_SIDS = ["RELI", "GRAI", "PERS"]
LABEL = "bse_shp"

COLS = ["sid", "scrip_cd", "end_date", "filed_at", "holder_category", "holder_seq",
        "holder_name", "promoter_type", "shares", "pct", "source_url", "fetched_at"]

_CONTEXT = re.compile(r"<xbrli:context\s+id=['\"]([^'\"]+)['\"].*?</xbrli:context>", re.S)
_INSTANT = re.compile(r"<xbrli:instant>\s*([\d-]{10})")
_XML_FACT = re.compile(r"<in-bse-shp:(\w+)\s+([^>]*?)>([^<]*)</in-bse-shp:\1>")
_IX_FACT = re.compile(r"<ix:non(?:Numeric|Fraction)\s+([^>]*?)>(.*?)</ix:non(?:Numeric|Fraction)>", re.S)
_ATTR = re.compile(r"([\w:]+)\s*=\s*['\"]([^'\"]*)['\"]")
_TAG = re.compile(r"<[^>]+>")
_KEY = re.compile(r"^(?:Details(?:Of)?SharesHeldBy)?(.+?)(?:_Context)?(\d+)$")


def _facts(text):
    """Every in-bse-shp fact as (name, contextRef, value) — XBRL .xml or inline .html."""
    for name, attrs, value in _XML_FACT.findall(text):
        yield name, dict(_ATTR.findall(attrs)).get("contextRef"), value.strip()
    for attrs, value in _IX_FACT.findall(text):
        a = dict(_ATTR.findall(attrs))
        name = a.get("name", "")
        if name.startswith("in-bse-shp:"):
            yield name.split(":", 1)[1], a.get("contextRef"), _TAG.sub("", value).strip()


def _number(value):
    """Both formats print the plain figure (the inline `scale='-2'` on a percentage
    is the XBRL fraction; the printed text is still percent)."""
    try:
        return float(value.replace(",", ""))
    except (AttributeError, ValueError):
        return None


def parse_holders(text):
    """A shareholding-pattern filing → [{end_date, holder_category, holder_seq,
    holder_name, promoter_type, shares, pct}], named holders only."""
    instants = {}
    for m in _CONTEXT.finditer(text):
        inst = _INSTANT.search(m.group(0))
        if inst:
            instants[m.group(1)] = inst.group(1)
    by_ctx = {}
    for name, ctx, value in _facts(text):
        if ctx:
            by_ctx.setdefault(ctx, {}).setdefault(name, value)

    holders = []
    for ctx, facts in by_ctx.items():
        name = facts.get("NameOfTheShareholder")
        key = ctx[2:] if ctx.startswith("D_") else None
        m = _KEY.match(key) if key else None
        if not (name and m):
            continue
        if any(k.lower().startswith("whetheracategoryormorethan1percentage") and v.strip().lower() == "category"
               for k, v in facts.items()):
            continue
        nums = by_ctx.get(key, {})
        shares = _number(nums.get("NumberOfShares"))
        pct = _number(nums.get("ShareholdingAsAPercentageOfTotalNumberOfShares"))
        end_date = instants.get(key)
        if shares is None or end_date is None:
            continue
        holders.append({
            "end_date": end_date, "holder_category": m.group(1), "holder_seq": int(m.group(2)),
            "holder_name": re.sub(r"\s+", " ", html.unescape(name)).strip(),
            "promoter_type": facts.get("TypeOfPromoterShareholding") or None,
            "shares": shares, "pct": pct,
        })
    return holders


def scrip_codes(sids=None):
    """{sid: BSE scrip code} for universe stocks listed on BSE. scrip_master also
    carries a second, non-BSE code per stock below 400000 — never that one."""
    df = read_sql("SELECT m.sid, MIN(m.scrip_cd) AS scrip_cd FROM scrip_master m "
                  "JOIN stocks s ON s.sid = m.sid WHERE m.scrip_cd >= 400000 GROUP BY m.sid")
    codes = dict(zip(df["sid"], df["scrip_cd"].astype(int)))
    return codes if sids is None else {s: codes[s] for s in sids if s in codes}


def fetch_index(session, scrip_cd):
    """The filings of one scrip that have an XBRL file, newest first:
    [{end_date, filed_at, url}]."""
    r = _http.polite_request("GET", INDEX_API, session=session, headers=INDEX_HEADERS, check=False,
                             retries=1, timeout=30,
                             params={"scripcode": scrip_cd, "flag": 0, "indtype": ""})
    if r.status_code != 200:
        raise RuntimeError(f"index HTTP {r.status_code} for scrip {scrip_cd}")
    table = r.json().get("Table")
    if table is None:
        raise RuntimeError(f"index for scrip {scrip_cd} has no Table (blocked? {len(r.content)} bytes)")
    out = []
    for x in table:
        path = (x.get("XBRLAttachment") or "").strip()
        if x.get("IsXBRL") == 1 and path.lower().endswith((".xml", ".html")) and x.get("D"):
            out.append({"end_date": (x.get("EndDate") or "")[:10] or None, "filed_at": x["D"],
                        "url": FILE_BASE + path})
    return out


# Every filing is kept, gzipped (~4-20 KB each), so facts the parser does not read yet —
# pledged and locked-in shares, total shares, warrants, retail holder counts — can be
# parsed later without downloading ~88,000 filings again. Not data/raw/: that is the
# canary zone and is pruned.
ARCHIVE = Path(__file__).resolve().parent.parent / "data" / "filings" / "bse_shp"


def archive_path(scrip_cd, url):
    return ARCHIVE / str(scrip_cd) / (url.rsplit("/", 1)[-1] + ".gz")


def fetch_filing(session, url, scrip_cd=None):
    """The filing's text; with `scrip_cd`, read from / saved to the archive."""
    path = archive_path(scrip_cd, url) if scrip_cd else None
    if path is not None and path.exists():
        return gzip.decompress(path.read_bytes()).decode("utf-8-sig", "replace")
    r = _http.polite_request("GET", url, session=session, check=False, retries=1, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"filing HTTP {r.status_code}: {url}")
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(r.content))
        tmp.replace(path)
    return r.content.decode("utf-8-sig", "replace")


def _stored(sid):
    df = read_sql("SELECT DISTINCT filed_at FROM shareholding_holders WHERE sid = ?", params=(sid,))
    return set(df["filed_at"])


def harvest_stock(api, files, sid, scrip_cd, quarters, skip_stored=True, errors=None):
    """Rows for the latest `quarters` XBRL filings of one stock that are not stored yet.
    A filing that could not be fetched is appended to `errors` (when given)."""
    filings = fetch_index(api, scrip_cd)[:quarters]
    have = _stored(sid) if skip_stored else set()
    fetched_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    for f in filings:
        if f["filed_at"] in have:
            continue
        try:
            holders = parse_holders(fetch_filing(files, f["url"], scrip_cd))
        except Exception as e:                       # one bad filing must not lose the others
            runlog.item_error(LABEL, f"{sid} {f['url']}", e)
            if errors is not None:
                errors.append(f["url"])
            continue
        if not holders:
            runlog.item_failed(LABEL, f"{sid} {f['url']}", "filing parsed to 0 named holders")
            continue
        for h in holders:
            rows.append({**h, "sid": sid, "scrip_cd": scrip_cd, "filed_at": f["filed_at"],
                         "source_url": f["url"], "fetched_at": fetched_at})
    return rows


def _write(rows):
    return insert_df(pd.DataFrame(rows)[COLS], "shareholding_holders", lock_retries=5)


def latest_quarter_end(today=None):
    """The most recent quarter end strictly before `today`."""
    today = today or date.today()
    for y, m, d in ((today.year, 9, 30), (today.year, 6, 30), (today.year, 3, 31), (today.year - 1, 12, 31)):
        if date(y, m, d) < today:
            return date(y, m, d).isoformat()


def due_sids(codes):
    """Stocks with no stored filing for the latest quarter, never-fetched first."""
    df = read_sql("SELECT sid, MAX(end_date) AS last FROM shareholding_holders GROUP BY sid")
    last = dict(zip(df["sid"], df["last"]))
    target = latest_quarter_end()
    return sorted((s for s in codes if last.get(s, "") < target), key=lambda s: last.get(s, ""))


DONE_FILE = Path(__file__).resolve().parent.parent / "output" / "bse_shp_backfill_done.txt"


def _done():
    return set(DONE_FILE.read_text().split()) if DONE_FILE.exists() else set()


def pending_sids(codes, quarters, full):
    """Stocks a history run still has to visit, largest first. A `--quarters N` run
    skips stocks that already hold N quarters; a full-history run (`--quarters 0`)
    skips stocks listed in DONE_FILE (every XBRL filing fetched without error)."""
    order = read_sql("SELECT sid FROM stocks ORDER BY market_cap_cr DESC NULLS LAST")["sid"]
    if full:
        skip = _done()
    else:
        have = read_sql("SELECT sid, COUNT(DISTINCT end_date) AS n FROM shareholding_holders GROUP BY sid")
        skip = set(have.loc[have["n"] >= quarters, "sid"])
    return [s for s in order if s in codes and s not in skip]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--smoke", action="store_true", help="3 stocks, latest filing, print, no write")
    p.add_argument("--sids", help="comma-separated universe SIDs")
    p.add_argument("--universe", action="store_true", help="every stock with a BSE code")
    p.add_argument("--due", action="store_true", help="stocks missing the latest quarter")
    p.add_argument("--quarters", type=int, default=1,
                   help="latest N XBRL filings per stock; 0 = every filing (full history, checkpointed)")
    p.add_argument("--budget-min", type=float, help="stop after this many minutes (rerun resumes)")
    args = p.parse_args()

    if args.smoke:
        codes = scrip_codes(SMOKE_SIDS)
    elif args.sids:
        codes = scrip_codes([s.strip() for s in args.sids.split(",") if s.strip()])
    elif args.universe or args.due:
        codes = scrip_codes()
    else:
        p.error("one of --smoke / --sids / --universe / --due")
    if not codes:
        raise RuntimeError("bse_shp: no requested stock has a BSE scrip code in scrip_master")
    full = args.quarters == 0
    quarters = 10_000 if full else args.quarters
    if args.due:
        items = due_sids(codes)
    elif args.universe:
        items = pending_sids(codes, quarters, full)
    else:
        items = list(codes)
    if not items:
        print("bse_shp: nothing to fetch — every requested stock is already stored")
        return

    api = _http.warm_session(WARM_URL, INDEX_HEADERS)
    files = _http.session(FILE_BASE)
    files.cookies.update(api.cookies)
    out_of_time = _http.time_budget("bse_api", args.budget_min) if args.budget_min else (lambda: False)

    if args.smoke:
        empty = []
        for sid in items:
            rows = harvest_stock(api, files, sid, codes[sid], 1, skip_stored=False)
            if not rows:
                empty.append(sid)
            print(f"\n{sid} (scrip {codes[sid]}): {len(rows)} named holders, quarter "
                  f"{rows[0]['end_date'] if rows else '-'}, filed {rows[0]['filed_at'] if rows else '-'}")
            for r in sorted(rows, key=lambda r: -(r["pct"] or 0))[:6]:
                print(f"   {r['pct']:6.2f}%  {r['holder_category'][:38]:38s} {r['holder_name'][:60]}")
        if empty:
            sys.exit(f"bse_shp smoke: no named holders for {empty}")
        return

    def fetch(sid):
        if out_of_time():
            return None
        errors = []
        rows = harvest_stock(api, files, sid, codes[sid], quarters, errors=errors)
        if full and args.universe and not errors:
            pending_done.append(sid)
        return rows

    def write(rows):
        n = _write(rows)
        if pending_done:                              # only after the rows are in the table
            with DONE_FILE.open("a") as f:
                f.write("".join(f"{s}\n" for s in pending_done))
            pending_done.clear()
        return n

    pending_done = []
    print(f"bse_shp: {len(items)} stocks, {'every filing' if full else f'latest {quarters} filing(s)'} each"
          + (f", budget {args.budget_min:.0f} min" if args.budget_min else ""))
    _http.run_harvester(items, fetch, write, flush_every=25, label=LABEL)
    if pending_done:                                  # stocks whose filings were all stored already
        with DONE_FILE.open("a") as f:
            f.write("".join(f"{s}\n" for s in pending_done))


if __name__ == "__main__":
    main()
