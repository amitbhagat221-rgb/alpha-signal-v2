"""
Alpha Signal v2 — corporate announcements, one reader for both exchanges (ADR 0082).

BSE history + NSE live, in BSE's taxonomy:
  bse_announcements   2018-01 -> 2026-10-12. The route is dropped (BSE's WAF 403s AnnSubCategoryGetData since
                      2026-10-13); the table stays as history.
  nse_announcements   from 2026-10-09, the live disclosure source. Each row gets its BSE-equivalent category and
                      subcategory from config.NSE_BSE_EQUIVALENT (first match wins; unmatched -> NULL subcategory).

The same filing reaches both exchanges: an NSE row is dropped when BSE has the same sid and subcategory within
`DEDUPE_DAYS` calendar days (BSE's row is kept). Before 2026-10-09 there are no NSE rows, so every reader sees
exactly the BSE history it saw before — point-in-time history is unchanged.

`sql()` is a subquery body (`FROM ({sql()}) a WHERE ...`), so a reader keeps its own filters; SQLite pushes them
into both arms. Columns (COLUMNS):
  source      'bse_announcements' | 'nse_announcements'
  id          BSE news_id | NSE seq_id
  sid         universe SID (NULL when the exchange row is unmapped)
  dt_tm       event time: BSE dt_tm, NSE an_dt (both start 'YYYY-MM-DD'; date(dt_tm) works for both)
  category    BSE CATEGORYNAME or the NSE row's BSE equivalent ('Result', 'Company Update', ...)
  subcategory BSE SUBCATNAME or the NSE row's BSE equivalent (NULL when NSE has no clear equivalent)
  filed_as    the exchange's own label: BSE subcategory / NSE desc
  title       one display line: BSE news_sub (else headline) / NSE subject (else desc)
  headline    BSE HEADLINE (body text) / NSE subject — what factors.RESULT_FILING_SQL tests
  news_sub    BSE NEWSSUB / NSE subject
  attachment  BSE attachment GUID / NSE attachment URL

`kind_sql(spec)` turns an event-kind spec ({"match": [{column: [LIKE, ...]}, ...], "exclude": [LIKE on title]})
into a WHERE condition on those columns; `events(kinds, since, until)` returns one row per (filing, kind) —
the multibagger red-flag gate (config.MB_THESIS["red_flags"]) live and in the backtest.
"""

from __future__ import annotations

import pandas as pd

import config

SOURCES = ("bse_announcements", "nse_announcements")
COLUMNS = ["source", "id", "sid", "dt_tm", "category", "subcategory", "filed_as", "title", "headline", "news_sub",
           "attachment"]
DEDUPE_DAYS = 2
KIND_COLUMNS = ("category", "subcategory", "filed_as", "title", "headline", "source")


def _lit(s):
    return "'" + str(s).replace("'", "''") + "'"


def _any_like(col, pats):
    return "(" + " OR ".join(f"{col} LIKE {_lit(p)}" for p in pats) + ")"


def _rule(r):
    conds = []
    if r.get("desc"):
        conds.append(_any_like("n.desc_category", r["desc"]))
    if r.get("subject"):
        conds.append(_any_like("n.subject", r["subject"]))
    if r.get("not_subject"):
        conds.append("NOT " + _any_like("COALESCE(n.subject, '')", r["not_subject"]))
    if not conds:
        raise ValueError(f"NSE_BSE_EQUIVALENT rule matches everything: {r}")
    return " AND ".join(conds)


def _case(i, rules):
    return "CASE " + " ".join(f"WHEN {_rule(r)} THEN {_lit(r['bse'][i])}" for r in rules) + " END"


def nse_sql(rules=None):
    """nse_announcements in the common shape, mapped to BSE's taxonomy (no dedupe)."""
    rules = config.NSE_BSE_EQUIVALENT if rules is None else rules
    return ("SELECT 'nse_announcements' AS source, n.seq_id AS id, n.sid, n.an_dt AS dt_tm, "
            f"{_case(0, rules)} AS category, {_case(1, rules)} AS subcategory, n.desc_category AS filed_as, "
            "COALESCE(NULLIF(n.subject, ''), n.desc_category) AS title, n.subject AS headline, n.subject AS news_sub, "
            "n.attachment_url AS attachment FROM nse_announcements n")


BSE_SQL = ("SELECT 'bse_announcements' AS source, news_id AS id, sid, dt_tm, category, subcategory, "
           "subcategory AS filed_as, COALESCE(NULLIF(news_sub, ''), headline) AS title, headline, news_sub, "
           "attachment FROM bse_announcements")


def sql(rules=None):
    """Subquery body: every BSE row + every NSE row that is not a copy of a BSE row (same sid and subcategory
    within DEDUPE_DAYS days). Use as `FROM ({sql()}) a`."""
    d = DEDUPE_DAYS
    return (f"{BSE_SQL} UNION ALL SELECT * FROM ({nse_sql(rules)}) m WHERE NOT (m.sid IS NOT NULL AND "
            "m.subcategory IS NOT NULL AND EXISTS (SELECT 1 FROM bse_announcements b WHERE b.sid = m.sid AND "
            f"b.subcategory = m.subcategory AND b.dt_tm >= date(m.dt_tm, '-{d} day') "
            f"AND b.dt_tm < date(m.dt_tm, '+{d + 1} day')))")


def kind_sql(spec, alias="a"):
    """WHERE condition for one event kind on the common columns. spec = {"match": [clause, ...], "exclude": [...]}:
    a row matches when ANY clause matches (a clause = {column: [LIKE patterns]}, every column must match one of
    its patterns) and its title matches no `exclude` pattern. LIKE is case-blind for ASCII."""
    clauses = []
    for cl in spec["match"]:
        bad = set(cl) - set(KIND_COLUMNS)
        if bad or not cl:
            raise ValueError(f"kind clause uses unknown columns {bad or 'none'}: {cl}")
        clauses.append("(" + " AND ".join(_any_like(f"{alias}.{c}", p) for c, p in cl.items()) + ")")
    cond = "(" + " OR ".join(clauses) + ")"
    if spec.get("exclude"):
        cond += " AND NOT " + _any_like(f"COALESCE({alias}.title, '')", spec["exclude"])
    return cond


def read(query, params=None, conn=None):
    if conn is None:
        from db import read_sql
        return read_sql(query, params)
    return pd.read_sql_query(query, conn, params=params)


EVENT_COLS = ["sid", "kind", "date", "source", "headline"]


def events(kinds, since=None, until=None, conn=None):
    """One row per (filing, kind) for the given kinds ({kind: spec}): [sid, kind, date (Timestamp), source,
    headline (the title)], mapped sids only, newest first. since is exclusive, until inclusive (filing dates,
    YYYY-MM-DD). Beyond sql()'s same-subcategory dedupe, an NSE event is dropped when BSE has the same sid and KIND
    within DEDUPE_DAYS (a kind can span several BSE subcategories, e.g. the CIRP ones); BSE's row is kept — also
    when it falls just before `since` (read DEDUPE_DAYS earlier, dedupe, then cut). A BSE twin after `until` is not
    knowable at `until`, so it never drops an NSE event (point in time)."""
    parts = []
    lo = None if not since else (pd.Timestamp(str(since)[:10]) - pd.Timedelta(days=DEDUPE_DAYS)).date().isoformat()
    for kind, spec in kinds.items():
        where, params = ["a.sid IS NOT NULL", kind_sql(spec)], []
        if lo:
            where.append("substr(a.dt_tm, 1, 10) > ?")
            params.append(lo)
        if until:
            where.append("substr(a.dt_tm, 1, 10) <= ?")
            params.append(str(until)[:10])
        q = (f"SELECT a.sid, substr(a.dt_tm, 1, 10) AS date, a.source, a.title AS headline FROM ({sql()}) a "
             f"WHERE {' AND '.join(where)}")
        parts.append(read(q, params, conn).assign(kind=kind))
    ev = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=EVENT_COLS)
    ev["date"] = pd.to_datetime(ev["date"])
    is_nse = ev["source"] == "nse_announcements"
    if is_nse.any() and (~is_nse).any():
        n = ev[is_nse].reset_index().merge(ev.loc[~is_nse, ["sid", "kind", "date"]], on=["sid", "kind"],
                                            suffixes=("", "_bse"))
        ev = ev.drop(index=n.loc[(n["date"] - n["date_bse"]).abs() <= pd.Timedelta(days=DEDUPE_DAYS), "index"].unique())
    if since:
        ev = ev[ev["date"] > pd.Timestamp(str(since)[:10])]
    return ev.sort_values(["date", "sid"], ascending=[False, True]).reset_index(drop=True)[EVENT_COLS]
