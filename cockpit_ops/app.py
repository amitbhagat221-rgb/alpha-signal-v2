"""
Alpha Signal v2 — Ops cockpit (port 3001).

Standalone service for the Ops surface: Health Center, Pipeline status,
SQL console, Flow diagram, Command centre. Imports its API surface from
cockpit_ops/api.py, which depends only on cockpit/_shared.py (not cockpit/api.py).

The main trading cockpit on port 3000 continues to run independently.
You can restart this service to fix an Ops-only bug without touching
the trading cockpit.

Run: uvicorn cockpit_ops.app:app --host 0.0.0.0 --port 3001 --reload
Production: systemctl restart alpha-cockpit-ops
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from cockpit._shared import COCKPIT_STATIC, make_templates, nav_model, prewarm
from cockpit_ops import api, pages

OPS_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Alpha Signal Ops")
# Gzip every response > 1KB. /system is 1.2MB plaintext HTML and compresses
# to ~150KB; for users on WAN (especially the Bengaluru → Oracle Cloud round
# trip) this is the difference between 3-5s and sub-second download.
app.add_middleware(GZipMiddleware, minimum_size=1024)
# Shared static assets from the main cockpit. No need to duplicate CSS/JS.
app.mount("/static", StaticFiles(directory=COCKPIT_STATIC), name="static")

# Ops pages first, then cockpit/templates for the shared base.html /
# _components.html / _icons.html (single copies — the ops forks went stale).
templates = make_templates([OPS_DIR / "templates"],
                           nav=nav_model(pages.PAGES, pages.OTHER_APP, pages.BRAND))


# ────────────── Startup cache warmer ──────────────
# Same parallel-prewarm pattern as cockpit/app.py, but for Ops-only
# endpoints. Cuts cold start on /system from ~19s to first-render-ready.
@app.on_event("startup")
def _prewarm_cache():
    prewarm([
        ("data_freshness",     lambda: api.get_data_freshness()),
        ("db_summary",         lambda: api.get_db_summary()),
        ("data_health_scores", lambda: api.get_data_health_scores(force=False)),
        ("factor_health",      lambda: api.get_factor_health()),
        ("model_overview",     lambda: api.get_model_overview()),
        ("flow_overview",      lambda: api.get_flow_overview()),
        ("command_centre",     lambda: api.get_command_centre()),
        ("health_overview",    lambda: api.get_health_overview()),
        ("pipeline_status",    lambda: api.get_pipeline_status()),
    ], label="ops cache-warm")


# ────────────── Pages ──────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Ops landing page → redirect to Health Center."""
    return await system(request)


@app.get("/system", response_class=HTMLResponse)
async def system(request: Request, refresh: int = 0):
    """Health Center page. Pass ?refresh=1 to force a recompute."""
    # These calls are independent and each is individually cached, but on a cold
    # (cache-expired) load the slow ones — get_health_overview ~14s, freshness
    # ~7s, db_summary ~3s — ran serially (~24s). Fire them concurrently; the
    # data_health(cache_ttl) memo dedupes the freshness scan shared with
    # get_health_overview. Wall-clock collapses to the slowest single call.
    import asyncio

    async def _overview():
        try:
            return await asyncio.to_thread(api.get_health_overview)
        except Exception:
            import traceback; traceback.print_exc()
            return None

    pipeline, health, summary, health_scores, factor_health, overview = await asyncio.gather(
        asyncio.to_thread(api.get_pipeline_status),
        asyncio.to_thread(api.get_data_freshness),
        asyncio.to_thread(api.get_db_summary),
        asyncio.to_thread(api.get_data_health_scores, bool(refresh)),
        asyncio.to_thread(api.get_factor_health),
        _overview(),
    )

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
        "factor_health": factor_health,
        "overview": overview,
    })


@app.get("/flow", response_class=HTMLResponse)
def flow_page(request: Request):
    overview = api.get_flow_overview()
    return templates.TemplateResponse(request, "flow.html", {
        "page": "flow", **overview,
    })


@app.get("/command", response_class=HTMLResponse)
def command_centre(request: Request):
    """Command centre — collapsible view of plans, factor library, data layer,
    pending actions. Updates whenever HANDOFF / plans / git change."""
    payload = api.get_command_centre()
    return templates.TemplateResponse(request, "command.html", {
        "page": "command", **payload,
    })


@app.get("/sql", response_class=HTMLResponse)
def sql_console(request: Request, table: str = None, q: str = None):
    """Read-only SQL query interface.

    Pre-fill via ?table=foo (SELECT * FROM foo LIMIT 20, auto-runs) or
    ?q=<verbatim query> (auto-runs — used by health drill-down links).
    """
    if q:
        initial_query = q
    elif table:
        initial_query = f"SELECT * FROM {table} LIMIT 20"
    else:
        initial_query = None
    return templates.TemplateResponse(request, "sql_console.html", {
        "page": "sql",
        "initial_query": initial_query,
    })


# ────────────── JSON API endpoints ──────────────

@app.get("/api/health/overview")
def api_health_overview():
    return api.get_health_overview()


@app.get("/api/health")
def api_health():
    return api.get_data_freshness()


@app.get("/api/pipeline")
def api_pipeline(days: int = 7):
    return api.get_pipeline_status(days=days)


@app.post("/api/pipeline/rerun/{step_name}")
def api_pipeline_rerun(step_name: str):
    """Trigger a single pipeline step in the background. Returns immediately."""
    from cockpit_ops.api import rerun_step
    result = rerun_step(step_name)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/api/sql")
async def api_sql(request: Request):
    """Execute a read-only SQL query and return JSON results."""
    import asyncio
    body = await request.json()
    query = body.get("query", "").strip()
    # async only to await the body; the query itself runs off the event loop.
    return await asyncio.to_thread(api.run_sql_query, query, max_rows=500)
