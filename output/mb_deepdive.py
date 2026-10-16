"""
Plan 0026 stage 4 — the deep-dive builders for one candidate stock (read-only).

Three plain functions, each returning rows that carry their own as-of date:
    results_trend(sid, n=12)   last n quarters: revenue, EBITDA, PAT, margin, YoY growth
    ownership_timeline(sid)    per filing (2016+): holder-category %, pledge, and named holders >= 1 % in/out
    peers(sid, k=8)            same industry and cap tier: valuation, quality, 6-month return, thesis score
Plus `brief_inputs(sid)`, the compact structured block the `mb_dossier` brief feeds the model.

Every number is read from a table; nothing is computed from a guess. Units follow the source tables:
Rs crore for money, percent for percentages (growth and margin are percent, e.g. 12.5 = 12.5 %).
"""
import pandas as pd

import db

HOLDER_MIN_PCT = 1.0
PARTIAL_SHARE = 0.6     # a filing naming < 60 % of the previous filing's >= 1 % holders is a partial list (279 such
                        # filings in 246 stocks, 2024+): comparing it makes holders "exit" and "re-enter"


def _has_table(name):
    return bool(db.one("SELECT 1 AS x FROM sqlite_master WHERE type = 'table' AND name = ?", [name]))


def _columns(table):
    return [r["name"] for r in db.rows(f"PRAGMA table_info({table})")]


def _pct(a, b):
    return round((a / b - 1) * 100, 1) if a is not None and b not in (None, 0) and a == a and b == b else None


def _f(x, nd=2):
    return None if x is None or x != x else round(float(x), nd)


# ── 1. results trend ─────────────────────────────────────────────────────────

def _quarters_income(sid):
    """quarterly_income rows, one per quarter end: consolidated preferred, standalone otherwise."""
    df = db.read_sql(
        "SELECT end_date, period, reporting, revenue, COALESCE(ebitda, operating_profit) AS ebitda, "
        "net_income AS pat FROM quarterly_income WHERE sid = ? AND end_date IS NOT NULL", [sid])
    if df.empty:
        return {}
    df["rank"] = (df["reporting"] != "consolidated").astype(int)
    df = df.sort_values(["end_date", "rank"]).drop_duplicates("end_date", keep="first")
    return {r["end_date"]: {**r, "source": f"quarterly_income ({r['reporting']})"} for r in df.to_dict("records")}


def _quarters_screener(sid):
    df = db.read_sql(
        "SELECT period_end AS end_date, line_item, value FROM fundamentals_screener "
        "WHERE sid = ? AND period_type = 'quarterly' AND line_item IN ('Sales', 'Operating Profit', 'Net profit')",
        [sid])
    out = {}
    for r in df.to_dict("records"):
        key = {"Sales": "revenue", "Operating Profit": "ebitda", "Net profit": "pat"}[r["line_item"]]
        out.setdefault(r["end_date"], {"end_date": r["end_date"], "period": r["end_date"],
                                       "source": "fundamentals_screener (quarterly)"})[key] = r["value"]
    return out


def results_trend(sid, n=12):
    """[{end_date, period, revenue, ebitda, pat, ebitda_margin_pct, rev_yoy_pct, pat_yoy_pct, source}],
    oldest first, the last n quarters. quarterly_income is primary; a quarter it lacks (or lacks revenue for)
    is filled from Screener's quarterly lines and says so in `source`."""
    inc, scr = _quarters_income(sid), _quarters_screener(sid)
    merged = dict(inc)
    for d, r in scr.items():
        if d not in merged or merged[d].get("revenue") is None:
            merged[d] = r
    dates = sorted(merged)
    out = []
    for d in dates:
        r = merged[d]
        year_ago = next((merged[x] for x in dates if 350 <= (pd.Timestamp(d) - pd.Timestamp(x)).days <= 380), None)
        rev, eb, pat = r.get("revenue"), r.get("ebitda"), r.get("pat")
        out.append({"end_date": d, "period": r.get("period"), "revenue": _f(rev), "ebitda": _f(eb), "pat": _f(pat),
                    "ebitda_margin_pct": _f(eb / rev * 100, 1) if eb is not None and rev else None,
                    "rev_yoy_pct": _pct(rev, year_ago.get("revenue")) if year_ago else None,
                    "pat_yoy_pct": _pct(pat, year_ago.get("pat")) if year_ago and (year_ago.get("pat") or 0) > 0 else None,
                    "source": r["source"]})
    return out[-n:]


# ── 2. ownership timeline ────────────────────────────────────────────────────

def _named_holders(sid):
    """{end_date: {normalised name: (display name, pct)}} for non-promoter holders >= HOLDER_MIN_PCT, taken from the
    latest filing of each quarter end."""
    df = db.read_sql(
        "SELECT h.end_date, h.holder_name, h.pct, h.holder_category FROM shareholding_holders h "
        "WHERE h.sid = ? AND h.pct >= ? AND h.promoter_type IS NULL AND h.filed_at = "
        "(SELECT MAX(filed_at) FROM shareholding_holders x WHERE x.sid = h.sid AND x.end_date = h.end_date)",
        [sid, HOLDER_MIN_PCT])
    out = {}
    for r in df.to_dict("records"):
        key = "".join(ch for ch in str(r["holder_name"]).lower() if ch.isalnum())   # spelling and spacing vary by filing
        out.setdefault(r["end_date"], {})[key] = (r["holder_name"].strip(), r["pct"])
    return out


def ownership_timeline(sid):
    """One row per quarter-end filing, oldest first: {end_date, filed_at, promoter_pct, fii_pct, dii_pct, mf_pct,
    retail_pct, n_shareholders, pledge_pct, entered: [{name, pct}], exited: [{name, pct}]}. `entered` / `exited`
    are non-promoter holders crossing 1 % between consecutive filings (names as filed; the first filing lists none)."""
    cats = db.read_sql(
        "SELECT c.end_date, c.filed_at, c.promoter_pct, c.foreign_inst_pct AS fii_pct, c.domestic_inst_pct AS dii_pct, "
        "c.mf_pct, c.retail_pct, c.n_shareholders FROM shareholding_categories c WHERE c.sid = ? AND c.filed_at = "
        "(SELECT MAX(filed_at) FROM shareholding_categories x WHERE x.sid = c.sid AND x.end_date = c.end_date) "
        "ORDER BY c.end_date", [sid])
    pledge = {r["end_date"]: r["pledge_pct"] for r in db.rows(
        "SELECT end_date, pledge_pct FROM shareholding WHERE sid = ?", [sid])}
    holders = _named_holders(sid)
    out, prev = [], None
    for r in cats.to_dict("records"):
        d = r["end_date"]
        cur = holders.get(d, {})
        entered = exited = []
        partial = prev is not None and len(holders.get(prev, {})) >= 3 and len(cur) < PARTIAL_SHARE * len(holders[prev])
        if prev is not None and prev in holders and not partial:
            entered = [{"name": v[0], "pct": _f(v[1])} for k, v in cur.items() if k not in holders[prev]]
            exited = [{"name": v[0], "pct": _f(v[1])} for k, v in holders[prev].items() if k not in cur]
        out.append({**{k: (_f(v) if k.endswith("_pct") else v) for k, v in r.items()},
                    "n_shareholders": None if r["n_shareholders"] != r["n_shareholders"] else r["n_shareholders"],
                    "pledge_pct": _f(pledge.get(d)), "entered": entered, "exited": exited})
        prev = d if d in holders and not partial else prev     # a partial holder list is skipped, not compared
    return out


# ── 3. peers ─────────────────────────────────────────────────────────────────

def peers(sid, k=8):
    """Up to k peers in the same industry and cap tier (nearest by market cap; industry alone if the tier has fewer
    than k): {sid, ticker, name, cap_tier, market_cap_cr, pe, pb, roe_pct, rev_growth_pct, ret_6m_pct, thesis_score,
    as_of}. as_of is the date of the 6-month return (pit snapshot); fundamentals are the stocks-table snapshot dated
    by `fundamentals_as_of`. The first row is the stock itself (is_self), so its place among peers reads off directly."""
    me = db.one("SELECT sid, industry, cap_tier, market_cap_cr FROM stocks WHERE sid = ?", [sid])
    if not me or not me.get("industry"):
        return []
    cols = ("sid, ticker, name, cap_tier, market_cap_cr, pe_ratio, pb_ratio, roe, revenue_growth, "
            "substr(updated_at, 1, 10) AS fundamentals_as_of")
    same = db.rows(f"SELECT {cols} FROM stocks WHERE industry = ? AND sid != ? AND market_cap_cr IS NOT NULL "
                   "AND cap_tier = ? ORDER BY ABS(market_cap_cr - ?) LIMIT ?",
                   [me["industry"], sid, me["cap_tier"], me["market_cap_cr"] or 0, k])
    basis = "industry + cap tier"
    if len(same) < k:
        same = db.rows(f"SELECT {cols} FROM stocks WHERE industry = ? AND sid != ? AND market_cap_cr IS NOT NULL "
                       "ORDER BY (cap_tier = ?) DESC, ABS(market_cap_cr - ?) LIMIT ?",
                       [me["industry"], sid, me["cap_tier"], me["market_cap_cr"] or 0, k])
        basis = "industry only" if len(same) else basis
    rows = db.rows(f"SELECT {cols} FROM stocks WHERE sid = ?", [sid]) + same
    sids = [r["sid"] for r in rows]
    ph = ",".join("?" * len(sids))
    snap = db.scalar("SELECT MAX(snapshot_date) FROM daily_snapshots_pit")
    pit = {r["sid"]: r for r in db.rows(
        f"SELECT sid, mom_6m, revenue_growth_yoy FROM daily_snapshots_pit WHERE snapshot_date = ? AND sid IN ({ph})",
        [snap, *sids])}
    mom = {k: v["mom_6m"] for k, v in pit.items()}
    thesis, thesis_date = {}, None
    if "thesis_score" in _columns("multibagger_scores"):
        thesis_date = db.scalar("SELECT MAX(snapshot_date) FROM multibagger_scores WHERE thesis_score IS NOT NULL")
        thesis = {r["sid"]: r["thesis_score"] for r in db.rows(
            f"SELECT sid, thesis_score FROM multibagger_scores WHERE snapshot_date = ? AND sid IN ({ph})",
            [thesis_date, *sids])}
    return [{"sid": r["sid"], "ticker": r["ticker"], "name": r["name"], "is_self": r["sid"] == sid,
             "cap_tier": r["cap_tier"], "market_cap_cr": _f(r["market_cap_cr"], 0), "pe": _f(r["pe_ratio"], 1),
             "pb": _f(r["pb_ratio"], 2), "roe_pct": _f(r["roe"], 1), "rev_growth_pct": _f(r["revenue_growth"] if r["revenue_growth"] is not None
                                 else (pit.get(r["sid"]) or {}).get("revenue_growth_yoy"), 1),
             "ret_6m_pct": _f(mom.get(r["sid"]), 1), "thesis_score": _f(thesis.get(r["sid"]), 3),
             "as_of": snap, "fundamentals_as_of": r["fundamentals_as_of"], "thesis_as_of": thesis_date,
             "peer_basis": basis} for r in rows]


# ── brief inputs ─────────────────────────────────────────────────────────────

def latest_valuation(sid):
    """The newest valuation_ranges rows for the stock, or [] while the table does not exist (plan 0026 phase 3)."""
    if not _has_table("valuation_ranges"):
        return []
    return db.rows("SELECT as_of, method, low, mid, high, basis FROM valuation_ranges WHERE sid = ? AND as_of = "
                   "(SELECT MAX(as_of) FROM valuation_ranges WHERE sid = ?) ORDER BY method", [sid, sid])


def headlines(sid, days=90, limit=40):
    """Last `days` days of BSE announcement headlines: [{date, category, subcategory, headline}] newest first,
    routine filings (trading window, newspaper ads, RTA certificates) dropped; headline text is third-party."""
    rows = db.rows(
        "SELECT substr(dt_tm, 1, 10) AS date, category, subcategory, COALESCE(news_sub, headline) AS headline "
        "FROM bse_announcements WHERE sid = ? AND dt_tm >= date('now', ?) "
        "AND COALESCE(subcategory, '') NOT LIKE 'Closure of Trading Window%' "
        "AND COALESCE(subcategory, '') NOT LIKE 'Newspaper Publication%' "
        "AND COALESCE(subcategory, '') NOT LIKE 'Certificate under Reg. 74%' "
        "ORDER BY dt_tm DESC LIMIT ?", [sid, f"-{int(days)} days", limit])
    return [{**r, "headline": (r["headline"] or "")[:160]} for r in rows]


def brief_inputs(sid):
    """Everything the mb_dossier brief reasons over, trimmed to fit a ~40 KB brief."""
    own = ownership_timeline(sid)[-8:]
    for o in own:
        o["entered"], o["exited"] = o["entered"][:5], o["exited"][:5]
    return {"results_trend": results_trend(sid, 12), "ownership_timeline": own, "peers": peers(sid, 8),
            "valuation_ranges": latest_valuation(sid), "headlines_90d": headlines(sid)}
