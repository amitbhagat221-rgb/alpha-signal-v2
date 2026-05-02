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


@app.get("/signals", response_class=HTMLResponse)
async def signals(request: Request):
    signal_data = api.get_active_signals()
    return templates.TemplateResponse(request, "signals.html", {
        "page": "signals", "signals": signal_data, "tooltips": api.SIGNAL_TOOLTIPS,
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

    return templates.TemplateResponse(request, "stock_detail.html", {
        "stock": detail, "page": "explorer",
    })


@app.get("/portfolio", response_class=HTMLResponse)
async def portfolio(request: Request):
    regime = api.get_regime()
    portfolio_data = api.get_model_portfolio()
    # Enrich portfolio stocks
    for key in ["large", "mid", "small"]:
        for s in portfolio_data.get(key, []):
            ac = api.get_analyst_consensus(s["sid"])
            pm = api.get_stock_price_metrics(s["sid"])
            s["pt_upside"] = ac.get("pt_upside_pct")
            s["price"] = pm.get("close_price")
            s["return_1m"] = pm.get("return_1m")
            s["price_target"] = ac.get("price_target")
    analytics = api.get_portfolio_analytics(portfolio_data, regime)
    return templates.TemplateResponse(request, "portfolio.html", {
        "page": "portfolio", "regime": regime, "portfolio": portfolio_data,
        "analytics": analytics,
    })


@app.get("/sectors", response_class=HTMLResponse)
async def sectors(request: Request):
    sector_data = api.get_sector_overview()
    return templates.TemplateResponse(request, "sectors.html", {
        "page": "sectors", "sectors": sector_data,
    })


@app.get("/model", response_class=HTMLResponse)
async def model_page(request: Request):
    overview = api.get_model_overview()
    return templates.TemplateResponse(request, "model.html", {
        "page": "model", **overview,
    })


@app.get("/flow", response_class=HTMLResponse)
async def flow_page(request: Request):
    overview = api.get_flow_overview()
    return templates.TemplateResponse(request, "flow.html", {
        "page": "flow", **overview,
    })


@app.get("/system", response_class=HTMLResponse)
async def system(request: Request, refresh: int = 0):
    """System page. Pass ?refresh=1 to force a recompute of the health model."""
    pipeline = api.get_pipeline_status()
    health = api.get_data_freshness()
    summary = api.get_db_summary()
    health_scores = api.get_data_health_scores(force=bool(refresh))

    # Group health rows by domain for the inventory section.
    from db import DOMAIN_ORDER
    by_domain: dict[str, list[dict]] = {}
    for row in health:
        by_domain.setdefault(row.get("domain") or "Other", []).append(row)
    inventory_groups = [
        {"domain": d, "rows": by_domain[d]}
        for d in DOMAIN_ORDER if d in by_domain
    ]

    return templates.TemplateResponse(request, "system.html", {
        "page": "system", "pipeline": pipeline, "health": health,
        "summary": summary, "health_scores": health_scores,
        "inventory_groups": inventory_groups,
    })


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

@app.get("/api/sectors")
async def api_sectors():
    return api.get_sector_overview()

@app.get("/api/pipeline")
async def api_pipeline(days: int = 7):
    return api.get_pipeline_status(days=days)

@app.get("/api/health")
async def api_health():
    return api.get_data_freshness()


# ── SQL Console ──

@app.get("/sql", response_class=HTMLResponse)
async def sql_console(request: Request, table: str = None, q: str = None):
    """Read-only SQL query interface.

    Two ways to pre-fill the query box:
      ?table=foo  → prefills `SELECT * FROM foo LIMIT 20` and auto-runs
      ?q=<query>  → prefills the verbatim query and auto-runs (used by health
                    drill-down links)
    """
    if q:
        initial_query = q
    elif table:
        initial_query = f"SELECT * FROM {table} LIMIT 20"
    else:
        initial_query = None
    return templates.TemplateResponse(request, "sql_console.html", {
        "page": "system",
        "initial_query": initial_query,
    })


@app.post("/api/sql")
async def api_sql(request: Request):
    """Execute a read-only SQL query and return JSON results."""
    body = await request.json()
    query = body.get("query", "").strip()
    return api.run_sql_query(query, max_rows=500)
