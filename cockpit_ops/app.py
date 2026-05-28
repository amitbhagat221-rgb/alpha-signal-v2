"""
Alpha Signal v2 — Ops cockpit (port 3001).

Standalone service for the Ops surface: Health Center, Pipeline status,
SQL console, Flow diagram, Command centre. Imports its API surface from
cockpit_ops/api.py (which in turn proxies cockpit.api in Stage 1).

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
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware

from cockpit_ops import api

# Shared static assets from the main cockpit. No need to duplicate CSS/JS.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPS_DIR = Path(__file__).resolve().parent
COCKPIT_STATIC = PROJECT_ROOT / "cockpit" / "static"

app = FastAPI(title="Alpha Signal Ops")
# Gzip every response > 1KB. /system is 1.2MB plaintext HTML and compresses
# to ~150KB; for users on WAN (especially the Bengaluru → Oracle Cloud round
# trip) this is the difference between 3-5s and sub-second download.
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", StaticFiles(directory=COCKPIT_STATIC), name="static")

# Reuse the SilentUndefined trick from main cockpit so templates don't
# blow up on missing attributes.
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
templates = Jinja2Templates(directory=OPS_DIR / "templates")
templates.env.undefined = SilentUndefined


# ────────────── Startup cache warmer ──────────────
# Same parallel-prewarm pattern as cockpit/app.py, but for Ops-only
# endpoints. Cuts cold start on /system from ~19s to first-render-ready.
@app.on_event("startup")
def _prewarm_cache():
    import threading
    import concurrent.futures as cf

    warmers = [
        ("data_freshness",     lambda: api.get_data_freshness()),
        ("db_summary",         lambda: api.get_db_summary()),
        ("data_health_scores", lambda: api.get_data_health_scores(force=False)),
        ("factor_health",      lambda: api.get_factor_health()),
        ("model_overview",     lambda: api.get_model_overview()),
        ("flow_overview",      lambda: api.get_flow_overview()),
        ("command_centre",     lambda: api.get_command_centre()),
        ("health_overview",    lambda: api.get_health_overview()),
        ("pipeline_status",    lambda: api.get_pipeline_status()),
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
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(_warm_one, n, f) for n, f in warmers]
            for fut in cf.as_completed(futures):
                name, dt, err = fut.result()
                if err:
                    print(f"  [ops cache-warm] {name}: FAILED — {err}")
                else:
                    print(f"  [ops cache-warm] {name}: {dt:.1f}s")
        print(f"  [ops cache-warm] total wall-clock: {_t.time()-t0:.1f}s")

    threading.Thread(target=_warm, daemon=True).start()


# ────────────── Pages ──────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Ops landing page → redirect to Health Center."""
    return await system(request)


@app.get("/system", response_class=HTMLResponse)
async def system(request: Request, refresh: int = 0):
    """Health Center page. Pass ?refresh=1 to force a recompute."""
    pipeline = api.get_pipeline_status()
    health = api.get_data_freshness()
    summary = api.get_db_summary()
    health_scores = api.get_data_health_scores(force=bool(refresh))

    from db import DOMAIN_ORDER
    by_domain: dict[str, list[dict]] = {}
    for row in health:
        by_domain.setdefault(row.get("domain") or "Other", []).append(row)
    inventory_groups = [
        {"domain": d, "rows": by_domain[d]}
        for d in DOMAIN_ORDER if d in by_domain
    ]

    factor_health = api.get_factor_health()
    try:
        overview = api.get_health_overview()
    except Exception as e:
        overview = None
        import traceback; traceback.print_exc()

    return templates.TemplateResponse(request, "system.html", {
        "page": "system", "pipeline": pipeline, "health": health,
        "summary": summary, "health_scores": health_scores,
        "inventory_groups": inventory_groups,
        "factor_health": factor_health,
        "overview": overview,
    })


@app.get("/flow", response_class=HTMLResponse)
async def flow_page(request: Request):
    overview = api.get_flow_overview()
    return templates.TemplateResponse(request, "flow.html", {
        "page": "flow", **overview,
    })


@app.get("/command", response_class=HTMLResponse)
async def command_centre(request: Request):
    """Command centre — collapsible view of plans, factor library, data layer,
    pending actions. Updates whenever HANDOFF / plans / git change."""
    payload = api.get_command_centre()
    return templates.TemplateResponse(request, "command.html", {
        "page": "command", **payload,
    })


@app.get("/sql", response_class=HTMLResponse)
async def sql_console(request: Request, table: str = None, q: str = None):
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
async def api_health_overview():
    return api.get_health_overview()


@app.get("/api/health")
async def api_health():
    return api.get_data_freshness()


@app.get("/api/pipeline")
async def api_pipeline(days: int = 7):
    return api.get_pipeline_status(days=days)


@app.post("/api/pipeline/rerun/{step_name}")
async def api_pipeline_rerun(step_name: str):
    """Trigger a single pipeline step in the background. Returns immediately."""
    from cockpit.api import rerun_step
    result = rerun_step(step_name)
    return JSONResponse(result, status_code=200 if result.get("ok") else 409)


@app.post("/api/sql")
async def api_sql(request: Request):
    """Execute a read-only SQL query and return JSON results."""
    body = await request.json()
    query = body.get("query", "").strip()
    return api.run_sql_query(query, max_rows=500)
