"""
Unified Health Score (UHS) — Plan 0007 Phase 1.

One number per entity (0-100 percentage). Five universal dimensions of 0-20 each.
Single source of truth for "is this entity trustworthy right now?". Replaces
11+ disparate quality vocabularies (weight_coverage, eligible_coverage,
TRUSTED/WOUND_UP/SEGREGATED, KEEP/WEAK/DROP, CRITICAL/WARN/INFO, ...) with one
number + one colour code.

ENTITY KINDS
    datum   — one row of source data (sid + source_table + source_key + date)
    factor  — one signal module (e.g. "piotroski_f_score")
    pick    — one daily_picks row (entity_id = "<sid>|<pick_date>")
    table   — one DB table
    system  — overall (geometric mean of tier-1 critical tables)

DIMENSIONS (0-20 each)
    Provenance     — known source + identity-verified (Gates 1, 6)
    Freshness      — within expected refresh cadence (existing data_health + Gate 4)
    Plausibility   — within domain prior for class (Gate 2) — Phase 3+
    Consistency    — agrees with peers, prior values, cross-sources (Gates 3, 4, 5)
    Coverage       — complete relative to expected inputs (eligibility + Gate 6)

LABELS (based on score_pct = score_total / score_max × 100)
    UNKNOWN      — no dimensions evaluated (score_pct is NULL)
    AVOID        — score_pct < 60
    REVIEW       — 60 ≤ score_pct < 80
    PRELIMINARY  — score_pct ≥ 80 but some dims NULL (gates from a later phase
                   aren't live yet — score is the user-facing number but isn't
                   final). Distinguishes a Phase 1 entity from a fully-evaluated one.
    TRUSTED      — score_pct ≥ 80 AND all 5 dims populated

ROLL-UP RULE (uniform across entity kinds)
    UHS(datum)   = sum of 5 dims, normalised to 100
    UHS(factor)  = weight_coverage-weighted mean of UHS(input data)
    UHS(pick)    = signal_weight-weighted mean of UHS(factor) for the SID
    UHS(table)   = median UHS of rows
    UHS(system)  = geometric mean of UHS for tier-1 critical tables

In Phase 1 only 3 of 5 dims are populated (provenance, freshness, coverage);
plausibility (Phase 3) and consistency (Phase 4) land later. Until then,
score_pct is over those 3 and `label` is PRELIMINARY for any ≥80.

Plan: docs/plans/0007-trust-pipeline-uhs.md
"""

import json
import math
from datetime import date as _date
from typing import Optional

import pandas as pd

from db import read_sql, upsert_df


# ── Tier-1 critical tables: used for system-level UHS geometric mean. ──
# These are the tables whose failure would compromise every downstream pick.
# Keep this list short — additions change the system-score's denominator and
# rebaseline historic readings.
TIER_1_CRITICAL_TABLES = [
    "stock_prices",
    "stocks",
    "daily_picks",
    "daily_snapshots",
    "analyst_consensus",
    "quarterly_income",
    "consensus_signals",
    "piotroski_scores",
]


# ── Wired factors in the production screener (Phase 1 backfill scope). ──
# Pulled from scoring/screener.SIGNAL_COLS. Hardcoded here to avoid an import
# cycle (screener imports config; this file is consumed by cockpit/api which
# is in a different layer).
WIRED_FACTORS = [
    "consensus",
    "earnings_yield",
    "accruals",
    "piotroski",
    "momentum",
    "book_to_price",
    "promoter",
    "smart_money",
    "pt_upside",
    "eps_growth",
    "pledge_quality",
    "delivery_anomaly_z",
]


# ── Per-table refresh-cadence in days (for the Freshness dim). ──
# Score: 20 if age ≤ threshold, scales linearly down to 0 at 3× threshold.
FRESHNESS_THRESHOLDS_DAYS = {
    "stock_prices":          1,
    "daily_picks":           1,
    "daily_snapshots":       1,
    "analyst_consensus":     7,
    "consensus_signals":     1,
    "piotroski_scores":      30,
    "quarterly_income":     90,
    "annual_balance_sheet": 365,
    "annual_cash_flow":     365,
    "banking_metrics":       30,
    "shareholding":          90,
    "mf_nav_history":         1,
    "mf_scheme_master":       7,
}


# ── Score → label mapping ──
def _label(score_pct: Optional[int], all_dims_populated: bool) -> str:
    if score_pct is None:
        return "UNKNOWN"
    if score_pct < 60:
        return "AVOID"
    if score_pct < 80:
        return "REVIEW"
    return "TRUSTED" if all_dims_populated else "PRELIMINARY"


def compute_uhs(
    entity_kind: str,
    entity_id: str,
    snapshot_date: str,
    dim_provenance: Optional[int] = None,
    dim_freshness: Optional[int] = None,
    dim_plausibility: Optional[int] = None,
    dim_consistency: Optional[int] = None,
    dim_coverage: Optional[int] = None,
    reasons: Optional[dict] = None,
) -> dict:
    """Build a UHS row dict. NULL dims are not penalised (score_max shrinks).

    Returns a dict matching the health_score table schema, ready for upsert_df.
    Caller is responsible for the persist step (so tests can build rows without DB).
    """
    dims = {
        "dim_provenance":   dim_provenance,
        "dim_freshness":    dim_freshness,
        "dim_plausibility": dim_plausibility,
        "dim_consistency":  dim_consistency,
        "dim_coverage":     dim_coverage,
    }
    present = {k: v for k, v in dims.items() if v is not None}
    if present:
        score_total = sum(present.values())
        score_max = 20 * len(present)
        score_pct = round(100 * score_total / score_max)
    else:
        score_total = None
        score_max = None
        score_pct = None
    all_populated = all(v is not None for v in dims.values())
    return {
        "entity_kind":      entity_kind,
        "entity_id":        entity_id,
        "snapshot_date":    snapshot_date,
        "dim_provenance":   dim_provenance,
        "dim_freshness":    dim_freshness,
        "dim_plausibility": dim_plausibility,
        "dim_consistency":  dim_consistency,
        "dim_coverage":     dim_coverage,
        "score_total":      score_total,
        "score_max":        score_max,
        "score_pct":        score_pct,
        "label":            _label(score_pct, all_populated),
        "reasons_json":     json.dumps(reasons or {}, ensure_ascii=False),
    }


def write_uhs(rows: list[dict]) -> int:
    """Persist a batch of UHS rows. Returns rows written."""
    if not rows:
        return 0
    df = pd.DataFrame(rows)
    return upsert_df(df, "health_score")


# ── Phase 1/3 dim computers ──
# Each returns (score_0_to_20, reason_string) or (None, reason).
# Phase 1 ships provenance/freshness/coverage; Phase 3 adds plausibility + consistency
# from trust_verdicts.gate_2_plausibility + gate_3_temporal pass-rates.


# Map factor → source_tables relevant for plausibility/consistency rollup.
# Used by dim_plausibility_for_factor / dim_consistency_for_factor to count
# pass vs fail per gate within the factor's upstream data scope.
FACTOR_UPSTREAM_TABLES = {
    "consensus":          ["consensus_signals", "analyst_consensus", "broker_recommendations"],
    "earnings_yield":     ["stock_prices", "quarterly_income"],
    "accruals":           ["annual_cash_flow", "annual_balance_sheet"],
    "piotroski":          ["quarterly_income", "annual_balance_sheet", "annual_cash_flow"],
    "momentum":           ["stock_prices"],
    "book_to_price":      ["annual_balance_sheet", "stock_prices"],
    "promoter":           [],   # shareholding — no quarantine table yet
    "smart_money":        ["stock_prices"],
    "pt_upside":          ["consensus_signals"],
    "eps_growth":         ["consensus_signals", "quarterly_income"],
    "pledge_quality":     [],   # shareholding
    "delivery_anomaly_z": ["stock_prices"],
}


def dim_provenance_for_factor(factor_id: str) -> tuple[Optional[int], str]:
    """Score from lineage.FACTOR_LINEAGE presence. Binary 0 or 20 in Phase 1.

    Phase 6 will refine this by also checking trust_verdicts.gate_1_identity
    pass-rate for the factor's upstream data rows.
    """
    try:
        from lineage import FACTOR_LINEAGE, get_factor_lineage
        if factor_id in FACTOR_LINEAGE:
            return 20, "registered in FACTOR_LINEAGE"
        # Some factor_ids in WIRED_FACTORS use short names; check via mapping
        # (e.g. "piotroski" → "piotroski_f_score" in the registry)
        registry_alias = {
            "consensus": "consensus_signal_combined",
            "earnings_yield": "earnings_yield",
            "accruals": "cf_accruals_ratio",
            "piotroski": "piotroski_f_score",
            "momentum": "mom_12m_adj",
            "book_to_price": "book_to_price",
            "promoter": "promoter_qoq",
            "smart_money": "avg_delivery_pct_30d",
            "pt_upside": "pt_upside",
            "eps_growth": "eps_growth_yoy",
            "pledge_quality": "pledge_quality",
            "delivery_anomaly_z": "delivery_anomaly_z",
        }
        if factor_id in registry_alias and registry_alias[factor_id] in FACTOR_LINEAGE:
            return 20, f"registered (alias → {registry_alias[factor_id]})"
        return 0, "no FACTOR_LINEAGE entry"
    except Exception as e:
        return None, f"lookup failed: {e}"


def dim_freshness_for_table(table: str, age_days: Optional[float]) -> tuple[Optional[int], str]:
    """Score from age in days vs declared threshold.

    20 if age ≤ threshold; 0 if age ≥ 3 × threshold; linear in between.
    """
    threshold = FRESHNESS_THRESHOLDS_DAYS.get(table)
    if threshold is None or age_days is None:
        return None, f"no threshold for table='{table}' or age unknown"
    if age_days <= threshold:
        return 20, f"fresh ({age_days}d ≤ {threshold}d threshold)"
    if age_days >= 3 * threshold:
        return 0, f"stale ({age_days}d ≥ 3× {threshold}d threshold)"
    # Linear scale between threshold and 3×threshold
    score = round(20 * (1 - (age_days - threshold) / (2 * threshold)))
    return max(0, min(20, int(score))), f"degraded ({age_days}d, threshold {threshold}d)"


def _gate_pass_rate(gate_col: str, tables: list[str], snapshot_date: str,
                     lookback_days: int = 7) -> Optional[float]:
    """Compute pass-rate of a trust_verdicts gate over a recent window.

    Returns fraction in [0, 1] or None if no rows in window.
    """
    if not tables:
        return None
    placeholders = ",".join("?" * len(tables))
    df = read_sql(
        f"""
        SELECT {gate_col} AS gate, COUNT(*) AS n
        FROM trust_verdicts
        WHERE source_table IN ({placeholders})
          AND snapshot_date >= date(?, '-{lookback_days} days')
          AND snapshot_date <= ?
          AND {gate_col} IS NOT NULL
        GROUP BY {gate_col}
        """,
        params=tables + [snapshot_date, snapshot_date],
    )
    if df.empty:
        return None
    total = df["n"].sum()
    pass_count = int(df.loc[df["gate"] == 1, "n"].sum())
    return pass_count / total if total > 0 else None


def dim_plausibility_for_factor(factor_id: str, snapshot_date: str) -> tuple[Optional[int], str]:
    """Phase 3: pass-rate of gate_2_plausibility over the factor's upstream tables.

    Returns None if no upstream rows have a verdict yet (gate not wired for
    those tables). When rows exist, maps fraction f → score: f=1.0 → 20;
    f=0.0 → 0; linear.
    """
    tables = FACTOR_UPSTREAM_TABLES.get(factor_id, [])
    if not tables:
        return None, "no upstream tables registered in FACTOR_UPSTREAM_TABLES"
    rate = _gate_pass_rate("gate_2_plausibility", tables, snapshot_date)
    if rate is None:
        return None, f"no gate_2 verdicts in last 7d for tables {tables}"
    score = int(round(20 * rate))
    return max(0, min(20, score)), f"gate_2 pass-rate {rate*100:.1f}% over {tables}"


def dim_consistency_for_factor(factor_id: str, snapshot_date: str) -> tuple[Optional[int], str]:
    """Phase 3+4: average pass-rate across gates 3 (temporal), 4 (cross-source),
    and 5 (unit-contract) over the factor's upstream tables.

    Each gate contributes equally; a gate with no verdicts is dropped from the
    average (so a factor with only gate_3 data still gets a score). Returns
    None only if NONE of the three gates have verdicts.
    """
    tables = FACTOR_UPSTREAM_TABLES.get(factor_id, [])
    if not tables:
        return None, "no upstream tables registered in FACTOR_UPSTREAM_TABLES"

    gates = [
        ("gate_3_temporal",     "g3"),
        ("gate_4_cross_source", "g4"),
        ("gate_5_unit",         "g5"),
        ("gate_7_anchor",       "g7"),   # Plan 0007 Phase 6 — external anchor
    ]
    rates = {}
    for col, key in gates:
        r = _gate_pass_rate(col, tables, snapshot_date)
        if r is not None:
            rates[key] = r
    if not rates:
        return None, f"no gate_3/4/5 verdicts in last 7d for tables {tables}"
    avg = sum(rates.values()) / len(rates)
    score = int(round(20 * avg))
    detail = ", ".join(f"{k}={r*100:.0f}%" for k, r in rates.items())
    return max(0, min(20, score)), f"consistency avg {avg*100:.1f}% ({detail}) over {tables}"


def dim_coverage_for_factor(factor_id: str, snapshot_date: str) -> tuple[Optional[int], str]:
    """Score from universe_eligibility.eligible / universe size on snapshot_date.

    Maps eligible fraction f → score: f≥0.95 → 20; f≤0.30 → 0; linear between.
    """
    df = read_sql(
        """
        SELECT SUM(eligible) AS n_elig, COUNT(*) AS n_total
        FROM universe_eligibility
        WHERE signal = ? AND snapshot_date = (
            SELECT MAX(snapshot_date) FROM universe_eligibility WHERE snapshot_date <= ?
        )
        """,
        params=[factor_id, snapshot_date],
    )
    if df.empty or df.iloc[0]["n_total"] is None or df.iloc[0]["n_total"] == 0:
        return None, "no universe_eligibility data"
    n_elig = float(df.iloc[0]["n_elig"] or 0)
    n_total = float(df.iloc[0]["n_total"])
    f = n_elig / n_total
    if f >= 0.95:
        return 20, f"coverage {f*100:.1f}%"
    if f <= 0.30:
        return 0, f"coverage {f*100:.1f}% (≤30%)"
    score = round(20 * (f - 0.30) / (0.95 - 0.30))
    return max(0, min(20, int(score))), f"coverage {f*100:.1f}%"


# ── Roll-ups ──

def rollup_factor_uhs(factor_id: str, snapshot_date: str) -> dict:
    """Compute UHS for one factor as of snapshot_date.

    Phases 1+3 active: provenance, freshness, coverage (Phase 1) +
    plausibility, consistency (Phase 3). Each returns None if its source
    data isn't available; NULL dims drop out of score_max so the label
    distinguishes PRELIMINARY from TRUSTED.
    """
    prov_score, prov_reason = dim_provenance_for_factor(factor_id)
    cov_score, cov_reason = dim_coverage_for_factor(factor_id, snapshot_date)
    plaus_score, plaus_reason = dim_plausibility_for_factor(factor_id, snapshot_date)
    cons_score, cons_reason = dim_consistency_for_factor(factor_id, snapshot_date)
    # Freshness for a factor = freshness of its primary upstream table.
    factor_table_map = {
        "consensus": "consensus_signals",
        "earnings_yield": "stock_prices",
        "accruals": "annual_cash_flow",
        "piotroski": "piotroski_scores",
        "momentum": "stock_prices",
        "book_to_price": "annual_balance_sheet",
        "promoter": "shareholding",
        "smart_money": "stock_prices",
        "pt_upside": "consensus_signals",
        "eps_growth": "consensus_signals",
        "pledge_quality": "shareholding",
        "delivery_anomaly_z": "stock_prices",
    }
    primary_table = factor_table_map.get(factor_id)
    fresh_score, fresh_reason = None, "no upstream table mapped"
    if primary_table:
        age = _table_age_days(primary_table, as_of=snapshot_date)
        fresh_score, fresh_reason = dim_freshness_for_table(primary_table, age)
    return compute_uhs(
        entity_kind="factor",
        entity_id=factor_id,
        snapshot_date=snapshot_date,
        dim_provenance=prov_score,
        dim_freshness=fresh_score,
        dim_coverage=cov_score,
        dim_plausibility=plaus_score,
        dim_consistency=cons_score,
        reasons={
            "provenance": prov_reason,
            "freshness": fresh_reason,
            "coverage": cov_reason,
            "plausibility": plaus_reason,
            "consistency": cons_reason,
        },
    )


def rollup_table_uhs(table: str, snapshot_date: str) -> dict:
    """UHS for a table. Phase 1: freshness only (plausibility + consistency
    arrive in Phase 3+4; coverage + provenance are factor-level concerns)."""
    age = _table_age_days(table, as_of=snapshot_date)
    fresh_score, fresh_reason = dim_freshness_for_table(table, age)
    return compute_uhs(
        entity_kind="table",
        entity_id=table,
        snapshot_date=snapshot_date,
        dim_freshness=fresh_score,
        reasons={
            "freshness": fresh_reason,
            "provenance": "Phase 6 — anchor verification not yet live",
            "plausibility": "phase_3_pending",
            "consistency": "phase_4_pending",
            "coverage": "row-count gate Phase 5+",
        },
    )


def rollup_system_uhs(snapshot_date: str) -> dict:
    """System-level UHS = geometric mean of tier-1 critical tables' score_pct.

    Geometric mean (vs arithmetic) ensures a single broken critical table drags
    the whole score sharply down — no hiding behind averages.
    """
    rows = []
    for table in TIER_1_CRITICAL_TABLES:
        u = rollup_table_uhs(table, snapshot_date)
        rows.append(u)
    pcts = [r["score_pct"] for r in rows if r["score_pct"] is not None]
    if not pcts:
        score_pct = None
        reasons = {"geometric_mean": "no tier-1 tables had a score_pct"}
    else:
        product = 1.0
        for p in pcts:
            product *= max(p, 1)  # avoid 0 collapsing the product entirely
        score_pct = round(product ** (1.0 / len(pcts)))
        reasons = {
            "geometric_mean": f"over {len(pcts)} tier-1 tables",
            "table_scores": {r["entity_id"]: r["score_pct"] for r in rows},
        }
    # Build a synthetic UHS row — the system score is the score_pct directly.
    return {
        "entity_kind":      "system",
        "entity_id":        "SYSTEM",
        "snapshot_date":    snapshot_date,
        "dim_provenance":   None,
        "dim_freshness":    None,
        "dim_plausibility": None,
        "dim_consistency":  None,
        "dim_coverage":     None,
        "score_total":      score_pct,
        "score_max":        100,
        "score_pct":        score_pct,
        "label":            _label(score_pct, all_dims_populated=False),
        "reasons_json":     json.dumps(reasons, ensure_ascii=False),
    }


def rollup_pick_uhs(sid: str, pick_date: str) -> dict:
    """UHS for one daily_picks row = signal_weight-weighted mean of factor UHS
    for the factors that actually contributed to this pick's tier.

    Phase 1 reads the production SIGNAL_WEIGHTS (not variants). Phase 5 will
    extend this with the per-row weight_coverage adjustment.
    """
    # Fetch the pick row to know its tier
    df = read_sql(
        "SELECT cap_tier FROM daily_picks WHERE sid=? AND pick_date=?",
        params=[sid, pick_date],
    )
    if df.empty:
        return compute_uhs("pick", f"{sid}|{pick_date}", pick_date)
    tier = df.iloc[0]["cap_tier"]
    from config import SIGNAL_WEIGHTS
    weights = SIGNAL_WEIGHTS.get(tier, {})
    if not weights:
        return compute_uhs("pick", f"{sid}|{pick_date}", pick_date)
    # Read each factor's UHS row for this snapshot_date
    factor_ids = list(weights.keys())
    placeholders = ",".join("?" * len(factor_ids))
    fdf = read_sql(
        f"""
        SELECT entity_id,
               dim_provenance, dim_freshness, dim_plausibility,
               dim_consistency, dim_coverage, score_pct
        FROM health_score
        WHERE entity_kind='factor'
          AND entity_id IN ({placeholders})
          AND snapshot_date = (
              SELECT MAX(snapshot_date) FROM health_score
              WHERE entity_kind='factor' AND snapshot_date <= ?
          )
        """,
        params=factor_ids + [pick_date],
    )
    if fdf.empty:
        return compute_uhs("pick", f"{sid}|{pick_date}", pick_date,
                           reasons={"weight_mean": "no factor UHS rows available"})
    fmap = {r["entity_id"]: r for _, r in fdf.iterrows()}

    # Per-dim weighted means — track each dim's numerator + denominator
    # independently so factors with one dim NULL don't poison the others.
    def _wmean(dim_col: str) -> Optional[int]:
        num = 0.0
        den = 0.0
        for fid, w in weights.items():
            if fid not in fmap:
                continue
            v = fmap[fid][dim_col]
            if pd.notna(v):
                num += w * float(v)
                den += w
        if den == 0:
            return None
        return int(round(num / den))

    n_contributing = sum(1 for f in weights if f in fmap)
    if n_contributing == 0:
        return compute_uhs("pick", f"{sid}|{pick_date}", pick_date)
    return compute_uhs(
        entity_kind="pick",
        entity_id=f"{sid}|{pick_date}",
        snapshot_date=pick_date,
        dim_provenance=_wmean("dim_provenance"),
        dim_freshness=_wmean("dim_freshness"),
        dim_plausibility=_wmean("dim_plausibility"),
        dim_consistency=_wmean("dim_consistency"),
        dim_coverage=_wmean("dim_coverage"),
        reasons={
            "weight_mean": f"across {n_contributing} factors of {len(weights)} weighted",
            "tier": tier,
        },
    )


# ── Helpers ──

_DATE_COL_BY_TABLE = {
    "stock_prices":          "date",
    "stocks":                "updated_at",
    "daily_picks":           "pick_date",
    "daily_snapshots":       "snapshot_date",
    "analyst_consensus":     "fetched_at",
    "consensus_signals":     "snapshot_date",
    "piotroski_scores":      "snapshot_date",
    "quarterly_income":      "end_date",
    "annual_balance_sheet":  "end_date",
    "annual_cash_flow":      "end_date",
    "banking_metrics":       "period_end",
    "shareholding":          "as_of_date",
    "mf_nav_history":        "nav_date",
    "mf_scheme_master":      "last_seen",
}


def _table_age_days(table: str, as_of: Optional[str] = None) -> Optional[float]:
    """Days between as_of (default = today) and most recent row ≤ as_of.

    Reads the appropriate date column per table. Caller treats None as
    "couldn't determine — Freshness dim returns NULL".
    """
    col = _DATE_COL_BY_TABLE.get(table)
    if not col:
        return None
    as_of_ts = pd.Timestamp(as_of) if as_of else pd.Timestamp.utcnow().tz_localize(None)
    try:
        df = read_sql(
            f"SELECT MAX({col}) AS d FROM {table} WHERE {col} <= ?",
            params=[as_of_ts.strftime("%Y-%m-%d %H:%M:%S")],
        )
        if df.empty or df.iloc[0]["d"] is None:
            return None
        latest = pd.to_datetime(df.iloc[0]["d"])
        if latest.tz is not None:
            latest = latest.tz_localize(None)
        return (as_of_ts - latest).days
    except Exception:
        return None


# ── Read helpers (consumed by cockpit) ──

def get_uhs(entity_kind: str, entity_id: str) -> Optional[dict]:
    """Most recent UHS row for an entity, or None."""
    df = read_sql(
        """
        SELECT * FROM health_score
        WHERE entity_kind=? AND entity_id=?
        ORDER BY snapshot_date DESC LIMIT 1
        """,
        params=[entity_kind, entity_id],
    )
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def get_factor_uhs_summary() -> pd.DataFrame:
    """Latest UHS for every wired factor — used by cockpit /system and /model pages."""
    placeholders = ",".join("?" * len(WIRED_FACTORS))
    return read_sql(
        f"""
        SELECT h.*
        FROM health_score h
        WHERE h.entity_kind='factor'
          AND h.entity_id IN ({placeholders})
          AND h.snapshot_date = (
              SELECT MAX(snapshot_date) FROM health_score
              WHERE entity_kind='factor' AND entity_id = h.entity_id
          )
        ORDER BY h.score_pct DESC NULLS LAST
        """,
        params=WIRED_FACTORS,
    )


# ── CLI ──

def _compute_snapshot_rows(snapshot_date: str, include_picks: bool = False) -> list[dict]:
    """All UHS rows for a single snapshot_date — factors + tables + system + (optional) picks."""
    rows = []
    for fid in WIRED_FACTORS:
        rows.append(rollup_factor_uhs(fid, snapshot_date))
    for tbl in TIER_1_CRITICAL_TABLES:
        rows.append(rollup_table_uhs(tbl, snapshot_date))
    rows.append(rollup_system_uhs(snapshot_date))
    if include_picks:
        # Pick UHS depends on factor UHS for the same snapshot — write factors first
        # so the read at pick rollup time finds them. write_uhs([factors]) before
        # invoking rollup_pick_uhs.
        write_uhs([r for r in rows if r["entity_kind"] == "factor"])
        picks_df = read_sql(
            "SELECT sid, pick_date FROM daily_picks WHERE pick_date=?",
            params=[snapshot_date],
        )
        for _, r in picks_df.iterrows():
            rows.append(rollup_pick_uhs(r["sid"], r["pick_date"]))
    return rows


def compute(snapshot_date: Optional[str] = None, include_picks: bool = True,
            dry_run: bool = False) -> int:
    """Pipeline entry point. Writes today's UHS for factors + tables + system + picks.

    Called from PIPELINE_STEPS as `compute_health_score`. Non-critical: UHS is
    observation, not a gate. Returns rows written.
    """
    d = snapshot_date or _date.today().isoformat()
    rows = _compute_snapshot_rows(d, include_picks=include_picks)
    if dry_run:
        print(f"Dry-run: would write {len(rows)} rows for {d}")
        return len(rows)
    n = write_uhs(rows)
    print(f"Wrote {n} health_score rows for {d} ({len(rows)} computed; picks included={include_picks})")
    return n


def main():
    """Compute UHS for wired factors + tier-1 tables + system + (optionally) picks.

    Default: just today's snapshot. `--backfill-days N` rolls through the last N
    days, computing each historic snapshot using as-of-that-date data state
    (tables use only rows with date_col ≤ snapshot_date, eligibility uses the
    most-recent universe_eligibility row ≤ snapshot_date).
    """
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=_date.today().isoformat())
    parser.add_argument("--backfill-days", type=int, default=0,
                        help="If >0, backfill N days ending at --date (inclusive)")
    parser.add_argument("--include-picks", action="store_true",
                        help="Also write pick-level UHS rows (requires --date to have daily_picks)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target_dates = (
        [(pd.Timestamp(args.date) - pd.Timedelta(days=i)).strftime("%Y-%m-%d")
         for i in range(args.backfill_days, -1, -1)]
        if args.backfill_days > 0
        else [args.date]
    )

    all_rows = []
    for d in target_dates:
        rows = _compute_snapshot_rows(d, include_picks=args.include_picks)
        all_rows.extend(rows)
        # Per-date summary
        n_avoid = sum(1 for r in rows if r["label"] == "AVOID")
        n_review = sum(1 for r in rows if r["label"] == "REVIEW")
        n_trusted = sum(1 for r in rows if r["label"] in ("TRUSTED", "PRELIMINARY"))
        print(f"  {d}: {len(rows)} rows · {n_trusted} trusted · {n_review} review · {n_avoid} avoid")

    if args.dry_run:
        print(f"\nDry-run: would write {len(all_rows)} rows.")
        return

    n = write_uhs(all_rows)
    print(f"\nWrote {n} rows to health_score.")


if __name__ == "__main__":
    main()
