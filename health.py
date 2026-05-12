"""
Alpha Signal v2 — Data Health Model

Comprehensive diagnostic scoring for every table in the database.

Each table is scored 0-100 across multiple factors:

  freshness            How current is the data vs its refresh interval (smart:
                       if next update is not yet due, score is 100 regardless
                       of age — annual data is fresh for ~1 year)
  completeness         Row count vs expected
  coverage             % of stock universe covered (per-stock tables)
  null_rate            NULL fraction on critical columns
  validity             Range / enum / type checks
  outliers             Z-score outliers on numeric columns
  backtest_sufficiency Enough history for backtesting?
  duplicates           Natural-key violations beyond PK

Each factor produces:
  {score, severity (ok/warn/error), message, fix, drill_sql}

When `score < 100` the user gets a one-line diagnostic and a concrete fix.
When applicable, a `drill_sql` is provided that the cockpit SQL console can
run to show the actual offending rows.

Public API:
  compute_table_health(tbl)  → dict for one table
  compute_db_health()         → dict for all tables (cached, see TTL below)
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Optional

import pandas as pd

from db import get_db, read_sql, _table_date_range, TABLE_META

# ── Constants ─────────────────────────────────────────────────────────────────

# Refresh intervals in days. Used by the freshness factor.
# Slow-cadence data (annual filings) is fresh for up to 1 year.
# "daily" = 3 because Indian markets have 2-day weekends and most daily
# producers publish EOD with a 1-day lag — pure 1-day cycle would flag
# every Monday morning as stale.
REFRESH_INTERVALS = {
    "daily":     3,
    "weekly":    7,
    "monthly":   30,
    "quarterly": 91,
    "annual":    365,
}

# Universe size for coverage checks (NSE non-ETF stocks)
UNIVERSE_SIZE = 2448

# Letter-grade thresholds — sorted high to low so the first match wins
GRADE_THRESHOLDS = [
    (95, "A+", "var(--green)"),
    (90, "A",  "var(--green)"),
    (85, "A-", "var(--green)"),
    (80, "B+", "var(--green)"),
    (75, "B",  "var(--amber)"),
    (70, "B-", "var(--amber)"),
    (60, "C",  "var(--amber)"),
    (50, "D",  "var(--red)"),
    (0,  "F",  "var(--red)"),
]


def grade(score: float) -> tuple[str, str]:
    for threshold, letter, color in GRADE_THRESHOLDS:
        if score >= threshold:
            return letter, color
    return "F", "var(--red)"


# ── Factor result helper ─────────────────────────────────────────────────────

def _factor(name, score, severity, message, fix=None, drill_sql=None, weight=1.0):
    """Build a uniform factor result dict."""
    return {
        "name": name,
        "score": int(round(max(0, min(100, score)))),
        "severity": severity,  # ok / warn / error
        "message": message,
        "fix": fix,
        "drill_sql": drill_sql,
        "weight": weight,
    }


# ── Factor 1: Freshness ──────────────────────────────────────────────────────

def factor_freshness(tbl, count, dates, meta, profile, conn):
    """Smart freshness: if next refresh isn't due yet, the data is fresh.

    Uses the table's registered refresh frequency (daily/weekly/monthly/...)
    as the interval. If `latest_date` is within one interval, score=100.
    Past one interval, score declines linearly until severely outdated.
    """
    weight = profile.get("freshness_weight", 0.20)
    freq = profile.get("refresh_freq_override") or meta.get("frequency")
    latest = dates.get("latest_date")

    # For tables where event date naturally lags ingestion (insider_trades:
    # filings cover past trades; bulk_deals: deal_date is the actual deal day),
    # freshness should track when the producer last ran, not the most recent
    # event. Producer-run cadence lives in fetched_at.
    fresh_col = profile.get("freshness_column")
    if fresh_col:
        try:
            row = conn.execute(
                f"SELECT MAX([{fresh_col}]) FROM [{tbl}] WHERE [{fresh_col}] IS NOT NULL"
            ).fetchone()
            if row and row[0]:
                # fetched_at is a datetime ('YYYY-MM-DD HH:MM:SS'); take date prefix.
                latest = str(row[0])[:10]
        except Exception:
            pass

    if not latest or freq not in REFRESH_INTERVALS:
        return _factor("freshness", 100, "ok",
                       "No refresh schedule (config / state table)",
                       weight=weight)

    # Absolute-day override wins over the frequency-mapped interval. Use for
    # tables whose upstream has a structural lag (NSE PIT filings come with a
    # 7-14 day delay regardless of how often we fetch).
    interval = profile.get("refresh_interval_days") or REFRESH_INTERVALS[freq]
    try:
        latest_d = datetime.strptime(latest, "%Y-%m-%d").date()
    except Exception:
        return _factor("freshness", 50, "warn",
                       f"Could not parse latest_date='{latest}'", weight=weight)

    age = (datetime.now().date() - latest_d).days
    overdue = age / interval if interval else 0

    # Brackets: 1× = fresh, 1-2× = slightly stale, 2-3× = stale, >3× = severely outdated.
    # Severity tracks "real" producer drift, not single-cycle slippage.
    if overdue <= 1.0:
        days_until_due = max(0, interval - age)
        return _factor("freshness", 100, "ok",
                       f"Fresh — {age}d old, next {freq} refresh due in {days_until_due}d",
                       weight=weight)

    if overdue <= 2.0:
        score = 100 - 40 * (overdue - 1.0)  # 100 → 60
        return _factor("freshness", score, "warn",
                       f"Slightly stale — {age}d old, {age - interval}d past {freq} cycle",
                       fix=f"Run the producer that writes {tbl}",
                       weight=weight)

    if overdue <= 3.0:
        score = 60 - 40 * (overdue - 2.0)  # 60 → 20
        return _factor("freshness", score, "error",
                       f"Stale — {age}d old, {overdue:.1f}× past {freq} cycle",
                       fix=f"Producer may be broken — check {meta.get('function') or tbl}",
                       weight=weight)

    return _factor("freshness", 0, "error",
                   f"Severely outdated — {age}d old, {overdue:.1f}× past {freq} cycle",
                   fix=f"Producer not running. Investigate {meta.get('function') or tbl}.",
                   weight=weight)


# ── Factor 2: Completeness ───────────────────────────────────────────────────

def factor_completeness(tbl, count, dates, meta, profile, conn):
    """Row count vs expected size."""
    weight = profile.get("completeness_weight", 0.15)
    expected = profile.get("expected_rows")
    min_rows = profile.get("min_rows", 1)

    if count == 0:
        return _factor("completeness", 0, "error", "Table is empty (0 rows)",
                       fix=f"Producer never ran. Check pipeline_log for {tbl}.",
                       drill_sql=f"SELECT * FROM pipeline_log WHERE step_name LIKE '%{tbl.split('_')[0]}%' ORDER BY started_at DESC LIMIT 10",
                       weight=weight)

    if expected is None:
        # No specific expectation — just check it has rows
        if count >= min_rows:
            return _factor("completeness", 100, "ok", f"{count:,} rows", weight=weight)
        return _factor("completeness", 50, "warn",
                       f"Only {count:,} rows (min expected {min_rows:,})",
                       weight=weight)

    ratio = count / expected
    if ratio >= 0.95:
        return _factor("completeness", 100, "ok",
                       f"{count:,} rows ({100 * ratio:.0f}% of expected {expected:,})",
                       weight=weight)
    if ratio >= 0.80:
        score = 60 + 40 * (ratio - 0.80) / 0.15
        return _factor("completeness", score, "warn",
                       f"{count:,} rows — {100 * ratio:.0f}% of expected {expected:,} ({expected - count:,} missing)",
                       fix="Some rows missing. Re-run producer or check upstream.",
                       weight=weight)

    return _factor("completeness", max(0, 60 * ratio / 0.80), "error",
                   f"Only {count:,} rows — {100 * ratio:.0f}% of expected {expected:,}",
                   fix="Major data loss. Check producer error log.",
                   weight=weight)


# ── Factor 3: Coverage ───────────────────────────────────────────────────────

def factor_coverage(tbl, count, dates, meta, profile, conn):
    """For per-stock tables: what % of the 2,448-stock universe has rows here?"""
    if not profile.get("per_stock"):
        return None
    weight = profile.get("coverage_weight", 0.15)

    try:
        n_stocks = conn.execute(f"SELECT COUNT(DISTINCT sid) FROM [{tbl}]").fetchone()[0]
    except Exception:
        return None

    coverage = n_stocks / UNIVERSE_SIZE if UNIVERSE_SIZE else 0
    missing = UNIVERSE_SIZE - n_stocks

    if coverage >= 0.95:
        return _factor("coverage", 100, "ok",
                       f"{n_stocks:,} of {UNIVERSE_SIZE:,} stocks ({100 * coverage:.0f}%)",
                       weight=weight)
    if coverage >= 0.80:
        score = 60 + 40 * (coverage - 0.80) / 0.15
        return _factor("coverage", score, "warn",
                       f"{n_stocks:,} of {UNIVERSE_SIZE:,} stocks ({100 * coverage:.0f}%) — {missing} missing",
                       fix="Some stocks have no data. May be dormant micro-caps; check quality_gate.",
                       drill_sql=f"SELECT s.sid, s.name, s.cap_tier FROM stocks s LEFT JOIN [{tbl}] t ON s.sid = t.sid WHERE t.sid IS NULL LIMIT 100",
                       weight=weight)
    return _factor("coverage", max(0, 60 * coverage / 0.80), "error",
                   f"Only {n_stocks:,} of {UNIVERSE_SIZE:,} stocks ({100 * coverage:.0f}%) — {missing} missing",
                   fix="Major coverage gap. Re-run signal/producer for missing stocks.",
                   drill_sql=f"SELECT s.sid, s.name, s.cap_tier FROM stocks s LEFT JOIN [{tbl}] t ON s.sid = t.sid WHERE t.sid IS NULL LIMIT 100",
                   weight=weight)


# ── Factor 4: NULL rate on critical columns ──────────────────────────────────

def factor_null_rate(tbl, count, dates, meta, profile, conn):
    """% NULL on each critical column. Uses worst column as the score."""
    critical = profile.get("critical_columns", [])
    if not critical or count == 0:
        return None
    weight = profile.get("null_weight", 0.15)

    selects = ", ".join(
        f"SUM(CASE WHEN [{c}] IS NULL THEN 1 ELSE 0 END) AS null_{i}"
        for i, c in enumerate(critical)
    )
    try:
        row = conn.execute(f"SELECT {selects} FROM [{tbl}]").fetchone()
    except Exception as e:
        return _factor("null_rate", 50, "warn",
                       f"NULL check failed: {type(e).__name__}", weight=weight)

    issues = []
    worst_score = 100
    worst_col = None
    for i, c in enumerate(critical):
        nulls = int(row[i] or 0)
        rate = nulls / count
        if rate > 0.10:
            issues.append(f"{c}: {100 * rate:.0f}% NULL ({nulls:,} of {count:,})")
            score = max(0, 100 - 100 * rate)
            if score < worst_score:
                worst_score = score
                worst_col = c

    if not issues:
        return _factor("null_rate", 100, "ok",
                       f"All {len(critical)} critical columns populated",
                       weight=weight)

    severity = "error" if worst_score < 50 else "warn"
    return _factor("null_rate", worst_score, severity,
                   "; ".join(issues),
                   fix="Refresh producer; some critical columns have missing data.",
                   drill_sql=f"SELECT * FROM [{tbl}] WHERE [{worst_col}] IS NULL LIMIT 100",
                   weight=weight)


# ── Factor 5: Validity (range / enum / type) ─────────────────────────────────

def factor_validity(tbl, count, dates, meta, profile, conn):
    """Range / enum / not-negative checks declared in the profile."""
    checks = profile.get("validity_checks", [])
    if not checks or count == 0:
        return None
    weight = profile.get("validity_weight", 0.15)

    issues = []
    worst_score = 100
    worst_drill = None

    for check in checks:
        col = check["column"]
        if "min" in check and "max" in check:
            cond = f"[{col}] IS NOT NULL AND ([{col}] < {check['min']} OR [{col}] > {check['max']})"
        elif "in" in check:
            in_list = ",".join(f"'{v}'" for v in check["in"])
            cond = f"[{col}] IS NOT NULL AND [{col}] NOT IN ({in_list})"
        elif check.get("not_negative"):
            cond = f"[{col}] IS NOT NULL AND [{col}] < 0"
        else:
            continue

        try:
            bad = conn.execute(f"SELECT COUNT(*) FROM [{tbl}] WHERE {cond}").fetchone()[0]
        except Exception:
            continue

        if bad > 0:
            label = check.get("label", col)
            rate = bad / count
            issues.append(f"{label}: {bad:,} invalid ({100 * rate:.1f}%)")
            score = max(0, 100 - 100 * rate)
            if score < worst_score:
                worst_score = score
                worst_drill = f"SELECT * FROM [{tbl}] WHERE {cond} LIMIT 100"

    if not issues:
        return _factor("validity", 100, "ok",
                       f"All {len(checks)} range/type checks pass",
                       weight=weight)

    severity = "error" if worst_score < 50 else "warn"
    return _factor("validity", worst_score, severity, "; ".join(issues),
                   fix="Investigate source data; values out of expected range.",
                   drill_sql=worst_drill, weight=weight)


# ── Factor 6: Outliers (z-score on numeric columns) ──────────────────────────

def factor_outliers(tbl, count, dates, meta, profile, conn):
    """Z-score outliers on declared numeric columns. >5σ is suspicious.

    Sample-based: stops at 50,000 rows to keep the check cheap on large
    tables. Outlier rate of >0.5% triggers a warning.
    """
    cols = profile.get("outlier_columns", [])
    if not cols or count == 0:
        return None
    weight = profile.get("outlier_weight", 0.10)

    issues = []
    worst_score = 100
    worst_drill = None
    SAMPLE_LIMIT = 50000
    Z_THRESHOLD = 5

    for col in cols:
        try:
            stats = conn.execute(
                f"SELECT AVG([{col}]), "
                f"       AVG([{col}] * [{col}]) - AVG([{col}]) * AVG([{col}]) "
                f"FROM (SELECT [{col}] FROM [{tbl}] WHERE [{col}] IS NOT NULL LIMIT {SAMPLE_LIMIT})"
            ).fetchone()
        except Exception:
            continue
        if stats[0] is None or stats[1] is None or stats[1] <= 0:
            continue
        mean = stats[0]
        std = math.sqrt(stats[1])
        if std == 0:
            continue

        lo = mean - Z_THRESHOLD * std
        hi = mean + Z_THRESHOLD * std
        try:
            bad = conn.execute(
                f"SELECT COUNT(*) FROM [{tbl}] "
                f"WHERE [{col}] IS NOT NULL AND ([{col}] < ? OR [{col}] > ?)",
                (lo, hi),
            ).fetchone()[0]
        except Exception:
            continue

        if bad > 0:
            rate = bad / count
            if rate > 0.005:  # >0.5% outliers — flag it
                issues.append(f"{col}: {bad:,} extreme values (>{Z_THRESHOLD}σ from mean {mean:.2f})")
                # Score: 100 at 0.5%, 50 at 5%, 0 at 10%+
                score = max(0, 100 - (rate - 0.005) * 1000)
                if score < worst_score:
                    worst_score = score
                    worst_drill = (
                        f"SELECT * FROM [{tbl}] WHERE [{col}] IS NOT NULL "
                        f"AND ([{col}] < {lo:.4f} OR [{col}] > {hi:.4f}) "
                        f"ORDER BY ABS([{col}] - {mean:.4f}) DESC LIMIT 100"
                    )

    if not issues:
        return _factor("outliers", 100, "ok",
                       f"No extreme outliers in {len(cols)} numeric column(s)",
                       weight=weight)

    severity = "warn"
    return _factor("outliers", worst_score, severity, "; ".join(issues),
                   fix="Investigate extreme values — may indicate data corruption or sentinel values.",
                   drill_sql=worst_drill, weight=weight)


# ── Factor 7: Backtest sufficiency ───────────────────────────────────────────

def factor_backtest_sufficiency(tbl, count, dates, meta, profile, conn):
    """Enough date range for backtesting?"""
    bt = profile.get("min_backtest")
    if not bt:
        return None
    weight = profile.get("backtest_weight", 0.10)

    earliest = dates.get("earliest_date")
    latest = dates.get("latest_date")
    if not earliest or not latest:
        return _factor("backtest_sufficiency", 0, "warn",
                       "No date range — cannot backtest",
                       weight=weight)
    try:
        e = datetime.strptime(earliest, "%Y-%m-%d").date()
        l = datetime.strptime(latest, "%Y-%m-%d").date()
        days = (l - e).days
    except Exception:
        return None

    target = bt["target_days"]
    minimum = bt.get("minimum_days", target // 2)

    if days >= target:
        return _factor("backtest_sufficiency", 100, "ok",
                       f"{days / 365:.1f}y of history (target {target / 365:.1f}y)",
                       weight=weight)
    if days >= minimum:
        score = 50 + 50 * (days - minimum) / (target - minimum)
        return _factor("backtest_sufficiency", score, "warn",
                       f"{days / 365:.1f}y of history — short of {target / 365:.1f}y target",
                       fix="Backfill more history if possible.",
                       weight=weight)
    return _factor("backtest_sufficiency", 100 * days / target, "error",
                   f"Only {days / 365:.1f}y of history — minimum {minimum / 365:.1f}y for backtesting",
                   fix="Insufficient for backtesting. Build historical reconstruction.",
                   weight=weight)


# ── Factor 8: Type conformance / illogicals ──────────────────────────────────

# Maps a SQLite declared type to the set of `typeof()` results we'll accept.
# SQLite is dynamically typed, so an INTEGER column can technically hold any
# value. This factor catches that drift.
#
# Affinity rules from the SQLite docs:
#   - INTEGER columns store integers; whole-number floats are stored as int
#   - REAL columns can hold either real or integer (any numeric)
#   - NUMERIC accepts both integer and real
#   - TEXT must be text (NULL always allowed)
#   - BLOB must be blob

_TYPE_AFFINITY = [
    ("INT",     {"integer"}),                  # INTEGER, BIGINT, INT, ...
    ("CHAR",    {"text"}),                     # CHAR, VARCHAR, TEXT
    ("CLOB",    {"text"}),
    ("TEXT",    {"text"}),
    ("BLOB",    {"blob"}),
    ("REAL",    {"real", "integer"}),          # REAL accepts integer values
    ("FLOA",    {"real", "integer"}),          # FLOAT
    ("DOUB",    {"real", "integer"}),          # DOUBLE
    ("NUM",     {"real", "integer"}),          # NUMERIC
    ("DECIMAL", {"real", "integer"}),
]


def _affinity_for(decl_type):
    """Return the allowed typeof() set for a SQLite declared column type."""
    if not decl_type:
        return None
    decl_upper = decl_type.upper()
    for needle, allowed in _TYPE_AFFINITY:
        if needle in decl_upper:
            return allowed
    return None


def _looks_like_date_col(col_name):
    """Heuristic: does this TEXT column appear to hold dates?

    NOTE: deliberately excludes the bare name `period`. In our schema `period`
    is a fiscal-year label like "FY 2015" / "DEC 2014", not a date — the real
    date column for those tables is `end_date`.
    """
    n = col_name.lower()
    return (
        n.endswith("_date") or n.endswith("_at") or n.endswith("_on")
        or n == "date"
    )


def factor_type_conformance(tbl, count, dates, meta, profile, conn):
    """Catch 'illogicals': values that don't match the column's declared type.

    Three checks per column:
      1. Numeric / TEXT / BLOB columns: typeof() matches the declared affinity
      2. TEXT columns that look like dates: values parse as dates
      3. Critical TEXT columns: not empty / whitespace-only

    SQLite's dynamic typing means a column declared INTEGER will silently
    accept text — without this factor, a buggy producer could insert garbage
    and we'd only find out when a downstream cast fails.
    """
    if count == 0:
        return None
    weight = profile.get("type_weight", 0.10)

    try:
        info = conn.execute(f"PRAGMA table_info([{tbl}])").fetchall()
    except Exception:
        return None
    if not info:
        return None

    critical = set(profile.get("critical_columns", []))
    issues = []
    worst_score = 100
    worst_drill = None
    checks_run = 0

    for row in info:
        col = row[1]
        decl = row[2] or ""
        allowed = _affinity_for(decl)
        if allowed is None:
            continue

        # 1. Type-of mismatch — value's typeof() not in the allowed set
        try:
            placeholders = ",".join(["?"] * len(allowed))
            bad = conn.execute(
                f"SELECT COUNT(*) FROM [{tbl}] "
                f"WHERE [{col}] IS NOT NULL AND typeof([{col}]) NOT IN ({placeholders})",
                tuple(allowed),
            ).fetchone()[0]
        except Exception:
            continue
        checks_run += 1

        if bad > 0:
            rate = bad / count
            issues.append(f"{col}: {bad:,} non-{decl.upper()} values ({100 * rate:.1f}%)")
            score = max(0, 100 - 100 * rate)
            if score < worst_score:
                worst_score = score
                placeholders = ",".join(f"'{a}'" for a in allowed)
                worst_drill = (
                    f"SELECT [{col}], typeof([{col}]) AS actual_type FROM [{tbl}] "
                    f"WHERE [{col}] IS NOT NULL AND typeof([{col}]) NOT IN ({placeholders}) LIMIT 100"
                )

        # 2. Date parseability — for TEXT columns that look like dates
        if "text" in allowed and _looks_like_date_col(col):
            try:
                # Sample up to 5,000 distinct values, parse, count failures
                sample = conn.execute(
                    f"SELECT DISTINCT [{col}] FROM [{tbl}] WHERE [{col}] IS NOT NULL LIMIT 5000"
                ).fetchall()
            except Exception:
                sample = []
            if sample:
                vals = [r[0] for r in sample]
                parsed = pd.to_datetime(pd.Series(vals), errors="coerce", utc=True, format="mixed")
                bad_dates = int(parsed.isna().sum())
                if bad_dates > 0:
                    rate = bad_dates / len(vals)
                    issues.append(f"{col}: {bad_dates:,}/{len(vals):,} sampled values don't parse as dates")
                    score = max(0, 100 - 100 * rate)
                    if score < worst_score:
                        worst_score = score
                        worst_drill = (
                            f"SELECT DISTINCT [{col}] FROM [{tbl}] WHERE [{col}] IS NOT NULL LIMIT 100"
                        )

        # 3. Empty / whitespace-only text in critical columns
        if "text" in allowed and col in critical:
            try:
                empty = conn.execute(
                    f"SELECT COUNT(*) FROM [{tbl}] WHERE [{col}] IS NOT NULL AND TRIM([{col}]) = ''"
                ).fetchone()[0]
            except Exception:
                empty = 0
            if empty > 0:
                rate = empty / count
                issues.append(f"{col}: {empty:,} empty/whitespace-only ({100 * rate:.1f}%)")
                score = max(0, 100 - 100 * rate)
                if score < worst_score:
                    worst_score = score
                    worst_drill = (
                        f"SELECT * FROM [{tbl}] WHERE [{col}] IS NOT NULL AND TRIM([{col}]) = '' LIMIT 100"
                    )

    if checks_run == 0:
        return None

    if not issues:
        return _factor("type_conformance", 100, "ok",
                       f"All {checks_run} typed columns conform (typeof + date parse + non-empty)",
                       weight=weight)

    severity = "error" if worst_score < 50 else "warn"
    return _factor("type_conformance", worst_score, severity, "; ".join(issues),
                   fix="Type drift detected — investigate the producer; check for sentinel values inserted as the wrong type.",
                   drill_sql=worst_drill, weight=weight)


# ── Factor 9: Duplicates ─────────────────────────────────────────────────────

def factor_duplicates(tbl, count, dates, meta, profile, conn):
    """Rows that violate the natural-key uniqueness."""
    pk = profile.get("natural_key")
    if not pk or count == 0:
        return None
    weight = profile.get("dup_weight", 0.05)

    cols = ", ".join(f"[{c}]" for c in pk)
    try:
        dups = conn.execute(
            f"SELECT COUNT(*) FROM (SELECT {cols} FROM [{tbl}] "
            f"GROUP BY {cols} HAVING COUNT(*) > 1)"
        ).fetchone()[0]
    except Exception:
        return None

    if dups == 0:
        return _factor("duplicates", 100, "ok",
                       f"No duplicates on ({', '.join(pk)})", weight=weight)

    return _factor("duplicates", max(0, 100 - 100 * dups / count), "warn",
                   f"{dups:,} duplicate keys on ({', '.join(pk)})",
                   fix="Add UNIQUE constraint or dedupe via window function.",
                   drill_sql=f"SELECT {cols}, COUNT(*) AS n FROM [{tbl}] GROUP BY {cols} HAVING n > 1 ORDER BY n DESC LIMIT 100",
                   weight=weight)


# ── Table profiles ────────────────────────────────────────────────────────────
# What to check for each table. Empty dict = run only universal factors.

TABLE_PROFILES = {
    # ── Universe & Reference ──
    "stocks": {
        "expected_rows": UNIVERSE_SIZE,
        "critical_columns": ["sid", "name", "sector", "cap_tier"],
        "validity_checks": [
            {"column": "cap_tier", "in": ["LARGE", "MID", "SMALL"], "label": "cap_tier value"},
        ],
        "outlier_columns": ["pe_ratio", "pb_ratio", "roe", "debt_to_equity"],
        "natural_key": ["sid"],
        "refresh_freq_override": "weekly",  # universe migrated weekly
    },
    "stock_prices": {
        "per_stock": True,
        "critical_columns": ["sid", "date", "close"],
        "validity_checks": [
            {"column": "close", "min": 0.01, "max": 10000000, "label": "close price"},
            {"column": "delivery_pct", "min": 0, "max": 100, "label": "delivery %"},
        ],
        "outlier_columns": ["close", "volume", "delivery_pct"],
        "min_backtest": {"target_days": 1095, "minimum_days": 252},  # 3y target / 1y min
        "natural_key": ["sid", "date"],
    },
    "vix_history": {
        "critical_columns": ["date", "vix"],
        "validity_checks": [
            {"column": "vix", "min": 5, "max": 100, "label": "VIX value"},
        ],
        "min_backtest": {"target_days": 1095, "minimum_days": 252},
    },
    "regime_state": {
        "expected_rows": 1,
        "critical_columns": ["regime", "alloc_large", "alloc_mid", "alloc_small"],
        "validity_checks": [
            {"column": "regime", "in": ["CALM", "NORMAL", "CAUTION", "CRISIS"], "label": "regime"},
            {"column": "alloc_large", "min": 0, "max": 1, "label": "alloc_large"},
        ],
    },

    # ── Tickertape Fundamentals ──
    # Freshness overrides: config registers these as "monthly" (how often the
    # fetcher should poll), but the underlying data only changes when companies
    # actually file new statements. The user wants "if next update is in a month
    # the data is fresh" — so we score against the *data update* cadence, not
    # the fetcher cadence.
    "quarterly_income": {
        "per_stock": True,
        "refresh_freq_override": "quarterly",
        "critical_columns": ["sid", "period", "revenue"],
        "validity_checks": [
            {"column": "revenue", "not_negative": True, "label": "revenue"},
        ],
        "outlier_columns": ["revenue", "net_income", "eps"],
        "min_backtest": {"target_days": 1095, "minimum_days": 730},
        "natural_key": ["sid", "period", "reporting"],
    },
    "annual_balance_sheet": {
        "per_stock": True,
        "refresh_freq_override": "annual",
        "critical_columns": ["sid", "period", "total_assets"],
        "outlier_columns": ["total_assets", "total_equity", "total_debt"],
        "min_backtest": {"target_days": 1825, "minimum_days": 1095},  # 5y target / 3y min
        "natural_key": ["sid", "period"],
    },
    "annual_cash_flow": {
        "per_stock": True,
        "refresh_freq_override": "annual",
        "critical_columns": ["sid", "period"],
        "outlier_columns": ["operating_cash_flow", "free_cash_flow"],
        "natural_key": ["sid", "period"],
    },
    "shareholding": {
        "per_stock": True,
        "refresh_freq_override": "quarterly",
        "critical_columns": ["sid", "end_date", "promoter_pct"],
        "validity_checks": [
            {"column": "promoter_pct", "min": 0, "max": 100, "label": "promoter %"},
            {"column": "fii_pct", "min": 0, "max": 100, "label": "FII %"},
            {"column": "pledge_pct", "min": 0, "max": 100, "label": "pledge %"},
        ],
        "natural_key": ["sid", "end_date"],
    },
    "analyst_consensus": {
        "per_stock": True,
        # total_analysts is intentionally absent: Tickertape omits it for ~60% of
        # covered stocks even when has_analyst_data=1; signals.consensus degrades
        # gracefully (confidence = 0.3 when missing). price_target is the actual
        # signal driver — that's what we care about being non-NULL.
        "critical_columns": ["sid", "price_target"],
        "validity_checks": [
            {"column": "price_target", "not_negative": True, "label": "price target"},
            {"column": "buy_pct", "min": 0, "max": 100, "label": "buy %"},
        ],
        "outlier_columns": ["price_target", "forward_eps"],
    },
    "forecast_history": {
        "per_stock": True,
        "critical_columns": ["sid", "date", "metric", "value"],
        "natural_key": ["sid", "metric", "date"],
    },

    # ── News & Trades ──
    "news_articles": {
        "critical_columns": ["title", "source", "published_at"],
        "min_rows": 100,
    },
    "news_article_stocks": {
        "critical_columns": ["article_id", "sid"],
        "natural_key": ["article_id", "sid"],
    },
    "insider_trades": {
        "critical_columns": ["sid", "trade_date", "transaction_type"],
        "validity_checks": [
            {"column": "value_lakhs", "not_negative": True, "label": "trade value"},
        ],
        "outlier_columns": ["value_lakhs", "shares"],
        "min_backtest": {"target_days": 730, "minimum_days": 365},
        # Freshness tracks producer cadence, not the most recent filing date —
        # insider filings are sparse (some days have none).
        "freshness_column": "fetched_at",
        # NSE PIT API publishes filings with a 7-14 day delay — even a same-day
        # fetch shows ~10 day staleness on `trade_date`. 14-day interval avoids
        # flagging an otherwise-working fetcher as outdated.
        "refresh_interval_days": 14,
    },
    "bulk_deals": {
        "critical_columns": ["sid", "deal_date", "client_name", "buy_sell"],
        "validity_checks": [
            {"column": "buy_sell", "in": ["BUY", "SELL", "Buy", "Sell"], "label": "buy/sell"},
            {"column": "quantity", "not_negative": True, "label": "quantity"},
        ],
        "freshness_column": "fetched_at",
    },
    "earnings_calendar": {
        "critical_columns": ["sid", "date"],
    },

    # ── Macro & Regulatory ──
    "macro_history": {
        "critical_columns": ["indicator_id", "date", "value"],
        "outlier_columns": ["value"],
        "min_backtest": {"target_days": 1095, "minimum_days": 730},
        "natural_key": ["indicator_id", "date"],
    },
    "macro_indicators": {
        "min_rows": 10,
        # v1-migration leftover. v2's macro pipeline writes to macro_sector_signals
        # (via signals.macro), not here. Mark static so it stops tripping freshness.
        "refresh_freq_override": "annual",
    },
    "macro_indicator_meta": {
        "expected_rows": 50,
        "critical_columns": ["indicator_id", "name", "source"],
        "natural_key": ["indicator_id"],
    },
    "macro_sector_map": {
        "critical_columns": ["indicator_id", "sector", "direction"],
        "validity_checks": [
            {"column": "direction", "min": -1, "max": 1, "label": "direction"},
        ],
        "natural_key": ["indicator_id", "sector"],
    },
    "macro_sector_signals": {
        "expected_rows": 18,
        "critical_columns": ["sector", "macro_score"],
        "validity_checks": [
            {"column": "macro_score", "min": 0, "max": 100, "label": "macro score"},
            {"column": "macro_signal", "in": ["TAILWIND", "FAVORABLE", "NEUTRAL", "HEADWIND", "ADVERSE"], "label": "macro signal"},
        ],
    },
    "regulatory_events": {
        "critical_columns": ["title", "published_at", "source"],
        "validity_checks": [
            {"column": "classifier_status",
             "in": ["pending", "haiku_rejected", "haiku_rejected_inferred",
                    "haiku_passed_sonnet_failed", "classified", "unknown"],
             "label": "classifier status"},
        ],
        # Harvester paused 2026-04-10 (Anthropic budget). Resumes May 2026; until
        # then, score against the manual cadence rather than daily.
        "refresh_freq_override": "monthly",
    },
    "regulatory_signals": {
        "critical_columns": ["event_id", "sector", "is_regulatory"],
        "validity_checks": [
            {"column": "direction", "min": -1, "max": 1, "label": "direction"},
        ],
        "natural_key": ["event_id", "sector"],
        # See regulatory_events note: same paused-harvester reason.
        "refresh_freq_override": "monthly",
    },

    # ── Computed Signals ──  (one row per stock per snapshot_date)
    "piotroski_scores": {
        "per_stock": True,
        "expected_rows": UNIVERSE_SIZE,
        "critical_columns": ["sid", "f_score"],
        "validity_checks": [
            {"column": "f_score", "min": 0, "max": 9, "label": "F-score"},
        ],
    },
    "accruals_scores": {
        "per_stock": True,
        "expected_rows": UNIVERSE_SIZE,
        "critical_columns": ["sid"],
        "outlier_columns": ["cf_accruals_ratio", "bs_accruals_ratio"],
    },
    "consensus_signals": {
        "per_stock": True,
        "expected_rows": UNIVERSE_SIZE,
        "critical_columns": ["sid"],
        "outlier_columns": ["pt_upside", "pt_revision_1yr"],
    },
    "promoter_signals": {
        "per_stock": True,
        "expected_rows": UNIVERSE_SIZE,
        "critical_columns": ["sid"],
    },
    "forensic_scores": {
        "per_stock": True,
        "expected_rows": UNIVERSE_SIZE,
        "critical_columns": ["sid", "m_score", "z_score"],
        "outlier_columns": ["m_score", "z_score"],
    },
    "smart_money_scores": {
        "per_stock": True,
        "expected_rows": UNIVERSE_SIZE,
        "critical_columns": ["sid"],
        "outlier_columns": ["smart_money_score"],
    },
    "sentiment_scores": {
        "per_stock": True,
        "expected_rows": UNIVERSE_SIZE,
        "critical_columns": ["sid"],
        "validity_checks": [
            {"column": "sentiment_7d", "min": -1, "max": 1, "label": "7d sentiment"},
        ],
    },
    "insider_signals": {
        "per_stock": True,
        "critical_columns": ["sid", "snapshot_date", "signal_type"],
        "min_backtest": {"target_days": 730, "minimum_days": 365},
        "natural_key": ["sid", "snapshot_date", "signal_type"],
    },

    # ── Output ──
    "daily_picks": {
        "per_stock": True,
        "expected_rows": UNIVERSE_SIZE,
        "critical_columns": ["sid", "pick_date", "final_score"],
        "validity_checks": [
            {"column": "cap_tier", "in": ["LARGE", "MID", "SMALL"], "label": "cap_tier"},
            {"column": "final_score", "min": 0, "max": 1, "label": "final score"},
        ],
        "outlier_columns": ["final_score"],
        "natural_key": ["sid", "pick_date"],
    },
    "daily_snapshots": {
        "per_stock": True,
        "critical_columns": ["sid", "snapshot_date"],
        "min_backtest": {"target_days": 365, "minimum_days": 180},
        "natural_key": ["sid", "snapshot_date"],
    },
    "daily_changes": {
        "critical_columns": ["change_date", "change_type", "headline"],
        "validity_checks": [
            {"column": "severity", "in": ["LOW", "MEDIUM", "HIGH", "CRITICAL"], "label": "severity"},
        ],
    },

    # ── Pipeline / Internal ──
    "pipeline_log": {
        "critical_columns": ["run_date", "step_name", "status"],
        "validity_checks": [
            {"column": "status", "in": ["RUNNING", "SUCCESS", "FAILED", "SKIPPED", "ABORTED"], "label": "status"},
        ],
    },
    "sqlite_sequence": {},  # internal — only existence matters
}


# ── Aggregation ──────────────────────────────────────────────────────────────

ALL_FACTORS = [
    factor_freshness,
    factor_completeness,
    factor_coverage,
    factor_null_rate,
    factor_validity,
    factor_type_conformance,
    factor_outliers,
    factor_backtest_sufficiency,
    factor_duplicates,
]


def _meta_for(tbl):
    """Look up registered metadata (frequency, source) for a table."""
    from config import PIPELINE_STEPS, RAW_TABLES
    for s in PIPELINE_STEPS:
        if s.get("table") == tbl:
            return {
                "source": s["source"],
                "frequency": s["frequency"],
                "function": f"{s['module']}.{s['function']}",
            }
    for r in RAW_TABLES:
        if r["table"] == tbl:
            return {
                "source": r["source"],
                "frequency": r["frequency"],
                "function": "—",
            }
    return {"source": "—", "frequency": None, "function": "—"}


def compute_table_health(tbl):
    """Run all applicable factors for one table. Returns aggregated diagnostics."""
    profile = TABLE_PROFILES.get(tbl, {})
    meta = _meta_for(tbl)

    with get_db() as conn:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM [{tbl}]").fetchone()[0]
        except Exception as e:
            return {
                "table": tbl, "score": 0, "grade": "F",
                "grade_color": "var(--red)", "rows": 0,
                "factors": [], "issue_count": 1,
                "fixes": [f"Cannot read table: {type(e).__name__}: {e}"],
                "kind": TABLE_META.get(tbl, {}).get("kind", "—"),
            }

        earliest, latest, span = _table_date_range(conn, tbl)
        dates = {"earliest_date": earliest, "latest_date": latest}

        factors = []
        for fn in ALL_FACTORS:
            try:
                result = fn(tbl, count, dates, meta, profile, conn)
                if result is not None:
                    factors.append(result)
            except Exception as e:
                factors.append(_factor(
                    fn.__name__.replace("factor_", ""), 50, "warn",
                    f"Check failed: {type(e).__name__}: {e}",
                    weight=0.05,
                ))

    # Weighted average across all factors that ran
    total_weight = sum(f["weight"] for f in factors) or 1
    score = sum(f["score"] * f["weight"] for f in factors) / total_weight
    grade_letter, grade_color = grade(score)

    issues = [f for f in factors if f["severity"] in ("warn", "error")]
    fixes = [f["fix"] for f in factors if f.get("fix")]

    return {
        "table": tbl,
        "score": int(round(score)),
        "grade": grade_letter,
        "grade_color": grade_color,
        "rows": count,
        "kind": TABLE_META.get(tbl, {}).get("kind", "—"),
        "factors": factors,
        "issue_count": len(issues),
        "issues": [{"factor": i["name"], "msg": i["message"], "severity": i["severity"]} for i in issues],
        "fixes": fixes,
        "earliest_date": earliest,
        "latest_date": latest,
        "date_span": span,
    }


# ── DB-wide aggregation with TTL cache ───────────────────────────────────────

_HEALTH_CACHE = None
_HEALTH_CACHE_TIME = 0.0
_HEALTH_TTL = 300  # 5 minutes — health checks scan every table, no need to recompute on every page load


def compute_db_health(force=False):
    """Compute health for every table. Cached for 5 minutes.

    Returns:
        {
            "tables":         [<per-table dict>, ...] sorted worst score first,
            "overall_score":  weighted average,
            "overall_grade":  letter,
            "overall_color":  CSS var,
            "total_issues":   sum of warn+error factors across all tables,
            "kind_summary":   {RAW: avg_score, COMPUTED: avg_score, ...},
            "computed_at":    ISO timestamp,
        }
    """
    global _HEALTH_CACHE, _HEALTH_CACHE_TIME
    now = time.time()
    if not force and _HEALTH_CACHE is not None and (now - _HEALTH_CACHE_TIME) < _HEALTH_TTL:
        return _HEALTH_CACHE

    with get_db() as conn:
        tables = [
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        ]

    results = []
    for tbl in tables:
        try:
            results.append(compute_table_health(tbl))
        except Exception as e:
            results.append({
                "table": tbl, "score": 0, "grade": "F", "grade_color": "var(--red)",
                "rows": 0, "kind": "—", "factors": [], "issue_count": 1,
                "issues": [{"factor": "system", "msg": f"Health check crashed: {e}", "severity": "error"}],
                "fixes": [f"Health check crashed: {type(e).__name__}: {e}"],
            })

    # Sort worst first
    results.sort(key=lambda r: r["score"])

    overall_score = sum(r["score"] for r in results) / len(results) if results else 0
    overall_grade, overall_color = grade(overall_score)

    # Per-kind summary
    by_kind = {}
    for r in results:
        by_kind.setdefault(r["kind"], []).append(r["score"])
    kind_summary = {k: round(sum(v) / len(v), 1) for k, v in by_kind.items() if v}

    payload = {
        "tables": results,
        "overall_score": int(round(overall_score)),
        "overall_grade": overall_grade,
        "overall_color": overall_color,
        "total_issues": sum(r["issue_count"] for r in results),
        "kind_summary": kind_summary,
        "computed_at": datetime.now().isoformat(timespec="seconds"),
    }

    _HEALTH_CACHE = payload
    _HEALTH_CACHE_TIME = now
    return payload


def invalidate_health_cache():
    """Force the next compute_db_health() call to recompute from scratch."""
    global _HEALTH_CACHE
    _HEALTH_CACHE = None


# ── CLI quick-test ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    print("Computing health for all tables...")
    h = compute_db_health(force=True)
    print(f"\nOverall: {h['overall_score']} ({h['overall_grade']})")
    print(f"Total issues: {h['total_issues']}")
    print(f"Kind summary: {h['kind_summary']}")
    print()
    print("=== Worst 10 tables ===")
    for r in h["tables"][:10]:
        print(f"  {r['score']:>3}  {r['grade']:<3}  {r['table']:<25} {r['issue_count']} issues")
        for f in r["factors"]:
            if f["severity"] != "ok":
                print(f"      [{f['severity']:5}] {f['name']:<20} {f['score']:>3} — {f['message']}")
                if f.get("fix"):
                    print(f"               fix: {f['fix']}")
