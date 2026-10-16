"""
Multibagger desk — per-name event watch and the stage-3 evidence card (plan 0026 phase 4).

`timeline(sid)`   one dated event table for a stock from every source we hold.
`govt_links(sid)` government / PSU / LIC holders and government-buyer orders (context for a human, never a score).
`card(sid)`       the stage-3 evidence card (a dict with a stable key set).
`new_since(sids, ts)`  events newer than a timestamp, severity >= medium, for the morning email / push.

Rules: every number comes from a table, never parsed from text; headlines are copied as filed (a derived
event, which has no filing, carries a "[derived] ..." label and its numbers in `detail`). Read-only: the DB is
opened `mode=ro`. Category maps and thresholds are data in `config` (BSE_ANNOUNCEMENT_CATEGORIES,
SUPERINVESTORS, GOVT_*, WATCH_*).

A second announcement source (NSE) plugs in by adding its category map to `config` and a loader to
`_ANN_LOADERS` below (same output columns as `_load_bse`).
"""
import json
import re
import sqlite3

import numpy as np
import pandas as pd

import config
from signals import forensic

COLUMNS = ["date", "source", "category", "severity", "headline", "detail", "url"]
CARD_KEYS = ["sid", "name", "cap_tier", "industry", "as_of", "thesis", "known_investors", "results",
             "events_90d", "top_events_90d", "valuation_position", "forensic", "pledge", "promoter"]
BSE_ATTACH = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/"


# ── plumbing ────────────────────────────────────────────────────────────────────────────────────

def _conn():
    return sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)


def _q(conn, sql, params=()):
    return pd.read_sql_query(sql, conn, params=params)


def _ts(s):
    """Any date string -> naive Timestamp (tz-aware values are converted to UTC then made naive)."""
    out = pd.to_datetime(s, errors="coerce", utc=True, format="mixed")
    return out.dt.tz_convert(None)


def _frame(rows):
    return pd.DataFrame(rows, columns=COLUMNS)


def _num(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def _norm(name):
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def investor_of(holder_name):
    """SUPERINVESTORS entry a holder name matches, else None."""
    n = str(holder_name).upper()
    for inv, pats in config.SUPERINVESTORS.items():
        if any(p in n for p in pats):
            return inv
    return None


def _sev_by_value(value_cr):
    t = config.WATCH_DEAL_VALUE_CR
    return "high" if value_cr >= t["high"] else "medium" if value_cr >= t["medium"] else "low"


# ── announcements (one loader per source; the category map lives in config) ──────────────────────

def _load_bse(conn, sid, since):
    df = _q(conn, "SELECT news_id, dt_tm, headline, news_sub, subcategory, category, critical_news, attachment, "
                  "nsurl, quarter_id FROM bse_announcements WHERE sid=?" + (" AND dt_tm>=?" if since else ""),
            (sid, since.strftime("%Y-%m-%dT%H:%M:%S")) if since else (sid,))
    if df.empty:
        return _frame([])
    cm = config.BSE_ANNOUNCEMENT_CATEGORIES
    cs = [cm.get(s, config.ANNOUNCEMENT_DEFAULT) for s in df["subcategory"]]
    out = pd.DataFrame({
        "date": _ts(df["dt_tm"]), "source": "bse_announcements",
        "category": [c for c, _ in cs], "severity": [v for _, v in cs],
        "headline": df["news_sub"].where(df["news_sub"].notna() & (df["news_sub"] != ""), df["headline"]),
        "url": np.where(df["attachment"].notna() & (df["attachment"] != ""), BSE_ATTACH + df["attachment"].fillna(""),
                        df["nsurl"]),
    })
    out["detail"] = [{"subcategory": s, "bse_category": c, "text": h, "quarter_id": q, "critical": cr, "news_id": n}
                     for s, c, h, q, cr, n in zip(df["subcategory"], df["category"], df["headline"], df["quarter_id"],
                                                  df["critical_news"], df["news_id"])]
    return out[COLUMNS]


def _category_severity():
    """NSE rows carry only a watch category; use the severity BSE gives that category most often."""
    votes = {}
    for cat, sev in config.BSE_ANNOUNCEMENT_CATEGORIES.values():
        votes.setdefault(cat, {}).setdefault(sev, 0)
        votes[cat][sev] += 1
    return {c: max(v, key=v.get) for c, v in votes.items()}


def _load_nse(conn, sid, since):
    try:
        df = _q(conn, "SELECT seq_id, an_dt, desc_category, category, subject, attachment_url "
                      "FROM nse_announcements WHERE sid=?", (sid,))
    except Exception:                       # table not created yet on this DB
        return _frame([])
    if df.empty:
        return _frame([])
    df["date"] = _ts(df["an_dt"])
    if since is not None:
        df = df[df["date"] >= since]
    if df.empty:
        return _frame([])
    sev = _category_severity()
    cat = df["category"].fillna(config.ANNOUNCEMENT_DEFAULT[0])
    out = pd.DataFrame({"date": df["date"], "source": "nse_announcements", "category": cat,
                        "severity": [sev.get(c, config.ANNOUNCEMENT_DEFAULT[1]) for c in cat],
                        "headline": df["subject"].where(df["subject"].notna() & (df["subject"] != ""),
                                                        df["desc_category"]),
                        "url": df["attachment_url"]})
    out["detail"] = [{"nse_desc": d, "seq_id": q} for d, q in zip(df["desc_category"], df["seq_id"])]
    return out[COLUMNS]


_ANN_LOADERS = {"bse": _load_bse, "nse": _load_nse}    # BSE blocked since 2026-10-13 (WAF); NSE keeps the feed alive


# ── derived: results ────────────────────────────────────────────────────────────────────────────

def _quarters(conn, sid):
    """Quarterly revenue / EBITDA / PAT by end_date. quarterly_income first (consolidated over standalone),
    Screener quarterly fills quarters it lacks."""
    qi = _q(conn, "SELECT period, end_date, reporting, revenue, COALESCE(ebitda, operating_profit) AS ebitda, "
                  "net_income AS pat FROM quarterly_income WHERE sid=? AND end_date IS NOT NULL", (sid,))
    if not qi.empty:
        qi["rank"] = (qi["reporting"] != "consolidated").astype(int)
        qi = qi.sort_values(["end_date", "rank"]).drop_duplicates("end_date")
        qi["source"] = "quarterly_income"
    fs = _q(conn, "SELECT period_end AS end_date, line_item, value FROM fundamentals_screener "
                  "WHERE sid=? AND period_type='quarterly' AND line_item IN ('Sales','Operating Profit','Net profit')",
            (sid,))
    if not fs.empty:
        fs = fs.pivot_table(index="end_date", columns="line_item", values="value", aggfunc="first").reset_index()
        fs = fs.rename(columns={"Sales": "revenue", "Operating Profit": "ebitda", "Net profit": "pat"})
        for c in ("revenue", "ebitda", "pat"):
            if c not in fs:
                fs[c] = np.nan
        fs["period"] = pd.to_datetime(fs["end_date"]).dt.strftime("%b %Y").str.upper()
        fs["reporting"] = "screener"
        fs["source"] = "fundamentals_screener"
        if not qi.empty:
            fs = fs[~fs["end_date"].isin(qi["end_date"])]
    cols = ["period", "end_date", "reporting", "revenue", "ebitda", "pat", "source"]
    parts = [d[cols] for d in (qi, fs) if len(d)]
    if not parts:
        return pd.DataFrame(columns=cols)
    q = pd.concat(parts).sort_values("end_date").reset_index(drop=True)
    q["end"] = pd.to_datetime(q["end_date"], errors="coerce")
    return q.dropna(subset=["end"])


def _yoy(q, i):
    """Row i against the quarter ~1 year earlier (within 20 days), or None."""
    target = q.loc[i, "end"] - pd.DateOffset(years=1)
    cand = q[(q["end"] - target).abs() <= pd.Timedelta(days=20)]
    return None if cand.empty else cand.iloc[0]


def _pct(a, b):
    a, b = _num(a), _num(b)
    return None if a is None or b is None or b <= 0 else round((a / b - 1) * 100, 1)


def results_vs_year_ago(conn, sid, n=1):
    """The latest n quarters, each with revenue / EBITDA / PAT and the change vs a year ago (structured)."""
    q = _quarters(conn, sid)
    out = []
    for i in list(q.index[::-1])[:n]:
        r, y = q.loc[i], _yoy(q, i)
        d = {"period": r["period"], "end_date": r["end_date"], "basis": r["reporting"], "source": r["source"],
             "revenue": _num(r["revenue"]), "ebitda": _num(r["ebitda"]), "pat": _num(r["pat"]),
             "year_ago_end_date": None if y is None else y["end_date"],
             "year_ago_revenue": None if y is None else _num(y["revenue"]),
             "year_ago_ebitda": None if y is None else _num(y["ebitda"]),
             "year_ago_pat": None if y is None else _num(y["pat"])}
        d["revenue_yoy_pct"] = _pct(d["revenue"], d["year_ago_revenue"])
        d["ebitda_yoy_pct"] = _pct(d["ebitda"], d["year_ago_ebitda"])
        d["pat_yoy_pct"] = _pct(d["pat"], d["year_ago_pat"])
        out.append(d)
    return out


def _ev_results(conn, sid, since):
    rows = []
    for d in results_vs_year_ago(conn, sid, n=8):
        dt = pd.to_datetime(d["end_date"])
        if since is not None and dt < since:
            continue
        rows.append((dt, "quarterly_income", "results", "medium",
                     f"[derived] results quarter ended {d['period']}", dict(d, date_basis="period_end"), None))
    return _frame(rows)


# ── derived: ownership ──────────────────────────────────────────────────────────────────────────

def _filings(conn, sid):
    """One row per quarter (first filing): end_date, filed_at, promoter / mf / fii pct, + pledge from `shareholding`."""
    c = _q(conn, "SELECT end_date, filed_at, promoter_pct, mf_pct, foreign_inst_pct AS fii_pct "
                 "FROM shareholding_categories WHERE sid=? ORDER BY end_date, filed_at", (sid,))
    c = c.drop_duplicates("end_date")
    s = _q(conn, "SELECT end_date, pledge_pct, promoter_pct AS s_promoter FROM shareholding WHERE sid=?", (sid,))
    m = c.merge(s, on="end_date", how="outer").sort_values("end_date").reset_index(drop=True)
    m["promoter_pct"] = pd.to_numeric(m["promoter_pct"], errors="coerce").fillna(pd.to_numeric(m["s_promoter"], errors="coerce"))
    m["date"] = _ts(m["filed_at"]).fillna(pd.to_datetime(m["end_date"], errors="coerce"))
    return m.drop(columns="s_promoter")


def _holders(conn, sid):
    """Named holders at or above WATCH_HOLDER_MIN_PCT, first filing per quarter."""
    h = _q(conn, "SELECT end_date, filed_at, holder_category, holder_name, promoter_type, pct "
                 "FROM shareholding_holders WHERE sid=? AND pct>=? ORDER BY end_date, filed_at",
           (sid, config.WATCH_HOLDER_MIN_PCT))
    if h.empty:
        return h
    first = h.groupby("end_date")["filed_at"].transform("min")
    h = h[h["filed_at"] == first].copy()
    h["key"] = h["holder_name"].map(_norm)
    h["investor"] = h["holder_name"].map(investor_of)
    h["is_promoter"] = h["promoter_type"].notna()
    # a holder can appear on several rows of one filing (several sections): keep the largest
    return h.sort_values("pct", ascending=False).drop_duplicates(["end_date", "key"]).sort_values("end_date")


def _ev_ownership(conn, sid, since):
    rows = []
    f = _filings(conn, sid)
    mv = config.WATCH_PROMOTER_MOVE_PTS
    for prev, cur in zip(f.index[:-1], f.index[1:]):
        a, b = f.loc[prev], f.loc[cur]
        dt = b["date"]
        if pd.isna(dt):
            continue
        for col, label, cat in (("promoter_pct", "promoter holding", "shareholding_sast"),
                                ("pledge_pct", "promoter pledge", "pledge"),
                                ("mf_pct", "mutual fund holding", "shareholding_sast"),
                                ("fii_pct", "foreign institution holding", "shareholding_sast")):
            x, y = _num(a[col]), _num(b[col])
            if x is None or y is None:
                continue
            d = round(y - x, 2)
            if abs(d) < mv or (col == "pledge_pct" and d < 0):
                continue
            sev = ("high" if abs(d) >= 5 else "medium") if col in ("promoter_pct", "pledge_pct") else \
                  ("medium" if abs(d) >= 2 else "low")
            rows.append((dt, "shareholding", cat, sev, f"[derived] {label} {'up' if d > 0 else 'down'} {abs(d)} pts",
                         {"metric": col, "from_pct": x, "to_pct": y, "change_pts": d, "end_date": b["end_date"],
                          "prev_end_date": a["end_date"]}, None))
    h = _holders(conn, sid)
    if not h.empty:
        fdate = dict(zip(f["end_date"], f["date"]))
        ends = sorted(h["end_date"].unique())
        for pe, ce in zip(ends[:-1], ends[1:]):
            a, b = h[h["end_date"] == pe], h[h["end_date"] == ce]
            dt = fdate.get(ce)
            if dt is None or pd.isna(dt):
                dt = pd.to_datetime(b["end_date"].iloc[0])
            for _, r in b[~b["key"].isin(a["key"])].iterrows():
                if r["is_promoter"]:
                    continue
                si = r["investor"]
                rows.append((dt, "shareholding_holders", "shareholding_sast", "high" if si else "medium",
                             f"[derived] {'known investor ' + si if si else 'new named holder'} entered: "
                             f"{r['holder_name']}",
                             {"holder_name": r["holder_name"], "pct": _num(r["pct"]), "investor": si,
                              "end_date": ce, "prev_end_date": pe, "event": "entry"}, None))
            for _, r in a[~a["key"].isin(b["key"])].iterrows():
                if r["investor"]:
                    rows.append((dt, "shareholding_holders", "shareholding_sast", "medium",
                                 f"[derived] known investor {r['investor']} exited: {r['holder_name']}",
                                 {"holder_name": r["holder_name"], "last_pct": _num(r["pct"]), "investor": r["investor"],
                                  "end_date": ce, "prev_end_date": pe, "event": "exit"}, None))
    out = _frame(rows)
    return out if since is None else out[out["date"] >= since]


# ── derived: deals, insiders ────────────────────────────────────────────────────────────────────

def _ev_bulk(conn, sid, since):
    b = _q(conn, "SELECT client_name, deal_type, buy_sell, quantity, price, deal_date FROM bulk_deals WHERE sid=?",
           (sid,))
    rows = []
    for _, r in b.iterrows():
        dt = pd.to_datetime(r["deal_date"], errors="coerce")
        if pd.isna(dt) or (since is not None and dt < since):
            continue
        val = (r["quantity"] or 0) * (r["price"] or 0) / 1e7
        rows.append((dt, "bulk_deals", "shareholding_sast", _sev_by_value(val),
                     f"[derived] {r['deal_type']} deal {str(r['buy_sell']).lower()}: {r['client_name']} (Rs {val:.2f} Cr)",
                     {"client": r["client_name"], "deal_type": r["deal_type"], "side": r["buy_sell"],
                      "quantity": _num(r["quantity"]), "price": _num(r["price"]), "value_cr": round(val, 2)}, None))
    return _frame(rows)


def _ev_insider(conn, sid, since):
    t = _q(conn, "SELECT person, person_category, transaction_type, shares, value_lakhs, trade_date, source "
                 "FROM insider_trades WHERE sid=? AND transaction_type IN ('Buy','Sell','Pledge','Pledge Revoke',"
                 "'Pledge Invoke')", (sid,))
    rows = []
    for _, r in t.iterrows():
        dt = pd.to_datetime(r["trade_date"], errors="coerce")
        if pd.isna(dt) or (since is not None and dt < since):
            continue
        val = (r["value_lakhs"] or 0) / 100.0
        pledge = r["transaction_type"].startswith("Pledge")
        rows.append((dt, "insider_trades", "pledge" if pledge else "shareholding_sast", _sev_by_value(val),
                     f"[derived] insider {r['transaction_type'].lower()}: {r['person']} (Rs {val:.2f} Cr)",
                     {"person": r["person"], "person_category": r["person_category"], "type": r["transaction_type"],
                      "shares": _num(r["shares"]), "value_cr": round(val, 2)}, None))
    return _frame(rows)


# ── market events (ratings), surveillance, regulatory, news, corporate actions ──────────────────

_RATING_SEV = {"upgrade": "medium", "downgrade": "high", "new": "low", "withdrawn": "medium", "reaffirm": "low",
               "unknown": "low"}


def _ev_ratings(conn, sid, since):
    m = _q(conn, "SELECT subtype, available_at, payload FROM market_events WHERE type='credit_rating' AND sid=?",
           (sid,))
    rows = []
    for _, r in m.iterrows():
        dt = pd.to_datetime(r["available_at"], errors="coerce")
        if pd.isna(dt) or (since is not None and dt < since):
            continue
        p = json.loads(r["payload"] or "{}")
        rows.append((dt, "market_events", "credit_rating", _RATING_SEV.get(r["subtype"], "low"),
                     f"{p.get('NameOfCRAgency')}: {p.get('CreditRating')} ({p.get('RatingAction')})",
                     {"agency": p.get("NameOfCRAgency"), "rating": p.get("CreditRating"), "outlook": p.get("Outlook"),
                      "action": r["subtype"], "rating_earlier": p.get("CreditRatingEarlier"),
                      "outlook_earlier": p.get("OutlookEarlier"), "notches": p.get("notches"), "isin": p.get("ISIN")},
                     p.get("XbrlFileName")))
    return _frame(rows)


_SURV_SEV = {"GSM": "high", "ASM_LT": "medium", "ASM_ST": "medium", "FNO_BAN": "low"}


def _ev_surveillance(conn, sid, since):
    f = _q(conn, "SELECT flag_type, flag_date, stage, reason FROM surveillance_flags WHERE sid=?", (sid,))
    rows = []
    for ft, g in f.groupby("flag_type"):
        alld = [r[0] for r in conn.execute("SELECT DISTINCT flag_date FROM surveillance_flags WHERE flag_type=? "
                                           "ORDER BY 1", (ft,))]
        pos = {d: i for i, d in enumerate(alld)}
        g = g.sort_values("flag_date")
        last_i = None
        run = []
        for _, r in g.iterrows():
            i = pos[r["flag_date"]]
            if last_i is None or i != last_i + 1:
                if run:
                    rows.append(_surv_exit(ft, run[-1], alld, last_i))
                rows.append((pd.to_datetime(r["flag_date"]), "surveillance_flags", "other", _SURV_SEV.get(ft, "low"),
                             f"{ft} listed", {"flag": ft, "event": "in", "stage": r["stage"], "reason": r["reason"]},
                             None))
                run = []
            run.append(r)
            last_i = i
        if run:
            rows.append(_surv_exit(ft, run[-1], alld, last_i))
    rows = [r for r in rows if r is not None]
    out = _frame(rows)
    return out if since is None else out[out["date"] >= since]


def _surv_exit(ft, last_row, alld, last_i):
    if last_i is None or last_i + 1 >= len(alld):
        return None            # still listed on the latest scrape
    return (pd.to_datetime(alld[last_i + 1]), "surveillance_flags", "other", "low", f"{ft} delisted from list",
            {"flag": ft, "event": "out", "last_listed": last_row["flag_date"]}, None)


def _ev_regulatory(conn, sid, since, floor):
    sec = conn.execute("SELECT sector FROM stocks WHERE sid=?", (sid,)).fetchone()
    if not sec or not sec[0]:
        return _frame([])
    r = _q(conn, "SELECT e.published_at, e.title, e.source_url, e.ministry, e.source, s.direction, s.magnitude, "
                 "s.time_horizon FROM regulatory_signals s JOIN regulatory_events e USING(event_id) "
                 "WHERE s.sector=? AND s.is_regulatory=1 AND s.magnitude='major'", (sec[0],))
    if r.empty:
        return _frame([])
    r["date"] = _ts(r["published_at"])
    r = r.dropna(subset=["date"])
    r = r[r["date"] >= (since if since is not None else floor)]
    rows = [(x.date, "regulatory_events", "other", "low", x.title,
             {"sector": sec[0], "direction": x.direction, "magnitude": x.magnitude, "ministry": x.ministry,
              "time_horizon": x.time_horizon, "scope": "sector"}, x.source_url) for x in r.itertuples()]
    return _frame(rows)


def _ev_news(conn, sid, since, floor):
    n = _q(conn, "SELECT a.published_at, a.title, a.url, a.source, s.match_location FROM news_article_stocks s "
                 "JOIN news_articles a USING(article_id) WHERE s.sid=?", (sid,))
    if n.empty:
        return _frame([])
    n["date"] = _ts(n["published_at"])
    n = n.dropna(subset=["date"])
    n = n[n["date"] >= (since if since is not None else floor)]
    rows = [(x.date, "news_articles", "other", "low", x.title, {"publisher": x.source, "match": x.match_location}, x.url)
            for x in n.itertuples()]
    return _frame(rows)


def _ev_actions(conn, sid, since):
    a = _q(conn, "SELECT ind, subject, ex_date, face_value FROM corporate_actions WHERE sid=?", (sid,))
    rows = []
    for _, r in a.iterrows():
        dt = pd.to_datetime(r["ex_date"], errors="coerce")
        if pd.isna(dt) or (since is not None and dt < since):
            continue
        sev = "medium" if str(r["ind"]).upper() in ("SPLIT", "BONUS", "RIGHTS") else "low"
        rows.append((dt, "corporate_actions", "other", sev, r["subject"],
                     {"type": r["ind"], "face_value": _num(r["face_value"])}, None))
    return _frame(rows)


# ── public API ──────────────────────────────────────────────────────────────────────────────────

def timeline(sid, since=None, conn=None):
    """Dated events for one stock, newest first. `since`: a date / Timestamp (default: everything; news and
    sector regulatory events default to the last WATCH_NEWS_DAYS days, they are high volume).
    Columns: date, source, category, severity, headline, detail (dict), url."""
    own = conn is None
    conn = conn or _conn()
    try:
        since = None if since is None else pd.Timestamp(since)
        floor = pd.Timestamp.now().normalize() - pd.Timedelta(days=config.WATCH_NEWS_DAYS)
        parts = [loader(conn, sid, since) for loader in _ANN_LOADERS.values()]
        parts += [_ev_results(conn, sid, since), _ev_ownership(conn, sid, since), _ev_bulk(conn, sid, since),
                  _ev_insider(conn, sid, since), _ev_ratings(conn, sid, since), _ev_surveillance(conn, sid, since),
                  _ev_regulatory(conn, sid, since, floor), _ev_news(conn, sid, since, floor),
                  _ev_actions(conn, sid, since)]
    finally:
        if own:
            conn.close()
    parts = [p for p in parts if len(p)]
    if not parts:
        return _frame([])
    df = pd.concat(parts, ignore_index=True)
    # the same filing reaches both exchanges: drop an NSE row when BSE has that category on that day
    if {"bse_announcements", "nse_announcements"} <= set(df["source"]):
        day = df["date"].dt.normalize()
        bse_keys = set(zip(day[df["source"] == "bse_announcements"], df.loc[df["source"] == "bse_announcements", "category"]))
        dup = (df["source"] == "nse_announcements") & pd.Series([k in bse_keys for k in zip(day, df["category"])],
                                                                 index=df.index)
        df = df[~dup]
    df = df.dropna(subset=["date"])
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date", ascending=False, kind="stable").reset_index(drop=True)[COLUMNS]


def govt_links(sid, conn=None):
    """Government / political link card. Context for a human, never a score."""
    own = conn is None
    conn = conn or _conn()
    try:
        h = _q(conn, "SELECT end_date, holder_category, holder_name, pct FROM shareholding_holders WHERE sid=? "
                     "AND pct>0", (sid,))
        orders = _q(conn, "SELECT dt_tm, news_sub, headline, attachment FROM bse_announcements WHERE sid=? AND "
                          "subcategory IN ('Award of Order / Receipt of Order', 'Memorandum of Understanding /Agreements')",
                    (sid,))
    finally:
        if own:
            conn.close()
    holders = []
    if not h.empty:
        latest = h["end_date"].max()
        u = h["holder_name"].str.upper()
        hit = h["holder_category"].isin(config.GOVT_HOLDER_CATEGORIES) | u.map(
            lambda n: any(p in n for p in config.GOVT_HOLDER_PATTERNS))
        hit &= ~u.isin(["0", "1"])
        g = h[hit].sort_values("end_date")
        latest_g = g[g["end_date"] == g["end_date"].max()] if len(g) else g
        holders = [{"holder_name": r.holder_name, "pct": _num(r.pct), "end_date": r.end_date,
                    "holder_category": r.holder_category, "in_latest_filing": r.end_date == latest}
                   for r in latest_g.itertuples()]
    govt_orders = []
    if not orders.empty:
        txt = (orders["news_sub"].fillna("") + " " + orders["headline"].fillna("")).str.upper()
        for r, t in zip(orders.itertuples(), txt):
            kws = [k for k in config.GOVT_BUYER_KEYWORDS if k in t]
            if kws:
                govt_orders.append({"date": r.dt_tm[:10], "headline": r.news_sub or r.headline, "matched": kws,
                                    "url": BSE_ATTACH + r.attachment if r.attachment else None})
    govt_orders.sort(key=lambda d: d["date"], reverse=True)
    return {"sid": sid, "govt_holders": holders, "govt_orders": govt_orders[:20], "n_govt_orders": len(govt_orders),
            "electoral_bond_donor": {"flag": None, "basis": "not loaded"}}


def _valuation_position(conn, sid):
    s = _q(conn, "SELECT snapshot_date, earnings_yield, book_to_price FROM daily_snapshots_pit WHERE sid=? "
                 "ORDER BY snapshot_date", (sid,))
    out = {"as_of": None if s.empty else s["snapshot_date"].iloc[-1]}
    for name, col in (("pe", "earnings_yield"), ("pb", "book_to_price")):
        v = s[col]
        mult = (1.0 / v[v > 0]).dropna()
        cur = None if s.empty or pd.isna(s[col].iloc[-1]) or s[col].iloc[-1] <= 0 else 1.0 / s[col].iloc[-1]
        out[name] = None if cur is None else round(float(cur), 2)
        out[f"{name}_percentile"] = (None if cur is None or len(mult) < 12
                                     else round(float((mult <= cur).mean() * 100), 1))
        out[f"{name}_n_obs"] = int(len(mult))
    return out


def _thesis(conn, sid):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(multibagger_scores)") if r[1].startswith("thesis_")]
    if not cols:
        return None
    r = conn.execute(f"SELECT snapshot_date, {', '.join(cols)} FROM multibagger_scores WHERE sid=? "
                     "ORDER BY snapshot_date DESC LIMIT 1", (sid,)).fetchone()
    return None if r is None else dict(zip(["snapshot_date"] + cols, r))


def _known_investors(conn, sid):
    """SUPERINVESTORS holders (>= WATCH_HOLDER_MIN_PCT) in the last two filings, flagged if new vs the one before."""
    h = _holders(conn, sid)
    if h.empty:
        return []
    ends = sorted(h["end_date"].unique())
    out = []
    for i, e in enumerate(ends[-2:], start=max(len(ends) - 2, 0)):
        prev = set(h[h["end_date"] == ends[i - 1]]["key"]) if i > 0 else None
        for r in h[(h["end_date"] == e) & h["investor"].notna()].itertuples():
            out.append({"investor": r.investor, "holder_name": r.holder_name, "end_date": e, "pct": _num(r.pct),
                        "entered": None if prev is None else r.key not in prev})
    return out


def card(sid, asof=None, conn=None):
    """Stage-3 evidence card. Keys are stable (CARD_KEYS); a missing part is None / empty, never absent."""
    own = conn is None
    conn = conn or _conn()
    try:
        asof = pd.Timestamp(asof) if asof is not None else pd.Timestamp.now().normalize()
        st = conn.execute("SELECT name, cap_tier, industry FROM stocks WHERE sid=?", (sid,)).fetchone()
        tl = timeline(sid, since=asof - pd.Timedelta(days=90), conn=conn)
        tl = tl[(tl["date"] <= asof) & ~tl["source"].isin(["news_articles", "regulatory_events"])]
        counts = {c: int((tl["category"] == c).sum()) for c in config.WATCH_CATEGORIES}
        sev = tl.assign(r=tl["severity"].map(config.WATCH_SEVERITY)).sort_values(["r", "date"], ascending=False)
        sev = sev.drop_duplicates(["source", "category", "headline"])
        top = [{"date": str(r.date)[:10], "category": r.category, "severity": r.severity, "headline": r.headline}
               for r in sev.head(3).itertuples()]
        f = _filings(conn, sid)
        f = f[f["date"] <= asof] if len(f) else f
        pledge = {"pledge_pct": None, "end_date": None}
        promoter = {"promoter_pct": None, "change_pts": None, "end_date": None}
        if len(f):
            fp = f.dropna(subset=["pledge_pct"])
            if len(fp):
                pledge = {"pledge_pct": _num(fp["pledge_pct"].iloc[-1]), "end_date": fp["end_date"].iloc[-1],
                          "change_pts": None if len(fp) < 2 else round(float(fp["pledge_pct"].iloc[-1] - fp["pledge_pct"].iloc[-2]), 2)}
            fq = f.dropna(subset=["promoter_pct"])
            if len(fq):
                promoter = {"promoter_pct": _num(fq["promoter_pct"].iloc[-1]), "end_date": fq["end_date"].iloc[-1],
                            "change_pts": None if len(fq) < 2 else round(float(fq["promoter_pct"].iloc[-1] - fq["promoter_pct"].iloc[-2]), 2)}
        fz = _q(conn, "SELECT snapshot_date, m_score, z_score FROM daily_snapshots_pit WHERE sid=? ORDER BY "
                      "snapshot_date DESC LIMIT 12", (sid,))
        m = fz.dropna(subset=["m_score"]).head(1)
        z = fz.dropna(subset=["z_score"]).head(1)
        forensic_card = {
            "m_score": None if m.empty else _num(m["m_score"].iloc[0]),
            "m_score_flag": None if m.empty else forensic._flag_m_score(m["m_score"].iloc[0]),
            "m_score_date": None if m.empty else m["snapshot_date"].iloc[0],
            "z_score": None if z.empty else _num(z["z_score"].iloc[0]),
            "z_score_flag": None if z.empty else forensic._flag_z_score(z["z_score"].iloc[0]),
            "z_score_date": None if z.empty else z["snapshot_date"].iloc[0]}
        res = results_vs_year_ago(conn, sid, n=1)
        return {"sid": sid, "name": st[0] if st else None, "cap_tier": st[1] if st else None,
                "industry": st[2] if st else None, "as_of": str(asof.date()), "thesis": _thesis(conn, sid),
                "known_investors": _known_investors(conn, sid), "results": res[0] if res else None,
                "events_90d": counts, "top_events_90d": top, "valuation_position": _valuation_position(conn, sid),
                "forensic": forensic_card, "pledge": pledge, "promoter": promoter}
    finally:
        if own:
            conn.close()


def new_since(sids, since_ts, min_severity="medium", conn=None):
    """Events newer than `since_ts` for the given stocks, severity >= min_severity, newest first, with a `sid`
    column. For the morning email / push. Derived results events are dated by period end and so rarely qualify;
    the BSE 'Financial Results' filing is the alert for a result."""
    own = conn is None
    conn = conn or _conn()
    try:
        since = pd.Timestamp(since_ts)
        floor = config.WATCH_SEVERITY[min_severity]
        parts = []
        for sid in sids:
            t = timeline(sid, since=since, conn=conn)
            t = t[(t["date"] > since) & (t["severity"].map(config.WATCH_SEVERITY) >= floor)
                  & ~t["source"].isin(["news_articles", "regulatory_events"])]
            if len(t):
                parts.append(t.assign(sid=sid))
    finally:
        if own:
            conn.close()
    if not parts:
        return pd.DataFrame(columns=["sid"] + COLUMNS)
    return pd.concat(parts, ignore_index=True).sort_values("date", ascending=False)[["sid"] + COLUMNS]
