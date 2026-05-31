"""Trust Pipeline backfill — runs Gates 2, 3, 4, 5, 7 against existing DB rows
and populates `trust_verdicts` so dim_plausibility + dim_consistency stop being
NULL across the UHS rollup.

WHY THIS EXISTS

Producer-side gates (in sources/*.py) only fire when a fetcher runs. Existing
rows in the DB were written before Plan 0007 wired the gates in — so on day 0
the dim_plausibility + dim_consistency columns are NULL everywhere and every
pick is PRELIMINARY. The forward path (cron + 7-day burn-in) eventually fills
the verdict pool, but it's slow and gives the operator no immediate proof the
gates do work.

This tool runs the SAME validators (`verify_plausibility`, `verify_continuity`,
`verify_cross_source`, `assert_unit`, `audit_drift`) against rows already in
the DB, writes one verdict row per (sid, source_table, source_key, datum_class)
into `trust_verdicts`, and then triggers a UHS recompute. Result: PRELIMINARY
labels flip to TRUSTED / REVIEW / AVOID with real evidence behind them.

IDENTITY GATE IS NOT BACKFILLED — it needs the original API response payload
(slug-segment, returned company name) which the DB does not retain. Gate 1
remains forward-only. That's a known limit and is documented in ADR 0033.

USAGE
    python -m tools.trust_backfill                       # default: today
    python -m tools.trust_backfill --date 2026-05-30
    python -m tools.trust_backfill --gate plausibility   # one gate only
    python -m tools.trust_backfill --dry-run             # count, don't write
"""

import argparse
import json
import sys
from datetime import date as _date, datetime, timedelta
from typing import Optional

from db import get_db, read_sql


# ────────────────────────────────────────────────────────────────────────────
# Verdict-batching helpers
# ────────────────────────────────────────────────────────────────────────────

def _batch_write_verdicts(rows: list[tuple], gate_col: str) -> int:
    """Bulk INSERT OR REPLACE rows into trust_verdicts.

    Each row tuple shape:
        (sid, source_table, source_key_json, datum_class, snapshot_date,
         gate_value, reasons_json, verdict_overall)

    The gate_col argument names which gate column the gate_value lands in.
    """
    if not rows:
        return 0
    sql = f"""
        INSERT OR REPLACE INTO trust_verdicts
          (sid, source_table, source_key, datum_class, snapshot_date,
           {gate_col}, reasons_json, verdict_overall)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    with get_db() as conn:
        conn.executemany(sql, rows)
    return len(rows)


def _segment_for_sid(sid: str, sid_to_tier: dict) -> str:
    return sid_to_tier.get(sid, "*")


def _load_sid_to_tier() -> dict:
    df = read_sql("SELECT sid, cap_tier FROM stocks WHERE cap_tier IS NOT NULL")
    return dict(zip(df["sid"], df["cap_tier"]))


# ────────────────────────────────────────────────────────────────────────────
# Gate 2 — Plausibility
# ────────────────────────────────────────────────────────────────────────────

# (table, column, datum_class, segment_lookup)
# segment_lookup: "tier" → use stock cap_tier; "*" → universal
PLAUSIBILITY_TARGETS = [
    ("consensus_signals", "pt_upside",      "pt_upside_pct", "tier"),
    ("consensus_signals", "eps_growth",     "eps_growth_pct", "*"),
    ("banking_metrics",   "gross_npa_pct",  "bank_gnpa_pct", "*"),
    ("banking_metrics",   "net_npa_pct",    "bank_nnpa_pct", "*"),
    ("banking_metrics",   "nim_pct",        "bank_nim_pct", "*"),
    ("banking_metrics",   "casa_pct",       "bank_casa_pct", "*"),
    ("banking_metrics",   "car_pct",        "bank_car_pct", "*"),
    ("piotroski_scores",  "f_score",        "piotroski_f", "*"),
]


def backfill_plausibility(snapshot_date: str, dry_run: bool = False) -> dict:
    """Run Gate 2 against existing rows. Returns counts per table."""
    from validators.plausibility import verify_plausibility

    sid_to_tier = _load_sid_to_tier()
    summary = {}

    for table, col, datum_class, seg_mode in PLAUSIBILITY_TARGETS:
        # Pick the right PK columns + date column per table
        if table == "consensus_signals":
            pk_cols = ["sid", "snapshot_date"]
            df = read_sql(
                f"SELECT sid, snapshot_date, {col} FROM {table} "
                f"WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM {table})"
            )
        elif table == "banking_metrics":
            pk_cols = ["sid", "period_end", "period_type"]
            df = read_sql(
                f"SELECT sid, period_end, period_type, {col} FROM {table} "
                f"WHERE period_end >= date('now','-365 days')"
            )
        elif table == "piotroski_scores":
            pk_cols = ["sid", "snapshot_date"]
            df = read_sql(
                f"SELECT sid, snapshot_date, {col} FROM {table} "
                f"WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM {table})"
            )
        else:
            continue

        verdicts = []
        n_pass = n_extreme = n_hard = n_null = n_undef = 0
        for _, r in df.iterrows():
            sid = r["sid"]
            value = r[col]
            seg = _segment_for_sid(sid, sid_to_tier) if seg_mode == "tier" else "*"
            v = verify_plausibility(datum_class, value, seg)
            if v.status == "NULL_VALUE":
                n_null += 1
                continue
            if v.status == "UNDEFINED":
                n_undef += 1
                continue
            source_key = json.dumps({k: r[k] for k in pk_cols}, default=str)
            reasons = json.dumps({"gate_2_plausibility": {
                "status":   v.status,
                "value":    str(v.value),
                "hard":     list(v.hard_range) if v.hard_range else None,
                "extreme":  list(v.extreme_range) if v.extreme_range else None,
                "segment":  v.segment,
                "reason":   v.reason,
            }})
            if v.status == "PASS":
                gate_val = 1
                overall = "TRUSTED"
                n_pass += 1
            elif v.status == "EXTREME":
                gate_val = 2
                overall = "PENDING_REVIEW"
                n_extreme += 1
            elif v.status == "OUT_OF_RANGE_HARD":
                gate_val = 0
                overall = "QUARANTINED"
                n_hard += 1
            else:
                continue
            verdicts.append((sid, table, source_key, datum_class, snapshot_date,
                              gate_val, reasons, overall))

        written = 0 if dry_run else _batch_write_verdicts(verdicts, "gate_2_plausibility")
        summary[f"{table}.{col}"] = {
            "scanned": len(df), "pass": n_pass, "extreme": n_extreme,
            "hard_fail": n_hard, "null": n_null, "undef": n_undef,
            "written": written,
        }
    return summary


# ────────────────────────────────────────────────────────────────────────────
# Gate 3 — Temporal continuity
# ────────────────────────────────────────────────────────────────────────────

def backfill_temporal(snapshot_date: str, dry_run: bool = False) -> dict:
    """Run Gate 3 against today's analyst_consensus.price_target and a sample
    of today's stock_prices.close (5,000 SIDs cap to keep it fast)."""
    from validators.temporal_continuity import verify_continuity

    summary = {}

    # ── analyst_consensus.price_target vs 30-day median baseline ──
    df = read_sql(
        """
        SELECT sid, fetched_at, price_target
        FROM analyst_consensus
        WHERE fetched_at >= datetime('now','-2 days')
          AND price_target IS NOT NULL
        """
    )
    verdicts = []
    n_pass = n_disc = n_nobaseline = n_undef = 0
    for _, r in df.iterrows():
        v = verify_continuity(
            sid=r["sid"], datum_class="analyst_pt",
            new_value=r["price_target"],
            as_of_date=snapshot_date,
            baseline_table="analyst_consensus_snapshots",
            baseline_col="target_mean",
            baseline_date_col="snapshot_date",
        )
        source_key = json.dumps({"sid": r["sid"], "fetched_at": r["fetched_at"]}, default=str)
        reasons = json.dumps({"gate_3_temporal": {
            "status":   v.status,
            "value":    str(v.value),
            "baseline": str(v.baseline) if v.baseline else None,
            "ratio":    f"{v.ratio:.2f}" if v.ratio else None,
            "threshold": v.threshold,
            "reason":   v.reason,
        }})
        if v.status == "CONTINUOUS":
            gate_val, overall = 1, "TRUSTED"
            n_pass += 1
        elif v.status == "DISCONTINUOUS":
            gate_val, overall = 0, "QUARANTINED"
            n_disc += 1
        elif v.status == "NO_BASELINE":
            n_nobaseline += 1
            continue
        else:
            n_undef += 1
            continue
        verdicts.append((r["sid"], "analyst_consensus", source_key, "analyst_pt",
                          snapshot_date, gate_val, reasons, overall))
    written = 0 if dry_run else _batch_write_verdicts(verdicts, "gate_3_temporal")
    summary["analyst_consensus.price_target"] = {
        "scanned": len(df), "pass": n_pass, "disc": n_disc,
        "no_baseline": n_nobaseline, "undef": n_undef, "written": written,
    }

    # ── stock_prices.close vs 30-day baseline (today only) ──
    today_close = read_sql(
        """
        SELECT sid, date, close
        FROM stock_prices
        WHERE date = (SELECT MAX(date) FROM stock_prices)
          AND close IS NOT NULL
        """
    )
    verdicts = []
    n_pass = n_disc = n_nobaseline = n_undef = 0
    for _, r in today_close.iterrows():
        v = verify_continuity(
            sid=r["sid"], datum_class="stock_close",
            new_value=r["close"],
            as_of_date=r["date"],
            baseline_table="stock_prices",
            baseline_col="close",
            baseline_date_col="date",
        )
        source_key = json.dumps({"sid": r["sid"], "date": r["date"]}, default=str)
        reasons = json.dumps({"gate_3_temporal": {
            "status":   v.status,
            "value":    str(v.value),
            "baseline": str(v.baseline) if v.baseline else None,
            "ratio":    f"{v.ratio:.2f}" if v.ratio else None,
            "threshold": v.threshold,
            "reason":   v.reason,
        }})
        if v.status == "CONTINUOUS":
            gate_val, overall = 1, "TRUSTED"
            n_pass += 1
        elif v.status == "DISCONTINUOUS":
            gate_val, overall = 0, "QUARANTINED"
            n_disc += 1
        elif v.status == "NO_BASELINE":
            n_nobaseline += 1
            continue
        else:
            n_undef += 1
            continue
        verdicts.append((r["sid"], "stock_prices", source_key, "stock_close",
                          snapshot_date, gate_val, reasons, overall))
    written = 0 if dry_run else _batch_write_verdicts(verdicts, "gate_3_temporal")
    summary["stock_prices.close"] = {
        "scanned": len(today_close), "pass": n_pass, "disc": n_disc,
        "no_baseline": n_nobaseline, "undef": n_undef, "written": written,
    }

    return summary


# ────────────────────────────────────────────────────────────────────────────
# Gate 4 — Cross-source
# ────────────────────────────────────────────────────────────────────────────

def backfill_cross_source(snapshot_date: str, dry_run: bool = False) -> dict:
    """Run Gate 4 against today's consensus_signals.pt_upside via a vectorised
    join against analyst_consensus.price_target + broker_recommendations.

    The plausibility-style range gates already catch absurd PTs. Gate 4's job
    here is the disagreement-across-sources signal that's silent inside any
    single source. We test pt_target_price (the canonical class)."""

    df = read_sql(
        """
        SELECT cs.sid,
               cs.snapshot_date,
               cs.pt_upside,
               ac.price_target  AS ac_pt,
               br.broker_pt
        FROM consensus_signals cs
        LEFT JOIN analyst_consensus ac ON ac.sid = cs.sid
        LEFT JOIN (
            SELECT sid, AVG(target_price) AS broker_pt
            FROM broker_recommendations
            WHERE reco_date >= date('now','-90 days')
              AND target_price IS NOT NULL
            GROUP BY sid
        ) br ON br.sid = cs.sid
        WHERE cs.snapshot_date = (SELECT MAX(snapshot_date) FROM consensus_signals)
          AND cs.pt_upside IS NOT NULL
        """
    )

    # Latest close per SID, for upside → implied-PT recovery
    closes = read_sql(
        """
        SELECT sid, close
        FROM stock_prices
        WHERE date = (SELECT MAX(date) FROM stock_prices)
          AND close IS NOT NULL
        """
    )
    sid_to_close = dict(zip(closes["sid"], closes["close"]))

    verdicts = []
    n_pass = n_tolerated = n_silent = n_skip = 0
    TOL_PCT = 20
    ELEV_PCT = 40

    for _, r in df.iterrows():
        sid = r["sid"]
        close = sid_to_close.get(sid)
        if close is None or close <= 0:
            n_skip += 1
            continue
        # Derived implied PT = close × (1 + pt_upside%)
        implied_pt = close * (1 + r["pt_upside"] / 100.0)
        peers = [p for p in (r["ac_pt"], r["broker_pt"]) if p is not None and p > 0]
        if not peers:
            n_skip += 1
            continue
        disagreements = [abs(implied_pt - p) / p * 100 for p in peers]
        max_dis = max(disagreements)
        if max_dis <= TOL_PCT:
            status, gate_val, overall = "PASS", 1, "TRUSTED"
            n_pass += 1
        elif max_dis <= ELEV_PCT:
            status, gate_val, overall = "DIVERGENT_TOLERATED", 2, "PENDING_REVIEW"
            n_tolerated += 1
        else:
            status, gate_val, overall = "DIVERGENT_SILENT", 0, "QUARANTINED"
            n_silent += 1
        source_key = json.dumps({"sid": sid, "snapshot_date": r["snapshot_date"]},
                                 default=str)
        reasons = json.dumps({"gate_4_cross_source": {
            "status":       status,
            "implied_pt":   f"{implied_pt:.2f}",
            "peer_count":   len(peers),
            "max_diff_pct": f"{max_dis:.1f}",
            "tolerance":    TOL_PCT,
            "elevated":     ELEV_PCT,
        }})
        verdicts.append((sid, "consensus_signals", source_key, "pt_target_price",
                          snapshot_date, gate_val, reasons, overall))

    written = 0 if dry_run else _batch_write_verdicts(verdicts, "gate_4_cross_source")
    return {
        "consensus_signals.pt_upside_vs_peer": {
            "scanned": len(df), "pass": n_pass, "tolerated": n_tolerated,
            "silent": n_silent, "skipped": n_skip, "written": written,
        }
    }


# ────────────────────────────────────────────────────────────────────────────
# Gate 5 — Unit contract
# ────────────────────────────────────────────────────────────────────────────

def backfill_unit_contract(snapshot_date: str, dry_run: bool = False) -> dict:
    """Sample each (table, col) with a declared unit, verify the live data
    falsifies or confirms the contract."""
    from lineage import UNIT_CONTRACTS

    summary = {}

    PK_BY_TABLE = {
        "consensus_signals":   ("sid, snapshot_date",),
        "analyst_consensus":   ("sid, fetched_at",),
        "stock_prices":        ("sid, date",),
        "banking_metrics":     ("sid, period_end, period_type",),
        "piotroski_scores":    ("sid, snapshot_date",),
        "quarterly_income":    ("sid, period_end",),
        "annual_balance_sheet": ("sid, period_end",),
        "mf_metrics":          ("scheme_code, snapshot_date",),
    }

    verdicts = []
    for (table, col), expected_unit in UNIT_CONTRACTS.items():
        pk_spec = PK_BY_TABLE.get(table)
        if pk_spec is None:
            continue
        pk_cols = pk_spec[0]
        try:
            df = read_sql(f"SELECT {pk_cols}, {col} FROM {table} "
                          f"WHERE {col} IS NOT NULL LIMIT 200")
        except Exception:
            continue
        if df.empty:
            continue
        # Cheap unit sniffing — same heuristics as db._check_frame_units
        n = len(df)
        col_values = df[col].astype(float)
        in_small_range = (col_values.abs() <= 1.5).sum()
        in_outside_5 = (col_values.abs() > 5).sum()
        passed = True
        reason = "values consistent with declared unit"
        if expected_unit == "pct_100":
            if n >= 20 and in_small_range / n >= 0.95:
                passed = False
                reason = (f"declared pct_100 but {in_small_range}/{n} values "
                          "≤|1.5| (looks like ratio_1)")
        elif expected_unit == "ratio_1":
            if in_outside_5 / n > 0.05:
                passed = False
                reason = (f"declared ratio_1 but {in_outside_5}/{n} values "
                          ">|5| (looks like pct_100)")
        sample_sid = df.iloc[0].get("sid") or df.iloc[0].get("scheme_code")
        source_key = json.dumps({"col": col, "n_sampled": n}, default=str)
        gate_val = 1 if passed else 0
        overall = "TRUSTED" if passed else "QUARANTINED"
        reasons = json.dumps({"gate_5_unit": {
            "expected": expected_unit, "n_sampled": n, "reason": reason,
        }})
        verdicts.append((str(sample_sid), table, source_key, col,
                          snapshot_date, gate_val, reasons, overall))
        summary.setdefault(table, {"checks": 0, "pass": 0, "fail": 0})
        summary[table]["checks"] += 1
        summary[table]["pass" if passed else "fail"] += 1

    written = 0 if dry_run else _batch_write_verdicts(verdicts, "gate_5_unit")
    summary["_written_verdicts"] = written
    return summary


# ────────────────────────────────────────────────────────────────────────────
# Gate 7 — External anchor
# ────────────────────────────────────────────────────────────────────────────

def backfill_anchor(snapshot_date: str, dry_run: bool = False) -> dict:
    """Defer to tools.anchor_audit.audit_drift — it already writes both PASS
    and FAIL verdicts to trust_verdicts.gate_7_anchor."""
    if dry_run:
        return {"skipped": "dry_run"}
    from tools.anchor_audit import audit_drift
    # Audit yesterday by default (NSE bhavcopy is T+1)
    anchor_date = (_date.fromisoformat(snapshot_date) - timedelta(days=1)).isoformat()
    counts = audit_drift(anchor_date)
    return {"anchor_date": anchor_date, **counts}


# ────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ────────────────────────────────────────────────────────────────────────────

def compute(snapshot_date: Optional[str] = None, dry_run: bool = False,
            only_gate: Optional[str] = None) -> dict:
    snapshot_date = snapshot_date or _date.today().isoformat()
    out = {"snapshot_date": snapshot_date, "dry_run": dry_run}

    if only_gate in (None, "plausibility"):
        print(f"\n[Gate 2] Plausibility for {snapshot_date}")
        out["plausibility"] = backfill_plausibility(snapshot_date, dry_run)
        for k, v in out["plausibility"].items():
            print(f"  {k}: scanned={v['scanned']} pass={v['pass']} "
                  f"extreme={v.get('extreme',0)} hard_fail={v.get('hard_fail',0)} "
                  f"null={v.get('null',0)} written={v['written']}")

    if only_gate in (None, "temporal"):
        print(f"\n[Gate 3] Temporal continuity for {snapshot_date}")
        out["temporal"] = backfill_temporal(snapshot_date, dry_run)
        for k, v in out["temporal"].items():
            print(f"  {k}: scanned={v['scanned']} pass={v['pass']} "
                  f"disc={v['disc']} no_baseline={v['no_baseline']} "
                  f"written={v['written']}")

    if only_gate in (None, "cross_source"):
        print(f"\n[Gate 4] Cross-source for {snapshot_date}")
        out["cross_source"] = backfill_cross_source(snapshot_date, dry_run)
        for k, v in out["cross_source"].items():
            print(f"  {k}: scanned={v['scanned']} pass={v['pass']} "
                  f"tolerated={v['tolerated']} silent={v['silent']} "
                  f"skipped={v['skipped']} written={v['written']}")

    if only_gate in (None, "unit"):
        print(f"\n[Gate 5] Unit contract for {snapshot_date}")
        out["unit"] = backfill_unit_contract(snapshot_date, dry_run)
        written = out["unit"].pop("_written_verdicts", 0)
        for k, v in out["unit"].items():
            print(f"  {k}: checks={v['checks']} pass={v['pass']} fail={v['fail']}")
        print(f"  total verdicts written: {written}")

    if only_gate in (None, "anchor"):
        print(f"\n[Gate 7] External anchor for {snapshot_date}")
        out["anchor"] = backfill_anchor(snapshot_date, dry_run)
        print(f"  {out['anchor']}")

    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", default=None, help="snapshot date ISO (default: today)")
    ap.add_argument("--gate", default=None,
                    choices=["plausibility", "temporal", "cross_source", "unit", "anchor"])
    ap.add_argument("--dry-run", action="store_true",
                    help="count verdicts without writing")
    args = ap.parse_args()
    out = compute(args.date, dry_run=args.dry_run, only_gate=args.gate)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
