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
from preview import PreviewReadOnly, add_redirects

import config
import views
from cockpit import api, book, model, pages, today, stocks as stocks_data
from cockpit._shared import COCKPIT_STATIC, COCKPIT_TEMPLATES, make_templates, nav_model, prewarm

app = FastAPI(title="Alpha Signal Cockpit")
# Gzip every response > 1KB (the long pages are 100s of KB of HTML).
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(LoginRequired, app_name="Cockpit")     # webauth.py — password login (review F5)
app.add_middleware(PreviewReadOnly)                       # preview.py — refuses writes when COCKPIT_PREVIEW=1
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
        ("today",              lambda: today.build()),
        ("book",               lambda: book.get_book()),
        ("model_page",         lambda: model.get_model()),
        ("news_pool_168",      lambda: api._get_news_pool(hours=168)),
        ("news_pool_720",      lambda: api._get_news_pool(hours=720)),
        ("sector_call",        lambda: api.get_sector_call()),
        ("multibagger",        lambda: api.get_multibagger_overview()),
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


# ── Page Routes ──
# Cockpit v2 site map: cockpit/pages.py (PAGES = the rail, REDIRECTS = the retired URLs).
# Today, Stocks, Markets, Ideas and Book are placeholders until their page group fills them:
# replace the body of the route with the real context and render the group's own template
# (see coming.html for the tab layout and pages.py `tabs` for the tab keys).

def _coming(request: Request, page_id: str):
    """Placeholder page for a v2 destination that is still being built."""
    entry = next(p for p in pages.PAGES if p["id"] == page_id)
    return templates.TemplateResponse(request, "coming.html", {"page": page_id, "entry": entry})


@app.get("/", response_class=HTMLResponse)
def today_page(request: Request):
    return templates.TemplateResponse(request, "today.html", {"page": "today", "t": today.build()})


@app.get("/stocks", response_class=HTMLResponse)
def stocks_page(request: Request):
    """The screener: every ranked stock in one sortable, filterable table; the state is the query string."""
    return templates.TemplateResponse(request, "stocks.html", {
        "page": "stocks", "s": stocks_data.screen(request.query_params)})


@app.get("/markets", response_class=HTMLResponse)
def markets_page(request: Request, sector: str = "", industry: str = ""):
    """Markets: Today (the editor's 3 stories + one sector call), Themes, Industries (the
    industry library + the reference table), Search (a partial, below). ?industry= and
    ?sector= open that group's detail on the Industries tab."""
    industry_list = api.get_group_list("industry")
    sector_list = api.get_group_list("sector")
    detail = None
    if industry and industry in industry_list:
        detail = _group_detail("industry", industry)
    elif sector and sector in sector_list:
        detail = _group_detail("sector", sector)
    today = dt.date.today().isoformat()
    return templates.TemplateResponse(request, "markets.html", {
        "page": "markets", "entry": next(p for p in pages.PAGES if p["id"] == "markets"),
        "today": today, "start_tab": "industries" if detail else "today",
        "call": api.get_sector_call(), **api.get_news_front(),
        "industries": api.get_industry_rotation(), "industry_list": industry_list,
        "detail": detail, "pick_date": api.latest_pick_date(),
        "sources": [n for n, _ in api.search_news(page_size=1)["sources"]],
    })


@app.get("/partial/news-search", response_class=HTMLResponse)
def partial_news_search(request: Request, q: str = "", theme: str = "", source: str = "",
                        hours: int = 168, page: int = 1):
    """The Search tab's results (words, theme, source, age), fetched into the tab."""
    return templates.TemplateResponse(request, "_news_search.html", {
        "s": api.search_news(q=q.strip(), theme=theme, source=source, hours=hours, page=page)})


@app.get("/ideas", response_class=HTMLResponse)
def ideas_page(request: Request, strict: int = 0):
    """Ideas: Screens (one table per chip, first chip rendered here) · Avoid · Track record.
    ?strict=1 opens Compounders with the strict (multibagger gates) toggle on."""
    from cockpit import playbooks
    entry = next(p for p in pages.PAGES if p["id"] == "ideas")
    return templates.TemplateResponse(request, "ideas.html", {
        "page": "ideas", "tabs": entry["tabs"], "screens": playbooks.SCREENS, "strict": bool(strict),
        "d": playbooks.screen("insiders"), "r": playbooks.rules()})


@app.get("/partial/ideas/screen/{key}", response_class=HTMLResponse)
def ideas_screen(request: Request, key: str, strict: int = 0):
    """One screen's table, fetched the first time its chip is opened."""
    from cockpit import playbooks
    if key not in dict(playbooks.SCREENS):
        raise HTTPException(404, "unknown screen")
    return templates.TemplateResponse(request, "_ideas_screen.html", {
        "d": playbooks.screen(key, strict=bool(strict)), "r": playbooks.rules()})


@app.get("/partial/ideas/avoid", response_class=HTMLResponse)
def ideas_avoid(request: Request):
    from cockpit import playbooks
    return templates.TemplateResponse(request, "_ideas_avoid.html", {"d": playbooks.avoid(), "r": playbooks.rules()})


@app.get("/partial/ideas/track", response_class=HTMLResponse)
def ideas_track(request: Request):
    from cockpit import playbooks
    return templates.TemplateResponse(request, "_ideas_track.html", {"d": playbooks.portfolios(), "r": playbooks.rules(),
                                                                       "ev": playbooks.evidence()})


@app.get("/book", response_class=HTMLResponse)
def book_page(request: Request):
    """The HRP sized book, its risk and its realised track record (tabs: book, risk, track-record)."""
    return templates.TemplateResponse(request, "book.html", {
        "page": "book", "tabs": next(p["tabs"] for p in pages.PAGES if p["id"] == "book"),
        "book": book.get_book(), "risk": book.get_risk(), "track": book.get_track_record(),
    })


add_redirects(app, pages.REDIRECTS)


@app.get("/stocks/{sid}", response_class=HTMLResponse)
def stock_detail(request: Request, sid: str):
    detail = api.get_stock_detail(sid)
    if not detail:
        return HTMLResponse("<h1>Stock not found</h1>", status_code=404)

    # Enrich with all new data
    detail["pm"] = api.get_stock_price_metrics(sid)
    detail["breakdown"] = views.pick_breakdown(sid, detail.get("pick_date")) if detail.get("final_score") is not None else None
    detail["factor_labels"] = api.get_factor_labels()
    detail["is_financial"] = detail.get("sector") in config.SCREEN["financial_sectors"]
    detail["ac"] = api.get_analyst_consensus(sid)
    detail["shareholding"] = api.get_shareholding_history(sid)
    detail["insider"] = api.get_insider_activity(sid)
    detail["insider_timeline"] = api.get_insider_timeline(sid)
    detail["news"] = api.get_stock_news(sid)
    detail["bulk_deals"] = api.get_bulk_deals(sid)
    detail["earnings"] = api.get_earnings_upcoming(sid)
    detail["dossier"] = api.get_dossier(sid)
    detail["management"] = api.get_management_score(sid)
    detail["managerial_ability"] = api.get_managerial_ability(sid)
    detail["financial_management"] = api.get_financial_management(sid)
    detail["quarterly"] = api.get_quarterly_financials(sid)
    detail["annual"] = api.get_annual_financials(sid)
    detail["forecasts"] = api.get_forecast_trend(sid)
    detail["sector_comp"] = api.get_sector_comparison(sid, detail.get("sector"))
    detail["in_book"] = sid in {r["sid"] for r in (api.get_sized_book() or {}).get("rows", [])}
    detail["chips"] = stocks_data.stock_chips(sid)
    detail["rank_move"] = stocks_data.rank_move(sid)
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
        "stock": detail, "page": "stocks", "latest_pick": api.latest_pick_date(),
        "today_iso": _date.today().isoformat(),
    })


def _group_detail(by, name):
    """The Markets > Industries detail pane for one industry (with its parent sector's macro
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


@app.get("/partial/industry-card/{industry}", response_class=HTMLResponse)
def partial_industry_card(request: Request, industry: str, sid: str = ""):
    """Full industry dossier fragment, lazy-loaded into the stock page's Sector
    tab. Renders the SAME shared _industry_detail.html partial that Markets > Industries uses
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
    plus a link to the full Markets industry page."""
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
    """Is the model working and should I change anything? (tabs: health, evidence, library, rules)"""
    return templates.TemplateResponse(request, "model.html", {
        "page": "model", "tabs": next(p["tabs"] for p in pages.PAGES if p["id"] == "model"),
        **model.get_model(),
    })


@app.get("/api/model/outcomes")
def api_model_outcomes(n: int = 10):
    return api.get_pick_outcomes_summary(top_n=n)


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


@app.get("/markets/theme/{theme_id}", response_class=HTMLResponse)
def news_theme_page(request: Request, theme_id: str):
    theme = api.get_news_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="No such theme")
    theme = api.annotate_themes([theme], api.get_news_today())[0]     # the same "out of date" flag as Markets > Themes
    return templates.TemplateResponse(request, "news_theme.html", {"page": "markets", "t": theme})


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
