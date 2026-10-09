"""
Alpha Signal Cockpit — FastAPI Application

Bloomberg-inspired stock intelligence dashboard.
Reads from v2 SQLite database via api.py.

Run: uvicorn cockpit.app:app --host 0.0.0.0 --port 3000 --reload
"""

import datetime as dt
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from webauth import LoginRequired

import views
from cockpit import api, pages
from cockpit._shared import COCKPIT_STATIC, COCKPIT_TEMPLATES, make_templates, nav_model, prewarm
from cockpit_ops.api import get_model_overview

app = FastAPI(title="Alpha Signal Cockpit")
# Gzip every response > 1KB — /explorer is 1.27MB of HTML (same as ops).
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(LoginRequired, app_name="Cockpit")     # webauth.py — password login (review F5)
app.mount("/static", StaticFiles(directory=COCKPIT_STATIC), name="static")

templates = make_templates([COCKPIT_TEMPLATES], nav=nav_model(pages.PAGES, pages.OTHER_APP, pages.BRAND))


# ────────────── Startup cache warmer ──────────────
# When uvicorn boots (or restarts via systemd), the in-process TTL caches
# in api.py are empty. The first user to visit any page would otherwise
# trigger a 5-37s cold-cache compute. Background-warm the expensive ones
# at startup so the first visit is always fast.
@app.on_event("startup")
def _prewarm_cache():
    # Ops-domain warmers (data_freshness, db_summary, data_health_scores,
    # factor_health, model_overview, flow_overview, command_centre,
    # health_overview, pipeline_status) moved to cockpit_ops/app.py during
    # Stage 2 split (2026-05-26).
    prewarm([
        ("top_picks",          lambda: api.get_top_picks()),
        ("action_candidates",  lambda: api.get_action_candidates()),
        ("model_portfolio",    lambda: api.get_model_portfolio()),
        ("news_pool_168",      lambda: api._get_news_pool(hours=168)),
        ("news_pool_720",      lambda: api._get_news_pool(hours=720)),
        ("portfolio_bundle",   lambda: api.get_portfolio_bundle()),
    ])


# Slide-style "headline + body" split for sector narrative bullets.
# Narratives concatenate headline + elaboration with em-dashes / colons / first-sentence breaks.
# slidify lifts the headline so templates can render bold-then-muted (progressive elaboration).
def _slidify(text):
    if not isinstance(text, str):
        return {"head": "", "body": ""}
    t = text.strip()
    if not t:
        return {"head": "", "body": ""}
    for sep in (" — ", " – ", " - "):
        if sep in t:
            h, _, b = t.partition(sep)
            h, b = h.strip().rstrip(".,;"), b.strip()
            # Lopsided split: short trailing qualifier after a long head.
            # If the trailer has a number ("3× the global average"), it's a punchy stat → swap so it leads.
            # If it has none ("a new post-COVID high"), it's a weak qualifier → keep whole sentence.
            if len(b) < 35 and len(h) > 100:
                if any(c.isdigit() for c in b):
                    return {"head": b.rstrip("."), "body": h}
                return {"head": t, "body": ""}
            return {"head": h, "body": b}
    if ": " in t:
        h, _, b = t.partition(": ")
        if 4 <= len(h) <= 80 and b:
            return {"head": h.strip(), "body": b.strip()}
    import re as _re
    m = _re.search(r"\.\s+(?=[A-Z(])", t)
    if m and 30 <= m.start() <= 140 and len(t) - m.end() >= 20:
        return {"head": t[: m.start()].strip() + ".", "body": t[m.end():].strip()}
    return {"head": t, "body": ""}


def _sentences(text, max_slides=5):
    if not isinstance(text, str) or not text.strip():
        return []
    import re as _re
    parts = _re.split(r"(?<=[.!?])\s+(?=[A-Z(₹])", text.strip())
    return [_slidify(s) for s in parts[:max_slides] if s.strip()]


templates.env.filters["slidify"] = _slidify
templates.env.filters["sentences"] = _sentences


# Build a URL on the current request preserving all query params except one,
# which gets set/unset. Used by /news for chip/tab/pagination links so each
# action keeps the rest of the user's filter state. Pass value="" to drop a key.
from urllib.parse import urlencode
def _url_keep(key, value):
    req = _current_request.get()
    if req is None:
        return f"?{key}={value}" if value not in ("", None) else "?"
    params = dict(req.query_params)
    # Reset pagination whenever any non-"page" filter changes
    if key != "page":
        params.pop("page", None)
    if value in ("", None, 0):
        params.pop(key, None)
    else:
        params[key] = str(value)
    base = req.url.path
    return f"{base}?{urlencode(params)}" if params else base
templates.env.globals["url_keep"] = _url_keep

# Track current request for url_keep — set by a tiny middleware.
import contextvars
_current_request: "contextvars.ContextVar[Request | None]" = contextvars.ContextVar(
    "current_request", default=None
)

@app.middleware("http")
async def _bind_request(request: Request, call_next):
    token = _current_request.set(request)
    try:
        return await call_next(request)
    finally:
        _current_request.reset(token)


# ── Page Routes ──

@app.get("/", response_class=HTMLResponse)
def morning_brief(request: Request):
    regime = api.get_regime()
    picks = api.get_top_picks(top=5)
    pick_date = api.latest_pick_date()
    stock_count = views.pick_count(pick_date)
    changes = api.get_changes()
    earnings = api.get_earnings_upcoming()

    # Enrich each pick with price metrics + analyst consensus + dossier —
    # one batched query per source for all 15 picks, not 4 queries per pick.
    sids = [s["sid"] for stocks in picks.values() for s in stocks]
    pm = api.get_stock_price_metrics_batch(sids)
    ac = api.get_analyst_consensus_batch(sids)
    dominant = api.get_dominant_signal_batch(sids)
    for tier, stocks in picks.items():
        for stock in stocks:
            sid = stock["sid"]
            stock["pm"] = pm.get(sid, {})
            stock["ac"] = ac.get(sid, {})
            stock["dossier"] = api.get_dossier(sid)
            stock["dominant_signal"] = dominant.get(sid, "")

    # Market pulse
    sectors = api.get_group_overview("sector")
    tailwinds = sum(1 for s in sectors if s.get("macro_signal") in ("TAILWIND", "FAVORABLE"))
    headwinds = sum(1 for s in sectors if s.get("macro_signal") in ("HEADWIND", "ADVERSE"))

    return templates.TemplateResponse(request, "morning_brief.html", {
        "regime": regime, "picks": picks, "pick_date": pick_date,
        "stock_count": stock_count, "changes": changes, "earnings": earnings,
        "tailwinds": tailwinds, "headwinds": headwinds,
        "page": "brief",
    })


@app.get("/actions", response_class=HTMLResponse)
def actions(request: Request):
    # Copy, don't mutate: get_action_candidates() hands back its cached dicts
    # and handlers now run concurrently in the threadpool.
    action_data = {k: [dict(s) for s in v] if isinstance(v, list) else v
                   for k, v in api.get_action_candidates().items()}
    # Enrich each candidate — one batched query per source, not 4 per stock.
    sids = [s.get("sid") for sec in ("buy", "watch", "exit") for s in action_data.get(sec, [])]
    pm = api.get_stock_price_metrics_batch(sids)
    ac = api.get_analyst_consensus_batch(sids)
    insider = api.get_insider_signal_batch(sids)
    for section in ["buy", "watch", "exit"]:
        for stock in action_data.get(section, []):
            sid = stock.get("sid")
            if sid:
                stock["pm"] = pm.get(sid, {})
                stock["ac"] = ac.get(sid, {})
                stock["dossier"] = api.get_dossier(sid)
                stock["insider_desc"] = insider.get(sid, {}).get("description", "")
    return templates.TemplateResponse(request, "action_queue.html", {
        "page": "actions", "actions": action_data,
    })


@app.get("/explorer", response_class=HTMLResponse)
def explorer(request: Request):
    tiers = api.get_heatmap_data()
    return templates.TemplateResponse(request, "explorer.html", {
        "page": "explorer", "tiers": tiers, "pick_date": api.latest_pick_date(),
    })


@app.get("/explorer/{sid}", response_class=HTMLResponse)
def stock_detail(request: Request, sid: str):
    detail = api.get_stock_detail(sid)
    if not detail:
        return HTMLResponse("<h1>Stock not found</h1>", status_code=404)

    # Enrich with all new data
    detail["pm"] = api.get_stock_price_metrics(sid)
    detail["ac"] = api.get_analyst_consensus(sid)
    detail["shareholding"] = api.get_shareholding_history(sid)
    detail["insider"] = api.get_insider_activity(sid)
    detail["insider_timeline"] = api.get_insider_timeline(sid)
    detail["news"] = api.get_stock_news(sid)
    detail["bulk_deals"] = api.get_bulk_deals(sid)
    detail["regulatory"] = api.get_sector_regulatory(detail.get("sector"), n=8, material=True)
    detail["earnings"] = api.get_earnings_upcoming(sid)
    detail["dossier"] = api.get_dossier(sid)
    detail["management"] = api.get_management_score(sid)
    detail["managerial_ability"] = api.get_managerial_ability(sid)
    detail["financial_management"] = api.get_financial_management(sid)
    detail["quarterly"] = api.get_quarterly_financials(sid)
    detail["annual"] = api.get_annual_financials(sid)
    detail["forecasts"] = api.get_forecast_trend(sid)
    detail["sector_comp"] = api.get_sector_comparison(sid, detail.get("sector"))
    detail["tooltips"] = api.SIGNAL_TOOLTIPS
    detail["metric_tooltips"] = api.METRIC_TOOLTIPS
    detail["signal_descriptions"] = api.SIGNAL_DESCRIPTIONS
    detail["piotroski_factors"] = api.PIOTROSKI_FACTORS

    # Sector averages for comparison
    sector_avgs = api.get_sector_averages()
    detail["sector_avg"] = sector_avgs.get(detail.get("sector"), {})

    # Approximate P/E from earnings yield
    ey = detail.get("earnings_yield") or (detail.get("pm", {}).get("earnings_yield"))
    if ey and ey > 0:
        detail["approx_pe"] = round(1 / ey, 1)

    from datetime import date as _date
    return templates.TemplateResponse(request, "stock_detail.html", {
        "stock": detail, "page": "explorer",
        "today_iso": _date.today().isoformat(),
    })


@app.get("/portfolio", response_class=HTMLResponse)
def portfolio(request: Request):
    bundle = api.get_portfolio_bundle()
    return templates.TemplateResponse(request, "portfolio.html", {
        "page": "portfolio",
        "regime": bundle["regime"],
        "portfolio": bundle["portfolio"],
        "analytics": bundle["analytics"],
        "sized_book": bundle.get("sized_book"),
    })


def _group_detail(by, name):
    """The /sectors detail pane for one industry (with its parent sector's macro
    and regulatory context) or one sector — also served as the stock page's lazy
    industry card."""
    parent = api.get_industry_parent_sector(name) if by == "industry" else None
    context = parent if by == "industry" else name
    return {
        "name": name,
        "parent_sector": parent,
        "narrative": api.get_group_metadata(name),
        "top_players": api.get_group_top_players(by, name, n=10),
        **({"competitive_landscape": api.get_industry_competitive_landscape(name)}
           if by == "industry" else {}),
        "picks": api.get_group_picks(by, name, top_n=10, bottom_n=5),
        "factor_means": api.get_group_factor_means(by, name),
        "macro_contributors": api.get_sector_macro_contributors(context) if context else [],
        "regulatory": api.get_sector_regulatory(context, n=10) if context else [],
    }


@app.get("/sectors", response_class=HTMLResponse)
def sectors(request: Request, sector: str = "", industry: str = ""):
    # Industry-first overview (drill-down primary); sectors as grouping
    industries_data = api.get_group_overview("industry")
    industry_list = api.get_group_list("industry")
    sector_list = api.get_group_list("sector")

    detail = None
    if industry and industry in industry_list:
        detail = _group_detail("industry", industry)
    elif sector and sector in sector_list:
        # Back-compat: ?sector=X falls back to sector-level detail
        detail = _group_detail("sector", sector)

    digest = api.get_sector_digest()

    return templates.TemplateResponse(request, "sectors.html", {
        "page": "sectors",
        "industries": industries_data,
        "industry_list": industry_list,
        "sector_list": sector_list,
        "selected_industry": industry,
        "selected_sector": sector,
        "detail": detail,
        "digest": digest,
    })


@app.get("/partial/industry-card/{industry}", response_class=HTMLResponse)
def partial_industry_card(request: Request, industry: str, sid: str = ""):
    """Full industry dossier fragment, lazy-loaded into the stock page's Sector
    tab. Renders the SAME shared _industry_detail.html partial that /sectors uses
    (metric strip, conviction bar, Overview/Players/Trends/Our-Picks sub-tabs,
    thesis, value chain, competitive landscape, picks, macro, regulatory) — so the
    stock page shows identical full detail, no drift."""
    return templates.TemplateResponse(request, "_industry_detail.html", {
        "detail": _group_detail("industry", industry),
        "industries": api.get_group_overview("industry"),
        "industry_list": api.get_group_list("industry"),
        "current_sid": sid,
        "embed": True,
    })


@app.get("/partial/sector-card/{sector}", response_class=HTMLResponse)
def partial_sector_card(request: Request, sector: str, sid: str = ""):
    """Compact sector dossier fragment, lazy-loaded into the stock page's Sector
    tab (sector context attached to every stock). Peers (with this stock
    highlighted) + our model's top/bottom + macro drivers + recent regulatory,
    plus a link to the full /sectors page."""
    return templates.TemplateResponse(request, "_sector_card.html", {
        "sector": sector,
        "sid": sid,
        "top_players": api.get_group_top_players("sector", sector, n=10),
        "picks": api.get_group_picks("sector", sector, top_n=10, bottom_n=5),
        "macro_contributors": api.get_sector_macro_contributors(sector),
        "regulatory": api.get_sector_regulatory(sector, n=10),
    })


@app.get("/model", response_class=HTMLResponse)
def model_page(request: Request):
    overview = get_model_overview()
    return templates.TemplateResponse(request, "model.html", {
        "page": "model", **overview,
    })


@app.get("/model/outcomes", response_class=HTMLResponse)
def model_outcomes_page(request: Request, n: int = 10):
    """Live equity curve — realized forward returns on actual picks.

    The factor model is hypothesis; this page is the answer. Per-tier × window
    summaries, rank-decile analysis, time-series of top-N basket returns.
    """
    summary = api.get_pick_outcomes_summary(top_n=n)
    return templates.TemplateResponse(request, "model_outcomes.html", {
        "page": "model-outcomes",
        "summary": summary,
        "top_n": n,
    })


@app.get("/api/model/outcomes")
def api_model_outcomes(n: int = 10):
    return api.get_pick_outcomes_summary(top_n=n)


@app.get("/multibagger", response_class=HTMLResponse)
def multibagger_page(request: Request):
    """Multibagger watchlist — the SEPARATE quality-gated funnel (plan 0008),
    kept OUT of daily_picks. Honest framing: the gates are the product (a
    junk-stripped watchlist); the ranking edge is validated weak/regime-dependent
    (ADR 0039), surfaced via the regime banner."""
    overview = api.get_multibagger_overview()
    return templates.TemplateResponse(request, "multibagger.html", {
        "page": "multibagger", "o": overview,
    })


@app.get("/playbooks", response_class=HTMLResponse)
def playbooks_page(request: Request):
    """Investor Playbooks — filters, events and watchlists in the style of well-known
    investors (avoid list, insider buying, compounders, superinvestor holdings).
    Separate from daily_picks; each tab states its own rule."""
    from cockpit import playbooks
    return templates.TemplateResponse(request, "playbooks.html", {"page": "playbooks", "o": playbooks.overview()})


# NOTE: /flow, /command, /system, /sql moved to cockpit_ops (port 3001)
# during Stage 2 split (2026-05-26). Their routes here are removed.


# ── Mutual Fund research section (plan prfect-lets-add-a-zazzy-eich) ──

@app.get("/mutual-funds", response_class=HTMLResponse)
def mutual_funds_page(
    request: Request,
    category: str = None, amc: str = None,
    plan: str = None, option: str = None,
    q: str = None, sort: str = "percentile", page: int = 1,
    show_all: int = 0,
):
    bundle = api.get_mf_universe_overview(
        category=category, amc=amc, plan=plan, option=option,
        q=q, sort=sort, page=page,
        include_non_investable=bool(show_all),
    )
    heatmap = api.get_mf_category_heatmap(include_non_investable=bool(show_all))
    return templates.TemplateResponse(request, "mutual_funds.html", {
        "page": "mutual-funds",
        "bundle": bundle, "heatmap": heatmap,
        "active_category": category, "active_amc": amc,
        "active_plan": plan, "active_option": option, "active_q": q,
        "active_sort": sort, "active_page": page,
        "show_all": show_all,
    })


@app.get("/mutual-funds/compare", response_class=HTMLResponse)
def mutual_fund_compare(request: Request, codes: str = ""):
    """Side-by-side compare. ?codes=A,B,C (2-5 scheme codes)."""
    scheme_codes = [c.strip() for c in (codes or "").split(",") if c.strip()]
    bundle = api.get_mf_compare(scheme_codes) if scheme_codes else {"schemes": [], "categories_seen": []}
    return templates.TemplateResponse(request, "mf_compare.html", {
        "page": "mutual-funds",
        "bundle": bundle,
        "input_codes": ",".join(scheme_codes),
    })


@app.get("/mutual-funds/{scheme_code}", response_class=HTMLResponse)
def mutual_fund_detail(request: Request, scheme_code: str):
    detail = api.get_mf_detail(scheme_code)
    if not detail:
        return HTMLResponse(f"Scheme {scheme_code} not found", status_code=404)
    peers = api.get_mf_peer_rank(scheme_code)
    holdings = api.get_mf_holdings(scheme_code)
    return templates.TemplateResponse(request, "mf_detail.html", {
        "page": "mutual-funds",
        "detail": detail, "peers": peers, "holdings": holdings,
        "scheme_code": scheme_code,
    })


@app.get("/api/mf-nav-series/{scheme_code}")
def api_mf_nav_series(scheme_code: str, days: int = None):
    return api.get_mf_nav_series(scheme_code, days=days)


@app.get("/api/mf-rolling/{scheme_code}")
def api_mf_rolling(scheme_code: str):
    return api.get_mf_rolling_returns(scheme_code)


@app.get("/api/mf-search")
def api_mf_search(q: str = "", limit: int = 10):
    return api.get_mf_search(q, limit=limit)


@app.get("/news", response_class=HTMLResponse)
def news_editor_page(request: Request):
    """Plan 0021: today's three items, the 7 themes, the week's radar and sectors."""
    return templates.TemplateResponse(request, "news.html", {
        "page": "news",
        "today_ed": api.get_news_today(),
        "themes": api.get_news_themes(),
        "week": api.get_news_week(),
        "radar": api.get_sector_radar(),
        "today": dt.date.today().isoformat(),
    })


@app.get("/news/theme/{theme_id}", response_class=HTMLResponse)
def news_theme_page(request: Request, theme_id: str):
    theme = api.get_news_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="No such theme")
    return templates.TemplateResponse(request, "news_theme.html", {"page": "news", "t": theme})


@app.get("/news/all", response_class=HTMLResponse)
def news_page(
    request: Request,
    topic: str = "",
    tier: int = 0,
    q: str = "",
    sentiment: str = "",
    confidence: str = "",
    hours: int = 168,
    sort: str = "smart",
    page: int = 1,
):
    """Flagship news feed: topic tabs, search, sentiment/confidence/tier filters,
    sort modes, server-side pagination. Single-page render, no SPA."""
    feed = api.get_news_feed(
        topic=(topic or None),
        tier=(tier if tier else None),
        q=(q or None),
        sentiment=(sentiment or None),
        confidence=(confidence or None),
        hours=hours,
        sort=sort,
        page=page,
        page_size=24,
    )
    brief = api.get_news_brief()
    return templates.TemplateResponse(request, "news_all.html", {
        "page": "news",
        "feed": feed,
        "brief": brief,
        "topic": topic,
        "active_tier": tier,
        "q": q,
        "active_sentiment": sentiment,
        "active_confidence": confidence,
        "active_hours": hours,
        "active_sort": sort,
        "active_page": page,
    })


# NOTE: /system moved to cockpit_ops (port 3001) during Stage 2 split.
# /api/health/overview also moved.

# ── JSON API Routes ──
# 2026-09-26: removed /api/regime, /api/changes, /api/picks, /api/stock/{sid},
# /api/prices/{sid}, /api/annual/{sid}, /api/sectors, /api/sector-detail/{sector}
# — no template/JS/doc caller and only 127.0.0.1 hits in output/cockpit.log.
# /api/model/outcomes and /api/mf-search stay: both had external hits this month.

@app.get("/api/search")
def api_search(q: str = ""):
    if len(q) < 2:
        return []
    return api.search_stocks(q)

@app.get("/api/prices-extended/{sid}")
def api_prices_extended(sid: str, days: int = 365):
    return api.get_price_series_extended(sid, days=days)

@app.get("/api/quarterly/{sid}")
def api_quarterly(sid: str):
    return api.get_quarterly_financials(sid)

@app.get("/api/shareholding/{sid}")
def api_shareholding(sid: str):
    return api.get_shareholding_history(sid)

@app.get("/api/forecasts/{sid}")
def api_forecasts(sid: str):
    return api.get_forecast_trend(sid)

@app.get("/api/insider-timeline/{sid}")
def api_insider_timeline(sid: str):
    return api.get_insider_timeline(sid)

@app.get("/api/lineage/{sid}")
def api_stock_lineage(sid: str):
    """Per-stock data lineage. See cockpit.api.get_stock_lineage + ADR 0027."""
    return api.get_stock_lineage(sid)

# NOTE: /api/pipeline, /api/pipeline/rerun, /api/health, /sql, /api/sql
# all moved to cockpit_ops (port 3001) during Stage 2 split (2026-05-26).
