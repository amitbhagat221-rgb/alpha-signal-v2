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

import factors
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


# ── Wired factors in the production screener: every weight key carrying a nonzero
# config.SIGNAL_WEIGHTS weight in some tier. Derived, so pick trust scores roll up
# over exactly the factors that score the pick (a hand-kept copy here drifted: it
# still listed pulled pt_upside and missed four wired factors).
WIRED_FACTORS = factors.wired_weight_keys()


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
    "fno_iv_history":         1,
    "bse_announcements":      1,
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
# Used by dim_plausibility_for_factor / dim_consistency_for_factor (per-factor)
# AND by rollup_pick_uhs's per-sid gate union to count pass vs fail per gate
# within the factor's upstream data scope.
#
# ADR 0037 follow-up (2026-06-02): these must point at the tables that actually
# CARRY trust_verdicts — the DERIVED tables — not the raw upstream financials.
# trust_verdicts.source_table only ever holds: analyst_consensus, consensus_signals,
# stock_prices, piotroski_scores, broker_recommendations, banking_metrics, mf_holdings.
# Raw tables (quarterly_income, annual_balance_sheet, annual_cash_flow) carry ZERO
# verdicts, so mapping a factor to them yielded no per-sid gate rows → the pick's
# plausibility/consistency dims silently fell back to the universe mean. The worst
# offender was the fundamental side: `piotroski_scores` holds a per-sid gate_2
# plausibility verdict for ~1,979 stocks, but the `piotroski` factor pointed at
# raw quarterly/annual tables, so fundamental-data plausibility never reached any
# pick UHS — the dim was driven only by `consensus_signals` (analyst data), and
# fell back to the mean for the 734/1,440 analyst-thin SMALL picks with no
# consensus row. Pointing the fundamental factors at `piotroski_scores` (the
# per-sid fundamental-plausibility verdict, same quarterly/annual inputs) closes
# that gap for every tier. Per-factor values live in factors.FACTORS["uhs_tables"].
FACTOR_UPSTREAM_TABLES = {
    k: factors.FACTORS[sid]["uhs_tables"]
    for k, sid in factors.WEIGHT_KEY_TO_SIGNAL.items() if "uhs_tables" in factors.FACTORS[sid]
}
# Primary upstream table per factor, for the Freshness dim.
FACTOR_FRESHNESS_TABLE = {
    k: factors.FACTORS[sid]["freshness_table"]
    for k, sid in factors.WEIGHT_KEY_TO_SIGNAL.items() if "freshness_table" in factors.FACTORS[sid]
}


def dim_provenance_for_factor(factor_id: str) -> tuple[Optional[int], str]:
    """Score from lineage.FACTOR_LINEAGE presence. Binary 0 or 20 in Phase 1.

    Phase 6 will refine this by also checking trust_verdicts.gate_1_identity
    pass-rate for the factor's upstream data rows.
    """
    try:
        from lineage import FACTOR_LINEAGE
        if factor_id in FACTOR_LINEAGE:
            return 20, "registered in FACTOR_LINEAGE"
        # WIRED_FACTORS use weight-key short names ("piotroski" → "piotroski_f_score")
        alias = factors.signal_for(factor_id)
        if alias in FACTOR_LINEAGE:
            return 20, f"registered (alias → {alias})"
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
                     lookback_days: int = 7, sid: Optional[str] = None) -> Optional[float]:
    """Compute pass-rate of a trust_verdicts gate over a recent window.

    When `sid` is given, restrict to THAT stock's verdicts (per-stock UHS);
    otherwise compute the universe-wide rate (legacy factor-level behaviour).
    Returns fraction in [0, 1] or None if no rows in window.
    """
    if not tables:
        return None
    placeholders = ",".join("?" * len(tables))
    sid_clause = " AND sid = ?" if sid else ""
    df = read_sql(
        f"""
        SELECT {gate_col} AS gate, COUNT(*) AS n
        FROM trust_verdicts
        WHERE source_table IN ({placeholders})
          AND snapshot_date >= date(?, '-{lookback_days} days')
          AND snapshot_date <= ?
          AND {gate_col} IS NOT NULL{sid_clause}
        GROUP BY {gate_col}
        """,
        params=tables + [snapshot_date, snapshot_date] + ([sid] if sid else []),
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
    primary_table = FACTOR_FRESHNESS_TABLE.get(factor_id)
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


_PICK_GATES = ("gate_1_identity", "gate_2_plausibility", "gate_3_temporal",
               "gate_4_cross_source", "gate_5_unit", "gate_7_anchor")
_FACTOR_DIMS = ("dim_provenance", "dim_freshness", "dim_plausibility",
                "dim_consistency", "dim_coverage", "score_pct")


def _latest_factor_uhs(factor_ids, as_of: str) -> dict:
    """{factor_id: row} of the latest factor UHS snapshot ≤ as_of (one query)."""
    if not factor_ids:
        return {}
    placeholders = ",".join("?" * len(factor_ids))
    fdf = read_sql(
        f"""
        SELECT entity_id, {", ".join(_FACTOR_DIMS)}
        FROM health_score
        WHERE entity_kind='factor'
          AND entity_id IN ({placeholders})
          AND snapshot_date = (
              SELECT MAX(snapshot_date) FROM health_score
              WHERE entity_kind='factor' AND snapshot_date <= ?
          )
        """,
        params=list(factor_ids) + [as_of],
    )
    return {r["entity_id"]: r for r in fdf.to_dict("records")}


def _sid_gate_counts(tables: list[str], snapshot_date: str, sids=None,
                     lookback_days: int = 7) -> dict:
    """{gate_col: DataFrame[sid, source_table, gate, n]} — per-sid verdict counts over
    `tables` in the window, one query per gate (the batched _gate_pass_rate). `sids`
    narrows the scan for small lookups (the cockpit's single-pick call)."""
    out = {}
    if not tables:
        return out
    placeholders = ",".join("?" * len(tables))
    sid_clause, sid_params = "", []
    if sids is not None and len(sids) <= 500:
        sid_clause = f" AND sid IN ({','.join('?' * len(sids))})"
        sid_params = list(sids)
    for gate_col in _PICK_GATES:
        out[gate_col] = read_sql(
            f"""
            SELECT sid, source_table, {gate_col} AS gate, COUNT(*) AS n
            FROM trust_verdicts
            WHERE source_table IN ({placeholders})
              AND snapshot_date >= date(?, '-{lookback_days} days')
              AND snapshot_date <= ?
              AND {gate_col} IS NOT NULL AND sid IS NOT NULL{sid_clause}
            GROUP BY sid, source_table, {gate_col}
            """,
            params=tables + [snapshot_date, snapshot_date] + sid_params,
        )
    return out


def _rate(counts: pd.DataFrame, tables: list[str]) -> Optional[float]:
    """_gate_pass_rate over pre-fetched counts for one sid."""
    c = counts[counts["source_table"].isin(tables)]
    total = c["n"].sum()
    return int(c.loc[c["gate"] == 1, "n"].sum()) / total if total > 0 else None


def rollup_picks_uhs(pick_date: str, sids=None, factor_rows=None) -> dict:
    """UHS for daily_picks rows = signal_weight-weighted mean of factor UHS for
    the factors that score each pick's tier. Returns {sid: UHS row}.

    Batched: three reads for the whole pick set instead of ~8 per pick. `sids`
    restricts to those picks (default: every pick on pick_date). `factor_rows`
    (list of factor UHS dicts) replaces the health_score read — for callers that
    just computed them. Phase 1 reads the production SIGNAL_WEIGHTS (not variants).
    """
    picks = read_sql("SELECT sid, cap_tier FROM daily_picks WHERE pick_date=?", params=[pick_date])
    tier_of = dict(zip(picks["sid"], picks["cap_tier"]))
    sids = list(tier_of) if sids is None else list(sids)
    from config import SIGNAL_WEIGHTS
    all_keys = sorted({k for t in tier_of.values() for k in SIGNAL_WEIGHTS.get(t, {})})
    if factor_rows is None:
        fmap_all = _latest_factor_uhs(all_keys, pick_date)
    else:
        fmap_all = {r["entity_id"]: r for r in factor_rows if r["entity_kind"] == "factor"}
    up_tables_all = sorted({t for k in all_keys for t in FACTOR_UPSTREAM_TABLES.get(k, [])})
    gate_counts = _sid_gate_counts(up_tables_all, pick_date, sids) if fmap_all else {}
    by_sid = {g: dict(tuple(df.groupby("sid"))) for g, df in gate_counts.items()}
    empty = pd.DataFrame(columns=["sid", "source_table", "gate", "n"])

    out = {}
    for sid in sids:
        tier = tier_of.get(sid)
        weights = SIGNAL_WEIGHTS.get(tier, {}) if tier is not None else {}
        if not weights:
            out[sid] = compute_uhs("pick", f"{sid}|{pick_date}", pick_date)
            continue
        fmap = {k: fmap_all[k] for k in weights if k in fmap_all}
        if not fmap:
            out[sid] = compute_uhs("pick", f"{sid}|{pick_date}", pick_date,
                                   reasons={"weight_mean": "no factor UHS rows available"})
            continue
        out[sid] = _pick_uhs(sid, pick_date, tier, weights, fmap,
                             {g: by_sid[g].get(sid, empty) for g in by_sid})
    return out


def _pick_uhs(sid, pick_date, tier, weights, fmap, gate_counts) -> dict:
    # Per-dim weighted means — track each dim's numerator + denominator
    # independently so factors with one dim NULL don't poison the others.
    # |w|: a negative weight (governance_resignation, an inverse signal) is still
    # a factor the pick depends on — a signed weight would shrink the denominator.
    def _wmean(dim_col: str) -> Optional[int]:
        num = 0.0
        den = 0.0
        for fid, w in weights.items():
            if fid not in fmap:
                continue
            v = fmap[fid][dim_col]
            if pd.notna(v):
                num += abs(w) * float(v)
                den += abs(w)
        if den == 0:
            return None
        return int(round(num / den))

    n_contributing = sum(1 for f in weights if f in fmap)

    # Per-STOCK dims: for the verdict-based dimensions (provenance / plausibility
    # / consistency) use THIS sid's own trust_verdicts over the pick's upstream
    # tables, so the badge reflects the individual stock's data quality — not the
    # universe-wide average that made every tier-mate identical. Fall back to the
    # factor-weighted mean when the stock has no per-sid verdict for that gate
    # (keeps coverage broad — no mass-PRELIMINARY). Freshness + coverage stay
    # table/factor-level (a table's recency/completeness isn't per-stock).
    up_tables = sorted({t for fid in weights for t in FACTOR_UPSTREAM_TABLES.get(fid, [])})

    def _sid_rate(gate_col):
        return _rate(gate_counts[gate_col], up_tables) if gate_col in gate_counts else None

    def _sid_dim(gate_col, fallback_dim):
        rate = _sid_rate(gate_col)
        return int(round(20 * rate)) if rate is not None else _wmean(fallback_dim)

    def _sid_consistency():
        rates = [r for r in (_sid_rate(g) for g in
                             ("gate_3_temporal", "gate_4_cross_source", "gate_5_unit", "gate_7_anchor"))
                 if r is not None]
        return int(round(20 * (sum(rates) / len(rates)))) if rates else _wmean("dim_consistency")

    return compute_uhs(
        entity_kind="pick",
        entity_id=f"{sid}|{pick_date}",
        snapshot_date=pick_date,
        dim_provenance=_sid_dim("gate_1_identity", "dim_provenance"),
        dim_freshness=_wmean("dim_freshness"),
        dim_plausibility=_sid_dim("gate_2_plausibility", "dim_plausibility"),
        dim_consistency=_sid_consistency(),
        dim_coverage=_wmean("dim_coverage"),
        reasons={
            "weight_mean": f"across {n_contributing} factors of {len(weights)} weighted",
            "tier": tier,
            "per_sid": f"prov/plaus/consistency from {sid}'s verdicts over {up_tables}",
        },
    )


def rollup_pick_uhs(sid: str, pick_date: str) -> dict:
    """UHS for one daily_picks row (see rollup_picks_uhs)."""
    return rollup_picks_uhs(pick_date, sids=[sid])[sid]


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
    "fno_iv_history":        "trade_date",
    "bse_announcements":     "fetched_at",
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
        # Pick UHS rolls up the factor UHS of the same snapshot — hand the rows just
        # computed straight in (no write-then-read, so --dry-run stays write-free).
        factor_rows = [r for r in rows if r["entity_kind"] == "factor"]
        rows.extend(rollup_picks_uhs(snapshot_date, factor_rows=factor_rows).values())
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
