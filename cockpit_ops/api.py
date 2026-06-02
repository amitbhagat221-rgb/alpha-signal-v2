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

Shared decorators (_persisted_cache, _ttl_cache) stay in cockpit/api.py and
are imported one-way here. Same for cross-cutting helpers like read_sql,
get_db (from db module).

See cockpit_ops/README.md for the split architecture. See ADR 0028 (TBW)
for the rationale.
"""

import functools
import glob
import json
import re
import sys
import time as _time
from datetime import datetime, date as _date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is importable (cockpit_ops/ lives at the root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, get_db

# Shared decorators — implementations live in cockpit/api.py (single-source).
# One-way import so cockpit doesn't need to know about cockpit_ops.
from cockpit._shared import _ttl_cache, _persisted_cache, safe_json_records


# ───────────────────────────── Ops functions ─────────────────────────────


def get_pipeline_status(days=7):
    """Pipeline log for last N days — deduped to one row per (date, step) showing the FINAL state.

    The pipeline writes 2 rows per step: a 'RUNNING' row when the step starts, then a
    'SUCCESS' or 'FAILED' row when it finishes. We only want to show the latest state.
    Also: a step is only treated as RUNNING if its started_at is recent (last 5 minutes)
    AND there's no completion row for it — otherwise it's a stale RUNNING row from a
    previous run that crashed before writing its completion."""
    df = read_sql(
        """
        WITH ranked AS (
            SELECT id, run_date, step_name, status, rows_affected, duration_sec,
                   error_message, started_at, finished_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY run_date, step_name
                       ORDER BY
                           CASE status
                               WHEN 'SUCCESS' THEN 1
                               WHEN 'FAILED'  THEN 2
                               WHEN 'RUNNING' THEN 3
                               ELSE 4
                           END,
                           id DESC
                   ) AS rn
            FROM pipeline_log
            WHERE run_date >= date('now', ?)
        )
        SELECT run_date, step_name, status, rows_affected, duration_sec,
               error_message, started_at, finished_at
        FROM ranked
        WHERE rn = 1
        ORDER BY started_at DESC
        """,
        params=[f"-{days} days"],
    )

    # Mark stale RUNNING rows as ABORTED — they're from runs that crashed mid-step
    if not df.empty:
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(minutes=5)).isoformat()
        df.loc[(df["status"] == "RUNNING") & (df["started_at"] < cutoff), "status"] = "ABORTED"

    df = df.astype(object).where(df.notna(), None)
    return df.to_dict("records")


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
    # cache_ttl shares the scan with health_report._gather_tables so a cold
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
    from config import SIGNAL_WEIGHTS, VIX_REGIMES, QUALITY_GATE, PORTFOLIO, TRANSACTION_COSTS_BPS

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
    for name, (vlo, vhi, large, mid, small) in VIX_REGIMES.items():
        regimes.append({
            "regime": name,
            "vix_lo": vlo, "vix_hi": vhi,
            "alloc_large": large, "alloc_mid": mid, "alloc_small": small,
        })

    # Current regime so the page can highlight the active row.
    cur = read_sql("SELECT regime, vix_latest FROM regime_state WHERE id = 1")
    current_regime = cur.iloc[0].to_dict() if not cur.empty else {}

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
        "quality_gate": QUALITY_GATE,
        "portfolio": PORTFOLIO,
        "transaction_costs_bps": TRANSACTION_COSTS_BPS,
        "backtest_roster": get_backtest_roster(),
    }


def get_backtest_roster():
    """Signal-level backtest readiness for /model.

    For each entry in db.BACKTEST_SIGNALS, enriches with live data:
      - C13b verdict + t-stat per cap_tier (from pit_ic_by_tier_v1)
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
    has_ic = "pit_ic_by_tier_v1" in names

    # ── IC table — group by signal for fast lookup ──
    ic_by_signal = {}
    if has_ic:
        ic_rows = read_sql_fast('SELECT signal, cap_tier, t_stat, verdict, n_periods FROM "pit_ic_by_tier_v1"')
        for _, r in ic_rows.iterrows():
            sig = r["signal"]
            ic_by_signal.setdefault(sig, {})[r["cap_tier"]] = {
                "t_stat": _safe_float(r["t_stat"], 2),
                "verdict": r["verdict"],
                "n_periods": _safe_int(r["n_periods"]),
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
                    df = read_sql(f"SELECT COUNT(DISTINCT snapshot_date) AS n, MIN(snapshot_date) AS f, MAX(snapshot_date) AS l FROM [{ext_tbl}]")
                    if not df.empty and df.iloc[0]["n"] > 0:
                        cov_ext = {
                            "n_dates": _safe_int(df.iloc[0]["n"]),
                            "first_date": df.iloc[0]["f"],
                            "last_date": df.iloc[0]["l"],
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
    for tbl in ["daily_snapshots_pit_v1", "daily_snapshots_pit", "pit_ic_by_tier_v1"]:
        if tbl not in names:
            continue
        try:
            r = read_sql_fast(f'SELECT COUNT(*) AS rows FROM "{tbl}"').iloc[0]
            entry = {"table": tbl, "rows": _safe_int(r["rows"])}
            if tbl != "pit_ic_by_tier_v1":
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
    """Pipeline DAG: source → raw → signals → scoring → output. Used by /flow.

    Builds the layered flow from PIPELINE_STEPS with the latest pipeline_log
    status overlaid so the page shows what last ran and how it went.
    """
    from config import PIPELINE_STEPS

    # Latest status per step from pipeline_log.
    latest = read_sql("""
        SELECT step_name, status, rows_affected, finished_at, duration_sec, error_message
        FROM pipeline_log p
        WHERE p.id = (SELECT MAX(id) FROM pipeline_log
                      WHERE step_name = p.step_name)
    """)
    status_by_step = {r["step_name"]: r.to_dict() for _, r in latest.iterrows()}

    # Layer assignment based on the step's role.
    LAYERS = {
        "fetch_macro_market": "Sources",
        "fetch_macro_gov":    "Sources",
        "fetch_insider":      "Sources",
        "fetch_bulk_deals":   "Sources",
        "fetch_bhavcopy":     "Sources",
        "fetch_news":         "Sources",
        "universe_liveness":  "Sources",
        "signal_sentiment":   "Signals",
        "signal_insider":     "Signals",
        "signal_forensic":    "Signals",
        "signal_piotroski":   "Signals",
        "signal_accruals":    "Signals",
        "signal_consensus":   "Signals",
        "signal_promoter":    "Signals",
        "signal_smart_money": "Signals",
        "signal_macro":       "Signals",
        "signal_regulatory":  "Signals",
        "quality_gate":       "Scoring",
        "regime_update":      "Scoring",
        "screener":           "Scoring",
        "snapshot":           "Output",
        "diff_engine":        "Output",
        "dossier":            "Output",
        "email":              "Output",
    }
    LAYER_ORDER = ["Sources", "Signals", "Scoring", "Output"]

    layers = {ln: [] for ln in LAYER_ORDER}
    for step in PIPELINE_STEPS:
        name = step["name"]
        layer = LAYERS.get(name, "Other")
        if layer not in layers:
            layers[layer] = []
        last = status_by_step.get(name, {})
        layers[layer].append({
            "name": name,
            "module": step["module"],
            "function": step["function"],
            "table": step.get("table"),
            "source": step.get("source"),
            "frequency": step.get("frequency"),
            "critical": step.get("critical", False),
            "last_status": last.get("status"),
            "last_finished_at": last.get("finished_at"),
            "last_duration_sec": last.get("duration_sec"),
            "last_rows": last.get("rows_affected"),
            "last_error": last.get("error_message"),
        })

    layered = [{"name": ln, "steps": layers[ln]} for ln in LAYER_ORDER if layers[ln]]

    return {
        "layers": layered,
        "step_count": sum(len(v) for v in layers.values()),
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
    from config import PIPELINE_STEPS, LOG_PATH

    valid = {s["name"] for s in PIPELINE_STEPS}
    if step_name not in valid:
        return {"ok": False, "error": f"unknown step: {step_name}"}

    recent = read_sql(
        """SELECT started_at FROM pipeline_log
           WHERE step_name = ? AND status = 'RUNNING'
           ORDER BY id DESC LIMIT 1""",
        params=[step_name],
    )
    if not recent.empty:
        try:
            started = datetime.fromisoformat(recent.iloc[0]["started_at"])
            if datetime.now() - started < timedelta(minutes=5):
                return {"ok": False, "error": f"{step_name} is already RUNNING"}
        except (ValueError, TypeError):
            pass

    project_root = Path(__file__).resolve().parent.parent
    rerun_log = project_root / "output" / "rerun.log"
    rerun_log.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(rerun_log, "ab")

    subprocess.Popen(
        [sys.executable, "pipeline.py", "--step", step_name],
        cwd=project_root,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return {"ok": True, "step": step_name, "log": str(rerun_log)}


def get_data_health_scores(force=False):
    """Comprehensive per-table data health from health.compute_db_health().

    Pass force=True to bypass the 5-minute TTL cache.
    """
    from health import compute_db_health
    return compute_db_health(force=force)


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

        # Best t-stat per signal — plan 0005 Phase D rule:
        # 1. Prefer sources with n_periods >= 12 (statistically meaningful)
        # 2. Within those, prefer v2_recompute over v1_archive (cleaner pipeline)
        # 3. Fall back to whatever has the highest n if nothing meets the bar
        # Pre-fix: always preferred v2_recompute even at n=6, masking the n=35
        # v1_archive result for the same signal. The n<12 gate then nuked the
        # whole factor library to INSUFFICIENT.
        ic = read_sql(
            "SELECT signal, source, t_stat, n_periods, t_stat_ci_lo, t_stat_ci_hi "
            "FROM pit_ic_by_tier_v2"
        )
        if ic.empty:
            best_by_signal = {}
        else:
            MIN_N = 12
            ic = ic.assign(
                abst=lambda d: d["t_stat"].abs(),
                _adequate_n=lambda d: (d["n_periods"] >= MIN_N).astype(int),
                _src=lambda d: d["source"].map({"v2_recompute": 0}).fillna(
                    d["source"].str.startswith("v2_recompute:").map({True: 0}).fillna(1)
                ),
            )
            # Sort: adequate_n DESC (1 first), _src ASC (v2 first), abst DESC
            best_by_signal = (ic.sort_values(["_adequate_n", "_src", "abst"],
                                              ascending=[False, True, False])
                                .drop_duplicates("signal", keep="first")
                                .set_index("signal")
                                .to_dict("index"))

        # PIT columns actually populated in daily_snapshots_pit (latest snapshot).
        # NOTE: daily_snapshots_pit is the *backtest* reconstruction, only refreshed
        # when tools/reconstruct_pit.py runs (manually, periodically). Use this
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
    # LIVE = actually wired into a production weight scheme (config.SIGNAL_WEIGHTS
    #   / _RETURN / _SHARPE). NOTE: the per-row `in_model` flag means "READY &
    #   |t|>=1.5" — that conflates live + waiting, so it is NOT used here.
    # The screener's weight keys are abstracted names ("consensus", "smart_money")
    # mapping to one canonical signal; keep in sync with screener.SIGNAL_COLS.
    import config as _cfg
    _WEIGHT_KEY_TO_SIGNAL = {
        "consensus":          "consensus_signal_combined",
        "earnings_yield":     "earnings_yield",
        "accruals":           "cf_accruals_ratio",
        "piotroski":          "piotroski_f_score",
        "momentum":           "mom_6m_adj",
        "book_to_price":      "book_to_price",
        "promoter":           "promoter_qoq",
        "smart_money":        "smart_money_score",
        "pt_upside":          "pt_upside",
        "eps_growth":         "eps_growth_yoy",
        "pledge_quality":     "pledge_quality",
        "delivery_anomaly_z": "delivery_anomaly_z",
    }
    wired = set()
    for _sch in ("SIGNAL_WEIGHTS", "SIGNAL_WEIGHTS_RETURN", "SIGNAL_WEIGHTS_SHARPE"):
        for _tier_w in (getattr(_cfg, _sch, {}) or {}).values():
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
    for _tier in ("LARGE", "MID", "SMALL"):
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
        # production-wired (signal,tier) pairs ONLY (config.SIGNAL_WEIGHTS — not the
        # RETURN/SHARPE dry-run variants), so the count matches what's deployed.
        live_rows = []
        for _tier, _tw in (getattr(_cfg, "SIGNAL_WEIGHTS", {}) or {}).items():
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
        {
            "signal": "fcf_yield",
            "label": "FCF Yield (Track 3)",
            "group": "Track 3 / Cash",
            "status": "READY",
            "status_reason": "",
            "track": "f-track",
            "score_table": "fcf_yield_scores",
        },
    ]

    # Promotion criterion: if pit_ic_by_tier_v2 has a row with |t| >= 1.5 in
    # any cap-tier (preferring v2_recompute over v1_archive when both exist),
    # the factor is "in model"; otherwise "library".
    PROMOTION_T_THRESHOLD = 1.5

    factors = []
    with get_db() as conn:
        try:
            ic = read_sql(
                "SELECT signal, cap_tier, t_stat, mean_ic, source, n_periods "
                "FROM pit_ic_by_tier_v2"
            )
            # Best |t| across cap_tier per signal — prefer v2_recompute over v1_archive.
            ic = ic.assign(
                abst=lambda d: d["t_stat"].abs(),
                src_priority=lambda d: d["source"].map(
                    {"v2_recompute": 0, "v1_archive": 1}
                ).fillna(2),
            )
            best = (
                ic.sort_values(["src_priority", "abst"], ascending=[True, False])
                  .drop_duplicates("signal", keep="first")
                  .set_index("signal")
                  .to_dict("index")
            )
        except Exception:
            best = {}

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
            ("fcf_yield_scores",       "Track 3 FCF Yield — 1,195 stocks"),
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
            "detail": f"Has {f['stocks']} stocks scored today but no `pit_{f['signal']}(sid, eval_date)` in tools/reconstruct_pit.py — can't be backtested. Pair the module with its PIT version on next ship.",
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

    # market_cap_cr rename
    todos.append({
        "title": "stocks.market_cap_cr is misnamed (actually rupees, not crores)",
        "detail": "RELI shows 1.83e13 in the column (= ₹18.3L cr in rupees). Fixed locally in signals/fcf_yield.py with /1e7 divisor. Other consumers (cockpit/api.py, output/email_sender.py) treat the value as-is and could be displaying wrong units. Defer until a slow session.",
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
            "name": "Quality gate",
            "summary": "Excludes F-Score ≤ 1, distress flags, dilution",
            "items": [
                ("scoring/quality_gate.py", "Hard exclusions before scoring"),
                ("Penalty: low Piotroski (F=2-3) → −0.15", "Soft penalty"),
                ("Penalty: distress (Z<1.81) → fixed", "Forensic penalty"),
            ],
        },
        {
            "name": "Cap-tier composite",
            "summary": "Within-tier weighted sum of validated signals (cf C13b rubric)",
            "items": [
                ("LARGE: 7 weighted signals", "consensus 1.0× / piotroski 0.1× / EY 0.5× ..."),
                ("MID: 7 weighted signals", "consensus 0.5× / piotroski 0.2× / EY 0.5× ..."),
                ("SMALL: 7 weighted signals", "EY 1.0× / piotroski 0.15× / promoter 1.0× ..."),
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
                ("Top 5 LARGE / MID / SMALL", "Ranked by composite, gated by quality_gate"),
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
                ("/signals", "Per-signal cross-section"),
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
# Health Center — unified one-screen pulse
#
# Surfaces ALL findings inside cockpit so the user never has to read terminal
# health_report output or email digests to know if the system is healthy:
#   1. tools.health_report.gather()  — pipeline + tables + watchdog + dossiers
#   2. tools.data_sanity.run()       — semantic invariants (CRITICAL/WARN/INFO)
#   3. pipeline_log endpoint_audit_* — per-endpoint cockpit coverage gaps
#   4. failed_streaks                — steps currently broken (not historical)
# Each issue is one row with severity / code / source / message / sample /
# drilldown URL, ready for filter+render in the template.
# ═══════════════════════════════════════════════════

def _drilldown_for_issue(issue):
    """Return ('/sql?q=...', label) for an issue, or (None, None) if no drilldown.

    Looks at the issue's source ('sanity'/'freshness'/'pipeline'/'endpoint'/'dossier')
    and table/code to pick the most useful SQL probe.
    """
    src = issue.get("source")
    table = issue.get("table")
    col = issue.get("column")
    if src == "pipeline" and issue.get("step"):
        sql = f"SELECT run_date, status, started_at, error_message FROM pipeline_log WHERE step_name='{issue['step']}' ORDER BY id DESC LIMIT 20"
        return (f"/sql?q={sql}", "Last 20 runs →")
    if src == "endpoint" and issue.get("endpoint"):
        sql = f"SELECT * FROM pipeline_log WHERE step_name='endpoint_audit_{issue['endpoint']}' ORDER BY id DESC LIMIT 10"
        return (f"/sql?q={sql}", "Endpoint audit log →")
    if src == "freshness" and table:
        sql = f"SELECT MAX(date) AS latest FROM {table}" if table else None
        return (f"/sql?table={table}", "Inspect table →") if table else (None, None)
    if src == "sanity":
        # If we have a sample sid, link to its stock detail (always useful)
        sample = issue.get("sample")
        sample = str(sample) if sample is not None else ""
        if sample and len(sample.split()) == 1 and len(sample) <= 12 and "@" not in sample:
            # Looks like a sid
            return (f"/explorer/{sample}", f"Inspect {sample} →")
        if table:
            return (f"/sql?table={table}", f"Inspect {table} →")
    return (None, None)


def _severity_rank(sev):
    return {"CRITICAL": 0, "WARN": 1, "INFO": 2}.get(sev, 3)


# ═══════════════════════════════════════════════════
# News feed — Inshorts/Finshots style
#
# Lightweight: pull from news_articles, rank by recency × source tier, dedupe
# by title-similarity. No per-article LLM call (would add cost + complexity).
# The spec calls for an LLM brief; we do that as a separate optional pass.
# ═══════════════════════════════════════════════════

# NOTE: `_NEWS_SOURCE_TIERS` lived here briefly after the Stage 2 extraction
# (2026-05-26) but was moved back to cockpit/api.py because `_news_tier()` —
# its only consumer — lives in the trading cockpit's news section.




@_persisted_cache(300, name="get_health_overview")
def get_health_overview(force=False):
    """One-stop Health Center overview.

    Returns:
        {
            "as_of":            ISO datetime,
            "verdict":          human string (e.g. "1 CRITICAL · 12 WARN"),
            "verdict_severity": "CRITICAL" | "WARN" | "INFO" | "OK",
            "counts":           {critical, warn, info, total},
            "tiles":            {data, factors, pipeline, dossiers}  each {grade, color, headline, detail, link},
            "issues":           [issue dicts] sorted CRITICAL → WARN → INFO,
            "categories":       list of category labels present (for filter dropdown),
            "sources":          list of source labels present,
        }
    """
    from tools import health_report as _hr
    try:
        from tools import data_sanity as _sanity
    except Exception:
        _sanity = None

    report = _hr.gather()
    issues = []

    # ── pipeline failures (today) + streaks (currently broken only) ──
    for f in report["pipeline"]["failed_steps_today"]:
        issues.append({
            "severity": "CRITICAL",
            "source": "pipeline",
            "category": "Pipeline",
            "code": f"PIPELINE_FAILED:{f['step']}",
            "table": None, "column": None,
            "step": f["step"],
            "message": f"Pipeline step '{f['step']}' failed today",
            "detail": (f.get("error") or "")[:240],
            "sample": None, "pct": None, "n_bad": None, "n_total": None,
        })
    for s in report["pipeline"]["failed_streaks"]:
        # Skip if it's already in today's failures (avoid duplicate)
        if any(i["code"] == f"PIPELINE_FAILED:{s['step']}" for i in issues):
            continue
        issues.append({
            "severity": "CRITICAL",
            "source": "pipeline",
            "category": "Pipeline",
            "code": f"PIPELINE_STREAK:{s['step']}",
            "table": None, "column": None,
            "step": s["step"],
            "message": f"Pipeline step '{s['step']}' has failed {s['days']} consecutive days (currently broken)",
            "detail": (s.get("sample_error") or "")[:240],
            "sample": None, "pct": None, "n_bad": s["days"], "n_total": None,
        })

    # ── freshness (stale / outdated / empty tables) ──
    for tbl, age, threshold, producer in report["tables"].get("outdated", []):
        sev = "CRITICAL" if tbl in _hr.CRITICAL_TABLE_OUTDATED else "WARN"
        issues.append({
            "severity": sev,
            "source": "freshness",
            "category": "Data freshness",
            "code": f"OUTDATED:{tbl}",
            "table": tbl, "column": "—",
            "message": f"{tbl} is OUTDATED ({age:.0f}d old, threshold {threshold:.0f}d)",
            "detail": f"producer: {producer}" if producer else "",
            "sample": None, "pct": None,
            "n_bad": round(age), "n_total": round(threshold),
        })
    for tbl, age, threshold, producer in report["tables"].get("stale", []):
        issues.append({
            "severity": "WARN",
            "source": "freshness",
            "category": "Data freshness",
            "code": f"STALE:{tbl}",
            "table": tbl, "column": "—",
            "message": f"{tbl} is STALE ({age:.0f}d / threshold {threshold:.0f}d)",
            "detail": f"producer: {producer}" if producer else "",
            "sample": None, "pct": None,
            "n_bad": round(age), "n_total": round(threshold),
        })
    for tbl in report["tables"].get("empty", []):
        # Shared policy (one source of truth = health_report.empty_table_severity):
        #   *_quarantine → OK (empty = nothing quarantined = clean) → suppress
        #   paper_* / uhs_calibration_log → INFO (feature not yet populated)
        #   anything else → CRITICAL (a producer wrote 0 rows where rows expected)
        sev = _hr.empty_table_severity(tbl)
        if sev == "OK":
            continue
        issues.append({
            "severity": sev,
            "source": "freshness",
            "category": "Data freshness",
            "code": f"EMPTY:{tbl}",
            "table": tbl, "column": "—",
            "message": (f"{tbl} is EMPTY — feature not yet populated"
                        if sev == "INFO" else
                        f"{tbl} is EMPTY (table exists but no rows)"),
            "detail": "expected-empty feature table" if sev == "INFO" else "",
            "sample": None, "pct": None, "n_bad": 0, "n_total": None,
        })

    # ── data_sanity violations ──
    # Performance: health_report.gather() already runs data_sanity.run()
    # internally (stored as report["sanity"]). Re-running it here was wasted
    # ~14s every page load. Reuse the existing output.
    sanity_violations = report.get("sanity") or []
    if not sanity_violations and _sanity is not None:
        # Fallback if health_report didn't include sanity for some reason
        try:
            sanity_violations = _sanity.run()
        except Exception as e:
            sanity_violations = []
            issues.append({
                "severity": "WARN",
                "source": "sanity",
                "category": "Data sanity",
                "code": "SANITY_RUN_FAILED",
                "table": None, "column": None,
                "message": f"data_sanity.run() itself raised: {type(e).__name__}",
                "detail": str(e)[:240],
                "sample": None, "pct": None, "n_bad": None, "n_total": None,
            })
    for v in sanity_violations:
        # categorize by code prefix for filter
        code = v.get("code", "")
        if any(p in code for p in ("CONSENSUS", "ANALYST", "PT_", "FORECAST")):
            cat = "Analyst / PT"
        elif any(p in code for p in ("REGULATORY", "NEWS", "SENTIMENT")):
            cat = "News / regulatory"
        elif any(p in code for p in ("FACTOR", "PIT", "BACKTEST", "PIOTROSKI", "M_SCORE")):
            cat = "Factors / backtest"
        elif any(p in code for p in ("DAILY_PICK", "SCORE_TABLE", "UNIVERSE", "PROMOTER", "INSIDER", "BULK")):
            cat = "Signals / picks"
        elif "COVERAGE" in code:
            cat = "Coverage"
        else:
            cat = "Data sanity"
        issues.append({
            "severity": v.get("severity", "WARN"),
            "source": "sanity",
            "category": cat,
            "code": code,
            "table": v.get("table"),
            "column": v.get("column"),
            "message": v.get("message", ""),
            "detail": "",
            "sample": v.get("sample"),
            "pct": v.get("pct_violations"),
            "n_bad": v.get("n_violations"),
            "n_total": v.get("n_total"),
        })

    # ── cockpit endpoint audit (most-recent per endpoint) ──
    try:
        ep = read_sql(
            """
            WITH ranked AS (
                SELECT step_name, status, error_message, started_at,
                       ROW_NUMBER() OVER (PARTITION BY step_name ORDER BY id DESC) AS rn
                FROM pipeline_log
                WHERE step_name LIKE 'endpoint_audit_%'
            )
            SELECT step_name, status, error_message, started_at
            FROM ranked WHERE rn = 1
            """
        )
    except Exception:
        ep = pd.DataFrame()
    for _, r in ep.iterrows():
        if r["status"] == "SUCCESS":
            continue  # endpoint is fine — message carries an [OK] summary we don't surface
        endpoint = r["step_name"].replace("endpoint_audit_", "")
        err = (r.get("error_message") or "").strip()
        # Derive severity from the message tag if present, else from status
        if "[CRITICAL]" in err:
            sev = "CRITICAL"
        elif "[WARN]" in err:
            sev = "WARN"
        else:
            sev = "CRITICAL" if r["status"] == "FAILED" else "WARN"
        issues.append({
            "severity": sev,
            "source": "endpoint",
            "category": "Cockpit endpoints",
            "code": f"ENDPOINT_AUDIT:{endpoint}",
            "table": None, "column": None,
            "endpoint": endpoint,
            "message": f"Cockpit endpoint `{endpoint}` has audit issues",
            "detail": err[:240] or f"status={r['status']}",
            "sample": None, "pct": None, "n_bad": None, "n_total": None,
        })

    # ── dossier validator failures ──
    dossiers_block = report.get("dossiers", {}) or {}
    invalid = dossiers_block.get("invalid_count", 0) or 0
    if invalid:
        issues.append({
            "severity": "WARN",
            "source": "dossier",
            "category": "Dossiers (LLM)",
            "code": "DOSSIER_VALIDATOR_FAILED",
            "table": None, "column": None,
            "message": f"{invalid} dossier(s) failed the narrative validator (raw numbers in prose, or signal mention without context)",
            "detail": ", ".join((dossiers_block.get("invalid_sample") or [])[:5]),
            "sample": None, "pct": None,
            "n_bad": invalid, "n_total": dossiers_block.get("total"),
        })

    # ── per-stock integrity violations (plan 0005 Phase B) ──
    try:
        integrity_rows = read_sql(
            "SELECT sid, integrity_status, integrity_reasons FROM daily_picks "
            "WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks) "
            "  AND integrity_status IN ('FAIL', 'WARN')"
        )
    except Exception:
        integrity_rows = pd.DataFrame()
    n_fail = int((integrity_rows["integrity_status"] == "FAIL").sum()) if not integrity_rows.empty else 0
    n_warn = int((integrity_rows["integrity_status"] == "WARN").sum()) if not integrity_rows.empty else 0
    if n_fail:
        sample = integrity_rows[integrity_rows["integrity_status"] == "FAIL"].iloc[0]
        issues.append({
            "severity": "CRITICAL",
            "source": "integrity",
            "category": "Per-stock integrity",
            "code": "INTEGRITY_FAIL",
            "table": "daily_picks", "column": "integrity_status",
            "message": f"{n_fail} pick(s) failed per-stock integrity validator — bumped from action_queue",
            "detail": f"{sample['sid']}: {sample['integrity_reasons'][:160]}",
            "sample": sample["sid"], "pct": None,
            "n_bad": n_fail, "n_total": None,
        })
    if n_warn:
        sample = integrity_rows[integrity_rows["integrity_status"] == "WARN"].iloc[0]
        issues.append({
            "severity": "WARN",
            "source": "integrity",
            "category": "Per-stock integrity",
            "code": "INTEGRITY_WARN",
            "table": "daily_picks", "column": "integrity_status",
            "message": f"{n_warn} pick(s) flagged with WARN by integrity validator — surfaced but not gated",
            "detail": f"{sample['sid']}: {sample['integrity_reasons'][:160]}",
            "sample": sample["sid"], "pct": None,
            "n_bad": n_warn, "n_total": None,
        })

    # ── universe eligibility coverage gaps (plan 0005 Phase A) ──
    # Surface per-signal eligibility deltas vs prior snapshot — a sudden jump
    # in INELIGIBLE count means a source went dark (yfinance broke, screener
    # source stopped delivering). Showing as INFO at baseline so the user has
    # the per-signal eligible/ineligible breakdown without alarm.
    try:
        elig_today = read_sql(
            "SELECT signal, "
            "       SUM(CASE WHEN eligible=1 THEN 1 ELSE 0 END) AS n_eligible, "
            "       SUM(CASE WHEN eligible=0 THEN 1 ELSE 0 END) AS n_ineligible "
            "FROM universe_eligibility "
            "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM universe_eligibility) "
            "GROUP BY signal ORDER BY signal"
        )
    except Exception:
        elig_today = pd.DataFrame()
    eligibility_block = elig_today.to_dict("records") if not elig_today.empty else []

    # ── attach drilldowns ──
    for i in issues:
        url, label = _drilldown_for_issue(i)
        i["drilldown_url"] = url
        i["drilldown_label"] = label

    # ── sort: severity then code ──
    issues.sort(key=lambda i: (_severity_rank(i["severity"]), i.get("code", "")))

    # ── counts + verdict ──
    counts = {"critical": 0, "warn": 0, "info": 0, "total": len(issues)}
    for i in issues:
        if i["severity"] == "CRITICAL": counts["critical"] += 1
        elif i["severity"] == "WARN":   counts["warn"]     += 1
        elif i["severity"] == "INFO":   counts["info"]     += 1
    if counts["critical"]:
        verdict_sev = "CRITICAL"
        verdict = f"⚠ {counts['critical']} CRITICAL · {counts['warn']} warn · {counts['info']} info"
    elif counts["warn"]:
        verdict_sev = "WARN"
        verdict = f"⚠ {counts['warn']} warn · {counts['info']} info"
    elif counts["info"]:
        verdict_sev = "INFO"
        verdict = f"{counts['info']} info"
    else:
        verdict_sev = "OK"
        verdict = "✓ all healthy"

    # ── tiles: one grade per pillar ──
    def _pillar_grade(critical_n, warn_n):
        if critical_n: return ("F", "#e74c3c")
        if warn_n >= 5: return ("C", "#f1c40f")
        if warn_n: return ("B", "#4d8eff")
        return ("A", "#2ecc71")

    def _count_by(src):
        c = sum(1 for i in issues if i["source"] == src and i["severity"] == "CRITICAL")
        w = sum(1 for i in issues if i["source"] == src and i["severity"] == "WARN")
        info = sum(1 for i in issues if i["source"] == src and i["severity"] == "INFO")
        return c, w, info

    data_c, data_w, data_i = (lambda: (
        sum(1 for i in issues if i["source"] in ("freshness", "sanity") and i["severity"] == "CRITICAL"),
        sum(1 for i in issues if i["source"] in ("freshness", "sanity") and i["severity"] == "WARN"),
        sum(1 for i in issues if i["source"] in ("freshness", "sanity") and i["severity"] == "INFO"),
    ))()

    pipe_c, pipe_w, pipe_i = _count_by("pipeline")
    ep_c, ep_w, ep_i = _count_by("endpoint")
    dos_c, dos_w, dos_i = _count_by("dossier")

    # Factor tile derives from get_factor_health()
    try:
        fh = get_factor_health() or {}
        fh_summary = fh.get("summary", {}) or {}
        # Crude factor pillar grade: F if any in_model factor has data F-grade
        f_grade_dist = fh_summary.get("data_grade_dist", {}) or {}
        f_validation = fh_summary.get("validation_dist", {}) or {}
        if f_grade_dist.get("F", 0):
            f_grade, f_color = ("D", "#e67e22")
        elif f_grade_dist.get("D", 0):
            f_grade, f_color = ("C", "#f1c40f")
        elif f_grade_dist.get("C", 0):
            f_grade, f_color = ("B", "#4d8eff")
        else:
            f_grade, f_color = ("A", "#2ecc71")
        f_headline = f"{fh_summary.get('in_model', 0)} in model · {fh_summary.get('in_library', 0)} library"
        f_detail = (
            f"{f_validation.get('KEEP', 0)} KEEP · "
            f"{f_validation.get('WEAK', 0)} WEAK · "
            f"{f_validation.get('DROP', 0)} DROP · "
            f"{f_validation.get('NONE', 0)} NONE"
        )
    except Exception:
        f_grade, f_color, f_headline, f_detail = ("?", "#888", "—", "factor health unavailable")

    int_c, int_w, int_i = _count_by("integrity")

    data_grade, data_color = _pillar_grade(data_c, data_w)
    pipe_grade, pipe_color = _pillar_grade(pipe_c, pipe_w)
    dos_grade, dos_color = _pillar_grade(dos_c, dos_w)
    int_grade, int_color = _pillar_grade(int_c, int_w)

    # Picks tile: total picks today + integrity status
    try:
        picks_row = read_sql(
            "SELECT COUNT(*) AS n FROM daily_picks "
            "WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)"
        )
        n_picks = int(picks_row.iloc[0]["n"]) if not picks_row.empty else 0
    except Exception:
        n_picks = 0

    tiles = {
        "data": {
            "label": "Data",
            "grade": data_grade, "color": data_color,
            "headline": f"{data_c} critical · {data_w} warn",
            "detail": f"freshness + sanity invariants across {len(report['tables'])} table-state slots",
            "link": "#data",
        },
        "factors": {
            "label": "Factors",
            "grade": f_grade, "color": f_color,
            "headline": f_headline,
            "detail": f_detail,
            "link": "#factors",
        },
        "picks": {
            "label": "Picks integrity",
            "grade": int_grade, "color": int_color,
            "headline": f"{n_picks} ranked · {n_fail} FAIL · {n_warn} WARN",
            "detail": "per-stock cross-source assertions (plan 0005 Phase B)",
            "link": "#overview",
        },
        "pipeline": {
            "label": "Pipeline",
            "grade": pipe_grade, "color": pipe_color,
            "headline": f"last run: {report['pipeline'].get('last_run_status') or '—'}",
            "detail": f"{pipe_c} broken streak(s) · {len(report['pipeline'].get('failed_steps_today', []))} failure(s) today",
            "link": "#pipeline",
        },
        "dossiers": {
            "label": "Dossiers",
            "grade": dos_grade, "color": dos_color,
            "headline": f"{dossiers_block.get('total', 0)} total · {dossiers_block.get('invalid_count', 0)} invalid",
            "detail": "narrative validator (raw numbers / signal-without-context)",
            "link": "#overview",
        },
    }

    # PIT replay tile (plan 0005 Phase E) — "can current code reproduce frozen picks?"
    try:
        pit_status_row = read_sql(
            "SELECT MAX(snapshot_date) AS d, COUNT(DISTINCT snapshot_date) AS n, "
            "MAX(frozen_at) AS last_freeze, MAX(frozen_by_commit) AS sha "
            "FROM pit_replay_snapshots"
        )
        if not pit_status_row.empty and pit_status_row.iloc[0]["d"]:
            r = pit_status_row.iloc[0]
            n_frozen = int(r["n"])
            last_d = r["d"]
            last_freeze = r["last_freeze"] or ""
            # We don't run replay here (would block page load 5-10s). Instead show
            # freeze recency + count of historical anchors. Replay verdict is
            # surfaced via dedicated /pit-replay endpoint if/when added.
            age_days = None
            try:
                from datetime import datetime as _dt
                last_dt = _dt.fromisoformat(last_freeze.split(".")[0]) if last_freeze else None
                age_days = (_dt.now() - last_dt).days if last_dt else None
            except Exception:
                pass
            if age_days is not None and age_days <= 2:
                pit_grade, pit_color = "OK", "var(--green)"
                pit_headline = f"{n_frozen} dates frozen · last {age_days}d ago"
            elif age_days is not None and age_days <= 7:
                pit_grade, pit_color = "STALE", "var(--amber)"
                pit_headline = f"{n_frozen} dates frozen · stale ({age_days}d)"
            else:
                pit_grade, pit_color = "OK", "var(--green)"
                pit_headline = f"{n_frozen} dates frozen"
            pit_detail = f"latest anchor: {last_d} · run `python -m tools.pit_replay replay-all` to verify"
        else:
            pit_grade, pit_color = "INFO", "var(--text-muted)"
            pit_headline = "no anchors yet"
            pit_detail = "run `python -m tools.pit_replay freeze` to create first anchor"
        tiles["pit_replay"] = {
            "label": "PIT replay",
            "grade": pit_grade, "color": pit_color,
            "headline": pit_headline,
            "detail": pit_detail,
            "link": "#pit-replay",
        }
    except Exception:
        pass

    categories = sorted({i["category"] for i in issues})
    sources = sorted({i["source"] for i in issues})

    return {
        "as_of": report["as_of"],
        "verdict": verdict,
        "verdict_severity": verdict_sev,
        "counts": counts,
        "tiles": tiles,
        "issues": issues,
        "categories": categories,
        "sources": sources,
        "watchdog": report.get("watchdog", {}),
        "pipeline_summary": report.get("pipeline", {}),
        "eligibility": eligibility_block,
        "integrity": {
            "n_fail": n_fail,
            "n_warn": n_warn,
            "fails": (integrity_rows[integrity_rows["integrity_status"] == "FAIL"].to_dict("records") if not integrity_rows.empty else []),
            "warns": (integrity_rows[integrity_rows["integrity_status"] == "WARN"].to_dict("records") if not integrity_rows.empty else []),
        },
        "trust": _trust_overview(),
    }


def _trust_overview() -> dict:
    """Plan 0007 Trust Pipeline + UHS summary block for /system.

    Reads health_score (entity_kind='system' + 'pick'), trust_verdicts (last 7d
    per-gate pass-rate), external_anchors (anchor coverage), and quarantine
    tables (row counts). Returns the data the Overview tab's Trust card needs."""
    from db import read_sql as _rs

    # ── system UHS pulse ──
    sys_df = _rs(
        """SELECT score_pct, label,
                  dim_provenance, dim_freshness, dim_plausibility,
                  dim_consistency, dim_coverage, snapshot_date
           FROM health_score
           WHERE entity_kind='system'
           ORDER BY snapshot_date DESC LIMIT 1"""
    )
    system_row = sys_df.iloc[0].to_dict() if not sys_df.empty else None

    # ── pick UHS distribution today ──
    picks_df = _rs(
        """SELECT uhs_label, COUNT(*) AS n,
                  ROUND(AVG(uhs_score),1) AS avg_score
           FROM daily_picks
           WHERE pick_date=(SELECT MAX(pick_date) FROM daily_picks)
             AND uhs_score IS NOT NULL
           GROUP BY uhs_label"""
    )
    pick_dist = {r["uhs_label"]: {"n": int(r["n"]), "avg": float(r["avg_score"])}
                  for _, r in picks_df.iterrows()}

    # ── per-gate verdict stats (last 7d) ──
    gates = [
        ("gate_1_identity",     "Identity (Gate 1)"),
        ("gate_2_plausibility", "Plausibility (Gate 2)"),
        ("gate_3_temporal",     "Temporal (Gate 3)"),
        ("gate_4_cross_source", "Cross-source (Gate 4)"),
        ("gate_5_unit",         "Unit contract (Gate 5)"),
        ("gate_6_lineage",      "Lineage (Gate 6)"),
        ("gate_7_anchor",       "Anchor (Gate 7)"),
    ]
    gate_stats = []
    for col, label in gates:
        try:
            df = _rs(
                f"""SELECT
                    SUM(CASE WHEN {col}=1 THEN 1 ELSE 0 END) AS n_pass,
                    SUM(CASE WHEN {col}=0 THEN 1 ELSE 0 END) AS n_fail,
                    SUM(CASE WHEN {col}=2 THEN 1 ELSE 0 END) AS n_pending,
                    COUNT({col}) AS n_total
                  FROM trust_verdicts
                  WHERE snapshot_date >= date('now','-7 days')
                    AND {col} IS NOT NULL"""
            )
            if df.empty or int(df.iloc[0]["n_total"] or 0) == 0:
                gate_stats.append({"col": col, "label": label, "n_pass": 0,
                                    "n_fail": 0, "n_pending": 0, "n_total": 0,
                                    "pass_pct": None})
                continue
            r = df.iloc[0]
            n_total = int(r["n_total"])
            n_pass = int(r["n_pass"] or 0)
            n_fail = int(r["n_fail"] or 0)
            n_pending = int(r["n_pending"] or 0)
            pass_pct = round(100 * n_pass / n_total, 1) if n_total else None
            gate_stats.append({"col": col, "label": label,
                                "n_pass": n_pass, "n_fail": n_fail,
                                "n_pending": n_pending, "n_total": n_total,
                                "pass_pct": pass_pct})
        except Exception:
            gate_stats.append({"col": col, "label": label, "n_pass": 0,
                                "n_fail": 0, "n_pending": 0, "n_total": 0,
                                "pass_pct": None})

    # ── quarantine row counts ──
    quarantine_tables = [
        "broker_recommendations_quarantine", "forecast_history_quarantine",
        "analyst_consensus_quarantine", "consensus_signals_quarantine",
        "banking_metrics_quarantine", "analyst_consensus_snapshots_quarantine",
        "quarterly_income_quarantine", "annual_balance_sheet_quarantine",
        "annual_cash_flow_quarantine", "mf_holdings_quarantine",
        "mf_sector_allocation_quarantine",
    ]
    quarantine_counts = []
    for tbl in quarantine_tables:
        try:
            df = _rs(f"SELECT COUNT(*) AS n FROM {tbl}")
            n = int(df.iloc[0]["n"]) if not df.empty else 0
            if n > 0:
                quarantine_counts.append({"table": tbl.replace("_quarantine", ""),
                                            "n": n})
        except Exception:
            continue
    quarantine_counts.sort(key=lambda r: -r["n"])

    # ── external_anchors ──
    anchor_df = _rs(
        """SELECT anchor_source, COUNT(*) AS n, MAX(anchor_date) AS last_date
           FROM external_anchors
           WHERE anchor_date >= date('now','-30 days')
           GROUP BY anchor_source
           ORDER BY n DESC"""
    )
    anchor_sources = [
        {"source": r["anchor_source"], "n": int(r["n"]), "last": r["last_date"]}
        for _, r in anchor_df.iterrows()
    ]

    # ── factor table — worst factors right now ──
    factor_df = _rs(
        """SELECT entity_id, score_pct, label, uhs_worst_dim_alias AS worst_dim
           FROM (
             SELECT entity_id, score_pct, label,
                    -- compute worst dim inline
                    CASE
                      WHEN dim_provenance IS NOT NULL AND dim_provenance <= COALESCE(dim_freshness,99)
                       AND dim_provenance <= COALESCE(dim_plausibility,99)
                       AND dim_provenance <= COALESCE(dim_consistency,99)
                       AND dim_provenance <= COALESCE(dim_coverage,99) THEN 'provenance'
                      WHEN dim_freshness IS NOT NULL AND dim_freshness <= COALESCE(dim_plausibility,99)
                       AND dim_freshness <= COALESCE(dim_consistency,99)
                       AND dim_freshness <= COALESCE(dim_coverage,99) THEN 'freshness'
                      WHEN dim_plausibility IS NOT NULL AND dim_plausibility <= COALESCE(dim_consistency,99)
                       AND dim_plausibility <= COALESCE(dim_coverage,99) THEN 'plausibility'
                      WHEN dim_consistency IS NOT NULL AND dim_consistency <= COALESCE(dim_coverage,99) THEN 'consistency'
                      WHEN dim_coverage IS NOT NULL THEN 'coverage'
                      ELSE NULL
                    END AS uhs_worst_dim_alias
             FROM health_score
             WHERE entity_kind='factor'
               AND snapshot_date=(SELECT MAX(snapshot_date) FROM health_score WHERE entity_kind='factor')
           )
           ORDER BY score_pct ASC LIMIT 12"""
    )
    factor_breakdown = [
        {"factor": r["entity_id"], "score": int(r["score_pct"]) if r["score_pct"] else None,
         "label": r["label"], "worst_dim": r["worst_dim"]}
        for _, r in factor_df.iterrows()
    ]

    return {
        "system": system_row,
        "pick_distribution": pick_dist,
        "gate_stats": gate_stats,
        "quarantine_counts": quarantine_counts,
        "anchor_sources": anchor_sources,
        "factor_breakdown": factor_breakdown,
    }
