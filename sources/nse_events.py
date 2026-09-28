"""
Alpha Signal v2 — NSE event streams → market_events (plan 0018, research 0005).

Three event streams, one table (plan 0017 `events` shape, ADR 0054):

  credit_rating   NSE system-driven Reg-30 credit-rating disclosures (≥ 2025-01):
                  agency, instrument rating, action, and the EARLIER rating, so the
                  direction (upgrade / downgrade / reaffirm / new / withdrawn) is
                  derived from the two ratings — not from the action label, which
                  hides most downgrades under "Other" (the 805:88 upgrade skew of
                  the BSE-headline attempt, checklist 1e).
                  available_at = NSE broadcast time (PIT).
  ipo_listing     NSE past issues (≥ 2012, EQ + SME): issue dates, price, listing
                  date; anchor lock-in expiries by the SEBI rule (50% at 30 days,
                  50% at 90 days from allotment ≈ listing − 1 trading day).
  index_change    NSE's own inclusion/exclusion log (IndexInclExcl.xls, 1996 → 2020-07):
                  effective date, index, company. available_at = the effective date
                  (conservative: the announcement came ~4 weeks earlier).

Usage:
    python -m sources.nse_events --ratings --days 10        # daily (run.sh forward)
    python -m sources.nse_events --ratings --backfill       # 2025-01 → today
    python -m sources.nse_events --ipos                     # all past issues (one call)
    python -m sources.nse_events --index-changes            # the historical log (one file)
"""

import argparse
import io
import json
import re
from datetime import date, datetime, timedelta

import pandas as pd

import runlog
from db import insert_df, read_sql
from sources import _http

NSE_HOME = "https://www.nseindia.com"
RATING_API = "https://www.nseindia.com/api/corporate-credit-rating"
RATING_REFERER = "https://www.nseindia.com/companies-listing/corporate-sdd-credit-rating-reg30"
IPO_API = "https://www.nseindia.com/api/public-past-issues"
IPO_REFERER = "https://www.nseindia.com/market-data/all-upcoming-issues-ipo"
INDEX_XLS = "https://nsearchives.nseindia.com/content/indices/IndexInclExcl.xls"
RATING_START = date(2025, 1, 1)
COLS = ["type", "subtype", "sid", "event_time", "available_at", "source", "source_key", "payload", "fetched_at"]

# ─────────────────────────────── rating scale ───────────────────────────────

_LONG = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-", "BB+", "BB", "BB-",
         "B+", "B", "B-", "C+", "C", "C-", "D"]
_SHORT = ["A1+", "A1", "A2+", "A2", "A3+", "A3", "A4+", "A4", "D"]
_LONG_RE = re.compile(r"(?<![A-Z0-9])(AAA|AA|A|BBB|BB|B|C|D)\s*([+-])?(?![A-Z0-9])")
_SHORT_RE = re.compile(r"(?<![A-Z0-9])A\s*([1-4])\s*(\+)?(?![0-9])")


def rating_grade(text):
    """('long'|'short', rank) for a rating string — 0 = best. None when there is no
    grade (withdrawn, suspended, 'not rated', issuer-not-cooperating text only).
    Agency prefixes/suffixes are ignored: 'Crisil A-/Stable', 'CARE AA; Stable',
    '[ICRA]A+(Stable)', 'IND AA-/Stable', 'CRISIL A1+'."""
    if not text:
        return None
    t = str(text).upper()
    t = re.sub(r"\b(CRISIL|CARE|ICRA|IND|ACUITE|BWR|INFOMERICS|IVR|FITCH|MOODY'?S|S&P|PR)\b", " ", t)
    t = re.sub(r"[\[\]()/;,]", " ", t)
    if re.search(r"\bWITHDRAWN\b|\bSUSPENDED\b", t) and not _LONG_RE.search(t) and not _SHORT_RE.search(t):
        return None
    m = _SHORT_RE.search(t)
    if m:
        g = f"A{m.group(1)}{m.group(2) or ''}"
        if g in _SHORT:
            return "short", _SHORT.index(g)
    m = _LONG_RE.search(t)
    if m:
        g = m.group(1) + (m.group(2) or "")
        if g in _LONG:
            return "long", _LONG.index(g)
    return None


def rating_direction(new, old, action=None):
    """upgrade / downgrade / reaffirm / new / withdrawn / unknown — from the two
    ratings on the same scale; the action label only breaks ties it can't read."""
    act = (action or "").strip().lower()
    if "withdraw" in act or (new and re.search(r"withdrawn", str(new), re.I)):
        return "withdrawn"
    g_new, g_old = rating_grade(new), rating_grade(old)
    if g_new and g_old and g_new[0] == g_old[0]:
        return "reaffirm" if g_new[1] == g_old[1] else ("upgrade" if g_new[1] < g_old[1] else "downgrade")
    if g_new and not old:
        return "new"
    return {"upgrade": "upgrade", "downgrade": "downgrade", "reaffirm": "reaffirm", "new": "new"}.get(act, "unknown")


# ─────────────────────────────── helpers ───────────────────────────────

def _iso(d, fmts=("%d-%m-%Y", "%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d-%b-%Y %H:%M:%S")):
    if d is None or (isinstance(d, float) and pd.isna(d)):
        return None
    if isinstance(d, (datetime, pd.Timestamp)):
        return pd.Timestamp(d).isoformat()
    s = str(d).strip()
    for f in fmts:
        try:
            return datetime.strptime(s, f).isoformat()
        except ValueError:
            continue
    return None


def _sid_maps():
    """(ticker → sid, ISIN → sid, issuer prefix → sid). Indian ISINs share a 7-char
    issuer code (INE002A…): a rated NCD / CP carries the issuer's code, so a debt
    ISIN finds the listed equity through it."""
    tick = _http.sid_map("ticker")
    isin = read_sql("SELECT isin, sid FROM scrip_master WHERE sid IS NOT NULL AND isin IS NOT NULL")
    full = dict(zip(isin["isin"], isin["sid"]))
    prefix = {}
    for i, s in full.items():
        prefix.setdefault(str(i)[:7], s)
    return tick, full, prefix


def _rating_sid(r, tick, isin_map, prefix):
    sym = (r.get("Symbol") or "").strip().upper()
    for isin in ((r.get("ISIN") or "").strip(), (r.get("ISIN_ER") or "").strip()):
        if isin in isin_map:
            return isin_map[isin]
    for isin in ((r.get("ISIN") or "").strip(), (r.get("ISIN_ER") or "").strip()):
        if len(isin) >= 7 and isin[:7] in prefix:
            return prefix[isin[:7]]
    return tick.get(sym)


def _session(referer):
    return _http.warm_session(NSE_HOME, headers={**_http.host("nse")[1]["headers"], "Referer": referer})


def _rows_json(resp):
    js = resp.json() if resp is not None and resp.content[:1] in (b"{", b"[") else None
    if isinstance(js, dict):
        return js.get("data") or []
    return js if isinstance(js, list) else []


def _write(rows):
    if not rows:
        return 0
    return insert_df(pd.DataFrame(rows, columns=COLS), "market_events", lock_retries=5)


# ─────────────────────────────── credit ratings ───────────────────────────────

def rating_rows(raw, tick, isin_map, prefix, now):
    out = []
    for r in raw:
        new, old = r.get("CreditRating"), r.get("CreditRatingEarlier")
        direction = rating_direction(new, old, r.get("RatingAction"))
        sid = _rating_sid(r, tick, isin_map, prefix)
        when = _iso(r.get("DateofCR")) or _iso(r.get("ReportingDate"))
        avail = _iso(r.get("BroadcastDateTime")) or _iso(r.get("ReportingDate")) or when
        if not when:
            continue
        key = "|".join(str(r.get(k) or "") for k in ("AppID", "ISIN_ER", "NameOfCRAgency", "CreditRating", "DateofCR"))
        payload = {k: r.get(k) for k in ("Symbol", "CompanyName", "ISIN", "NameOfCRAgency", "CreditRating",
                                         "Outlook", "RatingAction", "SpecifyOthRatingActn", "CreditRatingEarlier",
                                         "OutlookEarlier", "NameOfCRAgencyEarlier", "DateOfCREarlier",
                                         "BroadcastDateTime", "XbrlFileName", "ISIN_ER")}
        g_new, g_old = rating_grade(new), rating_grade(old)
        payload.update(scale=(g_new or g_old or (None,))[0],      # notches > 0 = upgrade, < 0 = downgrade
                       notches=(g_old[1] - g_new[1]) if g_new and g_old and g_new[0] == g_old[0] else None)
        out.append(["credit_rating", direction, sid, when, avail, "nse", key,
                    json.dumps(payload, default=str), now])
    return out


def fetch_ratings(frm, to, session=None):
    """Rating disclosures in [frm, to], one call per calendar month."""
    session = session or _session(RATING_REFERER)
    tick, isin_map, prefix = _sid_maps()
    now = datetime.now().isoformat(timespec="seconds")
    n_raw = n_written = 0
    d = frm
    while d <= to:
        end = min((d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1), to)
        resp = _http.polite_get(RATING_API, session=session, timeout=60, headers={"Referer": RATING_REFERER},
                                params={"index": "equities", "from_date": d.strftime("%d-%m-%Y"),
                                        "to_date": end.strftime("%d-%m-%Y")})
        raw = _rows_json(resp)
        n_raw += len(raw)
        n_written += _write(rating_rows(raw, tick, isin_map, prefix, now))
        print(f"  credit ratings {d} → {end}: {len(raw)} disclosures", flush=True)
        d = end + timedelta(days=1)
    return n_raw, n_written


# ─────────────────────────────── IPO listings ───────────────────────────────

def _lockins(listing_iso):
    """Anchor lock-in expiries by the SEBI rule: allotment ≈ listing − 1 trading
    day; 50% unlock at +30 days, the rest at +90 days (approximate by design)."""
    if not listing_iso:
        return None, None
    allot = pd.Timestamp(listing_iso) - pd.offsets.BDay(1)
    return (allot + pd.Timedelta(days=30)).date().isoformat(), (allot + pd.Timedelta(days=90)).date().isoformat()


def ipo_rows(raw, tick, now):
    out = []
    for r in raw:
        sym = (r.get("symbol") or "").strip().upper()
        listing = _iso(r.get("listingDate"))
        opened = _iso(r.get("ipoStartDate"))
        when = listing or _iso(r.get("ipoEndDate")) or opened
        if not when or not sym:
            continue
        l30, l90 = _lockins(listing)
        payload = {"company": r.get("company") or r.get("companyName"), "symbol": sym,
                   "security_type": r.get("securityType"), "price_range": r.get("priceRange"),
                   "issue_price": r.get("issuePrice"), "ipo_start": opened, "ipo_end": _iso(r.get("ipoEndDate")),
                   "listing_date": listing, "anchor_lockin_30d": l30, "anchor_lockin_90d": l90,
                   "lockin_rule": "allotment≈listing−1 BD; 50% at +30d, 50% at +90d (SEBI anchor rule)"}
        out.append(["ipo_listing", (r.get("securityType") or "").upper() or None, tick.get(sym), when,
                    when, "nse", f"{sym}|{opened or ''}", json.dumps(payload, default=str), now])
    return out


def fetch_ipos(session=None):
    session = session or _session(IPO_REFERER)
    tick, _, _ = _sid_maps()
    resp = _http.polite_get(IPO_API, session=session, timeout=60, headers={"Referer": IPO_REFERER})
    raw = _rows_json(resp)
    return len(raw), _write(ipo_rows(raw, tick, datetime.now().isoformat(timespec="seconds")))


# ─────────────────────────────── index changes ───────────────────────────────

def _norm(name):
    s = re.sub(r"\b(limited|ltd|the|india|co|company|corporation|corp)\b", " ", str(name or "").lower())
    return re.sub(r"[^a-z0-9]", "", s.replace("&", " and "))


def index_rows(frames, name_map, now):
    out = []
    for sheet, df in frames.items():
        if df.empty:
            continue
        cols = {c.lower().strip(): c for c in df.columns}
        ic, dc, nc, sc = (cols.get("index name"), cols.get("event date"), cols.get("scrip name"), cols.get("description"))
        if not (ic and dc and nc):
            continue
        for _, r in df.iterrows():
            when = _iso(r[dc])
            if not when:
                continue
            desc = str(r[sc]) if sc else ""
            sub = "inclusion" if "inclu" in desc.lower() else ("exclusion" if "exclu" in desc.lower() else desc.lower() or None)
            name = str(r[nc]).strip()
            payload = {"index": str(r[ic]).strip(), "company": name, "description": desc, "sheet": sheet,
                       "available_at_note": "effective date; the announcement came ~4 weeks earlier"}
            out.append(["index_change", sub, name_map.get(_norm(name)), when, when, "nse",
                        f"{payload['index']}|{when[:10]}|{name}|{desc}", json.dumps(payload, default=str), now])
    return out


def fetch_index_changes():
    resp = _http.polite_get(INDEX_XLS, timeout=60)
    if resp is None:
        raise RuntimeError("IndexInclExcl.xls not found (404) — the archive moved")
    frames = pd.read_excel(io.BytesIO(resp.content), sheet_name=None)
    st = read_sql("SELECT sid, name FROM stocks WHERE name IS NOT NULL")
    name_map = {_norm(n): s for s, n in zip(st["sid"], st["name"])}
    rows = index_rows(frames, name_map, datetime.now().isoformat(timespec="seconds"))
    return len(rows), _write(rows)


def relink_sids():
    """Fill sid on stored credit-rating events whose issuer is now matchable (the
    issuer-prefix rule, a new listing, a scrip_master refresh). Only NULL sids."""
    from db import get_db
    tick, isin_map, prefix = _sid_maps()
    df = read_sql("SELECT event_id, payload FROM market_events WHERE type = 'credit_rating' AND sid IS NULL")
    upd = []
    for eid, p in zip(df["event_id"], df["payload"]):
        sid = _rating_sid(json.loads(p or "{}"), tick, isin_map, prefix)
        if sid:
            upd.append((sid, int(eid)))
    if upd:
        with get_db() as conn:
            conn.executemany("UPDATE market_events SET sid = ? WHERE event_id = ? AND sid IS NULL", upd)
    return len(upd)


def main(argv=None):
    ap = argparse.ArgumentParser(description="NSE event streams → market_events (plan 0018)")
    ap.add_argument("--ratings", action="store_true")
    ap.add_argument("--days", type=int, default=10, help="ratings window (daily run)")
    ap.add_argument("--backfill", action="store_true", help="ratings from 2025-01")
    ap.add_argument("--ipos", action="store_true")
    ap.add_argument("--index-changes", action="store_true")
    a = ap.parse_args(argv)
    if not (a.ratings or a.ipos or a.index_changes):
        ap.error("choose --ratings, --ipos and/or --index-changes")
    total_raw = 0
    if a.ratings:
        to = date.today()
        frm = RATING_START if a.backfill else to - timedelta(days=a.days)
        n_raw, n_new = fetch_ratings(frm, to)
        total_raw += n_raw
        print(f"credit ratings: {n_raw} disclosures, {n_new} new")
        if n_raw == 0:
            raise RuntimeError(f"credit ratings: 0 disclosures for {frm} → {to} — endpoint moved or blocked?")
    if a.ipos:
        n_raw, n_new = fetch_ipos()
        print(f"IPO listings: {n_raw} issues, {n_new} new")
        if n_raw == 0:
            raise RuntimeError("IPO listings: 0 issues — endpoint moved or blocked?")
    if a.index_changes:
        n_raw, n_new = fetch_index_changes()
        print(f"index changes: {n_raw} events, {n_new} new")
        if n_raw == 0:
            raise RuntimeError("index changes: 0 events parsed — file format changed?")
    if a.ratings:
        print(f"credit ratings: linked {relink_sids()} stored events to a stock")
    runlog.note("nse_events done", ratings=a.ratings, ipos=a.ipos, index_changes=a.index_changes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
