"""
Alpha Signal v2 — BSE shareholding-pattern XBRL: who owns each stock, as filed.

`shareholding` (Tickertape) holds category percentages only, about two years deep. The
exchange filing also names every holder above 1% — promoters, mutual-fund schemes,
FPIs, individuals — and that is what a "who owns this, and who just bought" view needs.
This module writes two tables from each filing:
    shareholding_holders     one row per named holder
    shareholding_categories  one row per filing: the category totals (promoter, foreign
                             and domestic institutions, mutual funds, insurance, small
                             and large individuals) and the shareholder counts, from 2016

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
and is skipped. A category TOTAL is the instant context `<Category>_ContextI` (2016-17
filings also write `<Category>I`); the 2016 taxonomy has one `Institutions` total
(foreign portfolio investors inside it), the 2022 one splits `InstitutionsForeign` and
`InstitutionsDomestic`. A holder or category with shares but no percentage (the
persons-acting-in-concert section) gets shares / total shares.

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
    python -m sources.bse_shp --reparse                     # category totals from the archived filings
                                                            # (no network; filings already in shareholding_holders)
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
CAT_COLS = ["sid", "scrip_cd", "end_date", "filed_at", "promoter_pct", "public_pct", "foreign_inst_pct",
            "domestic_inst_pct", "mf_pct", "insurance_pct", "retail_pct", "hni_pct", "n_shareholders",
            "n_retail", "total_shares", "source_url", "fetched_at"]

# Category totals, by lower-cased context name (both taxonomies' spellings).
_TOTAL = "shareholdingpattern"
_PROMOTER = "shareholdingofpromoterandpromotergroup"
_PUBLIC = "publicshareholding"
_CATS = {
    "mf_pct": ("mutualfundsoruti",),
    "insurance_pct": ("insurancecompanies",),
    "retail_pct": ("residentindividualshareholdersholdingnominalsharecapitaluptorstwolakh",
                   "individualshareholdersholdingnominalsharecapitaluptorstwolakh"),
    "hni_pct": ("residentindividualshareholdersholdingnominalsharecapitalinexcessofrstwolakh",
                "individualshareholdersholdingnominalsharecapitalinexcessofrstwolakh"),
}
_FOREIGN_2022 = "institutionsforeign"
_DOMESTIC_2022 = "institutionsdomestic"
_INSTITUTIONS_2016 = "institutions"
_FOREIGN_2016 = ("institutionsforeignportfolioinvestor", "foreignportfolioinvestor", "foreigninstitutions",
                 "foreignventurecapitalinvestors")
_CAT_KEY = re.compile(r"^(.+?)(?:_Context)?I$")

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


def _contexts(text):
    """(instant date by context, {context: {fact: value}}) of one filing."""
    instants = {}
    for m in _CONTEXT.finditer(text):
        inst = _INSTANT.search(m.group(0))
        if inst:
            instants[m.group(1)] = inst.group(1)
    by_ctx = {}
    for name, ctx, value in _facts(text):
        if ctx:
            by_ctx.setdefault(ctx, {}).setdefault(name, value)
    return instants, by_ctx


def _shares(facts):
    return _number(facts.get("NumberOfShares") or facts.get("NumberOfFullyPaidUpEquityShares"))


def _totals(instants, by_ctx):
    """{lower-cased category: (shares, pct, holders)} and the filing's end date."""
    out, end_date = {}, None
    for ctx, facts in by_ctx.items():
        m = _CAT_KEY.match(ctx)
        if not m or ctx.startswith("D_") or m.group(1)[-1].isdigit():
            continue
        out.setdefault(m.group(1).lower(), (
            _shares(facts), _number(facts.get("ShareholdingAsAPercentageOfTotalNumberOfShares")),
            _number(facts.get("NumberOfShareholders"))))
        if m.group(1).lower() == _TOTAL:
            end_date = instants.get(ctx)
    total = (out.get(_TOTAL) or (None,))[0]
    if total:                                          # shares but no percentage → shares / total
        out = {k: (sh, pct if pct is not None or sh is None else round(100 * sh / total, 4), n)
               for k, (sh, pct, n) in out.items()}
    return out, end_date


def parse_holders(text):
    """A shareholding-pattern filing → [{end_date, holder_category, holder_seq,
    holder_name, promoter_type, shares, pct}], named holders only."""
    instants, by_ctx = _contexts(text)
    total = (_totals(instants, by_ctx)[0].get(_TOTAL) or (None,))[0]

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
        if pct is None and shares is not None and total:
            pct = round(100 * shares / total, 4)
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


def parse_categories(text):
    """A shareholding-pattern filing → one row of category totals, or None when the
    filing carries no total. An institution category the filing leaves out is 0 (a
    filing lists only the categories that hold shares); the individual categories
    and the counts stay NULL when absent."""
    t, end_date = _totals(*_contexts(text))
    if _TOTAL not in t or _PUBLIC not in t or end_date is None:
        return None

    def pct(*keys, absent=None):
        vals = [t[k][1] for k in keys if k in t and t[k][1] is not None]
        return round(sum(vals), 4) if vals else absent

    if _FOREIGN_2022 in t or _DOMESTIC_2022 in t:
        foreign, domestic = pct(_FOREIGN_2022, absent=0.0), pct(_DOMESTIC_2022, absent=0.0)
    else:
        foreign = pct(*_FOREIGN_2016, absent=0.0)
        inst = pct(_INSTITUTIONS_2016, absent=0.0)
        domestic = round(max(inst - foreign, 0.0), 4)
    retail_key = next((k for k in _CATS["retail_pct"] if k in t), None)
    return {
        "end_date": end_date,
        "promoter_pct": pct(_PROMOTER, absent=0.0), "public_pct": pct(_PUBLIC),
        "foreign_inst_pct": foreign, "domestic_inst_pct": domestic,
        "mf_pct": pct(*_CATS["mf_pct"], absent=0.0), "insurance_pct": pct(*_CATS["insurance_pct"], absent=0.0),
        "retail_pct": pct(*_CATS["retail_pct"]), "hni_pct": pct(*_CATS["hni_pct"]),
        "n_shareholders": t[_TOTAL][2], "n_retail": t[retail_key][2] if retail_key else None,
        "total_shares": t[_TOTAL][0],
    }


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
    """Filings of `sid` that need no fetch: category totals stored, or the file archived
    (the 2026-10-04 latest-quarter harvest stored holders before files were archived —
    those filings are fetched once more for their totals)."""
    cats = read_sql("SELECT DISTINCT filed_at FROM shareholding_categories WHERE sid = ?", params=(sid,))
    held = read_sql("SELECT DISTINCT scrip_cd, filed_at, source_url FROM shareholding_holders WHERE sid = ?",
                    params=(sid,))
    archived = {r.filed_at for r in held.itertuples() if archive_path(r.scrip_cd, r.source_url).exists()}
    return set(cats["filed_at"]) | archived


def _unarchived_sids():
    """Stocks with a stored filing that has neither category totals nor an archived file."""
    held = read_sql("""SELECT DISTINCT h.sid, h.scrip_cd, h.source_url FROM shareholding_holders h
                       WHERE NOT EXISTS (SELECT 1 FROM shareholding_categories c
                                         WHERE c.sid = h.sid AND c.filed_at = h.filed_at)""")
    return {r.sid for r in held.itertuples() if not archive_path(r.scrip_cd, r.source_url).exists()}


def harvest_stock(api, files, sid, scrip_cd, quarters, skip_stored=True, errors=None):
    """Rows for the latest `quarters` XBRL filings of one stock that are not stored yet:
    named holders, and one category-totals row per filing (tagged `_table`).
    A filing that could not be fetched is appended to `errors` (when given)."""
    filings = fetch_index(api, scrip_cd)[:quarters]
    have = _stored(sid) if skip_stored else set()
    fetched_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    for f in filings:
        if f["filed_at"] in have:
            continue
        try:
            text = fetch_filing(files, f["url"], scrip_cd)
            holders, cats = parse_holders(text), parse_categories(text)
        except Exception as e:                       # one bad filing must not lose the others
            runlog.item_error(LABEL, f"{sid} {f['url']}", e)
            if errors is not None:
                errors.append(f["url"])
            continue
        if not holders:
            runlog.item_failed(LABEL, f"{sid} {f['url']}", "filing parsed to 0 named holders")
            continue
        meta = {"sid": sid, "scrip_cd": scrip_cd, "filed_at": f["filed_at"],
                "source_url": f["url"], "fetched_at": fetched_at}
        rows += [{**h, **meta, "_table": "shareholding_holders"} for h in holders]
        if cats:
            rows.append({**cats, **meta, "_table": "shareholding_categories"})
    return rows


def _write(rows):
    df = pd.DataFrame(rows)
    n = insert_df(df.loc[df["_table"] == "shareholding_holders", COLS], "shareholding_holders", lock_retries=5)
    cats = df.loc[df["_table"] == "shareholding_categories", CAT_COLS]
    if len(cats):
        insert_df(cats, "shareholding_categories", lock_retries=5)
    return n


def reparse(chunk=2000):
    """Category totals for every archived filing already in shareholding_holders whose
    totals are not stored yet. Reads data/filings/bse_shp only — no network."""
    filings = read_sql("""
        SELECT DISTINCT h.sid, h.scrip_cd, h.filed_at, h.source_url FROM shareholding_holders h
        WHERE NOT EXISTS (SELECT 1 FROM shareholding_categories c
                          WHERE c.sid = h.sid AND c.filed_at = h.filed_at)""")
    fetched_at = datetime.now().isoformat(timespec="seconds")
    rows, n_missing, n_empty, n_written = [], 0, 0, 0
    print(f"bse_shp reparse: {len(filings)} filings without category totals")
    for i, f in enumerate(filings.itertuples(index=False), 1):
        path = archive_path(f.scrip_cd, f.source_url)
        if not path.exists():
            n_missing += 1
            continue
        cats = parse_categories(gzip.decompress(path.read_bytes()).decode("utf-8-sig", "replace"))
        if cats is None:
            n_empty += 1
            runlog.item_failed(LABEL, f"{f.sid} {f.source_url}", "filing has no category totals")
        else:
            rows.append({**cats, "sid": f.sid, "scrip_cd": f.scrip_cd, "filed_at": f.filed_at,
                         "source_url": f.source_url, "fetched_at": fetched_at})
        if rows and (len(rows) >= chunk or i == len(filings)):
            n_written += insert_df(pd.DataFrame(rows)[CAT_COLS], "shareholding_categories", lock_retries=5) or 0
            rows = []
    if rows:
        n_written += insert_df(pd.DataFrame(rows)[CAT_COLS], "shareholding_categories", lock_retries=5) or 0
    print(f"bse_shp reparse: {n_written} written · {n_empty} without totals · {n_missing} not archived")
    if len(filings) and not n_written:
        raise RuntimeError("bse_shp reparse: filings to parse but none produced category totals")


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
    skips stocks listed in DONE_FILE (every XBRL filing fetched without error) unless a
    stored filing still lacks its category totals and its archived file."""
    order = read_sql("SELECT sid FROM stocks ORDER BY market_cap_cr DESC NULLS LAST")["sid"]
    if full:
        skip = _done() - _unarchived_sids()
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
    p.add_argument("--reparse", action="store_true",
                   help="category totals from the archived filings (no network)")
    args = p.parse_args()

    if args.reparse:
        reparse()
        return

    if args.smoke:
        codes = scrip_codes(SMOKE_SIDS)
    elif args.sids:
        codes = scrip_codes([s.strip() for s in args.sids.split(",") if s.strip()])
    elif args.universe or args.due:
        codes = scrip_codes()
    else:
        p.error("one of --smoke / --sids / --universe / --due / --reparse")
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
            rows = [r for r in harvest_stock(api, files, sid, codes[sid], 1, skip_stored=False)
                    if r["_table"] == "shareholding_holders"]
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
