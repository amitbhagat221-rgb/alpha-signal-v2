"""
Alpha Signal v2 — Ops cockpit API (extracted Stage 2, 2026-05-26).

10 Ops-domain functions + their private helpers moved out of cockpit/api.py
during the cockpit_ops split.

Functions defined here (in original cockpit/api.py order):
  - get_pipeline_status
  - run_sql_query
  - get_data_freshness
  - get_db_summary
  - get_model_overview            (plus helper get_backtest_roster)
  - _safe_int, _safe_float        (helpers)
  - get_flow_overview
  - rerun_step
  - get_data_health_scores
  - get_factor_health
  - _read_md_section, _parse_plan_frontmatter   (helpers)
  - get_command_centre
  - _drilldown_for_issue, _severity_rank        (helpers for health overview)
  - get_health_overview

Shared decorators (_persisted_cache, _ttl_cache) live in cockpit/_shared.py and
are imported one-way here; cross-cutting helpers (read_sql, get_db) come from
db. Nothing here imports cockpit/api.py, and cockpit/app.py imports
get_model_overview from this module directly — no import cycle.

See cockpit_ops/README.md for the split architecture. See ADR 0028 (TBW)
for the rationale.
"""

import json
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
    state, stale RUNNING rows marked ABORTED — views.pipeline_status."""
    return views.pipeline_status(days)


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


@_persisted_cache(300, name="get_sql_schema")
def get_sql_schema():
    """The SQL console's Schema tab in ONE call: every table with its columns
    (sqlite_master + PRAGMA table_info) and its row count (from the cached
    data_health scan, so no COUNT(*) per table). `as_of` is when the counts were taken."""
    import datetime as _dt
    counts = {r["table"]: r.get("rows") for r in get_data_freshness()}
    out = []
    with get_db() as conn:
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                    "AND name != 'sqlite_sequence' ORDER BY name").fetchall():
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info([{name}])").fetchall()]
            n = counts.get(name)
            out.append({"name": name, "columns": cols, "rows": int(n) if n is not None else None})
    return {"tables": out, "as_of": _dt.date.today().isoformat()}


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
V1_BACKTEST_DIR = Path("/home/ubuntu/alpha-signal/data/backtest")


@_persisted_cache(300, name="get_model_overview")
def get_model_overview():
    """Tier weight tables, signal validation, regime rules. Used by /model."""
    from config import REGIMES, PORTFOLIO, TRANSACTION_COSTS_BPS
    from factors import SIGNAL_WEIGHTS

    # Per-tier signal weights — convert dict to ordered list of (signal, weight, pct).
    tiers = {}
    for tier, weights in SIGNAL_WEIGHTS.items():
        total = sum(weights.values()) or 1
        rows = sorted(weights.items(), key=lambda kv: -kv[1])
        tiers[tier] = [
            {"signal": s, "weight": w, "pct": round(100 * w / total, 1)}
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

    # Validation t-stats from v1 backtest (PIT reconstruction, 18 periods).
    validation_csv = V1_BACKTEST_DIR / "reconstructed_ic_by_tier.csv"
    validation_rows = []
    validation_meta = {}
    if validation_csv.exists():
        try:
            v = pd.read_csv(validation_csv)
            validation_meta = {
                "periods": int(v["n_periods"].max()) if "n_periods" in v.columns else None,
                "source": "v1 reconstructed_ic_by_tier.csv",
            }
            for _, row in v.iterrows():
                validation_rows.append({
                    "signal": row.get("signal"),
                    "description": row.get("description"),
                    "cap_tier": row.get("cap_tier"),
                    "n_stocks_avg": _safe_int(row.get("n_stocks_avg")),
                    "mean_ic": _safe_float(row.get("mean_ic"), 4),
                    "icir": _safe_float(row.get("icir"), 3),
                    "t_stat": _safe_float(row.get("t_stat"), 2),
                    "verdict": row.get("verdict"),
                })
        except Exception:
            pass

    return {
        "tiers": tiers,
        "regimes": regimes,
        "current_regime": current_regime,
        "validation": {"rows": validation_rows, "meta": validation_meta},
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


@_ttl_cache(300)
def get_flow_overview():
    """The pipeline as its dataflow graph, for /flow. Everything is derived from the
    step declarations (graph.py): edges are graph.edges() collapsed to step pairs
    (blocking = the reader sees this run's write; lagged = the previous run's),
    layers are the steps' module packages ordered left→right by their mean dataflow
    depth (longest chain of blocking edges above a step; steps keep run order inside
    a layer), and each step carries its latest views.step_status() row."""
    import graph
    from config import PIPELINE_STEPS

    status_by_step = views.step_status()
    try:
        derived = graph.order(PIPELINE_STEPS)
    except ValueError:  # a declaration cycle — fall back to list order, still render
        derived = [s["name"] for s in PIPELINE_STEPS]
    position = {n: i for i, n in enumerate(derived)}
    parents = {}
    for w, r, _, kind in graph.edges(PIPELINE_STEPS):
        if kind == "blocking":
            parents.setdefault(r, set()).add(w)
    depth = {}
    for n in derived:
        depth[n] = 1 + max((depth[p] for p in parents.get(n, ()) if p in depth), default=-1)

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

    def _layer(module):
        return module.split(".")[0].replace("_", " ").title() if "." in module else "Other"

    layers = {}
    for step in PIPELINE_STEPS:   # run order (list order) within a layer
        name = step["name"]
        last = status_by_step.get(name, {})
        layers.setdefault(_layer(step["module"]), []).append({
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
            "last_finished_at": last.get("finished_at"),
            "last_duration_sec": last.get("duration_sec"),
            "last_rows": last.get("rows_affected"),
            "last_error": last.get("error_message"),
        })

    def _mean_depth(steps):
        return sum(depth[s["name"]] for s in steps) / len(steps)

    layered = [{"name": ln, "steps": steps}
               for ln, steps in sorted(layers.items(), key=lambda kv: _mean_depth(kv[1]))]
    layer_of = {s["name"]: layer["name"] for layer in layered for s in layer["steps"]}
    for e in edges.values():
        e["cross_layer"] = layer_of.get(e["from"]) != layer_of.get(e["to"])

    return {
        "layers": layered,
        "step_count": sum(len(layer["steps"]) for layer in layered),
        "edges": sorted(edges.values(), key=lambda e: (position[e["from"]], position[e["to"]])),
        "n_blocking": sum(1 for e in edges.values() if e["kind"] == "blocking"),
        "n_lagged": sum(1 for e in edges.values() if e["kind"] == "lagged"),
        "failures": [
            s for layer in layered for s in layer["steps"]
            if s.get("last_status") in ("FAILED", "ABORTED")
        ],
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
# Factor Health — sister to data-health, but per-factor
# ═══════════════════════════════════════════════════

@_persisted_cache(300, name="get_factor_health")
def get_factor_health():
    """Return one row per registered factor with health metrics + grade.

    Per-factor metrics:
      - coverage_pct   : stocks with non-null score / eligible universe
      - freshness_days : days since last snapshot
      - best_abs_t     : best |t-stat| across cap-tiers from pit_ic_by_tier_v2
      - pit_ready      : factor has PIT helper + appears in daily_snapshots_pit
      - in_model       : marked production-ready
    Aggregated 0-100 grade with letter (A+/A/B/C/D/F).
    """
    from db import BACKTEST_SIGNALS, get_backtest_cadence as _bt_cadence

    # Track 3 extras list — all entries were duplicates of BACKTEST_SIGNALS
    # rows as of 2026-05-24 (Track 3 factors got promoted to BACKTEST_SIGNALS
    # when they shipped). Keeping them here double-counted each one and the
    # duplicate showed as F (cockpit looked up by score_table which sometimes
    # failed silently). Cleaned out; new Track 3 factors should be registered
    # directly in BACKTEST_SIGNALS with pit_column_v2.
    TRACK3_EXTRAS = []

    PROMOTION_T = 1.5

    # Universe baselines for coverage normalisation
    with get_db() as conn:
        uni_total = conn.execute(
            "SELECT COUNT(*) FROM stocks WHERE ticker IS NOT NULL"
        ).fetchone()[0]
        uni_excl_fin = conn.execute(
            "SELECT COUNT(*) FROM stocks WHERE ticker IS NOT NULL AND sector != 'Financials'"
        ).fetchone()[0]

        # Best t-stat per signal — plan 0005 Phase D rule, shared with /command.
        # Pre-fix: always preferred v2_recompute even at n=6, masking the n=35
        # v1_archive result for the same signal. The n<12 gate then nuked the
        # whole factor library to INSUFFICIENT.
        best_by_signal = best_ic_by_signal()

        # PIT columns actually populated in daily_snapshots_pit (latest snapshot).
        # NOTE: daily_snapshots_pit is the *backtest* reconstruction, only refreshed
        # when pit.py runs (manually, periodically). Use this
        # only for PIT-readiness flag (does the column exist) — NOT for factor
        # freshness shown in the UI. For production freshness see latest_live below.
        try:
            latest_pit = conn.execute(
                "SELECT MAX(snapshot_date) FROM daily_snapshots_pit"
            ).fetchone()[0]
        except Exception:
            latest_pit = None

        # Live production snapshot — written by scoring/screener.py + output/snapshot.py
        # on every daily pipeline run. This is what "factor freshness" should reflect.
        try:
            latest_live = conn.execute(
                "SELECT MAX(snapshot_date) FROM daily_snapshots"
            ).fetchone()[0]
        except Exception:
            latest_live = None

        # Per-column coverage at THAT COLUMN's latest non-null date.
        # ADR 0022 split cadence (weekly behavioural vs monthly fundamentals).
        # The latest table-wide snapshot_date is a Friday with ONLY the 6 behavioural
        # columns populated — using it for coverage gave 0/2448 for every monthly
        # fundamental, falsely grading 56 factors as F (2026-05-24).
        # Now each column reports coverage at its own most-recent populated date.
        pit_coverage = {}
        pit_latest_for_col = {}
        if latest_pit:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(daily_snapshots_pit)"
            ).fetchall()]
            skip = {"sid", "snapshot_date", "cap_tier", "close_price",
                    "reconstructed_at", "fwd_return_20d"}
            for c in cols:
                if c in skip:
                    continue
                try:
                    row = conn.execute(
                        f"SELECT MAX(snapshot_date) AS d, COUNT(*) AS n "
                        f"FROM daily_snapshots_pit "
                        f"WHERE [{c}] IS NOT NULL "
                        f"  AND snapshot_date = ("
                        f"      SELECT MAX(snapshot_date) FROM daily_snapshots_pit WHERE [{c}] IS NOT NULL"
                        f"  )"
                    ).fetchone()
                    pit_coverage[c] = int(row[1] or 0)
                    pit_latest_for_col[c] = row[0]
                except Exception:
                    pit_coverage[c] = 0
                    pit_latest_for_col[c] = None

        # Per-table count + freshness for Track 3 score tables
        def _table_stats(table, col):
            try:
                latest_snap = conn.execute(
                    f"SELECT MAX(snapshot_date) FROM {table}"
                ).fetchone()[0]
                cnt = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE snapshot_date = ? AND [{col}] IS NOT NULL",
                    (latest_snap,)
                ).fetchone()[0] if latest_snap else 0
                return latest_snap, int(cnt)
            except Exception:
                return None, 0

    today = pd.Timestamp.today().date()

    def _grade(score):
        for thr, letter, color in [
            (90, "A+", "#2ecc71"),
            (80, "A",  "#27ae60"),
            (70, "B",  "#4d8eff"),
            (60, "C",  "#f1c40f"),
            (40, "D",  "#e67e22"),
        ]:
            if score >= thr:
                return letter, color
        return "F", "#e74c3c"

    # Per-signal nature classifications — drive both grading and the visible
    # "nature badge" so the grade is self-explanatory at a glance.
    SPARSE_BY_NATURE = {
        "bulk_deal_signal",
        "sentiment_7d", "news_volume",
        "insider_signal",          # only stocks with recent insider trades
        "short_selling_signal",    # only 981/2448 stocks have any short reporting (NSE)
        "roiic",                   # needs multi-year NOPAT + IC history; ~46% of universe qualifies
    }
    SECTOR_LEVEL = {"regulatory_sector_signal", "macro_sector_signal"}
    COMPOSITE_NOT_FACTOR = {"screener_final_composite"}
    DATA_DEPTH_LIMITED = {"fii_dii_cash_net", "fii_dii_fno_positioning"}

    def _nature_of(signal):
        if signal in SECTOR_LEVEL:        return "sector"
        if signal in COMPOSITE_NOT_FACTOR: return "composite"
        if signal in DATA_DEPTH_LIMITED:   return "data-depth"
        if signal in SPARSE_BY_NATURE:     return "sparse"
        return "broad"

    def _build_row(name, signal, group, status, status_reason, in_model_flag,
                   coverage_n, eligible_n, latest_snap_str,
                   t_stat, n_periods, ic_source, pit_ready, track,
                   t_ci_lo=None, t_ci_hi=None):
        nature = _nature_of(signal)

        # Coverage score — context-aware so the grade reflects "should I worry?"
        # rather than mechanical % of universe.
        #
        # - broad factors: % of universe (the standard case)
        # - sparse-by-nature (insider/bulk/sentiment/news_volume): full credit
        #     IF data is flowing on cadence. These factors are SUPPOSED to
        #     cover only stocks with the underlying event (~10-15% of universe).
        #     Punishing them for that gave false D-grades and made the user
        #     second-guess healthy signals.
        # - sector / composite / data-depth: coverage % is meaningless for
        #     these; score 100 so they don't drag the average down with a
        #     metric that doesn't apply.
        if eligible_n > 0:
            coverage_pct = round(100 * coverage_n / eligible_n, 1)
        else:
            coverage_pct = 0.0

        if nature in ("sector", "composite", "data-depth"):
            # Per-stock coverage not applicable — full credit, surfaced via badge.
            coverage_score = 100
        elif nature == "sparse":
            # Full credit if the signal has any data today (it's flowing); else 0.
            coverage_score = 100 if coverage_n > 0 else 0
        else:
            coverage_score = min(100, coverage_pct * 1.05)  # cap at 100

        # Freshness score — CADENCE-AWARE.
        # Pre-fix this used a single curve (≤1d=100, decay through 30d=0). That
        # punished monthly fundamentals at the 23-day mark for being… monthly.
        # ADR 0022's cadence registry tells us each signal's expected refresh
        # interval; freshness is scored relative to THAT, not against a daily ideal.
        freshness_days = None
        if latest_snap_str:
            try:
                latest_d = pd.to_datetime(latest_snap_str).date()
                freshness_days = (today - latest_d).days
            except Exception:
                pass

        # Map cadence → expected refresh interval (days). One interval = "fresh".
        # 1-2× = ok (linear decay 100→60). 2-3× = stale (60→20). >3× = outdated.
        cadence = _bt_cadence(signal)
        cadence_interval = {
            "weekly":            7,
            "monthly":          30,
            "sector_portfolio":  7,
            "portfolio":         7,
        }.get(cadence, 30)  # default to monthly

        if freshness_days is None:
            freshness_score = 0
        elif freshness_days <= cadence_interval:
            freshness_score = 100
        elif freshness_days <= 2 * cadence_interval:
            # within one cadence past expected — light decay
            over = freshness_days - cadence_interval
            freshness_score = round(100 - 40 * over / cadence_interval)  # 100 → 60
        elif freshness_days <= 3 * cadence_interval:
            over = freshness_days - 2 * cadence_interval
            freshness_score = round(60 - 40 * over / cadence_interval)  # 60 → 20
        else:
            freshness_score = 0

        # Backtest score — |t-stat| capped at 3.0, scaled to 0-100
        if t_stat is None or pd.isna(t_stat):
            backtest_score = 0
        else:
            abs_t = min(3.0, abs(float(t_stat)))
            backtest_score = round(100 * abs_t / 3.0, 1)

        # PIT-readiness — boolean, becomes 100 or 0
        pit_score = 100 if pit_ready else 0

        # In-model badge — adds a 100% to overall (already-validated factor)
        # but doesn't count if factor isn't built yet
        model_score = 100 if in_model_flag else (0 if status in ("PROPOSED", "BLOCKED") else 50)

        # Two separate grades — pre-2026-05-24 these were conflated into one
        # composite. Caused user confusion: a factor with perfect data but a
        # DROP-verdict backtest would show 'F' as if the data were broken.
        #
        # data_health: is the signal COMPUTING properly? (data side)
        # validation:  is the signal PREDICTIVE in backtest? (alpha side)
        # NB: pit_score_effective is set below the issues block (depends on nature);
        # but we compute data_health before the issues block. Reorder if needed.
        data_health_pit = 100 if nature in ("sector", "composite", "data-depth") else pit_score
        data_health = (
            0.65 * coverage_score +
            0.25 * freshness_score +
            0.10 * data_health_pit
        )
        data_health = round(data_health, 1)
        data_grade, data_color = _grade(data_health)

        # Validation verdict — t-stat based with sample-size gate.
        # Plan 0005 Phase D.4: any KEEP/WEAK claim with n < 12 periods is
        # downgraded to INSUFFICIENT. The 2026-05-24 weekly+NW backtest found
        # `sentiment_7d LARGE` at t=-3.88 but n=4 — statistically meaningless;
        # this gate prevents preliminary findings from misleading prod decisions.
        MIN_N_FOR_VERDICT = 12
        n_int = int(n_periods) if (n_periods is not None and not pd.isna(n_periods)) else 0
        if t_stat is None or pd.isna(t_stat):
            validation_verdict, validation_color = "NONE", "var(--text-muted)"
        elif n_int < MIN_N_FOR_VERDICT:
            # Real t-stat but too few periods — show value but flag insufficiency
            validation_verdict, validation_color = "INSUFFICIENT", "#9b59b6"
        else:
            abs_t = abs(float(t_stat))
            if abs_t >= 2.5:
                validation_verdict, validation_color = "KEEP", "#2ecc71"
            elif abs_t >= 1.5:
                validation_verdict, validation_color = "WEAK", "#4d8eff"
            else:
                validation_verdict, validation_color = "DROP", "#e74c3c"

        # Back-compat: keep `overall` field but redirect callers to data_health
        overall = data_health
        letter, color = data_grade, data_color

        # Nature is already known (computed at top of _build_row). Issue chips
        # below are for *actionable* problems; the nature itself is shown via
        # the visible nature-badge in the template, not crammed into chips.
        issues = []
        if nature == "broad":
            if coverage_n == 0:
                issues.append("no scores in source table")
            elif coverage_pct < 40:
                issues.append(f"coverage {coverage_pct}% — many stocks unscored")
        elif nature == "sparse" and coverage_n == 0:
            # Sparse signal expected to be flowing but isn't — that IS actionable
            issues.append("no recent signal data — harvester silent?")

        # Stale chip is cadence-aware: a monthly factor at 23d is on schedule.
        # Only flag if past 1× cadence interval; emphasise if past 2×.
        if freshness_days is not None and freshness_days > cadence_interval:
            if freshness_days > 2 * cadence_interval:
                issues.append(f"overdue ({freshness_days}d, {cadence} cadence)")
            else:
                issues.append(f"stale ({freshness_days}d, {cadence} cadence)")
        if t_stat is None or pd.isna(t_stat):
            if nature not in ("composite", "data-depth"):
                issues.append("no backtest t-stat yet")
        elif abs(float(t_stat)) < 0.5:
            issues.append(f"t-stat near zero ({float(t_stat):+.2f})")
        if not pit_ready and nature not in ("composite", "sector", "data-depth"):
            issues.append("no PIT helper — can't be backtested")

        return {
            "name": name,
            "signal": signal,
            "group": group,
            "track": track,
            "status": status,
            "status_reason": status_reason,
            "nature": nature,             # 'broad' | 'sparse' | 'sector' | 'composite' | 'data-depth'
            "in_model": in_model_flag,
            "coverage_n": coverage_n,
            "eligible_n": eligible_n,
            "coverage_pct": coverage_pct,
            "freshness_days": freshness_days,
            "latest_snap": latest_snap_str,
            "t_stat": float(t_stat) if t_stat is not None and not pd.isna(t_stat) else None,
            "t_ci_lo": float(t_ci_lo) if t_ci_lo is not None and not pd.isna(t_ci_lo) else None,
            "t_ci_hi": float(t_ci_hi) if t_ci_hi is not None and not pd.isna(t_ci_hi) else None,
            "n_periods": int(n_periods) if n_periods is not None and not pd.isna(n_periods) else None,
            "ic_source": ic_source,
            "pit_ready": pit_ready,
            "scores": {
                "coverage": int(round(coverage_score)),
                "freshness": int(round(freshness_score)),
                "backtest": int(round(backtest_score)),
                "pit": int(pit_score),
                "model": int(model_score),
            },
            "overall": overall,         # = data_health (back-compat alias)
            "grade": letter,            # = data_grade (back-compat alias)
            "grade_color": color,
            "data_health": data_health,
            "data_grade": data_grade,
            "data_grade_color": data_color,
            "validation_verdict": validation_verdict,
            "validation_color": validation_color,
            "backtest_cadence": _bt_cadence(signal),
            "issues": issues,
        }

    out = []

    # ── BACKTEST_SIGNALS (legacy + already-registered) ──
    for spec in BACKTEST_SIGNALS:
        signal = spec["signal"]
        ic_row = best_by_signal.get(signal, {})
        t_stat = ic_row.get("t_stat")
        v2_col = spec.get("pit_column_v2")
        coverage_n = pit_coverage.get(v2_col, 0) if v2_col else 0
        # Freshness: prefer the column's own latest non-null date (handles
        # weekly+monthly cadence correctly). Fall back to global latest_live
        # only when the column has never been populated.
        col_latest = pit_latest_for_col.get(v2_col) if v2_col else None
        eligible = uni_total  # legacy signals span the whole universe
        in_model = (spec.get("status") == "READY"
                    and t_stat is not None and abs(t_stat) >= PROMOTION_T)
        out.append(_build_row(
            name=spec["label"],
            signal=signal,
            group=spec.get("group", "—"),
            status=spec.get("status"),
            status_reason=(spec.get("status_reason") or "")[:200],
            in_model_flag=in_model,
            coverage_n=coverage_n,
            eligible_n=eligible,
            latest_snap_str=col_latest or latest_live,
            t_stat=t_stat,
            n_periods=ic_row.get("n_periods"),
            ic_source=ic_row.get("source", "—"),
            t_ci_lo=ic_row.get("t_stat_ci_lo"),
            t_ci_hi=ic_row.get("t_stat_ci_hi"),
            pit_ready=bool(v2_col),
            track="legacy",
        ))

    # ── Track 3 extras ──
    for spec in TRACK3_EXTRAS:
        signal = spec["signal"]
        ic_row = best_by_signal.get(signal, {})
        t_stat = ic_row.get("t_stat")
        # Coverage: prefer per-snapshot table count over PIT column
        latest_snap_str, coverage_n = _table_stats(
            spec["score_table"], spec["score_col"]
        )
        # Eligible universe: most Track 3 factors exclude financials
        eligible = uni_excl_fin
        in_model = (t_stat is not None and abs(t_stat) >= PROMOTION_T)
        out.append(_build_row(
            name=spec["label"],
            signal=signal,
            group=spec.get("group", "Track 3"),
            status="READY",
            status_reason="",
            in_model_flag=in_model,
            coverage_n=coverage_n,
            eligible_n=eligible,
            latest_snap_str=latest_snap_str,
            t_stat=t_stat,
            n_periods=ic_row.get("n_periods"),
            ic_source=ic_row.get("source", "—"),
            t_ci_lo=ic_row.get("t_stat_ci_lo"),
            t_ci_hi=ic_row.get("t_stat_ci_hi"),
            pit_ready=signal in pit_coverage,  # PIT helper added if column exists
            track="f-track",
        ))

    # Aggregate summary — two distinct distributions
    n = len(out)
    by_data_grade = {}
    by_validation = {}
    for r in out:
        by_data_grade[r["data_grade"]] = by_data_grade.get(r["data_grade"], 0) + 1
        by_validation[r["validation_verdict"]] = by_validation.get(r["validation_verdict"], 0) + 1
    avg_data_health = round(sum(r["data_health"] for r in out) / n, 1) if n else 0

    # ── Promotion funnel — answers "where does every factor sit?" in one place.
    # The four questions Amit keeps re-deriving (total / validated / live /
    # waiting / trustworthy). Single source of truth so the cockpit, ops API and
    # any chat read the same numbers. See HANDOFF 2026-05-31.
    #
    # LIVE = actually wired into a production weight scheme (factors.SIGNAL_WEIGHTS
    #   / _RETURN / _SHARPE). NOTE: the per-row `in_model` flag means "READY &
    #   |t|>=1.5" — that conflates live + waiting, so it is NOT used here.
    # The screener's weight keys are abstracted names ("consensus", "smart_money")
    # mapping to one canonical signal; keep in sync with screener.SIGNAL_COLS.
    import factors as _factors
    from factors import WEIGHT_KEY_TO_SIGNAL as _WEIGHT_KEY_TO_SIGNAL
    wired = set()
    for _sch in _factors.WEIGHT_SCHEMES:
        for _tier_w in (getattr(_factors, _sch, {}) or {}).values():
            for _k in _tier_w:
                wired.add(_WEIGHT_KEY_TO_SIGNAL.get(_k, _k))
    if "mom_6m_adj" in wired:
        wired.add("mom_12m_adj")  # SMALL tier swaps in the 12m variant

    live_l, waiting_l, insuff_l = [], [], []
    for r in out:
        r["in_production"] = r["signal"] in wired
        v = r["validation_verdict"]
        if r["in_production"]:
            live_l.append(r["signal"])
        elif v in ("KEEP", "WEAK"):
            waiting_l.append(r["signal"])
        if v == "INSUFFICIENT":
            insuff_l.append(r["signal"])

    vd = by_validation
    funnel = {
        "total":             n,
        "validated":         vd.get("KEEP", 0) + vd.get("WEAK", 0),  # |t|>=1.5, n>=12
        "keep":              vd.get("KEEP", 0),
        "weak":              vd.get("WEAK", 0),
        "insufficient_data": vd.get("INSUFFICIENT", 0),  # promising t, too few periods
        "dropped":           vd.get("DROP", 0),
        "no_backtest":       vd.get("NONE", 0),
        "live":              len(live_l),      # wired into a production weight scheme
        "waiting":           len(waiting_l),   # validated but not yet wired
        "live_factors":         sorted(live_l),
        "waiting_factors":       sorted(waiting_l),
        "insufficient_factors":  sorted(insuff_l),
    }

    # ── Orthogonality — last factor_correlation run (offline, tools/
    # factor_correlation.py). Surfaces redundant pairs so promoting a "waiting"
    # factor doesn't double-count an idea already live. Composite↔component
    # overlap is expected by construction, so *_composite pairs are excluded.
    ORTHO_THRESHOLD = 0.8
    best_pair = {}  # (a,b) sorted tuple -> {a,b,rho,tier}
    ortho_computed_at = None
    for _tier in views.pickable_tiers():
        _p = PROJECT_ROOT / "data" / f"factor_correlation_{_tier}.json"
        if not _p.exists():
            continue
        try:
            _d = json.loads(_p.read_text())
        except Exception:
            continue
        ortho_computed_at = _d.get("computed_at", ortho_computed_at)
        _m = _d.get("matrix", {})
        for _a, _row in _m.items():
            if _a.endswith("_composite"):
                continue
            for _b, _rho in _row.items():
                if _a >= _b or _b.endswith("_composite") or _rho is None:
                    continue
                if abs(_rho) < ORTHO_THRESHOLD:
                    continue
                key = (_a, _b)
                if key not in best_pair or abs(_rho) > abs(best_pair[key]["rho"]):
                    best_pair[key] = {"a": _a, "b": _b, "rho": round(_rho, 2), "tier": _tier}
    redundant_pairs = sorted(best_pair.values(), key=lambda x: -abs(x["rho"]))
    # Flag pairs where a waiting factor duplicates a live one (the actionable bit).
    waiting_set, live_set = set(waiting_l), set(live_l)
    for p in redundant_pairs:
        sides = {p["a"], p["b"]}
        p["duplicates_live"] = bool(sides & live_set) and bool(sides & waiting_set)
    orthogonality = {
        "available":      bool(redundant_pairs),
        "computed_at":    ortho_computed_at,
        "threshold":      ORTHO_THRESHOLD,
        "redundant_pairs": redundant_pairs[:12],
        "n_redundant":    len(redundant_pairs),
        "n_waiting_dupes": sum(1 for p in redundant_pairs if p["duplicates_live"]),
    }

    # ── Horizon-resolved net-of-cost gate (ADR 0038, tools/promotion_gate.py).
    # The legacy validation_verdict above reads a single-20d |t|; this re-judges
    # each factor at its cost-resolved NATURAL horizon, net of turnover cost, so
    # the funnel shows BOTH lenses side by side. On-demand table (NOT in
    # PIPELINE_STEPS) — refreshed only when `python -m tools.promotion_gate` runs.
    # We surface the LIVE re-eval: of the production-wired (signal,tier) pairs,
    # how many still clear the net-of-cost bar at their own horizon.
    horizon_gate = {"available": False}
    try:
        hg = read_sql(
            "SELECT signal, cap_tier, natural_horizon, net_t, net_ir_annual, "
            "n_periods, sign_stable, verdict, turnover_assumed, computed_at "
            "FROM factor_horizon_gate")
    except Exception:
        hg = None
    if hg is not None and not hg.empty:
        gv = hg["verdict"].value_counts().to_dict()
        hg_idx = {(r.signal, r.cap_tier): r for r in hg.itertuples()}
        # production-wired (signal,tier) pairs ONLY (factors.SIGNAL_WEIGHTS — not the
        # RETURN/SHARPE dry-run variants), so the count matches what's deployed.
        live_rows = []
        for _tier, _tw in _factors.SIGNAL_WEIGHTS.items():
            for _k in _tw:
                _sig = _WEIGHT_KEY_TO_SIGNAL.get(_k, _k)
                row = hg_idx.get((_sig, _tier))
                if row is None and _sig == "mom_6m_adj":   # SMALL swaps in the 12m variant
                    row = hg_idx.get(("mom_12m_adj", _tier))
                live_rows.append({
                    "key": _k, "signal": _sig, "tier": _tier,
                    "weight": round(float(_tw[_k]), 3),
                    "verdict": row.verdict if row is not None else None,
                    "natural_horizon": int(row.natural_horizon) if row is not None and row.natural_horizon is not None else None,
                    "net_t": round(float(row.net_t), 2) if row is not None and row.net_t is not None else None,
                    "net_ir_annual": round(float(row.net_ir_annual), 3) if row is not None and row.net_ir_annual is not None else None,
                    "n_periods": int(row.n_periods) if row is not None and row.n_periods is not None else None,
                    "sign_stable": int(row.sign_stable) if row is not None and row.sign_stable is not None else None,
                })
        scored = [r for r in live_rows if r["verdict"]]
        flagged = [r for r in scored if r["verdict"] != "PROMOTE"]
        _ca = hg["computed_at"].dropna()
        _to = hg["turnover_assumed"].dropna()
        horizon_gate = {
            "available":   True,
            "computed_at": _ca.max() if not _ca.empty else None,
            "turnover":    round(float(_to.iloc[0]), 2) if not _to.empty else None,
            "promote":     int(gv.get("PROMOTE", 0)),
            "library":     int(gv.get("LIBRARY", 0)),
            "reject":      int(gv.get("REJECT", 0)),
            "insufficient": int(gv.get("INSUFFICIENT", 0)),
            "live_total":  len(scored),
            "live_clear":  sum(1 for r in scored if r["verdict"] == "PROMOTE"),
            "live_flagged": len(flagged),
            "unscored":    sum(1 for r in live_rows if not r["verdict"]),
            "live_rows":   sorted(live_rows, key=lambda x: (x["tier"], -(x["net_t"] if x["net_t"] is not None else -99))),
            "flagged_rows": sorted(flagged, key=lambda x: ({"REJECT": 0, "LIBRARY": 1}.get(x["verdict"], 2), x["tier"])),
        }

    summary = {
        "total": n,
        "in_model": sum(1 for r in out if r["in_model"]),
        "in_library": sum(1 for r in out if not r["in_model"] and r["coverage_n"] > 0),
        "not_built": sum(1 for r in out if r["coverage_n"] == 0),
        "with_t_stat": sum(1 for r in out if r["t_stat"] is not None),
        "pit_ready": sum(1 for r in out if r["pit_ready"]),
        # Back-compat aliases (template still reads these)
        "avg_overall": avg_data_health,
        "grade_dist": by_data_grade,
        # New, clearer fields
        "avg_data_health": avg_data_health,
        "data_grade_dist": by_data_grade,
        "validation_dist": by_validation,
        # Promotion funnel + orthogonality (2026-05-31)
        "funnel": funnel,
        "orthogonality": orthogonality,
        # Horizon-resolved net-of-cost gate (ADR 0038, 2026-06-02)
        "horizon_gate": horizon_gate,
    }

    return {"summary": summary, "factors": out}


# ═══════════════════════════════════════════════════
# Command Centre — overview of plans, factors, data layer, pending actions
# ═══════════════════════════════════════════════════

FACTOR_COUNT_TARGET = 100


def _read_md_section(md_path: Path, header: str) -> str | None:
    """Return the body of an H2 section by header text, or None."""
    if not md_path.exists():
        return None
    text = md_path.read_text()
    needle = f"\n## {header}"
    start = text.find(needle)
    if start < 0:
        return None
    body_start = start + len(needle)
    end = text.find("\n## ", body_start)
    return text[body_start:end if end > 0 else len(text)].strip()


def _parse_plan_frontmatter(md_path: Path) -> dict:
    """Parse YAML-ish frontmatter at top of a plan or ADR markdown file."""
    text = md_path.read_text()
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            fm[key.strip().lower()] = val.strip()
    return fm


def _cc_plans_and_adrs(project_root):
    """Filesystem half of the command centre — scan docs/plans + docs/decisions.
    Extracted from get_command_centre 2026-05-30 (mechanical split, no behaviour change)."""
    # ── Plans ────────────────────────────────────────────────
    plans = []
    for p in sorted((project_root / "docs" / "plans").glob("000*.md")):
        fm = _parse_plan_frontmatter(p)
        title_match = None
        for line in p.read_text().splitlines():
            if line.startswith("# "):
                title_match = line[2:].strip()
                break
        plans.append({
            "file": p.name,
            "title": title_match or p.stem,
            "status": fm.get("status") or "—",
            "last_updated": fm.get("last updated") or "—",
            "implementation": fm.get("implementation") or "",
        })

    # ── ADRs ─────────────────────────────────────────────────
    adrs = []
    for a in sorted((project_root / "docs" / "decisions").glob("0*.md")):
        first_lines = a.read_text().splitlines()[:10]
        title = next((l[2:].strip() for l in first_lines if l.startswith("# ")), a.stem)
        status_line = next((l for l in first_lines if l.startswith("**Status:")), "")
        date_line = next((l for l in first_lines if l.startswith("**Date:")), "")
        adrs.append({
            "file": a.name,
            "title": title,
            "status": status_line.replace("**Status:**", "").strip().rstrip("*").strip() or "—",
            "date": date_line.replace("**Date:**", "").strip().rstrip("*").strip() or "—",
        })
    return plans, adrs


def _cc_factor_library():
    """DB-introspection half — factor roster + counts from BACKTEST_SIGNALS ×
    pit_ic_by_tier_v2. Extracted from get_command_centre 2026-05-30 (mechanical split)."""
    # ── Factor library ───────────────────────────────────────
    # Source of truth: BACKTEST_SIGNALS in db.py (42 v1-derived signals) plus
    # Track 3 additions (ROIC, FCF Yield, …). Each factor's t-stat is looked
    # up from pit_ic_by_tier_v2 by `signal` column.
    from db import BACKTEST_SIGNALS

    # Track 3 factors not yet in BACKTEST_SIGNALS (no PIT helper yet, so no
    # entry in the v1-shaped registry). Same fields shape, so they render
    # uniformly.
    TRACK3_EXTRAS = [
        {
            "signal": "roic",
            "label": "ROIC (Track 3)",
            "group": "Track 3 / Quality",
            "status": "READY",
            "status_reason": "",
            "track": "f-track",
            "score_table": "roic_scores",
        },
    ]

    # Promotion criterion: if the best pit_ic_by_tier_v2 row (best_ic_by_signal —
    # the same rule /system uses) has |t| >= 1.5, the factor is "in model";
    # otherwise "library".
    PROMOTION_T_THRESHOLD = 1.5

    factors = []
    best = best_ic_by_signal()
    with get_db() as conn:

        # Score-table count helper (cached per table in this call)
        score_table_counts: dict[str, int] = {}

        def _stocks_in(table_name: str | None) -> int:
            if not table_name:
                return 0
            if table_name in score_table_counts:
                return score_table_counts[table_name]
            try:
                row = conn.execute(
                    f"SELECT COUNT(DISTINCT sid) FROM {table_name}"
                ).fetchone()
                n = int(row[0]) if row and row[0] is not None else 0
            except Exception:
                n = 0
            score_table_counts[table_name] = n
            return n

        # ── BACKTEST_SIGNALS (42 v1-derived) ──
        for spec in BACKTEST_SIGNALS:
            signal = spec["signal"]
            ic_row = best.get(signal, {})
            t_stat = ic_row.get("t_stat")
            n_periods = ic_row.get("n_periods")
            ic_source = ic_row.get("source")

            # Coverage: prefer the v2 PIT column count over generic table counts
            v2_col = spec.get("pit_column_v2")
            stocks = 0
            if v2_col:
                try:
                    row = conn.execute(
                        f"SELECT COUNT(DISTINCT sid) FROM daily_snapshots_pit "
                        f"WHERE {v2_col} IS NOT NULL"
                    ).fetchone()
                    stocks = int(row[0]) if row and row[0] is not None else 0
                except Exception:
                    stocks = 0

            in_production = (
                spec["status"] == "READY"
                and t_stat is not None
                and abs(t_stat) >= PROMOTION_T_THRESHOLD
            )

            factors.append({
                "name": spec["label"],
                "signal": signal,
                "group": spec.get("group", "—"),
                "status": spec.get("status"),
                "status_reason": spec.get("status_reason", "")[:240],
                "stocks": stocks,
                "t_stat": float(t_stat) if t_stat is not None else None,
                "n_periods": int(n_periods) if n_periods is not None else None,
                "ic_source": ic_source or "—",
                "in_production": in_production,
                "track": "legacy",
                "table": v2_col or "—",
            })

        # ── Track 3 extras (ROIC, FCF Yield, …) ──
        for spec in TRACK3_EXTRAS:
            signal = spec["signal"]
            ic_row = best.get(signal, {})
            t_stat = ic_row.get("t_stat")
            stocks = _stocks_in(spec.get("score_table"))
            in_production = (
                t_stat is not None and abs(t_stat) >= PROMOTION_T_THRESHOLD
            )
            factors.append({
                "name": spec["label"],
                "signal": signal,
                "group": spec.get("group", "Track 3"),
                "status": spec.get("status"),
                "status_reason": spec.get("status_reason", ""),
                "stocks": stocks,
                "t_stat": float(t_stat) if t_stat is not None else None,
                "n_periods": int(ic_row["n_periods"]) if ic_row.get("n_periods") is not None else None,
                "ic_source": ic_row.get("source") or "—",
                "in_production": in_production,
                "track": "f-track",
                "table": spec.get("score_table"),
            })

    # "Built" = has scores OR has a t-stat. "In model" = passes promotion.
    n_built = len([f for f in factors if f["stocks"] > 0 or f["t_stat"] is not None])
    n_in_prod = len([f for f in factors if f["in_production"]])
    n_in_library = n_built - n_in_prod
    return factors, n_built, n_in_prod, n_in_library


def _tier_weight_items():
    """One ("TIER: n weighted signals", "top-3 weights") line per pickable tier,
    read from factors.SIGNAL_WEIGHTS (was hand-written and had gone stale)."""
    from factors import weights
    items = []
    for tier in views.pickable_tiers():
        w = weights().get(tier, {})
        top = sorted(w.items(), key=lambda kv: -kv[1])[:3]
        items.append((f"{tier}: {len(w)} weighted signals",
                      " / ".join(f"{k} {v:.2f}" for k, v in top) + (" ..." if len(w) > 3 else "")))
    return items


def _book_label():
    """"Top 5 LARGE / MID / SMALL" from config.PORTFOLIO["picks_per_tier"]."""
    from config import PORTFOLIO
    n = PORTFOLIO["picks_per_tier"]
    sizes = {n.get(t) for t in views.pickable_tiers()}
    head = f"Top {sizes.pop()}" if len(sizes) == 1 else "Top N"
    return f"{head} " + " / ".join(views.pickable_tiers())


@_persisted_cache(300, name="get_command_centre")
def get_command_centre():
    """Assemble the command-centre payload — plans, factor library, data layer,
    pending actions. Server-rendered; no live polling."""
    project_root = Path(__file__).resolve().parent.parent

    # ── Plans + ADRs (filesystem scan of docs/) ──
    plans, adrs = _cc_plans_and_adrs(project_root)

    # ── Factor library (BACKTEST_SIGNALS × pit_ic_by_tier_v2) ──
    factors, n_built, n_in_prod, n_in_library = _cc_factor_library()

    # ── Data layer (lightweight, for the architecture flow header stats) ──
    data_layer = {}
    with get_db() as conn:
        for tbl in [
            "fundamentals_screener", "stock_prices", "quarterly_income",
            "annual_balance_sheet", "annual_cash_flow", "shareholding",
            "insider_trades", "bulk_deals", "regulatory_events", "news_articles",
        ]:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                stocks_cnt = None
                try:
                    stocks_cnt = conn.execute(
                        f"SELECT COUNT(DISTINCT sid) FROM {tbl}"
                    ).fetchone()[0]
                except Exception:
                    pass
                data_layer[tbl] = {
                    "rows": int(cnt),
                    "stocks": int(stocks_cnt) if stocks_cnt is not None else None,
                }
            except Exception:
                data_layer[tbl] = {"rows": 0, "stocks": None}
        try:
            tp = conn.execute(
                "SELECT COUNT(DISTINCT sid) FROM fundamentals_screener "
                "WHERE line_item='Trade Payables'"
            ).fetchone()[0]
            data_layer["fundamentals_screener"]["trade_payables_stocks"] = int(tp)
        except Exception:
            pass

    # ── Full data model (every table — schema, columns, row counts, source) ──
    # Logical grouping for the brain-map. Each table gets PRAGMA table_info.
    DATA_MODEL_GROUPS = [
        ("Universe & Reference", [
            ("stocks",                 "NSE/BSE master + Tickertape SID, sector, cap_tier, market_cap_cr"),
            ("nse_index_history",      "Nifty 50/100/500/Smallcap + smart-beta indices — daily OHLCV"),
            ("vix_history",            "India VIX — daily, regime input"),
        ]),
        ("Prices & Adjustments", [
            ("stock_prices",           "Daily OHLCV — NSE bhavcopy + nselib"),
            ("corporate_adjustments",  "Pre-multiplied split+bonus+dividend factors per (sid, ex_date) — ADR 0010"),
            ("corporate_actions",      "Raw corporate events (splits, bonuses, dividends, buybacks, M&A) from NSE"),
        ]),
        ("Fundamentals", [
            ("fundamentals_screener",  "Track 3 long-format — Screener Premium xlsx + schedules JSON. PK (sid, period_end, period_type, line_item)"),
            ("quarterly_income",       "Tickertape — quarterly income (legacy wide format)"),
            ("annual_balance_sheet",   "Tickertape — annual balance sheet"),
            ("annual_cash_flow",       "Tickertape — annual cash flow"),
            ("shareholding",           "Tickertape — quarterly promoter / FII / DII / public splits"),
        ]),
        ("Ownership Flows", [
            ("insider_trades",         "NSE PIT API — secAcq/secVal are the real values, not buy/sell qty"),
            ("bulk_deals",             "NSE bulk-deals daily snapshot — append-only, today-only API"),
            ("fii_dii_cash_flow",      "FII/DII cash market positioning — daily"),
            ("fii_dii_positioning",    "FII/DII F&O + cash positioning — by participant type"),
            ("short_selling_data",     "NSE short-selling — F&O-eligible names only"),
        ]),
        ("Analyst Forecasts", [
            ("analyst_consensus",          "Current snapshot — yfinance-sourced price_target + Tickertape-sourced eps/revenue. PK=sid, daily refresh."),
            ("analyst_consensus_snapshots", "Monthly history of yfinance aggregate — drives pt_revision signals. PK=(sid, snapshot_date, source). New 2026-05-22."),
            ("forecast_history",           "Tickertape year-end PT/EPS/Revenue snapshots (~1/yr per stock 2022-2025). Daily 'today' entries filtered at ingest."),
        ]),
        ("Events & News", [
            ("regulatory_events",      "BSE/NSE filings — raw + classifier_status (6 terminal states)"),
            ("regulatory_signals",     "Sector-level tailwind/headwind from AI-classified events (5,687 of 16,523 classified)"),
            ("news_articles",          "Google News RSS — title+source+published_at"),
            ("news_article_stocks",    "M2M join — article ↔ stock"),
            ("earnings_calendar",      "Upcoming filings schedule — used for daily-incremental Screener pulls"),
        ]),
        ("Macro & Sectors", [
            ("macro_indicators",       "Active per-indicator macro values"),
            ("macro_history",          "Long-format historical series — per-indicator monthly observations"),
            ("macro_indicator_meta",   "Indicator name → unit, transform, source registry"),
            ("macro_sector_map",       "Indicator → sector weights (30 mappings)"),
            ("macro_sector_signals",   "Per-sector macro signal output (today)"),
            ("macro_sector_signals_pit", "PIT version — 11 sectors × 7 dates"),
        ]),
        ("Surveillance", [
            ("surveillance_flags",     "ASM (LT/ST), GSM, F&O ban — append-only daily snapshot"),
        ]),
        ("Mutual Fund NAV", [
            ("mf_schemes",             "AMFI scheme master — 4,048 schemes"),
            ("mf_nav_history",         "Per-scheme NAV history from mfapi.in — ~13 yr daily"),
        ]),
        ("Computed Signals (per-stock)", [
            ("piotroski_scores",       "F-Score 0-9 — quality"),
            ("forensic_scores",        "M-Score (earnings manipulation) + Z-Score (distress)"),
            ("accruals_scores",        "CF + BS accruals + EPS CV + composite"),
            ("consensus_signals",      "PT upside, PT revision YoY, EPS revision YoY, combined"),
            ("promoter_signals",       "Promoter QoQ + 4q trend"),
            ("smart_money_scores",     "Bulk-deal + delivery anomaly composite"),
            ("insider_signals",        "Insider trades signal — 29 monthly snapshots"),
            ("sentiment_scores",       "News-based sentiment proxy — 7d volume + (FinBERT pending plan-0002)"),
            ("roic_scores",            "Track 3 ROIC — 1,501 stocks (NOPAT/IC, 3yr median, IC≥₹50cr)"),
        ]),
        ("Daily Output", [
            ("daily_picks",            "Top picks per cap-tier per snapshot_date — what the screener emits"),
            ("daily_changes",          "Day-over-day diff in picks (entered/exited)"),
            ("daily_snapshots",        "Today-only snapshot of all factors per stock — current cross-section"),
        ]),
        ("PIT Snapshots & Backtest", [
            ("daily_snapshots_pit",    "v2 PIT archive — 7 monthly dates × 26 signals × 2,448 stocks"),
            ("daily_snapshots_pit_v1", "Frozen v1 archive — port-correctness reference per ADR 0012"),
            ("pit_ic_by_tier_v1",      "v1 backtest IC table (older, for cross-checking)"),
            ("pit_ic_by_tier_v2",      "Backtest output — IC, t-stat, n_periods per (signal, cap_tier, source)"),
            ("pit_reconstruction_log", "Run-log of tools.reconstruct_pit invocations"),
        ]),
        ("Pipeline & Logging", [
            ("pipeline_log",           "Per-step run log (started_at, status, rows, duration)"),
            ("regime_state",           "Daily regime classifier output (Bullish/Neutral/Bearish)"),
            ("screener_pull_errors",   "Track 3 scrape audit trail — error_type ∈ {auth, http, parse, thin, empty, fetch}"),
        ]),
    ]
    data_model = []
    with get_db() as conn:
        # Get list of actually-existing tables once
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}

        for group_name, table_specs in DATA_MODEL_GROUPS:
            group_tables = []
            for tbl, desc in table_specs:
                if tbl not in existing:
                    continue
                # Columns
                try:
                    cols = [
                        {
                            "name": r[1], "type": r[2], "notnull": bool(r[3]),
                            "pk": int(r[5]),
                        }
                        for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()
                    ]
                except Exception:
                    cols = []
                # Indexes (skip auto-pk indexes)
                try:
                    idxs = [
                        r[1] for r in conn.execute(f"PRAGMA index_list({tbl})").fetchall()
                        if not r[1].startswith("sqlite_autoindex")
                    ]
                except Exception:
                    idxs = []
                # Foreign keys
                try:
                    fks = [
                        {"col": r[3], "ref_table": r[2], "ref_col": r[4]}
                        for r in conn.execute(f"PRAGMA foreign_key_list({tbl})").fetchall()
                    ]
                except Exception:
                    fks = []
                # Row count
                try:
                    rows = int(conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0])
                except Exception:
                    rows = 0
                # Distinct stocks if `sid` column present
                stocks = None
                if any(c["name"] == "sid" for c in cols) and rows > 0:
                    try:
                        stocks = int(conn.execute(
                            f"SELECT COUNT(DISTINCT sid) FROM {tbl}"
                        ).fetchone()[0])
                    except Exception:
                        pass
                # Latest timestamp if a candidate column exists
                latest = None
                for ts_col in ("fetched_at", "snapshot_date", "attempted_at",
                                "started_at", "created_at", "date", "ex_date"):
                    if any(c["name"] == ts_col for c in cols):
                        try:
                            r = conn.execute(
                                f"SELECT MAX({ts_col}) FROM {tbl}"
                            ).fetchone()
                            if r and r[0]:
                                latest = str(r[0])[:19]
                                break
                        except Exception:
                            pass

                pk_cols = [c["name"] for c in cols if c["pk"]]
                group_tables.append({
                    "name": tbl,
                    "desc": desc,
                    "cols": cols,
                    "n_cols": len(cols),
                    "pk": pk_cols,
                    "fks": fks,
                    "indexes": idxs,
                    "rows": rows,
                    "stocks": stocks,
                    "latest": latest,
                    "group": group_name,
                })
            if group_tables:
                data_model.append({
                    "name": group_name,
                    "tables": group_tables,
                    "n_tables": len(group_tables),
                    "n_rows": sum(t["rows"] for t in group_tables),
                })

    # ── To Do (synthesized — top-level "what needs to happen") ──
    todos = []

    # Schedules scrape progress
    try:
        import subprocess
        is_running = bool(subprocess.run(
            ["pgrep", "-f", "screener_schedules"], capture_output=True
        ).stdout.strip())
    except Exception:
        is_running = False
    tp_n = data_layer.get("fundamentals_screener", {}).get("trade_payables_stocks", 0)
    if is_running:
        todos.append({
            "title": "F1.2 universe scrape running",
            "detail": f"Trade Payables landed for {tp_n} stocks so far (target ~2,000). Detached process — claude won't notify. Check `ps -ef | grep screener_schedules`.",
            "status": "in-flight",
        })
    elif tp_n < 1500:
        todos.append({
            "title": "F1.2 universe scrape needs to finish or restart",
            "detail": f"Only {tp_n} stocks have Trade Payables; expected ~1,800–2,000. May have stopped early — check screener_pull_errors.",
            "status": "blocked",
        })

    # Factors built without PIT helpers (can't be backtested)
    f_track_no_pit = [
        f for f in factors
        if f["track"] == "f-track" and f["t_stat"] is None and f["stocks"] > 0
    ]
    for f in f_track_no_pit:
        todos.append({
            "title": f"Add PIT helper for {f['name']}",
            "detail": f"Has {f['stocks']} stocks scored today but no `pit_{f['signal']}(sid, eval_date)` in pit.py — can't be backtested. Pair the module with its PIT version on next ship.",
            "status": "todo",
        })

    # Factor count progress
    todos.append({
        "title": f"Build remaining {FACTOR_COUNT_TARGET - n_built} factors toward 100",
        "detail": f"At {n_built}/{FACTOR_COUNT_TARGET} ({round(100*n_built/FACTOR_COUNT_TARGET)}%). Next batch (data already in fundamentals_screener): cash_conversion_cycle, gross_margin_trend, roiic, working_capital_intensity, debt_structure, asset_tangibility. ~30 min each from the ROIC/FCF Yield template.",
        "status": "todo",
    })

    # Operational debt
    todos.append({
        "title": "Wire screener_pull + screener_schedules into weekly cron",
        "detail": "Both currently manual-run only. Schedule for Sunday 02:00 IST (clear of daily 03:30 UTC pipeline). Cookie-health probe on cockpit /system. Use earnings_calendar for daily incremental.",
        "status": "todo",
    })

    # Library surface
    todos.append({
        "title": "Build factor-library exploration surface",
        "detail": "Once 30+ factors exist, add a per-factor drill-down (IC by tier, distribution, top/bottom names). Notebook first; cockpit page after.",
        "status": "later",
    })


    # ── Pending actions + open questions from HANDOFF ────────
    handoff = project_root / "HANDOFF.md"
    next_actions_md = _read_md_section(handoff, "Next 3 actions (in order, concrete)") or ""
    open_questions_md = _read_md_section(handoff, "Open questions for me (decisions you need to make)") or ""
    where_md = _read_md_section(handoff, "Where I am") or ""

    # ── Recent commits ───────────────────────────────────────
    import subprocess
    try:
        log_out = subprocess.check_output(
            ["git", "log", "--pretty=format:%h|%s|%cr", "-15"],
            cwd=str(project_root), text=True, timeout=5,
        )
        commits = [
            dict(zip(["sha", "subject", "when"], line.split("|", 2)))
            for line in log_out.splitlines() if line
        ]
    except Exception:
        commits = []

    # ── Architecture flow (mother plan, layered) ─────────────
    # 4 vertical stages, each expandable. Counts pulled from real data so
    # the diagram updates as the system grows.
    factors_by_group = {}
    for f in factors:
        factors_by_group.setdefault(f["group"], []).append(f)

    arch_data_layer = [
        {
            "name": "Market data",
            "summary": f"{data_layer.get('stock_prices',{}).get('rows', 0):,} daily price rows · {data_layer.get('stock_prices',{}).get('stocks', 0):,} stocks",
            "items": [
                ("stock_prices", "Daily OHLCV — NSE bhavcopy + nselib"),
                ("daily_snapshots_pit", "PIT-reconstructed signal snapshots — 7 monthly dates"),
                ("daily_snapshots_pit_v1", "Frozen v1 archive — 36 monthly periods, port-correctness reference"),
            ],
        },
        {
            "name": "Fundamentals",
            "summary": f"{data_layer.get('fundamentals_screener',{}).get('rows', 0):,} long-format rows · {data_layer.get('quarterly_income',{}).get('rows', 0):,} quarterly · 2 sources",
            "items": [
                ("fundamentals_screener", "Screener Premium — 36 annual line items, 9 quarterly. Long-format (Track 3)"),
                ("quarterly_income", "Tickertape — quarterly income statement (legacy wide format)"),
                ("annual_balance_sheet", "Tickertape — annual balance sheet"),
                ("annual_cash_flow", "Tickertape — annual cash flow"),
                ("shareholding", "Tickertape — quarterly promoter / FII / DII / public splits"),
            ],
        },
        {
            "name": "Ownership & flows",
            "summary": f"insider trades, bulk deals, FII/DII positioning",
            "items": [
                ("insider_trades", f"NSE PIT API — {data_layer.get('insider_trades',{}).get('rows', 0):,} rows"),
                ("bulk_deals", f"NSE bulk-deals daily snapshot — {data_layer.get('bulk_deals',{}).get('rows', 0):,} rows"),
                ("fii_dii_cash", "FII/DII cash market positioning — daily"),
                ("fii_fno_positioning", "FII F&O positioning — daily"),
                ("short_selling_data", "NSE short-selling — daily, F&O-eligible names"),
            ],
        },
        {
            "name": "Events & news",
            "summary": f"{data_layer.get('regulatory_events',{}).get('rows', 0):,} regulatory events · {data_layer.get('news_articles',{}).get('rows', 0):,} news articles",
            "items": [
                ("regulatory_events", "BSE/NSE filings — AI-classified into per-sector signals"),
                ("regulatory_signals", "Sector-level regulatory tailwind/headwind (5,687 of 16,523 classified)"),
                ("corporate_actions", "Splits, bonuses, dividends — composed at signal-compute time per ADR 0010"),
                ("news_articles", "Google News RSS — 100/query, 2026-03+ dense"),
                ("earnings_calendar", "Upcoming filings schedule"),
            ],
        },
        {
            "name": "Macro",
            "summary": "Inflation, GDP, sector indicators — government & RBI",
            "items": [
                ("macro_indicators", "data.gov.in core sector index, RBI rates, monthly"),
                ("vix_history", "India VIX — regime classifier input"),
                ("benchmark_indices", "Nifty 50/100/500/Smallcap/Midcap + smart-beta indices"),
            ],
        },
    ]

    # Signals — group → factor list with counts
    arch_signals = []
    canonical_order = [
        "Value", "Quality", "Growth", "Momentum", "Ownership",
        "Smart Money", "Consensus", "Forensic", "Sentiment",
        "Regulatory", "Macro", "Composite",
        "Track 3 / Quality", "Track 3 / Cash",
    ]
    for grp in canonical_order:
        if grp in factors_by_group:
            in_group = factors_by_group[grp]
            in_model = sum(1 for f in in_group if f["in_production"])
            arch_signals.append({
                "name": grp,
                "n_total": len(in_group),
                "n_model": in_model,
                "items": [
                    (f["name"], f"{f['t_stat']:.2f}" if f["t_stat"] is not None else "—",
                     "model" if f["in_production"] else "library")
                    for f in in_group
                ],
            })

    arch_model = [
        {
            "name": "Cap-tier composite",
            "summary": "Within-tier weighted sum of validated signals (cf C13b rubric)",
            "items": [
                *_tier_weight_items(),
                ("Weight tiers", "|t|≥2.5 → 1.0× / 1.5-2.5 → 0.5× / 0.5-1.5 → 0.2× / <0.5 → 0×"),
            ],
        },
        {
            "name": "Regime overlay",
            "summary": "VIX-based + macro-sector overlays",
            "items": [
                ("scoring/regime.py", "Bullish / Neutral / Bearish from VIX + breadth"),
                ("Macro tilts", "Sector tailwind/headwind from regulatory + macro signals"),
            ],
        },
        {
            "name": "Personal factor library",
            "summary": f"{n_built - n_in_prod} factors built but not voting (yet)",
            "items": [
                ("Promotion criterion", "|t|≥1.5 in any tier (preferring v2_recompute)"),
                ("ADR 0012", "v2 archive refreshes after every signal-side fix"),
                ("Today: ROIC + FCF Yield", "Track 3 factors awaiting PIT helpers + backtest"),
            ],
        },
    ]

    arch_picks = [
        {
            "name": "Daily morning brief",
            "summary": "Top picks per cap tier with regime context, dossiers",
            "items": [
                ("/", "Cockpit Morning Brief route"),
                (_book_label(), "Ranked by composite within tier, then the pick gate"),
                ("Regime banner", "Bullish/Neutral/Bearish header"),
            ],
        },
        {
            "name": "Email digest",
            "summary": "Daily picks emailed via output/email_sender.py",
            "items": [
                ("output/email_sender.py", "Templated HTML email of top picks + commentary"),
            ],
        },
        {
            "name": "Cockpit explorer",
            "summary": "Per-stock dossiers, signals, action queue",
            "items": [
                ("/explorer", "Universe scan + per-stock detail"),
                ("/actions", "Buy / Watch / Exit candidates"),
                ("/portfolio", "Personal position tracking"),
            ],
        },
    ]

    architecture = {
        "data": arch_data_layer,
        "signals": arch_signals,
        "model": arch_model,
        "picks": arch_picks,
        "summary": {
            "tables": len(data_layer),
            "factors_total": len(factors),
            "factors_in_model": n_in_prod,
            "factors_in_library": n_in_library,
        },
    }

    return {
        "factors": factors,
        "factor_summary": {
            "built": n_built,
            "target": FACTOR_COUNT_TARGET,
            "pct": round(100 * n_built / FACTOR_COUNT_TARGET, 1),
            "in_production": n_in_prod,
            "in_library": n_in_library,
        },
        "data_layer": data_layer,
        "data_model": data_model,
        "todos": todos,
        "where_md": where_md,
        "commits": commits,
        "architecture": architecture,
    }


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
        return "/feeds", "Data Supply →"
    table = target if code.startswith("TABLE_") else issue.get("table")
    if table and table in db.TABLES:
        return f"/sql?table={table}", f"Inspect {table} →"
    return None, None


@_persisted_cache(300, name="get_health_overview")
def get_health_overview(force=False):
    """The Health Center overview: {as_of, verdict, verdict_severity, counts,
    scorecard (five questions), issues + tolerated (each with a drill-down link),
    catalog (every check), severity_meaning, watchdog, pipeline_summary,
    eligibility, integrity}."""
    from checks import SEVERITY_MEANING, report

    st = report.gather()

    def linked(rows):
        return [dict(i, drilldown_url=u, drilldown_label=l) for i in rows for u, l in [_drilldown(i)]]

    s = st["summary"]
    integrity = (st["integrity"] or {}).get("rows") or []
    return _clean({
        "as_of": st["as_of"],
        "verdict": s["verdict"],
        "verdict_severity": "CRITICAL" if s["critical"] else "WARN" if s["warn"] else "OK",
        "counts": {"critical": s["critical"], "warn": s["warn"], "info": len(st["tolerated"])},
        "scorecard": st["scorecard"],
        "issues": linked(st["issues"]),
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
        "new_sources": [r for r in rows if r["status"] in ("wanted", "candidate", "probation")],
        "drift": [{"what": w, "name": n} for w, n in drift],
    }


# ─────────────────────────── Boardroom (plan 0019) ───────────────────────────

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
