"""
Alpha Signal Cockpit — FastAPI Application

Bloomberg-inspired stock intelligence dashboard.
Reads from v2 SQLite database via api.py.

Run: uvicorn cockpit.app:app --host 0.0.0.0 --port 3000 --reload
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from cockpit import api

COCKPIT_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Alpha Signal Cockpit")
app.mount("/static", StaticFiles(directory=COCKPIT_DIR / "static"), name="static")

# Make Jinja2 treat undefined attributes as None instead of erroring
from jinja2 import Undefined
class SilentUndefined(Undefined):
    def __str__(self): return ""
    def __bool__(self): return False
    def __iter__(self): return iter([])
    def __eq__(self, other): return other is None
    def __ne__(self, other): return other is not None
    def __ge__(self, other): return False
    def __le__(self, other): return False
    def __gt__(self, other): return False
    def __lt__(self, other): return False
    def __float__(self): return 0.0
    def __int__(self): return 0
templates = Jinja2Templates(directory=COCKPIT_DIR / "templates")
templates.env.undefined = SilentUndefined


# ────────────── Startup cache warmer ──────────────
# When uvicorn boots (or restarts via systemd), the in-process TTL caches
# in api.py are empty. The first user to visit any page would otherwise
# trigger a 5-37s cold-cache compute. Background-warm the expensive ones
# at startup so the first visit is always fast.
@app.on_event("startup")
def _prewarm_cache():
    """Background-warm expensive TTL caches in PARALLEL so wall-clock matches the
    slowest single warmer (data_health_scores ~19s) rather than the sum (~38s).
    2026-05-25: bumped from sequential after /system cold path was 39s; parallel
    drops it to ~19s, and the cache survives until TTL expiry."""
    import threading
    import concurrent.futures as cf

    # Ops-domain warmers (data_freshness, db_summary, data_health_scores,
    # factor_health, model_overview, flow_overview, command_centre,
    # health_overview, pipeline_status) moved to cockpit_ops/app.py during
    # Stage 2 split (2026-05-26).
    warmers = [
        ("top_picks",          lambda: api.get_top_picks()),
        ("action_candidates",  lambda: api.get_action_candidates()),
        ("model_portfolio",    lambda: api.get_model_portfolio()),
        ("news_pool_168",      lambda: api._get_news_pool(hours=168)),
        ("news_pool_720",      lambda: api._get_news_pool(hours=720)),
        ("portfolio_bundle",   lambda: api.get_portfolio_bundle()),
    ]

    def _warm_one(name, fn):
        import time as _t
        t = _t.time()
        try:
            fn()
            return name, _t.time() - t, None
        except Exception as e:
            return name, _t.time() - t, str(e)

    def _warm():
        import time as _t
        t0 = _t.time()
        # SQLite is single-writer so unbounded parallelism doesn't help and
        # can starve user requests; 4 workers is the sweet spot for our mix.
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(_warm_one, n, f) for n, f in warmers]
            for fut in cf.as_completed(futures):
                name, dt, err = fut.result()
                if err:
                    print(f"  [cache-warm] {name}: FAILED — {err}")
                else:
                    print(f"  [cache-warm] {name}: {dt:.1f}s")
        print(f"  [cache-warm] total wall-clock: {_t.time()-t0:.1f}s")

    threading.Thread(target=_warm, daemon=True).start()


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

# Cache-busting for static assets — appends ?v=<mtime> so browser caches
# invalidate automatically whenever a static file is edited.
def _asset_version(filename: str) -> str:
    p = COCKPIT_DIR / "static" / filename
    try:
        return str(int(p.stat().st_mtime))
    except OSError:
        return "0"
templates.env.globals["asset_version"] = _asset_version


# Build a URL on the current request preserving all query params except one,
# which gets set/unset. Used by /news for chip/tab/pagination links so each
# action keeps the rest of the user's filter state. Pass value="" to drop a key.
from urllib.parse import urlencode
def _url_keep(key, value):
    import contextvars
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
async def morning_brief(request: Request):
    regime = api.get_regime()
    picks = api.get_top_picks(top=5)
    pick_date = api.get_pick_date()
    stock_count = api.get_stock_count()
    changes = api.get_changes()
    earnings = api.get_earnings_upcoming()

    # Enrich each pick with price metrics + analyst consensus + dossier
    for tier, stocks in picks.items():
        for stock in stocks:
            sid = stock["sid"]
            pm = api.get_stock_price_metrics(sid)
            ac = api.get_analyst_consensus(sid)
            dos = api.get_dossier(sid)
            stock["pm"] = pm
            stock["ac"] = ac
            stock["dossier"] = dos
            stock["dominant_signal"] = api.get_dominant_signal(sid)

    # Market pulse
    sectors = api.get_sector_overview()
    tailwinds = sum(1 for s in sectors if s.get("macro_signal") in ("TAILWIND", "FAVORABLE"))
    headwinds = sum(1 for s in sectors if s.get("macro_signal") in ("HEADWIND", "ADVERSE"))

    return templates.TemplateResponse(request, "morning_brief.html", {
        "regime": regime, "picks": picks, "pick_date": pick_date,
        "stock_count": stock_count, "changes": changes, "earnings": earnings,
        "tailwinds": tailwinds, "headwinds": headwinds,
        "page": "brief",
    })


@app.get("/actions", response_class=HTMLResponse)
async def actions(request: Request):
    action_data = api.get_action_candidates()
    # Enrich each candidate
    for section in ["buy", "watch", "exit"]:
        for stock in action_data.get(section, []):
            sid = stock.get("sid")
            if sid:
                stock["pm"] = api.get_stock_price_metrics(sid)
                stock["ac"] = api.get_analyst_consensus(sid)
                stock["dossier"] = api.get_dossier(sid)
                ia = api.get_insider_activity(sid)
                stock["insider_desc"] = ia.get("signal", {}).get("description", "")
    return templates.TemplateResponse(request, "action_queue.html", {
        "page": "actions", "actions": action_data,
    })


@app.get("/explorer", response_class=HTMLResponse)
async def explorer(request: Request):
    tiers = api.get_heatmap_data()
    # Table view data
    table = api.get_explorer_table()
    return templates.TemplateResponse(request, "explorer.html", {
        "page": "explorer", "tiers": tiers, "table": table,
    })


@app.get("/explorer/{sid}", response_class=HTMLResponse)
async def stock_detail(request: Request, sid: str):
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
    detail["regulatory"] = api.get_regulatory_for_sector(detail.get("sector"))
    detail["earnings"] = api.get_earnings_upcoming(sid)
    detail["dossier"] = api.get_dossier(sid)
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
async def portfolio(request: Request):
    bundle = api.get_portfolio_bundle()
    return templates.TemplateResponse(request, "portfolio.html", {
        "page": "portfolio",
        "regime": bundle["regime"],
        "portfolio": bundle["portfolio"],
        "analytics": bundle["analytics"],
    })


@app.get("/sectors", response_class=HTMLResponse)
async def sectors(request: Request, sector: str = "", industry: str = ""):
    # Industry-first overview (drill-down primary); sectors as grouping
    industries_data = api.get_industry_overview()
    industry_list = api.get_industry_list()
    sector_list = api.get_sector_list()

    detail = None
    if industry and industry in industry_list:
        parent_sector = api.get_industry_parent_sector(industry)
        detail = {
            "name": industry,
            "parent_sector": parent_sector,
            "narrative": api.get_industry_metadata(industry),
            "top_players": api.get_industry_top_players(industry, n=10),
            "competitive_landscape": api.get_industry_competitive_landscape(industry),
            "picks": api.get_industry_picks(industry, top_n=10, bottom_n=5),
            "factor_means": api.get_industry_factor_means(industry),
            "macro_contributors": api.get_sector_macro_contributors(parent_sector) if parent_sector else [],
            "regulatory": api.get_sector_recent_regulatory(parent_sector, n=10) if parent_sector else [],
        }
    elif sector and sector in sector_list:
        # Back-compat: ?sector=X falls back to sector-level detail
        detail = {
            "name": sector,
            "parent_sector": None,
            "narrative": api.get_sector_metadata(sector),
            "top_players": api.get_sector_top_players(sector, n=10),
            "picks": api.get_sector_picks(sector, top_n=10, bottom_n=5),
            "factor_means": api.get_sector_factor_means(sector),
            "macro_contributors": api.get_sector_macro_contributors(sector),
            "regulatory": api.get_sector_recent_regulatory(sector, n=10),
        }

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


@app.get("/api/sector-detail/{sector}")
async def api_sector_detail(sector: str):
    """JSON for live tab-2 sector switching without full page reload."""
    return JSONResponse({
        "narrative": api.get_sector_metadata(sector),
        "top_players": api.get_sector_top_players(sector, n=10),
        "picks": api.get_sector_picks(sector, top_n=10, bottom_n=5),
        "factor_means": api.get_sector_factor_means(sector),
        "macro_contributors": api.get_sector_macro_contributors(sector),
        "regulatory": api.get_sector_recent_regulatory(sector, n=10),
    })


@app.get("/model", response_class=HTMLResponse)
async def model_page(request: Request):
    overview = api.get_model_overview()
    return templates.TemplateResponse(request, "model.html", {
        "page": "model", **overview,
    })


@app.get("/model/outcomes", response_class=HTMLResponse)
async def model_outcomes_page(request: Request, n: int = 10):
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
async def api_model_outcomes(n: int = 10):
    return api.get_pick_outcomes_summary(top_n=n)


@app.get("/model/variants", response_class=HTMLResponse)
async def model_variants_page(request: Request, n: int = 10):
    """Side-by-side comparison of production / max-return / max-sharpe weight schemes.

    n: picks per tier per variant (default 10). All three variants run on the
    same universe; production is the live model writing to daily_picks, return
    and sharpe are computed live (cached 30 min).
    """
    bundle = api.get_model_variants(top_per_tier=n)
    return templates.TemplateResponse(request, "model_variants.html", {
        "page": "model-variants",
        "bundle": bundle,
        "n_per_tier": n,
    })


@app.get("/multibagger", response_class=HTMLResponse)
async def multibagger_page(request: Request):
    """Multibagger watchlist — the SEPARATE quality-gated funnel (plan 0008),
    kept OUT of daily_picks. Honest framing: the gates are the product (a
    junk-stripped watchlist); the ranking edge is validated weak/regime-dependent
    (ADR 0039), surfaced via the regime banner."""
    overview = api.get_multibagger_overview()
    return templates.TemplateResponse(request, "multibagger.html", {
        "page": "multibagger", "o": overview,
    })


# NOTE: /flow, /command, /system, /sql moved to cockpit_ops (port 3001)
# during Stage 2 split (2026-05-26). Their routes here are removed.


# ── Mutual Fund research section (plan prfect-lets-add-a-zazzy-eich) ──

@app.get("/mutual-funds", response_class=HTMLResponse)
async def mutual_funds_page(
    request: Request,
    category: str = None, amc: str = None,
    plan: str = None, option: str = None,
    q: str = None, sort: str = "score", page: int = 1,
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
async def mutual_fund_compare(request: Request, codes: str = ""):
    """Side-by-side compare. ?codes=A,B,C (2-5 scheme codes)."""
    scheme_codes = [c.strip() for c in (codes or "").split(",") if c.strip()]
    bundle = api.get_mf_compare(scheme_codes) if scheme_codes else {"schemes": [], "categories_seen": []}
    return templates.TemplateResponse(request, "mf_compare.html", {
        "page": "mutual-funds",
        "bundle": bundle,
        "input_codes": ",".join(scheme_codes),
    })


@app.get("/mutual-funds/{scheme_code}", response_class=HTMLResponse)
async def mutual_fund_detail(request: Request, scheme_code: str):
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
async def api_mf_nav_series(scheme_code: str, days: int = None):
    return api.get_mf_nav_series(scheme_code, days=days)


@app.get("/api/mf-rolling/{scheme_code}")
async def api_mf_rolling(scheme_code: str):
    return api.get_mf_rolling_returns(scheme_code)


@app.get("/api/mf-search")
async def api_mf_search(q: str = "", limit: int = 10):
    return api.get_mf_search(q, limit=limit)


@app.get("/news", response_class=HTMLResponse)
async def news_page(
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
    return templates.TemplateResponse(request, "news.html", {
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

@app.get("/api/regime")
async def api_regime():
    return api.get_regime()

@app.get("/api/changes")
async def api_changes(days: int = 1):
    return api.get_changes(days=days)

@app.get("/api/picks")
async def api_picks(tier: str = None, top: int = 5):
    return api.get_top_picks(tier=tier, top=top)

@app.get("/api/stock/{sid}")
async def api_stock(sid: str):
    detail = api.get_stock_detail(sid)
    return detail or {"error": "not found"}

@app.get("/api/search")
async def api_search(q: str = ""):
    if len(q) < 2:
        return []
    return api.search_stocks(q)

@app.get("/api/prices/{sid}")
async def api_prices(sid: str, days: int = 365):
    return api.get_price_series(sid, days=days)

@app.get("/api/prices-extended/{sid}")
async def api_prices_extended(sid: str, days: int = 365):
    return api.get_price_series_extended(sid, days=days)

@app.get("/api/quarterly/{sid}")
async def api_quarterly(sid: str):
    return api.get_quarterly_financials(sid)

@app.get("/api/annual/{sid}")
async def api_annual(sid: str):
    return api.get_annual_financials(sid)

@app.get("/api/shareholding/{sid}")
async def api_shareholding(sid: str):
    return api.get_shareholding_history(sid)

@app.get("/api/forecasts/{sid}")
async def api_forecasts(sid: str):
    return api.get_forecast_trend(sid)

@app.get("/api/insider-timeline/{sid}")
async def api_insider_timeline(sid: str):
    return api.get_insider_timeline(sid)

@app.get("/api/lineage/{sid}")
async def api_stock_lineage(sid: str):
    """Per-stock data lineage. See cockpit.api.get_stock_lineage + ADR 0027."""
    return api.get_stock_lineage(sid)

@app.get("/api/sectors")
async def api_sectors():
    return api.get_sector_overview()

# NOTE: /api/pipeline, /api/pipeline/rerun, /api/health, /sql, /api/sql
# all moved to cockpit_ops (port 3001) during Stage 2 split (2026-05-26).
