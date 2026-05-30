"""
Temporal Continuity Gate — Trust Pipeline Gate 3, Plan 0007 Phase 3.

A value that's individually plausible can still be a silent step-change from
the recent baseline. Franklin India Short Term Income's NAV went 1,628 → 4,383
in one day (+169%) — both endpoints individually pass plausibility, but the
*transition* is the canonical wind-up / settlement-event pattern.

POLICY
    Compare new_value to a baseline aggregate (median of last N) for the
    same (sid, datum_class). If the ratio (|new/baseline|) exceeds the
    per-class threshold → DISCONTINUOUS → quarantine (or PENDING_REVIEW
    if there's an explanation source like corporate_actions).

    Stock close 1.4× — covers most corporate-action splits/bonuses;
    auto-checked against corporate_actions to distinguish real splits
    (PASS) from sourcing artifacts (QUARANTINE).
    Analyst PT 1.5× — analyst revisions can be large but rarely > 50%.
    NAV 3.0× — wind-up reprice pattern from MF data_quality classifier.
    Fundamentals annual 5× — turnaround years are real (small base).

USAGE
    from validators.temporal_continuity import verify_continuity, route_on_continuity
    v = verify_continuity(
        sid="118566", datum_class="mf_nav",
        new_value=4383.0,
        baseline_table="mf_nav_history", baseline_col="nav", lookback_days=30,
    )
    if v.status == "DISCONTINUOUS":
        # Route to quarantine via route_on_continuity()
        ...
"""

from collections import namedtuple
from datetime import datetime
from typing import Optional


TemporalVerdict = namedtuple(
    "TemporalVerdict",
    ["status", "value", "baseline", "ratio", "threshold", "reason"],
)


# Per-datum-class ratio thresholds. `ratio = max(new/baseline, baseline/new)`.
# Above threshold → DISCONTINUOUS. Some classes have a corp-action escape hatch.
# Format: (multiplier, lookback_days, corp_action_excluded_if_in_table)
CONTINUITY_THRESHOLDS = {
    "stock_close":           {"multiplier": 1.4, "lookback_days": 30,
                              "corp_action_table": "corporate_actions"},
    "analyst_pt":            {"multiplier": 1.5, "lookback_days": 30},
    "mf_nav":                {"multiplier": 3.0, "lookback_days": 30},
    "bank_gnpa_pct":         {"multiplier": 3.0, "lookback_days": 120},
    "bank_nim_pct":          {"multiplier": 2.0, "lookback_days": 120},
    "annual_revenue":        {"multiplier": 5.0, "lookback_days": 1095},
    "annual_net_income":     {"multiplier": 8.0, "lookback_days": 1095},   # earnings volatility
    "promoter_pct":          {"multiplier": 1.5, "lookback_days": 120},
    "delivery_pct":          {"multiplier": 5.0, "lookback_days": 30},
}


def verify_continuity(
    sid: str,
    datum_class: str,
    new_value,
    baseline_values: Optional[list] = None,
    as_of_date: Optional[str] = None,
    baseline_table: Optional[str] = None,
    baseline_col: Optional[str] = None,
    baseline_date_col: Optional[str] = None,
) -> TemporalVerdict:
    """Check `new_value` against the historic baseline for (sid, datum_class).

    Baseline source — caller chooses one:
      (a) baseline_values: list of prior values, caller pre-fetched
      (b) baseline_table + baseline_col + baseline_date_col: helper queries
          the table for values within the lookback window

    Returns TemporalVerdict with status:
        CONTINUOUS    — ratio within threshold
        DISCONTINUOUS — ratio exceeds threshold
        NO_BASELINE   — insufficient prior data to compute (caller may pass-through)
        UNDEFINED     — datum_class not registered
        NULL_VALUE    — value is None / NaN
    """
    cfg = CONTINUITY_THRESHOLDS.get(datum_class)
    if cfg is None:
        return TemporalVerdict("UNDEFINED", new_value, None, None, None,
                                f"no threshold registered for {datum_class}")
    if new_value is None:
        return TemporalVerdict("NULL_VALUE", new_value, None, None, None,
                                "value is None")
    try:
        import math
        v = float(new_value)
        if math.isnan(v):
            return TemporalVerdict("NULL_VALUE", new_value, None, None, None,
                                    "value is NaN")
    except (TypeError, ValueError):
        return TemporalVerdict("UNDEFINED", new_value, None, None, None,
                                f"value '{new_value}' not numeric")

    # Resolve baseline
    if baseline_values is None and baseline_table is not None:
        baseline_values = _fetch_baseline(
            sid, baseline_table, baseline_col, baseline_date_col,
            lookback_days=cfg["lookback_days"], as_of_date=as_of_date,
        )
    if not baseline_values:
        return TemporalVerdict("NO_BASELINE", v, None, None, cfg["multiplier"],
                                "insufficient prior data")

    # Median for robustness against single-day outliers in the baseline window
    import statistics
    baseline = statistics.median(float(x) for x in baseline_values if x is not None)
    if baseline == 0 or baseline is None:
        return TemporalVerdict("NO_BASELINE", v, baseline, None, cfg["multiplier"],
                                "baseline is zero or null")
    ratio = max(abs(v / baseline), abs(baseline / v)) if v != 0 else float("inf")
    threshold = cfg["multiplier"]

    if ratio <= threshold:
        return TemporalVerdict("CONTINUOUS", v, baseline, ratio, threshold,
                                f"ratio {ratio:.2f}× within {threshold}× threshold")

    # Discontinuous — check corporate-action escape hatch where applicable
    if cfg.get("corp_action_table") and as_of_date:
        if _has_recent_corp_action(sid, cfg["corp_action_table"], as_of_date,
                                    window_days=7):
            return TemporalVerdict("CONTINUOUS", v, baseline, ratio, threshold,
                                    f"ratio {ratio:.2f}× explained by corp_action")
    return TemporalVerdict("DISCONTINUOUS", v, baseline, ratio, threshold,
                            f"ratio {ratio:.2f}× exceeds {threshold}× threshold")


def _fetch_baseline(sid, table, col, date_col, lookback_days, as_of_date):
    """Read `col` values from `table` within `lookback_days` ending at `as_of_date`."""
    from db import read_sql
    as_of = as_of_date or datetime.now().date().isoformat()
    pk_col = _likely_sid_col(table)
    df = read_sql(
        f"""
        SELECT {col} AS v
        FROM {table}
        WHERE {pk_col} = ?
          AND {date_col} < ?
          AND {date_col} >= date(?, '-{lookback_days} days')
          AND {col} IS NOT NULL
        ORDER BY {date_col} DESC
        LIMIT 50
        """,
        params=[sid, as_of, as_of],
    )
    return list(df["v"]) if not df.empty else []


def _has_recent_corp_action(sid, table, as_of_date, window_days):
    """True if any corporate_actions row exists for sid within window_days of as_of."""
    from db import read_sql
    try:
        df = read_sql(
            f"""
            SELECT 1 AS one FROM {table}
            WHERE sid = ?
              AND ex_date BETWEEN date(?, '-{window_days} days') AND date(?, '+1 day')
            LIMIT 1
            """,
            params=[sid, as_of_date, as_of_date],
        )
        return not df.empty
    except Exception:
        return False


def _likely_sid_col(table: str) -> str:
    """Most source tables key on `sid`; MF tables use `scheme_code`."""
    if table.startswith("mf_") and "nav" in table:
        return "scheme_code"
    if table.startswith("mf_"):
        return "scheme_code"
    return "sid"


def route_on_continuity(
    verdict: TemporalVerdict,
    source_table: str,
    row: dict,
    sid: str,
    datum_class: str,
    snapshot_date: Optional[str] = None,
) -> str:
    """Dispatch a row based on its continuity verdict.

    Returns: "WRITE_LIVE" | "QUARANTINED" | "PASS_THROUGH"
    """
    if verdict.status == "DISCONTINUOUS":
        _quarantine_for_continuity(source_table, row, sid, datum_class, verdict, snapshot_date)
        return "QUARANTINED"
    if verdict.status == "CONTINUOUS":
        _record_continuity_verdict(sid, source_table, row, datum_class, verdict,
                                    gate_value=1, overall="TRUSTED", snapshot_date=snapshot_date)
        return "WRITE_LIVE"
    return "PASS_THROUGH"


def _quarantine_for_continuity(source_table, row, sid, datum_class, verdict, snapshot_date):
    import json
    from db import get_db
    from validators.identity_check import _likely_pk_cols

    snapshot_date = snapshot_date or datetime.now().date().isoformat()
    mirror_table = f"{source_table}_quarantine"
    forensic = {
        "_q_failed_gate":     "gate_3_temporal",
        "_q_reason":          verdict.reason,
        "_q_quarantined_at":  datetime.now().isoformat(timespec="seconds"),
    }
    payload = {**row, **forensic}
    cols = list(payload.keys())
    placeholders = ",".join("?" * len(cols))
    cols_sql = ",".join(f'"{c}"' for c in cols)
    insert_sql = f'INSERT INTO {mirror_table} ({cols_sql}) VALUES ({placeholders})'
    source_key = json.dumps(
        {k: row.get(k) for k in _likely_pk_cols(source_table) if k in row},
        default=str,
    )
    reasons_blob = {
        "gate_3_temporal": {
            "status": verdict.status,
            "value": str(verdict.value),
            "baseline": str(verdict.baseline),
            "ratio": str(verdict.ratio),
            "threshold": verdict.threshold,
            "reason": verdict.reason,
        }
    }
    try:
        with get_db() as conn:
            conn.execute(insert_sql, [payload[c] for c in cols])
            conn.execute(
                """
                INSERT OR REPLACE INTO trust_verdicts
                  (sid, source_table, source_key, datum_class, snapshot_date,
                   gate_3_temporal, reasons_json, verdict_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, source_table, source_key, datum_class, snapshot_date,
                 0, json.dumps(reasons_blob), "QUARANTINED"),
            )
    except Exception as e:
        import sys
        print(f"  ⚠ _quarantine_for_continuity failed for {source_table}/{sid}: {e}",
              file=sys.stderr)


def _record_continuity_verdict(sid, source_table, row, datum_class, verdict,
                                gate_value, overall, snapshot_date):
    import json
    from db import get_db
    from validators.identity_check import _likely_pk_cols

    snapshot_date = snapshot_date or datetime.now().date().isoformat()
    source_key = json.dumps(
        {k: row.get(k) for k in _likely_pk_cols(source_table) if k in row},
        default=str,
    )
    reasons_blob = {
        "gate_3_temporal": {
            "status": verdict.status,
            "value": str(verdict.value),
            "baseline": str(verdict.baseline),
            "ratio": str(verdict.ratio),
            "threshold": verdict.threshold,
            "reason": verdict.reason,
        }
    }
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trust_verdicts
                  (sid, source_table, source_key, datum_class, snapshot_date,
                   gate_3_temporal, reasons_json, verdict_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, source_table, source_key, datum_class, snapshot_date,
                 gate_value, json.dumps(reasons_blob), overall),
            )
    except Exception as e:
        import sys
        print(f"  ⚠ _record_continuity_verdict failed for {source_table}/{sid}: {e}",
              file=sys.stderr)
