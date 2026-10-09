"""
alpha-research — the read-only MCP surface over what alpha-signal knows (plan 0016 §4).

    python -m alpha_mcp.research        # stdio server

Every tool reads through views.py / the cockpit query functions / the factor
registry on a read-only connection (_core.install_readonly). No tool writes.
"""
import glob
import json
import re
from pathlib import Path

from alpha_mcp import _core
from alpha_mcp._core import ROOT, page as _page, resolve_sid, today_iso

_core.install_readonly()

import db                                   # noqa: E402  (after install_readonly)
import factors                              # noqa: E402
from config import MISSING_FACTOR_SCORE      # noqa: E402
import views                                # noqa: E402
from mcp.server.fastmcp import FastMCP      # noqa: E402

INSTRUCTIONS = """\
Alpha Signal v2: daily factor-model stock picks for Indian equities (NSE universe of 2,448 stocks, ETFs excluded).

Tiers: every stock has a cap tier (LARGE = top 100 by market cap, MID = 101-250, SMALL = the rest, MICRO = a carved-out
illiquid slice that is never pickable). Ranking is ONLY within a tier: rank 1 LARGE and rank 1 SMALL are not comparable.

Score: final_score = base_score (0-1) minus any forensic penalty. base_score is the weighted average of the stock's
within-tier percentile on each WIRED factor (a negative weight inverts the percentile; a factor with no value counts as 0.5). pick_breakdown shows the exact
per-factor contributions.

Pick gate: a published pick has integrity_status != FAIL (the screener already required enough factor coverage,
price history and fundamentals before writing it). picks(gated=true) is
the published set; gated=false is every ranked stock.

Factors: WIRED = nonzero production weight in some tier (it moves ranks). LIBRARY/PROPOSED/BLOCKED/SUPERSEDED/CONTROL =
benched (computed and backtested, NOT used to rank). Evidence = t-stat of
the monthly rank IC per tier (ic_evidence); the promotion bar is |t| >= 2.5 plus a multiple-testing haircut.

Units: market_cap_cr and *_cr fields are Rs crore (1 Cr = 10 million rupees). Prices are rupees. *_pct and return_* are
percent. Dates are ISO (YYYY-MM-DD). Every result carries `as_of`: the date the data describes.

Rules for anything you write from these results: quote numbers exactly as returned, never invent or extrapolate a
number, and say which tool (and as_of date) a figure came from. Dossier narratives deliberately contain no numbers.
Physical table names in `sql`/`schema` are changing under plan 0017; prefer the named tools.
"""

mcp = FastMCP("alpha-research", instructions=INSTRUCTIONS)
tool = lambda **kw: _core.tool(mcp, "research", **kw)    # noqa: E731

_PICK_FIELDS = ["sid", "ticker", "name", "cap_tier", "sector", "rank", "final_score", "base_score",
                "forensic_adj", "eligible_coverage", "integrity_status",
                "market_cap_cr", "pe_ratio", "pb_ratio", "roe"]


def _api():
    import cockpit.api as api
    return api


def _latest_pick_date():
    d = views.latest_pick_date()
    if d is None:
        raise ValueError("no picks have been computed yet")
    return d


# ═══════════════════════════ picks and stocks ═══════════════════════════

@tool()
def picks(date: str | None = None, tier: str | None = None, gated: bool = True, top: int = 10) -> dict:
    """Ranked picks for one date (default: the latest), best first within each tier.

    date: YYYY-MM-DD pick date (see pick_dates). tier: LARGE | MID | SMALL (default: all pickable tiers).
    gated: true = the published set (integrity not FAIL); false = every ranked stock.
    top: stocks per tier (max 100).
    Fields: rank (1 = best in tier), final_score / base_score (0-1), forensic_adj (penalty subtracted),
    eligible_coverage (0-1: share of the factor weight that applies to the stock which had a value — the data
    behind the pick), market_cap_cr (Rs crore), pe_ratio, pb_ratio, roe (%)."""
    top = max(1, min(int(top), 100))
    if tier:
        tier = tier.upper()
        if tier not in views.tiers():
            raise ValueError(f"unknown tier {tier!r}; one of {views.tiers()}")
    df = views.picks(pick_date=date, gated=gated, tier=tier, per_tier=top)
    as_of = date or _latest_pick_date()
    if df.empty:
        raise ValueError(f"no picks on {as_of}" + ("" if date is None else " — see pick_dates"))
    df = df[[c for c in _PICK_FIELDS if c in df.columns]]
    return {"as_of": as_of, "gated": gated, "per_tier": top,
            "picks": {t: g.to_dict("records") for t, g in df.groupby("cap_tier", sort=False)}}


@tool()
def pick_dates(n: int = 10) -> dict:
    """The newest n pick dates (newest first) and how many stocks were ranked on each."""
    n = max(1, min(int(n), 60))
    dates = views.pick_dates(n)
    return {"as_of": dates[0] if dates else None,
            "items": [{"pick_date": d, "ranked": views.pick_count(d)} for d in dates]}


def _replay_frame(date):
    import pandas as pd
    rows = db.rows("SELECT sid, rank, final_score, cap_tier, inputs_json, output_json "
                   "FROM pit_replay_snapshots WHERE snapshot_date = ?", [date])
    if not rows:
        return None
    return pd.DataFrame([{**json.loads(r["inputs_json"] or "{}"), "_rank": r["rank"],
                          "_final": r["final_score"], **{f"_{k}": v for k, v in
                                                         json.loads(r["output_json"] or "{}").items()}}
                         for r in rows])


@tool()
def pick_breakdown(stock: str, date: str | None = None) -> dict:
    """Why a stock ranks where it does: the exact per-factor decomposition of its score on a pick date.

    For each WIRED factor in the stock's tier: its raw value, its within-tier percentile (0-1, higher = better
    before sign), the tier weight, and contribution = |weight| x percentile (x (1 - percentile) for a negative
    weight). A factor with no value for the stock contributes as if the stock sat in the middle of its tier
    (tier_percentile is null). base_score = sum(contributions) / sum(|weights|). Rebuilt from the screener's
    frozen inputs for that date (pit_replay_snapshots); `reproduces_stored_score` checks it against the stored score.
    Also lists the tier's top 3 for comparison. stock: sid or NSE ticker."""
    sid = resolve_sid(stock)
    date = date or _latest_pick_date()
    out = views.pick_breakdown(sid, date)   # the ONE breakdown, shared with the stock page
    if out is None:
        if _replay_frame(date) is None:
            raise ValueError(f"no frozen screener inputs for {date} (pit_replay_snapshots) — try pick_dates")
        raise ValueError(f"{sid} was not ranked on {date}")
    for c in out["contributions"]:
        c.pop("eligible", None)   # the page's flag; not part of this tool's contract
    out["note"] = ("contributions sum to base_score x (sum of |weights|); a factor with no value counts as "
                   "the middle of the tier (0.5), so missing data pulls a score towards the middle")
    return out


@tool()
def stock(stock: str) -> dict:
    """One stock now: identity (sid, ticker, name, sector, industry, cap_tier), fundamentals snapshot
    (market_cap_cr in Rs crore, pe_ratio, pb_ratio, roe %, debt_to_equity), its newest pick row (final_score,
    rank within tier, pick_date, `data` = the data behind the pick: score 0-100 = share of applicable factor
    weight that had a value, factors_used / factors_applicable, missing factors), newest display-signal values,
    latest close (Rs) and price metrics
    (return_1m/3m/6m/1y in %, 52-week range, rsi_14), plus whether a current dossier exists. stock: sid or ticker."""
    sid = resolve_sid(stock)
    s = views.stock(sid)
    s.update(views.price_metrics([sid]).get(sid, {}))
    for k in ("created_at", "updated_at", "mc_slug", "mc_checked_at", "slug"):
        s.pop(k, None)
    s["has_dossier"] = bool(views.published_dossier(views.dossier_index().get(sid)))
    s["as_of"] = s.get("price_date") or s.get("pick_date")
    return s


@tool()
def search_stocks(q: str) -> dict:
    """Find stocks by partial ticker or company name (max 20). Returns sid (use it in other tools), ticker,
    name, sector, cap_tier."""
    if len((q or "").strip()) < 2:
        raise ValueError("q needs at least 2 characters")
    return {"as_of": today_iso(), "items": _api().search_stocks(q.strip())}


@tool()
def stock_financials(stock: str, kind: str = "quarterly") -> dict:
    """Reported financials. kind=quarterly: last 10 quarters of the income statement (revenue, net_income,
    ebitda, operating_profit in Rs crore; eps in Rs) + TTM and YoY growth (%). kind=annual: last 5 years of
    balance sheet + cash flow (Rs crore) + derived ratios. Consolidated where available, else standalone."""
    sid = resolve_sid(stock)
    api = _api()
    if kind == "quarterly":
        out = api.get_quarterly_financials(sid)
        as_of = (out.get("quarters") or [{}])[0].get("end_date")
    elif kind == "annual":
        out = api.get_annual_financials(sid)
        as_of = None
        for part in out.values():
            if isinstance(part, list) and part and isinstance(part[0], dict):
                as_of = part[0].get("end_date")
                break
    else:
        raise ValueError("kind must be 'quarterly' or 'annual'")
    return {"as_of": as_of, "sid": sid, "kind": kind, **out}


@tool()
def stock_ownership(stock: str) -> dict:
    """Who owns and trades the stock: last 6 quarters of shareholding (promoter/FII/MF/DII/public/pledge, % of
    equity, with *_qoq change in percentage points), 24 months of insider trades by month (buy_value/sell_value
    in Rs lakh), and the 10 most recent bulk/block deals (quantity in shares, price in Rs)."""
    sid = resolve_sid(stock)
    api = _api()
    sh = api.get_shareholding_history(sid)
    return {"as_of": sh[0]["end_date"] if sh else None, "sid": sid, "shareholding": sh,
            "insider_by_month": api.get_insider_timeline(sid), "bulk_deals": api.get_bulk_deals(sid)}


@tool()
def stock_news(stock: str, days: int = 30, limit: int = 20) -> dict:
    """News articles tagged to the stock in the last `days` days (newest first, max 50), with the enrichment
    one_liner, sentiment and primary_topic when the classifier has processed the article."""
    sid = resolve_sid(stock)
    rows = db.rows(
        "SELECT na.article_id, na.title, na.source, na.published_at, na.url, "
        "ne.one_liner, ne.sentiment, ne.primary_topic "
        "FROM news_articles na JOIN news_article_stocks nas ON na.article_id = nas.article_id "
        "LEFT JOIN news_enriched ne ON ne.article_id = na.article_id "
        "WHERE nas.sid = ? AND na.published_at >= date('now', ?) "
        "ORDER BY na.published_at DESC LIMIT ?",
        [sid, f"-{max(1, int(days))} days", max(1, min(int(limit), 50))])
    return {"as_of": today_iso(), "sid": sid, "days": days, "items": rows}


@tool()
def stock_analyst(stock: str) -> dict:
    """Sell-side view: current consensus (price_target in Rs, total_analysts, buy %, rating mix, pt_upside %) and
    the EPS / revenue forecast revision history. Analyst targets are episodic (revised quarterly at best)."""
    sid = resolve_sid(stock)
    api = _api()
    cons = api.get_analyst_consensus(sid)
    trend = api.get_forecast_trend(sid)
    trend = {k: v[-24:] for k, v in trend.items()}
    return {"as_of": cons.get("fetched_at"), "sid": sid,
            "consensus": cons, "forecast_trend": trend}


@tool()
def stock_lineage(stock: str, factor: str | None = None) -> dict:
    """Data lineage for the stock. Without `factor`: which factors have lineage (registry = declared source
    tables/columns; emitted = the actual source rows the last computation used, top ~300 stocks only). With
    `factor`: that factor's declared inputs and its emitted source rows (table, key, columns, contribution)."""
    sid = resolve_sid(stock)
    lin = _api().get_stock_lineage(sid)
    dyn, static = lin.get("dynamic_lineage") or {}, lin.get("static_registry") or {}
    base = {"as_of": today_iso(), "sid": sid, "in_active_universe": lin.get("in_active_universe"),
            "mixed_source_tables": lin.get("mixed_source_tables")}
    if not factor:
        return {**base, "factors_with_emitted_rows": sorted(dyn), "factors_in_registry": sorted(static),
                "hint": "pass factor=<name> for its inputs and source rows"}
    if factor not in dyn and factor not in static:
        raise ValueError(f"no lineage for factor {factor!r}; known: {sorted(set(dyn) | set(static))}")
    return {**base, "factor": factor, "registry": static.get(factor), "emitted": dyn.get(factor)}


def _dossier_on(sid, date):
    path = ROOT / "output" / f"dossiers_{date}.json"
    if not path.exists():
        raise ValueError(f"no dossier file for {date}")
    from datetime import date as _d
    for d in json.loads(path.read_text()):
        if d.get("sid") == sid and d.get("thesis"):
            fd = _d.fromisoformat(date)
            return views.published_dossier((d, fd, (_d.today() - fd).days))
    return {}


@tool()
def dossier(stock: str, date: str | None = None) -> dict:
    """The stock's published research dossier (LLM-written thesis, bull/bear case, catalysts, risks, plus
    structured target_price / stop_loss in Rs). Default: the newest one at most 3 days old. Narrative fields
    never contain numbers by design; numbers live only in the structured fields. Returns an error if none is
    current or it failed validation."""
    sid = resolve_sid(stock)
    d = _dossier_on(sid, date) if date else views.published_dossier(views.dossier_index().get(sid))
    if not d:
        raise ValueError(f"no current, validated dossier for {sid}" + (f" on {date}" if date else
                         " (dossiers are written for published picks; the LLM step may be down)"))
    return d


@tool()
def price_series(stock: str, days: int = 90) -> dict:
    """Daily OHLCV (Rs, shares) and delivery_pct (%) for the last `days` trading days (max 400), oldest first."""
    sid = resolve_sid(stock)
    rows = _api().get_price_series_extended(sid, max(1, min(int(days), 400)))
    return {"as_of": rows[-1]["date"] if rows else None, "sid": sid, "items": rows}


# ═══════════════════════════ model and evidence ═══════════════════════════

def _best_ic():
    from cockpit_ops.api import best_ic_by_signal
    return best_ic_by_signal(per_tier=True)


@tool(name="factors")
def factors_list(status: str | None = None, family: str | None = None) -> dict:
    """The factor registry: every factor's id, label, family, lifecycle status (WIRED moves ranks; LIBRARY /
    PROPOSED / BLOCKED / SUPERSEDED / CONTROL are benched), production weight per tier,
    and best backtest t-stat per tier. Filter by status and/or family (case-insensitive)."""
    ic = _best_ic()
    w = factors.weights()
    items = []
    for fid, f in factors.FACTORS.items():
        st = factors.status(fid)
        if status and st.upper() != status.upper():
            continue
        if family and (f.get("family") or "").lower() != family.lower():
            continue
        key = f.get("weight_key", fid)
        items.append({"id": fid, "label": f.get("label"), "family": f.get("family"), "status": st,
                      "weights": {t: tw[key] for t, tw in w.items() if key in tw} or None,
                      "best_t": {t: r.get("t_stat") for t, r in ic.get(fid, {}).items()} or None})
    return {"as_of": today_iso(), "total": len(items), "items": items}


_FACTOR_KEYS = ("label", "group", "family", "description", "source_tables", "source_columns", "filing_lag",
                "producer", "cadence", "pit_range", "weight_key", "weights", "bench", "tiers",
                "v1_verdict_summary", "freshness_table")


@tool()
def factor(id: str) -> dict:
    """One factor in full: registry definition (description, inputs, filing lag, cadence, weights, bench),
    status, eligibility rule, backtest evidence per tier (t_stat, mean_ic, n_periods, verdict, 95% CI) and the
    horizon/cost gate (gross vs net-of-cost IC per tier)."""
    f = factors.FACTORS.get(id) or factors.PIT_EXTRA.get(id)
    if not f:
        near = [k for k in factors.FACTORS if id.lower() in k.lower()][:10]
        raise ValueError(f"unknown factor {id!r}" + (f" — did you mean {near}" if near else
                                                     " — see factors_list"))
    out = {k: f[k] for k in _FACTOR_KEYS if k in f}
    if f.get("eligibility"):
        out["eligibility"] = f["eligibility"].get("description")
    out.update({"id": id, "status": factors.status(id), "as_of": today_iso(),
                "evidence": _best_ic().get(id, {}),
                "horizon_gate": db.rows(
                    "SELECT cap_tier, source, cadence, natural_horizon, gross_ic, gross_t, net_ic, net_t, "
                    "net_ir_annual, n_periods, sign_stable, verdict, computed_at "
                    "FROM factor_horizon_gate WHERE signal = ? ORDER BY cap_tier", [id])})
    return out


@tool()
def model_weights(scheme: str = "SIGNAL_WEIGHTS") -> dict:
    """Production factor weights per tier (SIGNAL_WEIGHTS, the only scheme). Keys are weight
    keys; negative = inverse factor."""
    if scheme not in factors.WEIGHT_SCHEMES:
        raise ValueError(f"scheme must be one of {factors.WEIGHT_SCHEMES}")
    w = factors.weights(scheme)
    return {"as_of": today_iso(), "scheme": scheme, "weights": w,
            "signal_ids": {t: {k: factors.signal_for(k, t) for k in tw} for t, tw in w.items()}}


@tool()
def ic_evidence(factor: str | None = None, tier: str | None = None, limit: int = 60, offset: int = 0) -> dict:
    """Backtest evidence: the best rank-IC row per (factor, tier): t_stat, mean_ic, n_periods (months),
    verdict, t-stat 95% CI, source. Sorted by |t| descending. Filter by factor id and/or tier."""
    rows = [r for sig, tiers in _best_ic().items() for r in tiers.values()]
    if factor:
        rows = [r for r in rows if r["signal"] == factor]
    if tier:
        rows = [r for r in rows if r["cap_tier"] == tier.upper()]
    rows.sort(key=lambda r: -abs(r.get("t_stat") or 0))
    return {"as_of": today_iso(), **_page(rows, limit, offset)}


@tool()
def regime() -> dict:
    """The market regime from India VIX: regime label, vix_latest, vix_20d_avg, and the capital allocation per
    tier (alloc_large/mid/small, fractions summing to 1)."""
    r = views.regime()
    if not r:
        raise ValueError("regime has never been computed")
    r.pop("color", None)
    r.pop("id", None)
    r["as_of"] = r.get("updated_at")
    return r


@tool()
def changes(days: int = 1, limit: int = 50, offset: int = 0) -> dict:
    """What changed in the model output over the last `days` days (new/dropped picks, rank jumps, flags),
    HIGH severity first."""
    rows = views.changes(max(1, min(int(days), 30)))
    return {"as_of": rows[0].get("change_date") if rows else today_iso(), **_page(rows, limit, offset)}


@tool()
def pick_outcomes() -> dict:
    """Realised performance of past picks: forward return, excess return vs benchmark and hit rate per
    (tier, horizon in trading days), for all picks and for the top-10 book, plus rank-decile spreads."""
    out = _api().get_pick_outcomes_summary()
    return {"as_of": (out or {}).get("as_of"), **(out or {})}


# ═══════════════════════════ portfolio, sectors, macro, news ═══════════════════════════

@tool()
def book() -> dict:
    """The advisory HRP-sized book (latest asof_date): per-name weight (fraction of capital), marginal risk
    contribution, rank and tier, plus sector / tier concentration. Advisory only; no capital deployed."""
    out = _api().get_sized_book()
    if not out:
        raise ValueError("no sized book has been built yet")
    return {"as_of": out.get("asof_date") or out.get("asof"), **out}


@tool()
def risk(stocks: list[str]) -> dict:
    """Risk decomposition for a set of stocks (sids or tickers, max 60): style tilts vs the universe (z-scores),
    sector concentration (HHI; >1500 concentrated, >2500 highly), top-3 sector share and the cap-tier mix."""
    sids = [resolve_sid(s) for s in (stocks or [])[:60]]
    if not sids:
        raise ValueError("pass at least one stock")
    return {"as_of": today_iso(), "sids": sids, **(_api().get_risk_decomposition(sids) or {})}


@tool()
def sectors(by: str = "sector") -> dict:
    """Rollup of today's ranking by sector (by=sector) or industry (by=industry): stock count, market-cap-weighted
    average score, breadth (% of stocks scoring >= 0.55), macro signal and top-3 tickers."""
    if by not in ("sector", "industry"):
        raise ValueError("by must be 'sector' or 'industry'")
    out = _api().get_group_overview(by)
    return {"as_of": _latest_pick_date(), "by": by, "items": out if isinstance(out, list) else out}


@tool()
def sector(name: str) -> dict:
    """One sector: its brief (bucket BOOMING/LIKELY/HEADWIND/QUIET, macro score and drivers, breadth, top picks),
    the narrative (manual or auto), the last 90 days of material regulatory signals (direction +1/-1) and the
    macro indicators that feed its macro score (weight, latest value)."""
    api = _api()
    digest = api.get_sector_digest()
    brief = None
    for bucket, entries in (digest.get("buckets") or {}).items():
        for e in entries:
            if (e.get("sector") or "").lower() == name.lower():
                brief = {**e, "bucket": bucket}
    if brief is None:
        known = sorted({e.get("sector") for es in (digest.get("buckets") or {}).values() for e in es})
        raise ValueError(f"unknown sector {name!r}; one of {known}")
    name = brief["sector"]
    return {"as_of": digest.get("snapshot_date"), "sector": name, "brief": brief,
            "narrative": views.sector_narrative(name),
            "regulatory": api.get_sector_regulatory(name, n=15, material=True),
            "macro_contributors": api.get_sector_macro_contributors(name)}


@tool()
def macro(indicator: str | None = None, months: int = 12) -> dict:
    """Macro indicators. Without `indicator`: the latest reading + signal of every indicator. With one: its
    monthly history over `months` months (value, yoy_change and mom_change in %, unit, source)."""
    if not indicator:
        rows = db.rows("SELECT indicator, signal, value, detail, snapshot_date FROM macro_indicators "
                       "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM macro_indicators) "
                       "ORDER BY indicator")
        return {"as_of": rows[0]["snapshot_date"] if rows else None, "items": rows,
                "available_history": [r["indicator_id"] for r in db.rows(
                    "SELECT DISTINCT indicator_id FROM macro_history ORDER BY 1")]}
    rows = db.rows("SELECT date, value, yoy_change, mom_change, unit, source FROM macro_history "
                   "WHERE indicator_id = ? AND date >= date('now', ?) ORDER BY date",
                   [indicator, f"-{max(1, min(int(months), 240))} months"])
    if not rows:
        raise ValueError(f"no history for indicator {indicator!r} — call macro() for the list")
    meta = db.one("SELECT name, category, frequency, unit, description FROM macro_indicator_meta "
                  "WHERE indicator_id = ?", [indicator])
    return {"as_of": rows[-1]["date"], "indicator": indicator, "meta": meta, "items": rows}


@tool()
def news(topic: str | None = None, q: str | None = None, hours: int = 72, page: int = 1,
         page_size: int = 20) -> dict:
    """Enriched market news, ranked (relevance x recency x source tier). topic: macro, global_economy,
    india_markets, finance, earnings, deals, ai_tech, politics, energy, consumer, industrial, pharma_health, other.
    q: text search. hours: look-back window (max 720). Each item has one_liner, why_it_matters, sentiment."""
    out = _api().get_news_feed(topic=topic, q=q, hours=max(1, min(int(hours), 720)),
                               page=max(1, int(page)), page_size=max(1, min(int(page_size), 40)))
    keep = ("article_id", "title", "source", "published_at", "url", "primary_topic", "one_liner",
            "why_it_matters", "what_to_watch", "sentiment", "confidence", "key_numbers", "keywords",
            "hours_old", "stocks")
    items = [{k: c.get(k) for k in keep if k in c} for c in out.get("items") or out.get("cards") or []]
    meta = {k: v for k, v in out.items() if k not in ("items", "cards", "topics", "topic_counts")}
    return {"as_of": today_iso(), **meta, "items": items}


@tool()
def news_brief(date: str | None = None) -> dict:
    """The daily news brief (THE BIG ONE, FIVE FAST, ONE TO WATCH, ZOOM OUT), newest or for a given date."""
    b = _api().get_news_brief(date)
    if not b:
        raise ValueError("no news brief" + (f" for {date}" if date else " has been generated"))
    return {"as_of": b.get("brief_date"), **b}


@tool()
def regulatory(sector: str | None = None, days: int = 30, material: bool = False, limit: int = 30,
               offset: int = 0) -> dict:
    """Classified regulatory events (policy, RBI/SEBI, duties, court orders) and their sector impact:
    direction (+1 good / -1 bad for the sector), magnitude (minor <5% / moderate 5-10% / major >10% potential),
    time_horizon, confidence, one-line reasoning. material=true keeps major/moderate + high/medium confidence."""
    where = ["julianday('now') - julianday(re.published_at) <= ?"]
    params = [max(1, min(int(days), 365))]
    if sector:
        from cockpit.api import _REGULATORY_SECTOR_ALIASES
        al = _REGULATORY_SECTOR_ALIASES.get(sector, [sector])
        where.append(f"rs.sector IN ({','.join('?' * len(al))})")
        params += al
    if material:
        where.append("rs.magnitude IN ('major','moderate') AND rs.confidence IN ('high','medium')")
    rows = db.rows(
        "SELECT re.event_id, re.published_at, re.title, re.source, re.ministry, rs.sector, rs.stage, "
        "rs.direction, rs.magnitude, rs.time_horizon, rs.confidence, rs.ai_reasoning "
        "FROM regulatory_events re JOIN regulatory_signals rs ON rs.event_id = re.event_id "
        f"WHERE {' AND '.join(where)} ORDER BY julianday(re.published_at) DESC LIMIT 1000", params)
    return {"as_of": today_iso(), **_page(rows, limit, offset)}


@tool()
def mf_search(q: str) -> dict:
    """Find mutual-fund schemes by name (max 20): scheme_code (use it in `mf`), scheme_name, amc, category."""
    from cockpit.mf import get_mf_search
    return {"as_of": today_iso(), "items": get_mf_search(q, limit=20)}


@tool()
def mf(scheme_code: str) -> dict:
    """One mutual-fund scheme: identity (AMC, category, plan/option, aum_cr in Rs crore, expense_ratio %,
    benchmark), latest metrics (returns %, risk, scorer breakdown) and calendar-year returns vs benchmark (%)."""
    from cockpit.mf import get_mf_detail
    d = get_mf_detail(str(scheme_code))
    if not d:
        raise ValueError(f"unknown scheme_code {scheme_code!r} — use mf_search")
    return {"as_of": (d.get("metrics") or {}).get("as_of_date"), **d}


# ═══════════════════════════ raw SQL ═══════════════════════════

@tool()
def sql(query: str, max_rows: int = 100) -> dict:
    """Run ONE read-only SELECT/WITH statement (max 500 rows, 20 s). Use when no named tool answers the
    question. Table names are physical and CHANGING under plan 0017 (old names survive as compatibility views
    until each is dropped) — call `schema` first, and prefer the named tools."""
    df, err = db.safe_read_sql(query, max_rows=max(1, min(int(max_rows), 500)))
    if err:
        raise ValueError(err)
    return {"as_of": today_iso(), "columns": list(df.columns), "rows": df.to_dict("records"),
            "row_count": len(df)}


@tool()
def schema(table: str | None = None) -> dict:
    """Without `table`: every table with its registry description, kind and row-count class. With one: its
    columns (name, type, pk) and full registry entry. Physical names change under plan 0017."""
    import tables
    if not table:
        names = [r["name"] for r in db.rows(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {"as_of": today_iso(), "total": len(names),
                "items": [{"table": n, "description": (tables.TABLES.get(n) or {}).get("description"),
                           "kind": (tables.TABLES.get(n) or {}).get("kind")} for n in names]}
    if not db.one("SELECT 1 AS ok FROM sqlite_master WHERE type IN ('table','view') AND name = ?", [table]):
        raise ValueError(f"no table {table!r} — call schema() for the list")
    cols = db.rows(f"SELECT name, type, pk, \"notnull\" FROM pragma_table_info('{table}')")
    entry = {k: v for k, v in (tables.TABLES.get(table) or {}).items() if k != "contract"}
    return {"as_of": today_iso(), "table": table, "columns": cols, "registry": entry}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
