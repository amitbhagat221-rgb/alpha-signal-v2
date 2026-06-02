"""
Pick-level UHS rollup — Plan 0007 Phase 5.

Each daily_picks row gets a 0-100 UHS score, label, and breakdown surfaced
to the user before sizing capital. Reads health_score for the SID's
contributing factors, applies Gate 6 (lineage completeness) provenance cap,
and computes the per-pick 5-dim UHS.

GATE 6 — LINEAGE COMPLETENESS
    For each factor a pick depends on, check what fraction of the input rows
    referenced by that factor have a matching signal_lineage row. If <80%
    coverage, cap the factor's Provenance dim at 10/20 — telling the user
    "we can't trace where this data came from, treat the pick with caution."

    SMALL caps get a `consensus` waiver per existing eligibility/registry.py
    (consensus isn't ELIGIBLE for SMALL caps without analyst coverage; not
    having lineage for an ineligible signal isn't a Provenance hit).

USAGE
    from scoring.confidence import compute_pick_confidence, batch_write_pick_uhs
    # Compute for one pick:
    u = compute_pick_confidence("RELI", "2026-05-30")
    # Bulk write for today's daily_picks:
    n = batch_write_pick_uhs(pick_date="2026-05-30")

INTEGRATION
    scoring/screener.compute() calls batch_write_pick_uhs after writing
    daily_picks rows. Cockpit /explorer/<sid> reads uhs_score + breakdown
    from daily_picks. Dossier email pulls uhs_label + uhs_worst_dim into
    the per-pick footer.
"""

import json
from datetime import date as _date
from typing import Optional

import pandas as pd

from db import read_sql, get_db
from scoring.health_score import (
    rollup_pick_uhs, compute_uhs, FACTOR_UPSTREAM_TABLES, WIRED_FACTORS,
    _gate_pass_rate,
)


# Minimum lineage coverage for Gate 6 to PASS. Below this, the factor's
# Provenance dim is capped at 10/20 with a warning attached.
GATE_6_LINEAGE_THRESHOLD = 0.80


def lineage_coverage_for_factor(factor_id: str, snapshot_date: str) -> tuple[Optional[float], str]:
    """Fraction of (signal_lineage rows for this factor) over (production picks).

    Reads signal_lineage for the most recent snapshot ≤ snapshot_date. Returns
    None if signal_lineage is empty for the factor (interpretation: lineage
    tracking is gated to top-300 SIDs per ADR 0027 — for factors that don't
    write lineage in this snapshot, treat as "lineage not applicable" not
    "lineage failed").
    """
    # Try canonical factor name first; fall back to short alias.
    alias = {
        "consensus": "consensus_signal_combined",
        "earnings_yield": "earnings_yield",
        "accruals": "cf_accruals_ratio",
        "piotroski": "piotroski_f_score",
        "momentum": "mom_12m_adj",
        "book_to_price": "book_to_price",
        "promoter": "promoter_qoq",
        "smart_money": "smart_money_score",
        "pt_upside": "pt_upside",
        "eps_growth": "eps_growth_yoy",
        "pledge_quality": "pledge_quality",
        "delivery_anomaly_z": "delivery_anomaly_z",
    }
    factor_canonical = alias.get(factor_id, factor_id)

    df = read_sql(
        """
        SELECT COUNT(DISTINCT sid) AS traced
        FROM signal_lineage
        WHERE factor = ?
          AND snapshot_date = (
              SELECT MAX(snapshot_date) FROM signal_lineage
              WHERE factor = ? AND snapshot_date <= ?
          )
        """,
        params=[factor_canonical, factor_canonical, snapshot_date],
    )
    traced = int(df.iloc[0]["traced"] or 0) if not df.empty else 0

    if traced == 0:
        return None, f"no signal_lineage rows for factor '{factor_canonical}' — lineage gating not applied"

    # Denominator: production-pick SIDs at that snapshot
    picks_df = read_sql(
        "SELECT COUNT(DISTINCT sid) AS n FROM daily_picks WHERE pick_date = ?",
        params=[snapshot_date],
    )
    n_picks = int(picks_df.iloc[0]["n"] or 0) if not picks_df.empty else 0
    if n_picks == 0:
        return None, "no daily_picks rows on snapshot date"

    coverage = traced / n_picks
    return coverage, f"{traced} traced / {n_picks} picks = {coverage*100:.1f}%"


def compute_pick_confidence(sid: str, pick_date: str) -> dict:
    """Full per-pick UHS row: 5 dims, score, label, worst dim, breakdown JSON.

    Calls rollup_pick_uhs (Phase 1 base) then applies Gate 6 cap.
    """
    base = rollup_pick_uhs(sid, pick_date)

    # Read the pick's tier so we know which factors are weighted
    df = read_sql("SELECT cap_tier FROM daily_picks WHERE sid=? AND pick_date=?",
                   params=[sid, pick_date])
    if df.empty:
        return base

    tier = df.iloc[0]["cap_tier"]
    from config import SIGNAL_WEIGHTS
    weights = SIGNAL_WEIGHTS.get(tier, {})

    # Gate 6 — lineage completeness check on each weighted factor.
    # SMALL caps get a consensus waiver per existing eligibility registry.
    gate_6_penalties = []
    for fid, w in weights.items():
        if tier == "SMALL" and fid == "consensus":
            continue  # waiver
        coverage, reason = lineage_coverage_for_factor(fid, pick_date)
        if coverage is None:
            continue  # lineage not applicable (factor doesn't write lineage)
        if coverage < GATE_6_LINEAGE_THRESHOLD:
            gate_6_penalties.append({
                "factor": fid, "weight": w, "coverage": coverage, "reason": reason,
            })

    # If Gate 6 fails for any factor, cap dim_provenance at 10
    if gate_6_penalties:
        cur_prov = base.get("dim_provenance")
        if cur_prov is not None and cur_prov > 10:
            base["dim_provenance"] = 10
            # Recompute score_total / score_max / score_pct / label
            base = compute_uhs(
                entity_kind=base["entity_kind"],
                entity_id=base["entity_id"],
                snapshot_date=base["snapshot_date"],
                dim_provenance=base["dim_provenance"],
                dim_freshness=base["dim_freshness"],
                dim_plausibility=base.get("dim_plausibility"),
                dim_consistency=base.get("dim_consistency"),
                dim_coverage=base["dim_coverage"],
                reasons=_merge_reasons_with_gate6(base.get("reasons_json"), gate_6_penalties),
            )

    # Find worst dim
    dim_pairs = [
        ("provenance",   base.get("dim_provenance")),
        ("freshness",    base.get("dim_freshness")),
        ("plausibility", base.get("dim_plausibility")),
        ("consistency",  base.get("dim_consistency")),
        ("coverage",     base.get("dim_coverage")),
    ]
    populated = [(n, v) for n, v in dim_pairs if v is not None]
    worst = min(populated, key=lambda kv: kv[1])[0] if populated else None
    base["uhs_worst_dim"] = worst

    return base


def _merge_reasons_with_gate6(existing_json, gate_6_penalties):
    """Inject gate_6 penalties into the reasons dict."""
    try:
        existing = json.loads(existing_json) if existing_json else {}
    except Exception:
        existing = {}
    existing["gate_6_lineage"] = {
        "policy": f"Provenance capped at 10 when any weighted factor has <{int(GATE_6_LINEAGE_THRESHOLD*100)}% lineage coverage",
        "penalties": gate_6_penalties,
    }
    return existing


def batch_write_pick_uhs(pick_date: Optional[str] = None) -> int:
    """For every daily_picks row on pick_date, compute pick UHS and persist
    to the daily_picks row's uhs_score / uhs_breakdown_json / uhs_label /
    uhs_worst_dim columns.

    Called from scoring/screener.compute() after the daily_picks write.
    """
    pick_date = pick_date or _date.today().isoformat()
    df = read_sql(
        "SELECT sid FROM daily_picks WHERE pick_date = ?",
        params=[pick_date],
    )
    if df.empty:
        print(f"  No daily_picks rows for {pick_date}; skipping UHS write")
        return 0

    n = 0
    with get_db() as conn:
        for sid in df["sid"]:
            u = compute_pick_confidence(sid, pick_date)
            conn.execute(
                """
                UPDATE daily_picks
                SET uhs_score = ?, uhs_breakdown_json = ?, uhs_label = ?, uhs_worst_dim = ?
                WHERE sid = ? AND pick_date = ?
                """,
                (
                    u.get("score_pct"),
                    json.dumps({
                        "dims": {
                            "provenance":   u.get("dim_provenance"),
                            "freshness":    u.get("dim_freshness"),
                            "plausibility": u.get("dim_plausibility"),
                            "consistency":  u.get("dim_consistency"),
                            "coverage":     u.get("dim_coverage"),
                        },
                        "reasons": json.loads(u.get("reasons_json", "{}") or "{}"),
                    }, ensure_ascii=False),
                    u.get("label"),
                    u.get("uhs_worst_dim"),
                    sid, pick_date,
                ),
            )
            n += 1
    print(f"  Wrote UHS to {n} daily_picks rows for {pick_date}")
    return n


def update_calibration_log() -> int:
    """Populate uhs_calibration_log with every (pick_outcomes row × daily_picks.uhs_score).

    Runs nightly. The table is the scaffold for retrospective validation of the
    uniform 20/20/20/20/20 dim weighting once 6+ months of forward-return data
    accumulate (~late Nov 2026). Until then, this is observation only.

    Idempotent: INSERT OR REPLACE on PK (sid, pick_date, window_days).
    """
    df = read_sql(
        """
        SELECT po.sid, po.pick_date, po.window_days, po.fwd_return_pct,
               dp.uhs_score, dp.uhs_label, dp.uhs_worst_dim, dp.cap_tier
        FROM pick_outcomes po
        JOIN daily_picks dp ON po.sid = dp.sid AND po.pick_date = dp.pick_date
        WHERE dp.uhs_score IS NOT NULL
        """
    )
    if df.empty:
        return 0
    rows = df.to_dict("records")
    with get_db() as conn:
        for r in rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO uhs_calibration_log
                  (sid, pick_date, window_days, fwd_return_pct, uhs_score,
                   uhs_label, uhs_worst_dim, cap_tier)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (r["sid"], r["pick_date"], r["window_days"],
                 r["fwd_return_pct"], r["uhs_score"], r["uhs_label"],
                 r["uhs_worst_dim"], r["cap_tier"]),
            )
    print(f"  Updated uhs_calibration_log with {len(rows)} rows")
    return len(rows)


def compute(snapshot_date: Optional[str] = None, dry_run: bool = False) -> int:
    """Pipeline entry point. Writes pick-level UHS for today's daily_picks."""
    if dry_run:
        # Compute one sample without writing
        from datetime import date
        d = snapshot_date or date.today().isoformat()
        df = read_sql("SELECT sid FROM daily_picks WHERE pick_date=? LIMIT 1", params=[d])
        if df.empty:
            print(f"Dry-run: no picks on {d}")
            return 0
        sample = compute_pick_confidence(df.iloc[0]["sid"], d)
        print(f"Dry-run sample: {sample.get('label')} {sample.get('score_pct')} worst={sample.get('uhs_worst_dim')}")
        return 1
    return batch_write_pick_uhs(snapshot_date)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=_date.today().isoformat())
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    compute(snapshot_date=args.date, dry_run=args.dry_run)
