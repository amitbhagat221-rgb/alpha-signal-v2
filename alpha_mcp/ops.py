"""
alpha-ops — read-only system health for the MCP (plan 0016 §4 "ops").

    python -m alpha_mcp.ops        # stdio server

Same checks as the 04:00 UTC health email (checks.report.gather — one source
of truth), pipeline step state, table freshness, the LLM ledger, the llm_tasks
queue and the per-feed incident bundle. Nothing here writes, sends or reruns.
"""
import time

from alpha_mcp import _core
from alpha_mcp._core import page as _page, today_iso

_core.install_readonly()

import db                                   # noqa: E402
import views                                # noqa: E402
from mcp.server.fastmcp import FastMCP      # noqa: E402

INSTRUCTIONS = """\
Alpha Signal v2 operations view (read-only). health = the same verdicts as the daily 04:00 UTC health email
(five questions, each OK / WATCH / BROKEN, and the CRITICAL / WARN issues behind them with what to do first). pipeline_status = each pipeline step's final state per run date.
freshness = every table's age vs its threshold. llm_usage = the LLM ledger (mode api = paid API, session / local /
routine = Claude subscription). queue_status = the llm_tasks work queue. feed_incident = everything needed to
diagnose one data feed. org = the agent org: roster and scorecards, the CEO inbox, the board pack and desk memos.
Nothing here can rerun, fix or send anything: report what you find and propose the fix.
"""

mcp = FastMCP("alpha-ops", instructions=INSTRUCTIONS)
tool = lambda **kw: _core.tool(mcp, "ops", **kw)    # noqa: E731

HEALTH_TTL_S = 300          # gather() takes ~15-20 s cold; one scan serves 5 minutes of questions
_health_memo = {"ts": 0.0, "value": None}


def _gather():
    now = time.monotonic()
    if _health_memo["value"] is None or now - _health_memo["ts"] > HEALTH_TTL_S:
        from checks.report import gather
        _health_memo["value"], _health_memo["ts"] = gather(), now
    return _health_memo["value"]


@tool()
def health(severity: str | None = None) -> dict:
    """System health as the daily email sees it. scorecard = the five questions (did everything run, did the
    data arrive, is the data right, can today's picks be trusted, is the model still sound), each OK / WATCH /
    BROKEN. issues = every CRITICAL / WARN finding: theme (which question), code, message (what was found),
    detail (the evidence), why (why it matters), fix (what to do first). CRITICAL = act today, WARN = look this
    week. Also failed steps today, multi-day failure streaks and the watchdog summary. Cached for 5 minutes
    (a full scan takes ~15-20 s). severity: CRITICAL or WARN to filter the issues."""
    st = _gather()
    issues = st.get("issues") or []
    if severity:
        issues = [i for i in issues if i["severity"] == severity.upper()]
    p = st.get("pipeline") or {}
    t = st.get("tables") or {}
    return {"as_of": st.get("as_of"), "summary": st.get("summary"), "scorecard": st.get("scorecard"),
            "issues": issues,
            "pipeline": {k: p.get(k) for k in ("last_run_date", "last_run_status",
                                               "failed_steps_today", "failed_streaks")},
            "tables": {"fresh": t.get("fresh"), "n_stale": len(t.get("stale") or []),
                       "n_outdated": len(t.get("outdated") or []), "empty": t.get("empty")},
            "watchdog": st.get("watchdog")}


@tool()
def pipeline_status(days: int = 2, status: str | None = None, limit: int = 100, offset: int = 0) -> dict:
    """Each pipeline step's FINAL state per run date over the last `days` days, newest first: status
    (SUCCESS / FAILED / RUNNING / ABORTED / SKIPPED...), rows_affected, duration_sec, error_message.
    status: filter, e.g. FAILED."""
    rows = views.pipeline_status(max(1, min(int(days), 30)))
    if status:
        rows = [r for r in rows if (r.get("status") or "").upper() == status.upper()]
    for r in rows:
        if r.get("error_message"):
            r["error_message"] = r["error_message"][:400]
    return {"as_of": rows[0]["run_date"] if rows else None, **_page(rows, limit, offset)}


@tool()
def freshness(status: str | None = None, limit: int = 60, offset: int = 0) -> dict:
    """Every table's freshness: rows, latest_date, age_days vs threshold_days, freshness class and status,
    and the producing step. status: filter on the freshness/status text (e.g. OUTDATED, STALE, EMPTY)."""
    df = db.data_health(cache_ttl=HEALTH_TTL_S)
    keep = [c for c in ("table", "rows", "kind", "frequency", "latest_date", "age_days", "threshold_days",
                        "freshness", "status", "produced_by") if c in df.columns]
    rows = df[keep].to_dict("records")
    if status:
        s = status.upper()
        rows = [r for r in rows if s in str(r.get("status") or "").upper()
                or s in str(r.get("freshness") or "").upper()]
    return {"as_of": today_iso(), **_page(rows, limit, offset)}


@tool()
def llm_usage(days: int = 7) -> dict:
    """The LLM ledger by day, step, model and mode (api = paid Anthropic API; session / local / routine =
    Claude subscription): calls, input/output tokens, estimated cost in USD (API only)."""
    rows = db.rows(
        "SELECT date(called_at) AS day, step, model, mode, SUM(n_calls) AS calls, "
        "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
        "ROUND(SUM(COALESCE(est_cost_usd, 0)), 4) AS est_cost_usd "
        "FROM llm_usage WHERE called_at >= date('now', ?) GROUP BY 1, 2, 3, 4 ORDER BY 1 DESC, 2",
        [f"-{max(1, min(int(days), 90))} days"])
    return {"as_of": rows[0]["day"] if rows else None, "items": rows}


@tool()
def queue_status() -> dict:
    """The llm_tasks work queue per kind: depth by status (queued / claimed / done / invalid / failed),
    oldest queued item, expired leases, invalid-result rate, and today's deadline misses."""
    from alpha_mcp import tasks
    return {"as_of": today_iso(), **tasks.queue_status()}


@tool()
def feed_incident(feed: str) -> dict:
    """Incident bundle for one data feed: what it is, routes and hosts, code paths, recent canary verdicts,
    recent runs, the failing run's events (exact file:line, redacted upstream responses), past incidents and the
    runbook entry for the symptom class. feed: a feeds.FEEDS key."""
    import feeds
    import runlog
    if feed not in feeds.FEEDS:
        raise ValueError(f"unknown feed {feed!r}; one of {sorted(feeds.FEEDS)}")
    b = runlog.bundle(feed)
    return {"as_of": b.get("generated_at"), **b}


@tool(name="org")
def org_overview(role: str | None = None, days: int = 7, work_order: int | None = None) -> dict:
    """The agent org (plan 0019): CEO = the human, every other seat an agent. Without `role`: the roster (seat,
    type desk/builder, reports_to, cadence, 30-day scorecard: tasks done, first-pass rate, compliance grade 0-8,
    tokens), the CEO inbox (asks and hypothesis cards awaiting approve / reject / park), the latest board pack and
    memo headlines from the last `days` days. With `role` (e.g. cio, risk-officer, data-engineer): that seat's
    mission, gate and measures plus its memos in full. Decisions are taken with `python -m org decide` or on the
    ops cockpit /org page; nothing here writes. With `work_order` (a number): that work order in full (items, owner
    seats, done_when, status) plus the chat conversation it was written from: what a session needs to run it."""
    import org as _org
    if work_order is not None:
        import org_chat
        w = _org.work_order(work_order)
        if not w:
            raise ValueError(f"no work order {work_order}; existing: {[x['number'] for x in _org.work_orders()]}")
        return {"as_of": today_iso(), "work_order": w, "chat_it_came_from": org_chat.transcript(w["role"], w["conv"]),
                "how_to_run": "In a Claude Code session in the repo: /work-order <number>. It must be approved first."}
    ov = _org.overview(days=max(1, min(int(days), 60)))
    if role:
        if role not in _org.ROLES:
            raise ValueError(f"unknown role {role!r}; one of {sorted(_org.ROLES)}")
        seat = next(r for r in ov["roles"] if r["id"] == role)
        return {"as_of": ov["as_of"], "role": seat,
                "memos": [m for m in ov["memos"] + ([ov["board_pack"]] if ov["board_pack"] else [])
                          if m["fields"].get("role") == role][:12],
                "inbox": [i for i in ov["inbox"] if i["fields"].get("role") == role]}
    return {"as_of": ov["as_of"],
            "roles": [{k: r.get(k) for k in ("id", "title", "type", "reports_to", "cadence", "score", "latest")}
                      for r in ov["roles"]],
            "inbox": [{"item_id": i["doc_id"], "type": i["type"], "from": i["fields"].get("role"),
                       "title": i["title"], "age_days": i["age_days"],
                       "recommendation": i["fields"].get("recommendation") or i["fields"].get("test")}
                      for i in ov["inbox"]],
            "work_orders": [{k: w[k] for k in ("number", "title", "role", "status", "date")} | {"items": len(w["items"])}
                            for w in ov["work_orders"]],
            "board_pack": ov["board_pack"] and {"week": ov["board_pack"]["key"], **ov["board_pack"]["fields"]},
            "memos": [{"doc_id": m["doc_id"], "date": m["doc_date"], "role": m["fields"].get("role"),
                       "type": m["type"], "headline": m["title"], "grade": (m.get("grade") or {}).get("total")}
                      for m in ov["memos"]]}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
