"""
External Anchor audit — Trust Pipeline Gate 7, Plan 0007 Phase 6.

The closed-loop fix. Today every quality check compares values to other
internal values — there's no independent ground truth. This module promotes
NSE bhavcopy (which we already fetch authoritatively) to the canonical
anchor for close/volume/delivery_pct, then audits non-NSE sources (yfinance,
Tickertape) against it. Drift beyond tolerance emits gate_7_anchor=0 verdicts
that feed UHS Consistency dim down.

THREE TIERS OF ANCHOR (per plan 0007 §Phase 6):
    A. NSE bhavcopy        — automated, daily, all 2,448 stocks for close/volume.
                              Tolerance vs other sources: 0.5% close, 5% volume.
    B. BSE manual spot      — top-50 LARGE close prices, weekly manual seed.
                              30-min/week process. Uses --seed-bse-csv flag.
    C. AMC factsheets       — top-50 MF schemes, monthly manual parse for
                              1Y/3Y return cross-check. Uses --seed-amc-csv.

WHAT'S NOT ANCHORED (the honest scope ceiling):
    Fundamentals (revenue, NPA, EPS) — no free anchor exists at our scale.
    Gate 4 cross-source agreement (Tickertape vs Screener.in vs Moneycontrol)
    is the best free proxy. Bloomberg/Refinitiv would be the upgrade (~$20K/yr).
    See ADR 0033.

USAGE
    python -m tools.anchor_audit                # promote yesterday's bhavcopy
                                                 + audit yfinance drift
    python -m tools.anchor_audit --dry-run
    python -m tools.anchor_audit --status       # show coverage + drift counts
    python -m tools.anchor_audit --seed-bse-csv /path/to/file.csv
    python -m tools.anchor_audit --seed-amc-csv /path/to/factsheets.csv
"""

import argparse
import json
import sys
from datetime import date as _date, datetime, timedelta
from typing import Optional

import pandas as pd

from db import get_db, read_sql, upsert_df


# Tolerance for drift detection: |diff| / anchor > tolerance → DRIFTED
DRIFT_TOLERANCE = {
    "close":           0.5,    # 0.5% — tight, NSE bhavcopy is authoritative
    "volume":          5.0,    # 5% — volume can legitimately differ across data feeds
    "delivery_pct":    1.0,    # 1pp absolute (handled separately below)
    "mf_ret_1y":       2.0,    # 2pp absolute for MF return cross-check
    "mf_ret_3y_cagr":  1.5,
}


def promote_nse_bhavcopy_anchors(anchor_date: Optional[str] = None) -> int:
    """Copy NSE bhavcopy rows for `anchor_date` into external_anchors as
    datum_class='close'/'volume'/'delivery_pct'. Idempotent.

    Per CLAUDE.md, stock_prices uses NSE bhavcopy as the canonical source;
    rows with source='nse_bhavcopy' (or source IS NULL — bhavcopy is the
    default) are the anchor. yfinance-sourced rows are the *follower*.
    """
    anchor_date = anchor_date or (_date.today() - timedelta(days=1)).isoformat()
    df = read_sql(
        """
        SELECT sid, close, volume, delivery_pct
        FROM stock_prices
        WHERE date = ?
          AND (source IS NULL OR source = 'bhavcopy' OR source = 'nse_bhavcopy')
          AND close IS NOT NULL
        """,
        params=[anchor_date],
    )
    if df.empty:
        print(f"  No NSE bhavcopy rows on {anchor_date}")
        return 0

    rows = []
    for _, r in df.iterrows():
        for datum_class, col in (("close", "close"), ("volume", "volume"),
                                  ("delivery_pct", "delivery_pct")):
            val = r.get(col)
            if pd.notna(val):
                rows.append({
                    "datum_class":    datum_class,
                    "sid_or_segment": r["sid"],
                    "anchor_value":   float(val),
                    "anchor_source":  "nse_bhavcopy",
                    "anchor_date":    anchor_date,
                    "notes":          None,
                })
    if not rows:
        return 0
    out = pd.DataFrame(rows)
    n = upsert_df(out, "external_anchors")
    print(f"  Promoted {n} NSE bhavcopy anchor rows for {anchor_date}")
    return n


def audit_drift(anchor_date: Optional[str] = None) -> dict:
    """Compare non-anchor sources to the anchor for `anchor_date`. Per
    (datum_class, sid), emit gate_7_anchor=0 verdicts where |diff|/anchor
    exceeds DRIFT_TOLERANCE.

    Currently audits yfinance vs NSE bhavcopy for `close` (the highest-
    value cross-check — yfinance is the canonical yet most-suspect price
    source for a few thin-coverage SMALLs). Extending to other classes is
    additive — add a `_audit_<class>()` function below.

    Returns counts: {audited, drifted, written_verdicts}.
    """
    anchor_date = anchor_date or (_date.today() - timedelta(days=1)).isoformat()
    counts = {"audited": 0, "drifted": 0, "written_verdicts": 0}

    # Audit yfinance vs NSE for close. yfinance source label varies
    # (yfinance / yfinance.NS / yfinance.BO).
    yf_df = read_sql(
        """
        SELECT sid, close FROM stock_prices
        WHERE date = ? AND source LIKE 'yfinance%' AND close IS NOT NULL
        """,
        params=[anchor_date],
    )
    if yf_df.empty:
        return counts

    anchor_df = read_sql(
        """
        SELECT sid_or_segment AS sid, anchor_value AS anchor
        FROM external_anchors
        WHERE datum_class = 'close' AND anchor_date = ?
          AND anchor_source = 'nse_bhavcopy'
        """,
        params=[anchor_date],
    )
    if anchor_df.empty:
        return counts
    merged = yf_df.merge(anchor_df, on="sid", how="inner")
    counts["audited"] = len(merged)
    tol = DRIFT_TOLERANCE["close"]
    merged["drift_pct"] = (merged["close"] - merged["anchor"]).abs() / merged["anchor"] * 100
    drifted = merged[merged["drift_pct"] > tol]
    counts["drifted"] = len(drifted)

    # Write per-(sid, datum_class) gate_7 verdicts
    with get_db() as conn:
        for _, r in drifted.iterrows():
            conn.execute(
                """
                INSERT OR REPLACE INTO trust_verdicts
                  (sid, source_table, source_key, datum_class, snapshot_date,
                   gate_7_anchor, reasons_json, verdict_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (r["sid"], "stock_prices",
                 json.dumps({"sid": r["sid"], "date": anchor_date, "source": "yfinance"}),
                 "close", anchor_date,
                 0,
                 json.dumps({
                     "gate_7_anchor": {
                         "status": "DRIFTED",
                         "value":  str(r["close"]),
                         "anchor": str(r["anchor"]),
                         "drift_pct": f"{r['drift_pct']:.2f}",
                         "tolerance_pct": tol,
                         "anchor_source": "nse_bhavcopy",
                     }
                 }),
                 "QUARANTINED"),
            )
            counts["written_verdicts"] += 1

        # Write PASS verdicts for the non-drifted yfinance rows (so UHS rollup
        # has positive evidence, not just absence).
        passing = merged[merged["drift_pct"] <= tol]
        for _, r in passing.iterrows():
            conn.execute(
                """
                INSERT OR REPLACE INTO trust_verdicts
                  (sid, source_table, source_key, datum_class, snapshot_date,
                   gate_7_anchor, reasons_json, verdict_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (r["sid"], "stock_prices",
                 json.dumps({"sid": r["sid"], "date": anchor_date, "source": "yfinance"}),
                 "close", anchor_date,
                 1,
                 json.dumps({
                     "gate_7_anchor": {
                         "status": "PASS",
                         "drift_pct": f"{r['drift_pct']:.2f}",
                         "tolerance_pct": tol,
                     }
                 }),
                 "TRUSTED"),
            )
            counts["written_verdicts"] += 1

    print(f"  Drift audit (close) for {anchor_date}: "
          f"{counts['audited']} audited · {counts['drifted']} drifted "
          f"· {counts['written_verdicts']} verdicts written")
    return counts


def seed_bse_csv(csv_path: str) -> int:
    """Manual BSE seed. CSV columns: sid, close, anchor_date.

    Used for the weekly 30-min top-50 LARGE spot-check process. Run once
    a week with a small hand-curated CSV from bseindia.com.
    """
    df = pd.read_csv(csv_path)
    required = {"sid", "close", "anchor_date"}
    if not required.issubset(df.columns):
        raise ValueError(f"BSE CSV missing required cols: {required - set(df.columns)}")
    rows = [{
        "datum_class":    "close",
        "sid_or_segment": r["sid"],
        "anchor_value":   float(r["close"]),
        "anchor_source":  "bse_manual",
        "anchor_date":    str(r["anchor_date"]),
        "notes":          "weekly manual spot-check",
    } for _, r in df.iterrows()]
    n = upsert_df(pd.DataFrame(rows), "external_anchors")
    print(f"  Seeded {n} BSE manual anchor rows from {csv_path}")
    return n


def seed_amc_csv(csv_path: str) -> int:
    """Manual AMC factsheet seed. CSV cols: scheme_code, ret_1y, ret_3y_cagr, anchor_date."""
    df = pd.read_csv(csv_path)
    required = {"scheme_code", "anchor_date"}
    if not required.issubset(df.columns):
        raise ValueError(f"AMC CSV missing required cols: {required - set(df.columns)}")
    rows = []
    for _, r in df.iterrows():
        for col, datum_class in [("ret_1y", "mf_ret_1y"), ("ret_3y_cagr", "mf_ret_3y_cagr")]:
            if col in df.columns and pd.notna(r.get(col)):
                rows.append({
                    "datum_class":    datum_class,
                    "sid_or_segment": str(r["scheme_code"]),
                    "anchor_value":   float(r[col]),
                    "anchor_source":  "amc_factsheet",
                    "anchor_date":    str(r["anchor_date"]),
                    "notes":          "monthly factsheet parse",
                })
    if not rows:
        return 0
    n = upsert_df(pd.DataFrame(rows), "external_anchors")
    print(f"  Seeded {n} AMC factsheet anchor rows from {csv_path}")
    return n


def status() -> dict:
    """Coverage + drift summary for cockpit /system Anchors tile."""
    df = read_sql(
        """
        SELECT anchor_source, datum_class,
               COUNT(DISTINCT sid_or_segment) AS n_entities,
               MAX(anchor_date) AS latest_date
        FROM external_anchors
        GROUP BY anchor_source, datum_class
        """
    )
    coverage = df.to_dict("records") if not df.empty else []

    drift_df = read_sql(
        """
        SELECT COUNT(*) AS n_drift FROM trust_verdicts
        WHERE gate_7_anchor = 0
          AND snapshot_date >= date('now', '-7 days')
        """
    )
    drift_7d = int(drift_df.iloc[0]["n_drift"] or 0) if not drift_df.empty else 0
    out = {
        "coverage_by_source": coverage,
        "drift_count_7d": drift_7d,
    }
    print(json.dumps(out, indent=2, default=str))
    return out


def compute(anchor_date: Optional[str] = None, dry_run: bool = False) -> int:
    """Pipeline entry. Promotes yesterday's NSE bhavcopy + runs the yfinance drift audit."""
    if dry_run:
        print(f"Dry-run: would promote NSE anchors + audit drift for {anchor_date or 'yesterday'}")
        return 0
    promoted = promote_nse_bhavcopy_anchors(anchor_date)
    audit = audit_drift(anchor_date)
    return promoted + audit.get("written_verdicts", 0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=None,
                   help="Anchor date (YYYY-MM-DD). Default: yesterday.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--status", action="store_true",
                   help="Show coverage + 7d drift summary; do not write.")
    p.add_argument("--seed-bse-csv", default=None,
                   help="Seed external_anchors with top-50 BSE close prices from a CSV.")
    p.add_argument("--seed-amc-csv", default=None,
                   help="Seed external_anchors with MF factsheet returns from a CSV.")
    args = p.parse_args()

    if args.status:
        status()
        return
    if args.seed_bse_csv:
        seed_bse_csv(args.seed_bse_csv)
        return
    if args.seed_amc_csv:
        seed_amc_csv(args.seed_amc_csv)
        return

    compute(anchor_date=args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
