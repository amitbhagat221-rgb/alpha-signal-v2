"""
Alpha Signal v2 — Ops cockpit API (the data the Health, Feeds, Flow, Boardroom and SQL pages read).

Views over the one sources of truth, never a second copy of a rule:
  - Health: a VIEW over checks.report.gather() (get_health_overview: issues grouped by cause, the
    real error of a failed job, since-yesterday); the Inventory (get_data_freshness, get_table_columns)
  - Feeds: feeds.FEEDS + checks.feeds (get_feed_overview); the Data tab (get_data_health_scores)
  - Flow: the pipeline's dataflow graph by stage (get_flow_overview), the step log (get_pipeline_status)
  - Boardroom: org.overview() plus the inbox cards' board-pack call, options and settled flags
  - get_model_overview / get_backtest_roster / get_validation_evidence feed the trading cockpit's Model page

Shared decorators (_persisted_cache, _ttl_cache) live in cockpit/_shared.py and are imported
one-way here; cross-cutting helpers (read_sql, get_db) come from db. Nothing here imports
cockpit/api.py, and cockpit/app.py imports get_model_overview from this module directly.
"""

import re
import sys
from pathlib import Path

import pandas as pd

# Ensure project root is importable (cockpit_ops/ lives at the root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import db
import views
from db import read_sql, get_db

# Shared decorators — implementations live in cockpit/_shared.py (single-source).
from cockpit._shared import _ttl_cache, _persisted_cache, safe_json_records


# ───────────────────────────── Ops functions ─────────────────────────────


def get_pipeline_status(days=7):
    """Pipeline log for the last N days, one row per (date, step) in its FINAL
    state, stale RUNNING rows marked ABORTED — views.pipeline_status. A failed row also carries
    `error_text`: the real error line (see real_error), not the "exit 1 (...)" pointer."""
    rows = views.pipeline_status(days)
    for r in rows:
        m = r.get("error_message")
        if m and r.get("status") in ("FAILED", "ABORTED"):
            r["error_text"] = real_error(m)["error"] or m
    return rows


def run_sql_query(query, max_rows=500):
    """Execute a read-only SQL query via the SQL console.
    Returns: {"columns": [...], "rows": [...], "error": str|None, "row_count": int}"""
    from db import safe_read_sql
    df, error = safe_read_sql(query, max_rows=max_rows)
    if error:
        return {"columns": [], "rows": [], "error": error, "row_count": 0}
    if df is None or df.empty:
        return {"columns": list(df.columns) if df is not None else [],
                "rows": [], "error": None, "row_count": 0}
    # JSON-safe coercion via the shared helper (cockpit/_shared.safe_json_records) —
    # this function was the canonical superset the helper was lifted from.
    rows = safe_json_records(df)
    return {
        "columns": list(df.columns),
        "rows": rows,
        "error": None,
        "row_count": len(rows),
    }


@_persisted_cache(300, name="get_data_freshness")
def get_data_freshness():
    """Data health from db.data_health(). NaN floats are coerced to None so the
    payload is JSON-safe (Jinja's tojson preserves NaN literals which break
    JSON.parse in the browser)."""
    from db import data_health
    # cache_ttl shares the scan with checks.system.table_facts so a cold
    # /system load runs the ~7s freshness scan once, not twice. See ADR 0031.
    return safe_json_records(data_health(cache_ttl=60))


@_persisted_cache(300, name="get_db_summary")
def get_db_summary():
    """High-level health verdict for the system page header."""
    from db import db_summary
    return db_summary()


# ═══════════════════════════════════════════════════
# Model + Flow pages
# ═══════════════════════════════════════════════════

# v1 holds the C13b 18-period reconstructed validation. v2 doesn't have its
# own backtest yet — we surface the v1 file as the canonical signal map.


def get_validation_evidence():
    """The IC evidence behind the weights: one row per (signal, cap_tier) from
    tools.backtest_pit.evidence() — the SAME source as the Backtests roster, /system
    and /command. Wired (signal, tier) pairs first with their weight, then the rest by
    |t|. Returns {rows, meta} with meta.n_wired / n_rows / as_of."""
    from factors import SIGNAL_WEIGHTS, signal_for
    # weight keys (piotroski) are not evidence ids (piotroski_f_score): key both by registry id
    by_id = {(signal_for(k, t), t): w for t, tw in SIGNAL_WEIGHTS.items() for k, w in tw.items()}
    try:
        from tools.backtest_pit import evidence
        ev = evidence()
    except Exception:
        return {"rows": [], "meta": {}}
    rows = []
    for r in ev.to_dict("records"):
        w = by_id.get((r["signal"], r["cap_tier"]))
        rows.append({
            "signal": r["signal"], "cap_tier": r["cap_tier"],
            "weight": w, "wired": bool(w),
            "t_stat": _safe_float(r["t_stat"], 2), "mean_ic": _safe_float(r["mean_ic"], 4),
            "icir": _safe_float(r["icir"], 3), "n_periods": _safe_int(r["n_periods"]),
            "n_stocks_avg": _safe_int(r["n_stocks_avg"]), "verdict": r["verdict"],
            "thin": (_safe_int(r["n_periods"]) or 0) < IC_MIN_PERIODS,
        })
    rows.sort(key=lambda x: (not x["wired"], -abs(x["t_stat"] or 0)))
    computed = ev["computed_at"].max() if "computed_at" in ev and len(ev) else None
    return {"rows": rows, "meta": {
        "n_wired": sum(r["wired"] for r in rows), "n_rows": len(rows),
        "as_of": str(computed)[:10] if computed is not None else None,
        "min_periods": IC_MIN_PERIODS}}


@_persisted_cache(300, name="get_model_overview")
def get_model_overview():
    """Tier weight tables, signal validation, regime rules. Used by /model."""
    from config import REGIMES, PORTFOLIO, TRANSACTION_COSTS_BPS
    from factors import SIGNAL_WEIGHTS

    # Per-tier signal weights. The bar is |w| / sum|w|: a negative weight (an inverted
    # factor) is a bar of its own size, flagged `inverted`, never a negative CSS width.
    tiers = {}
    for tier, weights in SIGNAL_WEIGHTS.items():
        total = sum(abs(w) for w in weights.values()) or 1
        rows = sorted(weights.items(), key=lambda kv: -abs(kv[1]))
        tiers[tier] = [
            {"signal": s, "weight": w, "pct": round(100 * abs(w) / total, 1), "inverted": w < 0}
            for s, w in rows
        ]

    # VIX regime → allocation table.
    regimes = []
    for name, spec in REGIMES.items():
        vlo, vhi = spec["vix"]
        regimes.append({
            "regime": name,
            "vix_lo": vlo, "vix_hi": vhi,
            **{f"alloc_{t.lower()}": a for t, a in spec["alloc"].items()},
        })

    # Current regime so the page can highlight the active row.
    current_regime = views.regime() or {}

    validation = get_validation_evidence()

    return {
        "tiers": tiers,
        "regimes": regimes,
        "current_regime": current_regime,
        "validation": validation,
        "portfolio": PORTFOLIO,
        "transaction_costs_bps": TRANSACTION_COSTS_BPS,
        "backtest_roster": get_backtest_roster(),
    }


from tools.backtest_pit import IC_MIN_PERIODS  # noqa: E402  below this a t-stat carries no verdict


def best_ic_by_signal(per_tier=False):
    """Best backtest row per signal from pit_ic_by_tier_v2 — the ONE ranking rule
    shared by /system (factor health), /command (factor library) and /model
    (backtest roster). Pre-2026-09-26 each surface ranked sources its own way, so
    /system and /command disagreed on which factors were promoted.

    Rule: per (signal, cap_tier) the ONE evidence row of tools.backtest_pit.evidence()
    (v2 panel before v1 archive, then most anchors). per_tier=False picks, across a
    signal's tiers, rows with n_periods >= IC_MIN_PERIODS first, then highest |t|.

    per_tier=False → {signal: row};  per_tier=True → {signal: {cap_tier: row}}.
    Rows carry signal, cap_tier, source, t_stat, n_periods, mean_ic, verdict,
    t_stat_ci_lo, t_stat_ci_hi."""
    try:
        from tools.backtest_pit import evidence
        ic = evidence()[["signal", "cap_tier", "source", "t_stat", "n_periods", "mean_ic", "verdict",
                         "t_stat_ci_lo", "t_stat_ci_hi"]]
    except Exception:
        return {}
    if ic.empty:
        return {}
    ranked = (
        ic.assign(_abst=ic["t_stat"].abs(), _adequate_n=(ic["n_periods"] >= IC_MIN_PERIODS).astype(int))
        .sort_values(["_adequate_n", "_abst"], ascending=[False, False])
        .drop(columns=["_abst", "_adequate_n"])
    )
    if not per_tier:
        return ranked.drop_duplicates("signal", keep="first").set_index("signal", drop=False).to_dict("index")
    out = {}
    for r in ranked.drop_duplicates(["signal", "cap_tier"], keep="first").to_dict("records"):
        out.setdefault(r["signal"], {})[r["cap_tier"]] = r
    return out


def get_backtest_roster():
    """Signal-level backtest readiness for /model.

    For each entry in db.BACKTEST_SIGNALS, enriches with live data:
      - best backtest verdict + t-stat per cap_tier (pit_ic_by_tier_v2 via
        best_ic_by_signal — v1 is a frozen 10-signal 2026-05-03 import)
      - Coverage snapshot (max history available, n_periods)

    Returns a dict with:
      signals: list of enriched signal rows
      response: info on the response variable (fwd_return_20d)
      pit_tables: summary of the PIT tables themselves
      summary: count by status (READY / PARTIAL / MISSING)
    """
    from db import BACKTEST_SIGNALS, get_db, read_sql, read_sql_fast

    # ── Existing PIT tables ──
    with get_db() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    has_pit_v1 = "daily_snapshots_pit_v1" in names
    has_pit_v2 = "daily_snapshots_pit" in names

    # ── IC table — best row per (signal, cap_tier) ──
    ic_by_signal = {
        sig: {
            tier: {
                "t_stat": _safe_float(r["t_stat"], 2),
                "verdict": r["verdict"],
                "n_periods": _safe_int(r["n_periods"]),
            }
            for tier, r in tiers.items()
        }
        for sig, tiers in best_ic_by_signal(per_tier=True).items()
    }

    # ── Coverage per PIT column (DuckDB replica — 27× faster on this scan) ──
    def _coverage(table, column):
        if not column or table not in names:
            return None
        try:
            df = read_sql_fast(f'''
                SELECT COUNT(DISTINCT snapshot_date) AS n_dates,
                       MIN(snapshot_date) AS first_date,
                       MAX(snapshot_date) AS last_date,
                       AVG(CASE WHEN "{column}" IS NOT NULL THEN 1.0 ELSE 0 END) AS pct_filled
                FROM "{table}"
                WHERE "{column}" IS NOT NULL
            ''')
            if df.empty or df.iloc[0]["n_dates"] == 0:
                return None
            r = df.iloc[0]
            return {
                "n_dates": _safe_int(r["n_dates"]),
                "first_date": r["first_date"],
                "last_date": r["last_date"],
                "pct_filled": round(float(r["pct_filled"]) * 100, 1) if pd.notna(r["pct_filled"]) else None,
            }
        except Exception:
            return None

    # ── Enrich each signal ──
    signals = []
    for s in BACKTEST_SIGNALS:
        cov_v1 = _coverage("daily_snapshots_pit_v1", s.get("pit_column_v1"))
        cov_v2 = _coverage("daily_snapshots_pit", s.get("pit_column_v2"))
        cov_ext = None
        if s.get("external_table"):
            ext_tbl = s["external_table"]
            if ext_tbl in names:
                try:
                    r = db.one(f"SELECT COUNT(DISTINCT snapshot_date) AS n, MIN(snapshot_date) AS f, MAX(snapshot_date) AS l FROM [{ext_tbl}]")
                    if r and r["n"] > 0:
                        cov_ext = {
                            "n_dates": _safe_int(r["n"]),
                            "first_date": r["f"],
                            "last_date": r["l"],
                            "table": ext_tbl,
                        }
                except Exception:
                    pass

        # Pick the deeper coverage as the headline
        depths = []
        if cov_v1 and cov_v1["n_dates"]: depths.append(("v1 archive", cov_v1["n_dates"], cov_v1["first_date"], cov_v1["last_date"]))
        if cov_v2 and cov_v2["n_dates"]: depths.append(("v2 recompute", cov_v2["n_dates"], cov_v2["first_date"], cov_v2["last_date"]))
        if cov_ext:                       depths.append((cov_ext["table"], cov_ext["n_dates"], cov_ext["first_date"], cov_ext["last_date"]))

        max_dates = max((d[1] for d in depths), default=0)
        first_date = min((d[2] for d in depths), default=None)
        last_date = max((d[3] for d in depths), default=None)
        sources = ", ".join(d[0] for d in depths) or "—"

        signals.append({
            **s,
            "ic_by_tier": ic_by_signal.get(s["signal"], {}),
            "coverage_v1": cov_v1,
            "coverage_v2": cov_v2,
            "coverage_external": cov_ext,
            "max_dates": max_dates,
            "first_date": first_date,
            "last_date": last_date,
            "live_source": sources,
        })

    # ── Response variable ──
    response = {"variable": "fwd_return_20d", "computed_from": "stock_prices.close",
                "horizon_days": 20, "available_in": []}
    if has_pit_v1:
        try:
            df = read_sql_fast('SELECT COUNT(*) AS n, MIN(snapshot_date) AS f, MAX(snapshot_date) AS l FROM "daily_snapshots_pit_v1" WHERE fwd_return_20d IS NOT NULL')
            if not df.empty and df.iloc[0]["n"] > 0:
                response["available_in"].append({
                    "table": "daily_snapshots_pit_v1",
                    "rows": _safe_int(df.iloc[0]["n"]),
                    "first_date": df.iloc[0]["f"],
                    "last_date": df.iloc[0]["l"],
                    "note": "precomputed",
                })
        except Exception:
            pass
    response["available_in"].append({
        "table": "stock_prices",
        "rows": None,
        "note": "Compute on the fly: close on (eval_date + 20 trading days) / close on eval_date − 1",
    })

    # ── PIT table summary ──
    pit_tables = []
    for tbl in ["daily_snapshots_pit_v1", "daily_snapshots_pit", "pit_ic_by_tier_v2"]:
        if tbl not in names:
            continue
        try:
            # pit_ic_by_tier_v2 isn't in the DuckDB mirror — count it in SQLite.
            _reader = read_sql if tbl == "pit_ic_by_tier_v2" else read_sql_fast
            r = _reader(f'SELECT COUNT(*) AS rows FROM "{tbl}"').iloc[0]
            entry = {"table": tbl, "rows": _safe_int(r["rows"])}
            if tbl != "pit_ic_by_tier_v2":
                d = read_sql_fast(f'SELECT COUNT(DISTINCT snapshot_date) AS n_dates, MIN(snapshot_date) AS f, MAX(snapshot_date) AS l, COUNT(DISTINCT sid) AS sids FROM "{tbl}"').iloc[0]
                entry.update({
                    "n_dates": _safe_int(d["n_dates"]),
                    "first_date": d["f"],
                    "last_date": d["l"],
                    "n_stocks": _safe_int(d["sids"]),
                })
            pit_tables.append(entry)
        except Exception:
            pass

    # ── Summary counts by status ──
    summary = {"READY": 0, "PARTIAL": 0, "MISSING": 0, "PROPOSED": 0, "BLOCKED": 0}
    for s in signals:
        summary[s["status"]] = summary.get(s["status"], 0) + 1

    # ── Grouped (by signal.group) for the page layout ──
    from collections import OrderedDict
    GROUP_ORDER = ["Value", "Quality", "Growth", "Momentum", "Ownership",
                   "Forensic", "Smart Money", "Consensus", "Sentiment",
                   "Regulatory", "Macro", "Composite"]
    grouped = OrderedDict((g, []) for g in GROUP_ORDER)
    for s in signals:
        g = s.get("group") or "Other"
        grouped.setdefault(g, []).append(s)

    return {
        "signals": signals,
        "groups": [{"name": g, "signals": gs} for g, gs in grouped.items() if gs],
        "response": response,
        "pit_tables": pit_tables,
        "summary": summary,
    }



def _safe_int(v):
    try:
        if pd.isna(v): return None
        return int(v)
    except Exception:
        return None


def _safe_float(v, places=2):
    try:
        if pd.isna(v): return None
        return round(float(v), places)
    except Exception:
        return None


# The pipeline's stages, in run order. A step belongs to the first stage whose rule matches its name;
# STAGE_OF names the ones the prefix rules do not catch. tests/test_ops_pages.py holds that every
# config.PIPELINE_STEPS entry lands in one (a new step must be placed, not fall into "Other").
STAGES = [
    ("collect", "1 · Collect", "fetch raw data from the outside world"),
    ("prepare", "2 · Prepare", "adjust prices, classify, assign cap tiers"),
    ("signals", "3 · Signals", "turn raw tables into per-stock factors"),
    ("rank", "4 · Rank", "regime, eligibility, screener, portfolio, outcomes"),
    ("publish", "5 · Publish", "snapshot, dossiers, news briefs, the email"),
]
STAGE_OF = {
    "universe_liveness": "collect", "scrape_mf_holdings": "collect", "fetch_nse_indices": "collect",
    "compute_corporate_adjustments": "prepare", "compute_fno_pcr": "prepare", "compute_fno_iv": "prepare",
    "segment_tiers": "prepare", "classify_micro_tier": "prepare", "classify_mf_quality": "prepare",
    "classify_news": "prepare", "classify_regulatory": "prepare", "compute_mf_metrics": "prepare",
    "refresh_pit_panel": "prepare",
    "sector_analyst_breadth": "signals", "sector_sentiment_breadth": "signals", "sector_policy": "signals",
    "compute_financial_signal": "signals", "compute_sector_briefs": "signals", "compute_sector_momentum": "signals",
    "compute_sector_forces": "signals",
    "refresh_eligibility": "rank", "regime_update": "rank", "screener": "rank", "portfolio_construction": "rank",
    "compute_pick_outcomes": "rank", "portfolio_outcomes": "rank",
    "compute_sector_dossiers": "publish", "snapshot": "publish", "diff_engine": "publish", "dossier": "publish",
    "pit_replay_freeze": "publish", "email": "publish", "news_brief": "publish", "news_desk": "publish",
}


def stage_of(step_name):
    """The stage id of a pipeline step: an explicit entry, else its name prefix (fetch_ = collect, signal_ = signals)."""
    if step_name in STAGE_OF:
        return STAGE_OF[step_name]
    if step_name.startswith("fetch_"):
        return "collect"
    if step_name.startswith("signal_"):
        return "signals"
    return "other"


@_ttl_cache(300)
def get_flow_overview():
    """The pipeline as its dataflow graph, for /flow. Everything is derived from the step
    declarations (graph.py): edges are graph.edges() collapsed to step pairs (blocking = the
    reader sees this run's write; lagged = the previous run's), the columns are the STAGES
    above (steps keep run order inside a stage), and each step carries its latest
    views.step_status() row with the real error line of a failure."""
    import graph
    from config import PIPELINE_STEPS

    status_by_step = views.step_status()
    try:
        derived = graph.order(PIPELINE_STEPS)
    except ValueError:  # a declaration cycle — fall back to list order, still render
        derived = [s["name"] for s in PIPELINE_STEPS]
    position = {n: i for i, n in enumerate(derived)}

    edges = {}
    for writer, reader, dataset, kind in graph.edges(PIPELINE_STEPS):
        e = edges.setdefault((writer, reader), {"from": writer, "to": reader,
                                                 "kind": kind, "datasets": []})
        e["datasets"].append(dataset)
        if kind == "blocking":
            e["kind"] = "blocking"
    upstream, downstream = {}, {}
    for (w, r) in edges:
        upstream.setdefault(r, []).append(w)
        downstream.setdefault(w, []).append(r)

    by_stage = {sid: [] for sid, _, _ in STAGES}
    by_stage["other"] = []
    for step in PIPELINE_STEPS:   # run order (list order) within a stage
        name = step["name"]
        last = status_by_step.get(name, {})
        err = last.get("error_message")
        by_stage[stage_of(name)].append({
            "name": name,
            "module": step["module"],
            "function": step["function"],
            "table": step.get("table"),
            "writes": graph.writes(step),
            "source": step.get("source"),
            "frequency": step.get("frequency"),
            "critical": step.get("critical", False),
            "upstream": sorted(upstream.get(name, []), key=position.get),
            "downstream": sorted(downstream.get(name, []), key=position.get),
            "last_status": last.get("status"),
            "last_run_date": last.get("run_date"),
            "last_finished_at": last.get("finished_at"),
            "last_duration_sec": last.get("duration_sec"),
            "last_rows": last.get("rows_affected"),
            "last_error": (real_error(err)["error"] or err) if err else None,
        })

    layered = [{"id": sid, "name": label, "desc": desc, "steps": by_stage[sid],
                "n_failed": sum(1 for x in by_stage[sid] if x["last_status"] in ("FAILED", "ABORTED"))}
               for sid, label, desc in STAGES if by_stage[sid]]
    if by_stage["other"]:
        layered.append({"id": "other", "name": "Other", "desc": "steps not placed in a stage", "steps": by_stage["other"],
                        "n_failed": sum(1 for x in by_stage["other"] if x["last_status"] in ("FAILED", "ABORTED"))})
    layer_of = {s["name"]: layer["name"] for layer in layered for s in layer["steps"]}
    for e in edges.values():
        e["cross_layer"] = layer_of.get(e["from"]) != layer_of.get(e["to"])

    in_dag = {s["name"] for s in PIPELINE_STEPS}
    import datetime as _dt
    cutoff = (_dt.date.today() - _dt.timedelta(days=7)).isoformat()   # an old failure is history, not a banner
    # Cron jobs and datamodel steps log to pipeline_log but are not DAG steps: a failure there is
    # invisible in the DAG, so the banner lists them too (Health reports them as run failures).
    outside = [{"name": n, "last_status": r.get("status"),
                "last_error": (real_error(r.get("error_message"))["error"] or r.get("error_message")),
                "run_date": r.get("run_date")}
               for n, r in sorted(status_by_step.items())
               if n not in in_dag and r.get("status") in ("FAILED", "ABORTED")
               and str(r.get("run_date") or "") >= cutoff]
    all_steps = [s for layer in layered for s in layer["steps"]]
    return {
        "layers": layered,
        "outside_failures": outside,
        "step_count": len(all_steps),
        "n_ok": sum(1 for s in all_steps if s["last_status"] == "SUCCESS"),
        "n_never": sum(1 for s in all_steps if not s["last_status"]),
        "edges": sorted(edges.values(), key=lambda e: (position[e["from"]], position[e["to"]])),
        "n_blocking": sum(1 for e in edges.values() if e["kind"] == "blocking"),
        "n_lagged": sum(1 for e in edges.values() if e["kind"] == "lagged"),
        "failures": [s for s in all_steps if s.get("last_status") in ("FAILED", "ABORTED")],
    }


# ── Step rerun (UI button on /flow) ──────────────────────────────────────

def rerun_step(step_name: str) -> dict:
    """Spawn `python pipeline.py --step <name>` as a detached subprocess.

    Returns immediately so the HTTP request doesn't block. The pipeline writes
    its RUNNING/SUCCESS/FAILED rows to pipeline_log; the /flow page picks them
    up on its next auto-refresh.

    Refuses if (a) the step name isn't in PIPELINE_STEPS, or (b) a RUNNING row
    for that step is younger than 5 minutes (treat older as crashed / stale).
    """
    import subprocess
    import sys
    from datetime import datetime, timedelta
    from pathlib import Path
    from config import PIPELINE_STEPS

    valid = {s["name"] for s in PIPELINE_STEPS}
    if step_name not in valid:
        return {"ok": False, "error": f"unknown step: {step_name}"}

    recent = db.scalar(
        """SELECT started_at FROM pipeline_log
           WHERE step_name = ? AND status = 'RUNNING'
           ORDER BY id DESC LIMIT 1""",
        [step_name],
    )
    if recent is not None:
        try:
            started = datetime.fromisoformat(recent)
            if datetime.now() - started < timedelta(minutes=5):
                return {"ok": False, "error": f"{step_name} is already RUNNING"}
        except (ValueError, TypeError):
            pass

    # No-two-harvesters (CLAUDE.md): a rerun takes the same lock as run.sh harvesting jobs
    # and the watchdog. Refuse now if it is held; the child
    # re-takes it with `flock -n` for its whole run (plan 0015 D6).
    import fcntl
    lock_path = "/tmp/alpha_signal_harvest.lock"
    with open(lock_path, "a") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lf, fcntl.LOCK_UN)
        except BlockingIOError:
            return {"ok": False, "error": "another pipeline/harvester run holds the lock — try later"}

    project_root = Path(__file__).resolve().parent.parent
    rerun_log = project_root / "output" / "rerun.log"
    rerun_log.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(rerun_log, "ab")

    subprocess.Popen(
        ["flock", "-n", lock_path, sys.executable, "pipeline.py", "--step", step_name],
        cwd=project_root,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return {"ok": True, "step": step_name, "log": str(rerun_log)}


def get_data_health_scores(force=False):
    """Comprehensive per-table data health from health.compute_db_health().

    Pass force=True to recompute now. Otherwise served from a 5-minute
    _persisted_cache: an expired entry is returned stale and refreshed in the
    background (health.py's own cache recomputed inline — ~40s on the first
    /system hit after it lapsed)."""
    return _data_health_scores(_force=bool(force))


@_persisted_cache(300, name="get_data_health_scores")
def _data_health_scores():
    from health import compute_db_health
    # This layer owns the TTL, so each (re)compute is a real one.
    return compute_db_health(force=True)


# ═══════════════════════════════════════════════════
# Health Center — a VIEW over the health report (ADR 0059)
#
# checks.report.gather() is the one state: the terminal block, the email,
# the push, the MCP and this page all render it. Nothing here decides what is an
# issue or how severe it is — this only adds a drill-down link per issue and the
# catalog of every check.
# ═══════════════════════════════════════════════════

def _drilldown(issue):
    """('/sql?…', label) for an issue, or (None, None)."""
    code, target = issue["code"], issue["target"]
    if code.startswith("PIPELINE_"):
        sql = ("SELECT run_date, status, started_at, error_message FROM pipeline_log "
               f"WHERE step_name='{target}' ORDER BY id DESC LIMIT 20")
        return f"/sql?q={sql}", "Last 20 runs →"
    if code.startswith("FEED_"):
        return "/feeds", "Feeds →"
    table = target if code.startswith("TABLE_") else issue.get("table")
    if table and table in db.TABLES:
        return f"/sql?table={table}", f"Inspect {table} →"
    return None, None


# ── the real error behind a failed job ──

_FAIL_NEW = re.compile(r"^(?P<line>.*) \(exit (?P<rc>\d+); python -m runlog events --run (?P<run>\S+)\)$", re.S)
_FAIL_OLD = re.compile(r"^exit (?P<rc>\d+) \(python -m runlog events --run (?P<run>\S+)\)$")


def real_error(msg):
    """Split a pipeline_log.error_message into {error, rc, evidence}. `error` is the line that says
    why it failed: what run.sh `logged` recorded (runlog.failure_message), or for older "exit 1 (...)"
    rows the exception / ERROR event the run left in run_events. None when nothing was recorded."""
    msg = (msg or "").strip()
    m = _FAIL_NEW.match(msg) or _FAIL_OLD.match(msg)
    if not m:
        return {"error": msg or None, "rc": None, "evidence": None}
    d = m.groupdict()
    line = (d.get("line") or "").strip() or None
    evidence = f"python -m runlog events --run {d['run']}"
    if line is None:
        try:
            import runlog
            for e in runlog.events(run_id=d["run"], level="ERROR", limit=20):
                if e.get("event") in ("run_exit", "run_end"):
                    continue
                line = ": ".join(x for x in (e.get("error_type"), e.get("message")) if x)[:300] or None
                if line:
                    break
        except Exception:                                   # noqa: BLE001 — run_events absent on a fresh DB
            line = None
    return {"error": line, "rc": int(d["rc"]), "evidence": evidence}


def _cron_job(step):
    """(job, command) of the run.sh case whose `logged <step> run <command>` line records this log name."""
    case = None
    try:
        text = (PROJECT_ROOT / "run.sh").read_text()
    except OSError:
        return None, None
    for line in text.splitlines():
        m = re.match(r"^    (\w+)\)", line)
        if m:
            case = m.group(1)
        m = re.search(rf"\blogged {re.escape(step)} run (.+?)(?:\s*(?:\|\||;|$))", line)
        if m:
            return case, m.group(1).strip()
    return None, None


def _fix_for(issue):
    """The check's own 'do first' text with the step / feed filled in: no `<name>` placeholders, and
    for a failed job the exact command that reruns it."""
    code, target = issue["code"], issue["target"]
    fix = issue["fix"]
    if code == "PIPELINE_STEP":
        import runlog
        from config import PIPELINE_STEPS
        feed = runlog.feed_for(target)
        if target in {s["name"] for s in PIPELINE_STEPS}:
            rerun = f"`python pipeline.py --step {target}` (or Rerun on the Flow page)"
        else:
            job, cmd = _cron_job(target)
            rerun = (f"`{cmd}` (it also runs with `run.sh {job}`)" if cmd else "its cron job in run.sh")
        fix = f"Read the error, fix its cause, then rerun {rerun}."
        if feed:
            fix += f" Evidence: `python -m runlog bundle {feed}`."
    elif code.startswith("FEED_"):
        fix = fix.replace("<feed>", target)
    if "<" in fix:                                          # an unfilled placeholder is worse than no sentence
        fix = " ".join(x for x in re.split(r"(?<=\.) ", fix) if not re.search(r"<\w+>", x))
    return fix


def backfill_marker(days=3):
    """{"active": bool, "last": ISO date | None}: is a history backfill (run.sh backfill, output/backfill.log) running
    now. Active = the log was written in the last `days` days. Volume spikes during one are expected."""
    import datetime as _dt
    try:
        last = _dt.datetime.fromtimestamp((PROJECT_ROOT / "output" / "backfill.log").stat().st_mtime).date()
    except OSError:
        return {"active": False, "last": None}
    return {"active": (_dt.date.today() - last).days <= days, "last": last.isoformat()}


GROUP_TITLE = {          # code -> "{n} ..." headline for a group of issues sharing a cause
    "TABLE_EMPTY": "{n} tables or output files are empty",
    "FEED_PROBE": "{n} feeds failed their morning probe",
    "FEED_VOLUME": "{n} feeds wrote an unusual number of rows",
    "PIPELINE_STEP": "{n} steps failed",
}


def _cause(issue):
    """Issues with the same cause key are shown as one group. The datamodel jobs share one (the
    reconcile compares what the sync wrote, so it cannot pass while the sync fails); a probe failing
    with the same error text, empty tables, and volume spikes of the same direction share by code."""
    code, target = issue["code"], issue["target"]
    if code == "PIPELINE_STEP" and target.startswith("datamodel_"):
        return ("datamodel",)
    if code == "FEED_PROBE":
        return (code, re.sub(r"\d[\d.,]*", "#", (issue.get("detail") or "").lower()).strip())
    if code == "FEED_VOLUME":
        return (code, "spike" if "SPIKE" in issue["id"] else "drop")
    if code == "TABLE_EMPTY":
        return (code,)
    return (issue["id"],)


def _plain_name(text):
    """`_file_db_backup` is the checker's virtual table for the output file db_backup: say so."""
    return re.sub(r"\b_file_(\w+)", r"output file \1", text or "")


def _member(issue):
    e = real_error(issue.get("detail")) if issue["code"] == "PIPELINE_STEP" else {"error": None, "evidence": None}
    return {"id": issue["id"], "target": _plain_name(issue["target"]), "message": _plain_name(issue["message"]), "detail": issue.get("detail") or "",
            "error": e["error"], "evidence": e["evidence"], "days": issue["days"], "standing": issue["standing"],
            "drilldown_url": issue.get("drilldown_url"), "drilldown_label": issue.get("drilldown_label")}


def group_issues(issues, backfill=None):
    """The gathered issues of ONE question, folded into groups that share a cause, worst first.
    Pure presentation: every issue keeps its own severity (the group takes the worst), why and fix come
    from the check, and the member list carries each issue's real error line."""
    import feeds
    buckets = {}
    for i in issues:
        buckets.setdefault((i["theme"],) + _cause(i), []).append(i)
    groups = []
    for key, members in buckets.items():
        first = members[0]
        sev = "CRITICAL" if any(m["severity"] == "CRITICAL" for m in members) else "WARN"
        n = len(members)
        g = {"key": ":".join(map(str, key)), "theme": first["theme"], "severity": sev, "n": n, "code": first["code"],
             "members": [_member(m) for m in members], "why": first["why"], "fix": _fix_for(first),
             "days": max(m["days"] for m in members), "standing": any(m["standing"] for m in members),
             "cause": None, "note": None, "title": _plain_name(first["message"])}
        if n > 1:
            if key[1] == "datamodel":
                g["title"] = "The v3 data-model jobs failed (" + ", ".join(m["target"] for m in members) + ")"
                g["fix"] = ("Fix the sync first, then rerun it: `python -m datamodel.sync`, then "
                            "`python -m datamodel.reconcile` (the reconcile cannot pass while the sync fails). "
                            "Both also run with `run.sh morning` at 03:30 UTC.")
            else:
                g["title"] = GROUP_TITLE.get(first["code"], "{n} x " + first["message"]).format(n=n)
        if first["code"] == "FEED_PROBE" and n > 1:
            hosts = None
            for m in members:
                h = set((feeds.FEEDS.get(m["target"]) or {}).get("hosts") or [])
                hosts = h if hosts is None else hosts & h
            if hosts:
                host = sorted(hosts)[0]
                g["cause"] = (f"All {n} read the {host} host and fail with the same error: look at that host first "
                              f"(one upstream cause), not at {n} separate feeds.")
        if first["code"] == "FEED_VOLUME" and "SPIKE" in first["id"] and backfill and backfill["active"]:
            g["note"] = f"Expected while the history backfill runs (output/backfill.log last written {backfill['last']})."
        groups.append(g)
    groups.sort(key=lambda g: (g["severity"] != "CRITICAL", -g["days"], g["title"]))
    return groups


def since_yesterday(issues, prev):
    """New / still open / cleared against the last recorded day. `issues` = today's gathered issues,
    `prev` = checks.history.previous_firing(). None when there is no earlier day to compare with."""
    if not prev or not prev.get("day"):
        return None
    now = {i["id"]: i for i in issues}
    before = prev["firing"]
    short = lambda x: x.split(":", 1)[-1]                      # noqa: E731 — "PIPELINE_STEP:fetch_x" -> "fetch_x"
    return {"day": prev["day"],
            "new": [{"id": k, "label": now[k]["message"]} for k in now if k not in before],
            "open": [{"id": k, "label": now[k]["message"], "days": now[k]["days"]} for k in now if k in before],
            "cleared": [{"id": k, "label": short(k)} for k in before if k not in now]}


@_persisted_cache(300, name="get_health_overview")
def get_health_overview(force=False):
    """The Health page: {as_of, verdict, verdict_severity, counts, scorecard (five questions), issues +
    tolerated (flat, each with a drill-down link), sections (per question: its issues grouped by cause),
    since (new / open / cleared against the last recorded day), catalog, severity_meaning, watchdog,
    pipeline_summary, eligibility, integrity}. checks.report.gather() is the one source."""
    from checks import SEVERITY_MEANING, history, report

    st = report.gather()

    def linked(rows):
        return [dict(i, drilldown_url=u, drilldown_label=l) for i in rows for u, l in [_drilldown(i)]]

    s = st["summary"]
    issues = linked(st["issues"])
    integrity = (st["integrity"] or {}).get("rows") or []
    bf = backfill_marker()
    try:
        prev = history.previous_firing()
    except Exception:                                       # noqa: BLE001 — history table absent on a fresh DB
        prev = None
    sections = [{**q, "groups": group_issues([i for i in issues if i["theme"] == q["theme"]], bf)}
                for q in st["scorecard"]]
    return _clean({
        "as_of": st["as_of"],
        "verdict": s["verdict"],
        "verdict_severity": "CRITICAL" if s["critical"] else "WARN" if s["warn"] else "OK",
        "counts": {"critical": s["critical"], "warn": s["warn"], "info": len(st["tolerated"])},
        "scorecard": st["scorecard"],
        "sections": sections,
        "since": since_yesterday(issues, prev),
        "issues": issues,
        "tolerated": linked(st["tolerated"]),
        "catalog": report.catalog(st),
        "severity_meaning": SEVERITY_MEANING,
        "watchdog": st["watchdog"],
        "pipeline_summary": st["pipeline"],
        # per-signal "who should have a score" vs "who lacks it" (plan 0005 Phase A)
        "eligibility": db.rows(
            "SELECT signal, "
            "       SUM(CASE WHEN eligible=1 THEN 1 ELSE 0 END) AS n_eligible, "
            "       SUM(CASE WHEN eligible=0 THEN 1 ELSE 0 END) AS n_ineligible "
            "FROM universe_eligibility "
            "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM universe_eligibility) "
            "GROUP BY signal ORDER BY signal"),
        "integrity": {status.lower() + "s": [r for r in integrity if r["integrity_status"] == status]
                      for status in ("FAIL", "WARN")},
    })


def get_table_columns():
    """Every table's columns for the Inventory: {table: {cols: [{name, type, pk, notnull}], fks: [...]}} (PRAGMA only)."""
    out = {}
    with get_db() as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name")]
        for t in names:
            out[t] = {"cols": [{"name": r[1], "type": r[2], "pk": int(r[5]), "notnull": bool(r[3])}
                               for r in conn.execute(f"PRAGMA table_info([{t}])")],
                      "fks": [{"col": r[3], "ref": f"{r[2]}.{r[4]}"} for r in conn.execute(f"PRAGMA foreign_key_list([{t}])")]}
    return out


# ─────────────── Data Supply (plan 0018): feeds, canaries, discovery, known issues ───────────────

def _clean(o):
    """NaN/NaT → None, recursively, so templates and JSON see plain values."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    try:
        if o is not None and not isinstance(o, str) and pd.isna(o):
            return None
    except (TypeError, ValueError):
        pass
    return o


_PLAIN = {   # verdict code → plain words for the page (the email keeps the precise codes)
    "FEED_CANARY_FAIL": "Health check failed",
    "FEED_CANARY_WARN": "Health check warning",
    "FEED_CANARY_ERROR": "Health check crashed (our code)",
    "FEED_CANARY_MISSING": "Health check hasn't run recently",
    "FEED_RUN_FAILED": "Last run failed",
    "FEED_OUTDATED": "Data is out of date",
    "FEED_VOLUME_DROP": "Wrote far fewer rows than usual",
    "FEED_VOLUME_SPIKE": "Wrote far more rows than usual",
    "FEED_RECONCILE_FAIL": "Disagrees with an independent source",
}


def _age_label(days):
    if days is None:
        return None
    d = int(round(float(days)))
    # age of the newest data point (e.g. a quarter-end), not of the fetch; the page
    # shows it with the feed's cadence ("101 d · quarterly"); "on schedule" / "overdue" comes from the freshness rule, which knows the lag
    return "today" if d <= 0 else f"{d} d"


def _plain(r):
    """Plain-language fields for the simplified Data Supply page."""
    last = r.get("canary_last") or {}
    r["state"] = {"CRITICAL": "Broken", "WARN": "Needs a look"}.get(r.get("health"), "OK")
    r["importance"] = {"T1": "Critical", "T2": "Normal"}.get(r.get("tier"), "")
    if not r.get("canary"):
        r["check"] = "no check"
    elif not last:
        r["check"] = "not run yet"
    else:
        r["check"] = {"PASS": "passed", "FAIL": "failed", "WARN": "warning", "ERROR": "crashed"}.get(last["status"], last["status"])
    r["check_when"] = (last.get("checked_at") or "")[5:16].replace("T", " ") if last else ""
    wf = r.get("worst_freshness") or {}
    r["age"] = _age_label(wf.get("age_days"))
    r["age_bad"] = wf.get("freshness") in ("OUTDATED", "STALE")
    r["backup"] = {"fallback": "Yes", "serve-stale": "No — keeps using the last good data",
                   "none": "No"}.get(r.get("resilience"), "—")
    # registry facts (held by tests/test_feeds.py, shown here because the page lists them)
    labels = (["Not scheduled to run"] if not r.get("schedule") else []) + \
             (["Critical, and no backup source"] if r.get("tier") == "T1" and r.get("resilience") == "none" else [])
    problems = list(labels)
    for v in r.get("verdicts", []):
        # T2 canary warnings are INFO for the email, but the page shows them: a
        # "warning" health check next to an "OK" status reads as a contradiction.
        shown = v["severity"] in ("CRITICAL", "WARN") or v["code"] == "FEED_CANARY_WARN"
        if shown and v["code"] in _PLAIN:
            detail = (v.get("detail") or "").strip()
            labels.append(_PLAIN[v["code"]])
            problems.append(_PLAIN[v["code"]] + (f": {detail[:200]}" if detail else ""))
    r["problems"], r["problem_labels"] = problems, labels
    if r["state"] == "OK" and labels:
        r["state"] = "Needs a look"
    r["where"] = next((e.get("location") for e in r.get("log_problems") or [] if e.get("location")), None)
    return r


def group_feed_alarms(rows, backfill=None):
    """The feeds' alarms folded by cause, worst first: feeds that fail the same way (same verdict, and for a
    failed health check the same error text) are one group, with the host they share named, and a volume
    spike during a declared backfill marked as expected. Each feed keeps its own verdicts below."""
    import feeds
    buckets = {}
    for r in rows:
        for v in r.get("verdicts", []):
            shown = v["severity"] in ("CRITICAL", "WARN") or v["code"] == "FEED_CANARY_WARN"
            if not (shown and v["code"] in _PLAIN):
                continue
            detail = (v.get("detail") or "").strip()
            same_error = v["code"] in ("FEED_CANARY_FAIL", "FEED_CANARY_WARN", "FEED_CANARY_ERROR")
            key = (v["code"], re.sub(r"\d[\d.,]*", "#", detail.lower()) if same_error else "")
            b = buckets.setdefault(key, {"code": v["code"], "label": _PLAIN[v["code"]], "severity": v["severity"],
                                         "detail": detail if same_error else "", "feeds": [], "samples": {}})
            b["feeds"].append(r["feed"])
            b["samples"][r["feed"]] = detail
            if v["severity"] == "CRITICAL":
                b["severity"] = "CRITICAL"
    out = []
    for b in buckets.values():
        n = len(b["feeds"])
        b["n"] = n
        b["cause"] = b["note"] = None
        if n > 1 and b["code"].startswith("FEED_CANARY"):
            hosts = None
            for f in b["feeds"]:
                h = set((feeds.FEEDS.get(f) or {}).get("hosts") or [])
                hosts = h if hosts is None else hosts & h
            if hosts:
                b["cause"] = (f"All {n} read the {sorted(hosts)[0]} host and fail with the same error: "
                              f"one upstream cause to look at, not {n} broken feeds.")
        if b["code"] == "FEED_VOLUME_SPIKE" and backfill and backfill["active"]:
            b["note"] = f"Expected while the history backfill runs (output/backfill.log last written {backfill['last']})."
        out.append(b)
    out.sort(key=lambda b: (b["severity"] != "CRITICAL", -b["n"], b["label"]))
    return out


@_persisted_cache(300, name="get_feed_overview")
def get_feed_overview():
    """Everything the /feeds page shows, from feeds.FEEDS + checks.feeds (one source
    of truth with the health report — the page and the email cannot disagree)."""
    import feeds
    from checks import CRITICAL, WARN
    from checks.feeds import feed_state, feed_verdicts, registry_drift

    rows = _clean(feed_state())
    drift = registry_drift()
    verdicts = feed_verdicts(rows)
    by_feed = {}
    for v in verdicts:
        by_feed.setdefault(v["target"], []).append(v)
    sev_rank = {CRITICAL: 0, WARN: 1, "INFO": 2}
    for r in rows:
        vs = list(by_feed.get(r["feed"], []))
        # The page's dot is OVERALL health: canary/registry verdicts (the email's),
        # plus the feed's last run and the freshness of what it writes (the email
        # reports those through its pipeline/freshness verdicts).
        live_feed = r["status"] in feeds.LIVE and r["tier"] in ("T1", "T2")
        lr = r.get("last_run") or {}
        if live_feed and lr.get("status") == "FAILED":
            vs.append({"severity": WARN, "code": "FEED_RUN_FAILED", "target": r["feed"],
                       "message": f"{r['feed']} last run FAILED ({lr.get('step_name')})",
                       "detail": (lr.get("error_message") or "")[:200]})
        wf = r.get("worst_freshness") or {}
        if live_feed and wf.get("freshness") == "OUTDATED":
            vs.append({"severity": WARN, "code": "FEED_OUTDATED", "target": r["feed"],
                       "message": f"{r['feed']} writes {wf['table']}, OUTDATED ({wf.get('age_days')}d old)",
                       "detail": ""})
        vs.sort(key=lambda v: sev_rank.get(v["severity"], 3))
        r["verdicts"] = vs
        r["health"] = vs[0]["severity"] if vs and vs[0]["severity"] in (CRITICAL, WARN) else "OK"
        last = r.get("canary_last") or {}
        r["canary_status"] = last.get("status")

    # Run log (runlog.py): each feed's latest run and its recent WARN/ERROR events.
    import runlog
    try:
        last_runs, recent = {}, {}
        for x in runlog.runs(limit=600):
            if x.get("feed"):
                last_runs.setdefault(x["feed"], x)
        for e in runlog.events(level="WARN", since="7d", limit=1500):
            if e.get("feed") and len(recent.setdefault(e["feed"], [])) < 5:
                recent[e["feed"]].append({k: e.get(k) for k in ("ts", "level", "event", "symptom", "message",
                                                                 "location", "http_status", "item", "run_id")})
    except Exception:                                     # noqa: BLE001 — table absent on a fresh DB
        last_runs, recent = {}, {}
    for r in rows:
        r["log_run"] = _clean(last_runs.get(r["feed"]))
        r["log_problems"] = _clean(recent.get(r["feed"], []))

    for r in rows:
        _plain(r)

    live = [r for r in rows if r["status"] in feeds.LIVE]
    probed = [r for r in live if r["canary"]]
    t1 = [r for r in live if r["tier"] == "T1"]

    def count(pred, rs=live):
        return sum(1 for r in rs if pred(r))

    summary = {
        "live": len(live), "t1": len(t1), "t2": count(lambda r: r["tier"] == "T2"),
        "discovery": count(lambda r: r["status"] in feeds.DISCOVERY + ("probation",), rows),
        "retired": count(lambda r: r["status"] == "retired", rows),
        "canary_total": len(probed), "canary_pass": count(lambda r: r["canary_status"] == "PASS", probed),
        "canary_fail": count(lambda r: r["canary_status"] in ("FAIL", "ERROR"), probed),
        "canary_warn": count(lambda r: r["canary_status"] == "WARN", probed),
        "drift": count(lambda r: (r.get("canary_last") or {}).get("symptom") == "D", probed),
        "critical": count(lambda r: r["health"] == CRITICAL), "warn": count(lambda r: r["health"] == WARN),
        "t1_fallback": count(lambda r: r["resilience"] == "fallback", t1),
        "t1_single": count(lambda r: r["resilience"] == "serve-stale", t1),
        "orphans": count(lambda r: not r["schedule"]), "registry_drift": len(drift),
        "last_canary": max((r["canary_last"]["checked_at"] for r in probed if r.get("canary_last")), default=None),
    }
    order = {"Broken": 0, "Needs a look": 1, "OK": 2}
    summary.update(n_ok=sum(r["state"] == "OK" for r in live),
                   n_look=sum(r["state"] == "Needs a look" for r in live),
                   n_broken=sum(r["state"] == "Broken" for r in live),
                   critical_no_backup=sum(r["tier"] == "T1" and r["resilience"] != "fallback" for r in live))
    return {
        "summary": summary,
        "simple": sorted(live, key=lambda r: (order[r["state"]], r["tier"] != "T1", r["feed"])),
        "alarms": group_feed_alarms(live, backfill_marker()),
        "new_sources": [r for r in rows if r["status"] in ("wanted", "candidate", "probation")],
        "drift": [{"what": w, "name": n} for w, n in drift],
    }


# ─────────────────────────── Boardroom (plan 0019) ───────────────────────────

BOARD_ORDER = {"approve": 0, "discuss": 1, "park": 2, "reject": 3}     # the board pack's recommendation, best first
STALE_AFTER_DAYS = 14                                                    # an undecided card this old is flagged


def _settled_refs(ids, git_log=None, adr_dir=None):
    """{item id: ["ADR 0064", "commit abc123 feat: ..."]} for every inbox id an ADR or a commit
    message names (the card was probably settled outside the Boardroom). Commits come from the
    last 600 on the current branch; ADRs from docs/decisions."""
    import re
    import subprocess
    found = {}
    if not ids:
        return found
    if git_log is None:
        try:
            git_log = subprocess.run(["git", "log", "-n", "600", "--format=%h%x1f%s%x1f%b%x1e"], cwd=PROJECT_ROOT,
                                     capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            git_log = ""
    commits = [c.strip("\n").split("\x1f", 2) for c in git_log.split("\x1e") if c.strip()]
    adr_dir = Path(adr_dir) if adr_dir else PROJECT_ROOT / "docs" / "decisions"
    adrs = []
    for f in sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md")) if adr_dir.is_dir() else []:
        try:
            adrs.append((f.name[:4], f.read_text(errors="replace")))
        except OSError:
            pass
    for i in ids:
        pat = re.compile(rf"(?<![\d.]){int(i)}(?!\d)")
        refs = [f"ADR {n}" for n, text in adrs if pat.search(text)]
        refs += [f"commit {h} {subj[:60]}" for h, subj, *body in commits if pat.search(subj + " " + (body[0] if body else ""))]
        if refs:
            found[int(i)] = refs[:3]
    return found


def _inbox_cards(ov):
    """Each inbox item with the board pack's call on it, its option buttons, and whether it looks
    settled; sorted by the pack's recommendation (approve, discuss, park, reject, not listed)."""
    pack = (ov.get("board_pack") or {}).get("fields") or {}
    calls = {int(d["item_id"]): d for d in pack.get("decisions") or [] if str(d.get("item_id", "")).isdigit()}
    refs = _settled_refs([i["doc_id"] for i in ov["inbox"]])
    for i in ov["inbox"]:
        f = i["fields"]
        c = calls.get(i["doc_id"])
        i["board"] = {"recommendation": c["recommendation"], "why_now": c.get("why_now")} if c else None
        i["board_rank"] = BOARD_ORDER.get(c["recommendation"], 4) if c else 4
        rec = (f.get("recommendation") or "").lower()
        i["option_list"] = [{"i": n, "text": t, "recommended": bool(rec) and rec.startswith(t.lower()[:30])}
                            for n, t in enumerate(f.get("options") or [])]
        i["settled_by"] = refs.get(i["doc_id"], [])
        i["stale"] = i.get("age_days", 0) >= STALE_AFTER_DAYS
    ov["inbox"].sort(key=lambda i: (i["board_rank"], i["fields"].get("urgency") != "now",
                                    {"work_order": 0, "ask": 1, "hypothesis": 2}.get(i["type"], 3), i["doc_id"]))
    return ov


@_persisted_cache(300, name="get_org_overview")      # 0.5-9 s uncached; a decision invalidates it
def get_org_overview(mfrom=None, mto=None, mrole=None):
    """Everything the /org Boardroom page shows: the role tree with each seat's
    scorecard, the CEO inbox, the latest board pack, recent memos with their grades
    and recent decisions. org.overview() is the one source — the alpha-ops `org`
    MCP tool returns the same data."""
    import datetime as _dt
    import org
    ov = _clean(org.overview())
    # The Memos tab's filter: a date range and/or one employee. No filter = the newest of the last 14 days.
    def _date(v):
        try:
            return _dt.date.fromisoformat(str(v)[:10]).isoformat() if v else None
        except ValueError:
            return None
    recent = len(ov["memos"])                 # the tile counts the last 14 days whatever the filter shows
    mfrom, mto = _date(mfrom), _date(mto)
    mrole = mrole if mrole in org.ROLES else None
    filtered = bool(mfrom or mto or mrole)
    if filtered:
        ov["memos"] = _clean([m for m in org.memos(mfrom, mto, mrole, limit=151) if m["type"] != "board_pack"])
    today = _dt.date.today()
    ov["memo_filter"] = {
        "mfrom": mfrom or "", "mto": mto or "", "mrole": mrole or "", "active": filtered,
        "capped": filtered and len(ov["memos"]) > 150,
        "quick": [("Today", today.isoformat()), ("7 days", (today - _dt.timedelta(days=7)).isoformat()),
                  ("30 days", (today - _dt.timedelta(days=30)).isoformat()), ("All time", "2000-01-01")],
        "first": org.docs(org.MEMO_TYPES, days=None, limit=1) and db.scalar(
            "SELECT MIN(substr(doc_date, 1, 10)) FROM documents WHERE source = 'org' AND status = 'valid'"),
    }
    by_id = {r["id"]: r for r in ov["roles"]}
    tree = []

    def walk(boss, depth):
        for r in ov["roles"]:
            if r["reports_to"] == boss:
                tree.append({**r, "depth": depth})
                walk(r["id"], depth + 1)
    walk(None, 0)
    for m in ov["memos"] + ov["inbox"] + ov["decisions"]:
        m["role_title"] = (by_id.get(m["fields"].get("role")) or {}).get("title") or m["fields"].get("role")
    graded = [r["score"]["grade"] for r in ov["roles"] if (r.get("score") or {}).get("grade") is not None]
    ov["tree"] = tree
    _inbox_cards(ov)
    # item id -> the CEO's verdict, so the board pack can say what became of a decision it lists
    ov["decided"] = {d["parent_doc_id"]: d["fields"].get("verdict") for d in reversed(ov["decisions"])
                     if d.get("parent_doc_id")}
    ov["memos"] = ov["memos"][:150 if filtered else 40]   # unfiltered: the newest; the date filter reaches the rest
    ov["running"] = org_running()
    ov["summary"] = {
        "agents": sum(1 for r in ov["roles"] if r["type"] != "human"),
        "desk": sum(1 for r in ov["roles"] if r["type"] == "desk"),
        "inbox": len(ov["inbox"]),
        "memos": recent,
        "avg_grade": round(sum(graded) / len(graded), 1) if graded else None,
    }
    return ov


def get_org_memo(doc_id):
    """One desk memo for the archive's lazy body: {memo, grade} or None when the id is not a memo."""
    import org
    m = org.doc(doc_id)
    if not m or m["type"] not in org.MEMO_TYPES or m["status"] != "valid":
        return None
    g = next(iter(org.docs(["grade"], days=None, parent=m["doc_id"], limit=1)), None)
    m["grade"] = ({"total": g["fields"].get("total"), "verdict": g["fields"].get("verdict"),
                   "issues": g["fields"].get("issues")} if g else None)
    return _clean(m)


def invalidate_org_overview():
    """Drop every cached Boardroom view (memo + pickles): the next read recomputes, so a
    decision shows on the next page load instead of up to 5 minutes later."""
    from cockpit._shared import _PERSISTED_CACHE_DIR
    get_org_overview.cache_clear()
    for f in _PERSISTED_CACHE_DIR.glob("get_org_overview*.pkl"):
        f.unlink(missing_ok=True)


ORG_LOCK = "/tmp/alpha_signal_org.lock"      # the same lock run.sh `org` takes: org runs never overlap


def org_running():
    """True while an org run (cron or a Run-now click) holds the org lock."""
    import fcntl
    with open(ORG_LOCK, "a") as lf:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lf, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True


def org_run(role):
    """Start a seat (or "all" enabled desk seats) now, detached: an ad hoc run that leaves
    the scheduled period free and sends no email. Memos appear on the page as each seat
    finishes. Refuses while another org run holds the lock."""
    import subprocess
    import sys
    from pathlib import Path
    import org
    if role != "all" and (role not in org.ROLES or org.ROLES[role]["type"] != "desk"):
        return {"ok": False, "error": f"{role!r} is not a desk seat (builders are started from a Claude Code session)"}
    if org_running():
        return {"ok": False, "error": "an org run is already in progress; try again when it finishes"}
    root = Path(__file__).resolve().parent.parent
    log_fp = open(root / "output" / "org.log", "ab")
    args = ["--all"] if role == "all" else ["--role", role]
    subprocess.Popen(["flock", "-n", ORG_LOCK, sys.executable, "-m", "org", "run", *args, "--adhoc", "--no-deliver"],
                     cwd=root, stdout=log_fp, stderr=subprocess.STDOUT, start_new_session=True)
    return {"ok": True, "role": role, "log": "output/org.log"}
