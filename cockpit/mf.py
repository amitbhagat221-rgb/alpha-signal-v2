"""
Alpha Signal Cockpit — Mutual Fund research data layer.

Extracted from cockpit/api.py 2026-05-30 (mechanical split — MF is a distinct
domain with its own schema; it was living inside the stock-detail data layer).
Functions are unchanged and re-exported from cockpit.api, so existing
`api.get_mf_*` call sites keep resolving.
"""

from db import read_sql
from cockpit._shared import _persisted_cache


# ── Mutual Fund research section (plan prfect-lets-add-a-zazzy-eich) ──
# Standalone research section. See cockpit/templates/mutual_funds.html (universe
# browser) and mf_detail.html (per-scheme deep-dive). Data layer:
#   - mf_scheme_master   AMFI universe (~14k schemes, refreshed weekly)
#   - mf_nav_history     daily NAV per scheme (AMFI daily + mfapi.in backfill)
#   - mf_metrics         per-scheme returns/risk/composite_score (monthly recompute)
#   - mf_rolling_returns 3Y/5Y rolling CAGR sampled monthly per scheme
#   - mf_calendar_returns per-year returns table
#   - mf_category_stats  category medians/deciles


@_persisted_cache(600, name="mf_universe_overview")
def get_mf_universe_overview(category: str = None, amc: str = None,
                              plan: str = None, option: str = None,
                              q: str = None, sort: str = "score",
                              page: int = 1, page_size: int = 50,
                              include_non_investable: bool = False) -> dict:
    """Filterable + paginated universe browser. Returns dict with rows + facets + counts.

    Filters:
      category   one of mf_scheme_master.category_norm (or family prefix like 'Equity')
      amc        substring match on AMC name
      plan       'DIRECT' / 'REGULAR'
      option     'GROWTH' / 'IDCW'
      q          free-text on scheme_name
      include_non_investable  if True, include schemes that are NOT realistically
                       investable: data_quality != 'TRUSTED' (wound-up, segregated,
                       interval, bonus, anomalous NAV) OR latest NAV is stale
                       (>30 days old — matured FMPs, delisted plans). Default False.
    Sort: 'score' (default) / 'ret_1y' / 'ret_3y' / 'sharpe_1y' / 'name'.
    """
    where = ["sm.active = 1"]
    if not include_non_investable:
        where.append("(sm.data_quality IS NULL OR sm.data_quality = 'TRUSTED')")
        where.append(
            "EXISTS (SELECT 1 FROM mf_nav_history n "
            "WHERE n.scheme_code = sm.scheme_code "
            "AND n.nav_date >= date('now','-30 days'))"
        )
    params: list = []
    if category:
        if "/" in category:
            where.append("sm.category_norm = ?")
            params.append(category)
        else:
            where.append("sm.category_norm LIKE ?")
            params.append(f"{category}%")
    if amc:
        where.append("sm.amc LIKE ?")
        params.append(f"%{amc}%")
    if plan:
        where.append("sm.plan_type = ?")
        params.append(plan.upper())
    if option:
        where.append("sm.option_type = ?")
        params.append(option.upper())
    if q:
        where.append("sm.scheme_name LIKE ?")
        params.append(f"%{q}%")

    where_sql = " AND ".join(where)
    sort_map = {
        "score":     "m.composite_score DESC NULLS LAST",
        "ret_1y":    "m.ret_1y DESC NULLS LAST",
        "ret_3y":    "m.ret_3y_cagr DESC NULLS LAST",
        "ret_5y":    "m.ret_5y_cagr DESC NULLS LAST",
        "sharpe_1y": "m.sharpe_1y DESC NULLS LAST",
        "max_dd":    "m.max_drawdown DESC NULLS LAST",
        "name":      "sm.scheme_name ASC",
    }
    order_by = sort_map.get(sort, sort_map["score"])

    # Join to LATEST mf_metrics row per scheme (defensive — table should be clean
    # after the monthly compute, but stale rows from earlier runs can stick around).
    metrics_join = """LEFT JOIN mf_metrics m
        ON sm.scheme_code = m.scheme_code
       AND m.as_of_date = (SELECT MAX(as_of_date) FROM mf_metrics)"""

    # Count for pagination
    total = read_sql(
        f"""SELECT COUNT(*) AS n FROM mf_scheme_master sm
            {metrics_join}
            WHERE {where_sql}""",
        params=params,
    ).iloc[0]["n"]

    # Page rows
    offset = max(0, (page - 1) * page_size)
    rows = read_sql(
        f"""SELECT sm.scheme_code, sm.scheme_name, sm.amc, sm.category_norm,
                   sm.plan_type, sm.option_type,
                   m.nav, m.nav_date,
                   m.ret_1y, m.ret_3y_cagr, m.ret_5y_cagr,
                   m.sharpe_1y, m.max_drawdown,
                   m.composite_score, m.score_percentile, m.peer_rank_3y
            FROM mf_scheme_master sm
            {metrics_join}
            WHERE {where_sql}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?""",
        params=params + [page_size, offset],
    )

    return {
        "rows":      rows.replace({float("nan"): None}).to_dict("records"),
        "total":     int(total),
        "page":      page,
        "page_size": page_size,
        "n_pages":   (int(total) + page_size - 1) // page_size,
        "sort":      sort,
        "filters":   {"category": category, "amc": amc, "plan": plan, "option": option, "q": q},
    }


@_persisted_cache(3600, name="mf_category_heatmap")
def get_mf_category_heatmap(include_non_investable: bool = False) -> list[dict]:
    """Category-level medians for the heatmap on /mutual-funds.

    One row per category_norm with median 3Y CAGR, scheme count.
    Used to render colored squares at the top of the page (click to filter).

    When include_non_investable=False (default), categories with zero investable
    schemes (e.g. Debt / Income legacy FMPs, ETFs that aren't real funds) are
    hidden, and scheme_count reflects the investable-only count to match the
    table below.
    """
    df = read_sql("""
        SELECT cs.category_norm,
               cs.scheme_count,
               ROUND(cs.median_ret_1y, 2)  AS median_ret_1y,
               ROUND(cs.median_ret_3y, 2)  AS median_ret_3y,
               ROUND(cs.median_ret_5y, 2)  AS median_ret_5y,
               ROUND(cs.median_sharpe_1y, 2) AS median_sharpe_1y,
               ROUND(cs.median_std_1y, 2)    AS median_std_1y,
               ROUND(cs.top_decile_ret_1y, 2) AS top_decile_ret_1y
        FROM mf_category_stats cs
        WHERE cs.as_of_date = (SELECT MAX(as_of_date) FROM mf_category_stats)
        ORDER BY cs.scheme_count DESC
    """)
    if include_non_investable:
        return df.replace({float("nan"): None}).to_dict("records")

    inv = read_sql("""
        SELECT sm.category_norm, COUNT(*) AS investable_count
        FROM mf_scheme_master sm
        WHERE sm.active = 1
          AND (sm.data_quality IS NULL OR sm.data_quality = 'TRUSTED')
          AND EXISTS (SELECT 1 FROM mf_nav_history n
                      WHERE n.scheme_code = sm.scheme_code
                        AND n.nav_date >= date('now','-30 days'))
        GROUP BY sm.category_norm
    """)
    inv_map = dict(zip(inv["category_norm"], inv["investable_count"]))
    df["scheme_count"] = df["category_norm"].map(inv_map).fillna(0).astype(int)
    df = df[df["scheme_count"] > 0].sort_values("scheme_count", ascending=False).copy()
    return df.replace({float("nan"): None}).to_dict("records")


def get_mf_detail(scheme_code: str) -> dict | None:
    """Per-scheme deep-dive payload — identity, snapshot, returns, risk, scorer breakdown."""
    info = read_sql(
        """SELECT sm.scheme_code, sm.scheme_name, sm.amc, sm.category_norm, sm.category_raw,
                  sm.plan_type, sm.option_type, sm.isin_growth, sm.isin_div,
                  sm.aum_cr, sm.expense_ratio, sm.benchmark,
                  sm.data_quality, sm.quality_reason,
                  ms.inception_date, ms.has_full_history, sm.last_seen
           FROM mf_scheme_master sm
           LEFT JOIN mf_schemes ms ON sm.scheme_code = ms.scheme_code
           WHERE sm.scheme_code = ?""",
        params=[scheme_code],
    )
    if info.empty:
        return None
    info_dict = info.iloc[0].replace({float("nan"): None}).to_dict()

    metrics = read_sql(
        "SELECT * FROM mf_metrics WHERE scheme_code = ? ORDER BY as_of_date DESC LIMIT 1",
        params=[scheme_code],
    )
    metrics_dict = metrics.iloc[0].replace({float("nan"): None}).to_dict() if not metrics.empty else {}

    calendar = read_sql(
        "SELECT year, ret_pct, bench_ret_pct FROM mf_calendar_returns "
        "WHERE scheme_code = ? ORDER BY year DESC",
        params=[scheme_code],
    )
    calendar_list = calendar.replace({float("nan"): None}).to_dict("records")

    return {
        "info":     info_dict,
        "metrics":  metrics_dict,
        "calendar": calendar_list,
    }


def get_mf_nav_series(scheme_code: str, days: int = None) -> list[dict]:
    """NAV time series for the chart. `days` filters to last N days; None = full history.

    NAV is spliced for scale artifacts (÷10/÷100 early segments) via the same
    clean_nav_series the metrics use — so the chart doesn't show a phantom 10× step.
    """
    if days:
        df = read_sql(
            "SELECT nav_date, nav FROM mf_nav_history "
            "WHERE scheme_code = ? AND nav_date >= date('now', ?) "
            "ORDER BY nav_date",
            params=[scheme_code, f"-{int(days)} day"],
        )
    else:
        df = read_sql(
            "SELECT nav_date, nav FROM mf_nav_history "
            "WHERE scheme_code = ? ORDER BY nav_date",
            params=[scheme_code],
        )
    from signals.mf_metrics import clean_nav_series
    df = clean_nav_series(df).rename(columns={"nav_date": "date"})
    return df.to_dict("records")


def get_mf_rolling_returns(scheme_code: str) -> list[dict]:
    """Rolling 3Y / 5Y CAGR series (monthly anchors)."""
    df = read_sql(
        """SELECT anchor_date,
                  rolling_3y_cagr, rolling_5y_cagr,
                  rolling_3y_beats_category, rolling_5y_beats_category
           FROM mf_rolling_returns
           WHERE scheme_code = ? ORDER BY anchor_date""",
        params=[scheme_code],
    )
    return df.replace({float("nan"): None}).to_dict("records")


def get_mf_peer_rank(scheme_code: str, top_n: int = 10) -> dict:
    """Peer comparison — top N schemes in same category_norm by composite_score."""
    cat = read_sql(
        "SELECT category_norm FROM mf_scheme_master WHERE scheme_code = ?",
        params=[scheme_code],
    )
    if cat.empty or not cat.iloc[0]["category_norm"]:
        return {"category": None, "peers": []}
    category = cat.iloc[0]["category_norm"]

    peers = read_sql(
        """SELECT sm.scheme_code, sm.scheme_name, sm.amc,
                  m.composite_score, m.ret_3y_cagr, m.sharpe_3y
           FROM mf_metrics m
           JOIN mf_scheme_master sm ON sm.scheme_code = m.scheme_code
           WHERE sm.category_norm = ? AND m.composite_score IS NOT NULL
           ORDER BY m.composite_score DESC LIMIT ?""",
        params=[category, top_n],
    )
    return {
        "category": category,
        "peers":    peers.replace({float("nan"): None}).to_dict("records"),
    }


def get_mf_holdings(scheme_code: str) -> dict:
    """Top holdings + sector allocation for a scheme (mf_holdings + mf_sector_allocation).

    Returns dict with `top` (list of holding dicts), `sectors` (list of sector dicts),
    and `as_of_date`. Empty if no holdings data has been ingested for this scheme.
    """
    top = read_sql(
        """SELECT holding_rank, instrument_name, sid, isin, sector, pct_of_aum,
                  market_value_cr, instrument_type
           FROM mf_holdings
           WHERE scheme_code = ?
             AND as_of_date = (SELECT MAX(as_of_date) FROM mf_holdings WHERE scheme_code = ?)
           ORDER BY holding_rank ASC""",
        params=[scheme_code, scheme_code],
    )
    sectors = read_sql(
        """SELECT sector, pct_of_aum FROM mf_sector_allocation
           WHERE scheme_code = ?
             AND as_of_date = (SELECT MAX(as_of_date) FROM mf_sector_allocation WHERE scheme_code = ?)
           ORDER BY pct_of_aum DESC""",
        params=[scheme_code, scheme_code],
    )
    as_of = top["holding_rank"].iloc[0] if False else None
    if not top.empty:
        as_of_row = read_sql(
            "SELECT MAX(as_of_date) AS d FROM mf_holdings WHERE scheme_code = ?",
            params=[scheme_code],
        )
        as_of = as_of_row.iloc[0]["d"] if not as_of_row.empty else None
    return {
        "top":         top.replace({float("nan"): None}).to_dict("records"),
        "sectors":     sectors.replace({float("nan"): None}).to_dict("records"),
        "as_of_date":  as_of,
    }


def get_mf_compare(scheme_codes: list[str]) -> dict:
    """Side-by-side comparison for 2-5 schemes — same metrics shape as detail page.

    Returns dict with `schemes` (one entry per code) + `categories_seen` (so the
    UI can warn when comparing across categories).
    """
    if not scheme_codes:
        return {"schemes": [], "categories_seen": []}
    scheme_codes = scheme_codes[:5]
    ph = ",".join("?" * len(scheme_codes))

    info = read_sql(
        f"""SELECT sm.scheme_code, sm.scheme_name, sm.amc, sm.category_norm,
                   sm.plan_type, sm.option_type,
                   ms.inception_date, ms.has_full_history
            FROM mf_scheme_master sm
            LEFT JOIN mf_schemes ms ON sm.scheme_code = ms.scheme_code
            WHERE sm.scheme_code IN ({ph})""",
        params=scheme_codes,
    )
    metrics = read_sql(
        f"""SELECT * FROM mf_metrics WHERE scheme_code IN ({ph})
            AND as_of_date = (SELECT MAX(as_of_date) FROM mf_metrics)""",
        params=scheme_codes,
    )

    info_by_code = {r["scheme_code"]: r for _, r in info.iterrows()}
    metrics_by_code = {r["scheme_code"]: r for _, r in metrics.iterrows()}

    schemes = []
    for code in scheme_codes:
        if code not in info_by_code:
            continue
        i = info_by_code[code].replace({float("nan"): None}).to_dict()
        m = metrics_by_code.get(code)
        m = m.replace({float("nan"): None}).to_dict() if m is not None else {}
        schemes.append({"info": i, "metrics": m})

    cats = sorted({s["info"].get("category_norm") for s in schemes if s["info"].get("category_norm")})
    return {"schemes": schemes, "categories_seen": cats}


def get_mf_search(q: str, limit: int = 10) -> list[dict]:
    """Typeahead suggestions for scheme search."""
    if not q or len(q) < 2:
        return []
    df = read_sql(
        """SELECT scheme_code, scheme_name, amc, category_norm
           FROM mf_scheme_master
           WHERE active = 1 AND scheme_name LIKE ?
           ORDER BY LENGTH(scheme_name) ASC LIMIT ?""",
        params=[f"%{q}%", limit],
    )
    return df.to_dict("records")
