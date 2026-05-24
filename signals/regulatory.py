"""
Alpha Signal v2 — Regulatory Sector Signal

Computes a rolling regulatory_score per sector from AI-classified events.

Formula per sector S on date D, looking back W days:
  reg_score = Σ(direction × mag_weight × conf_weight × decay) / max(1, count)

  mag_weight:  minor=0.3, moderate=0.6, major=1.0
  conf_weight: low=0.3, medium=0.6, high=1.0
  decay:       exp(-0.02 × days_since_event)  [half-life ~35 days]

Score range: -1.0 (heavy regulatory headwind) to +1.0 (strong tailwind).
Merged into macro_sector_signals alongside the economic macro_score.

Reads: regulatory_events, regulatory_signals
Writes: Updates macro_sector_signals with regulatory columns

Usage:
    python -m signals.regulatory            # compute and save
    python -m signals.regulatory --dry-run  # compute but don't save
    python -m signals.regulatory --window 90  # 90-day lookback (default: 60)
"""

import argparse
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from db import read_sql, get_db, upsert_df

# Magnitude → numeric weight
MAG_WEIGHT = {"minor": 0.3, "moderate": 0.6, "major": 1.0}

# Confidence → numeric weight
CONF_WEIGHT = {"low": 0.3, "medium": 0.6, "high": 1.0}

# Decay rate (half-life ~35 days)
DECAY_RATE = 0.02

# Default lookback window
DEFAULT_WINDOW = 60


def compute_regulatory_scores(eval_date=None, window_days=DEFAULT_WINDOW):
    """
    Compute regulatory_score per sector for a given date.
    Returns DataFrame: sector, reg_score, reg_events, reg_major_events, reg_signal
    """
    if eval_date is None:
        eval_date = date.today()
    elif isinstance(eval_date, str):
        eval_date = datetime.strptime(eval_date, "%Y-%m-%d").date()

    cutoff = (eval_date - timedelta(days=window_days)).isoformat()
    eval_str = eval_date.isoformat()

    # Load classified signals with event dates
    signals = read_sql("""
        SELECT rs.sector, rs.direction, rs.magnitude, rs.confidence,
               re.published_at
        FROM regulatory_signals rs
        JOIN regulatory_events re ON rs.event_id = re.event_id
        WHERE rs.is_regulatory = 1
          AND re.published_at >= ?
          AND re.published_at <= ?
          AND rs.direction IS NOT NULL
        ORDER BY re.published_at DESC
    """, params=[cutoff, eval_str + " 23:59:59"])

    if signals.empty:
        return pd.DataFrame(columns=["sector", "reg_score", "reg_events",
                                     "reg_major_events", "reg_signal"])

    # Parse dates and compute days since event
    signals["pub_date"] = pd.to_datetime(signals["published_at"], errors="coerce")
    signals = signals.dropna(subset=["pub_date"])
    signals["days_ago"] = (pd.Timestamp(eval_date) - signals["pub_date"]).dt.days.clip(lower=0)

    # Compute weighted contribution per signal. Unmapped magnitude/confidence
    # labels are dropped, not silently filled with a midpoint — a classifier
    # typo or new label should fail loud rather than skew sector scores.
    signals["mag_w"] = signals["magnitude"].map(MAG_WEIGHT)
    signals["conf_w"] = signals["confidence"].map(CONF_WEIGHT)
    unmapped = signals[signals["mag_w"].isna() | signals["conf_w"].isna()]
    if not unmapped.empty:
        bad_mag = unmapped["magnitude"].dropna().unique().tolist()
        bad_conf = unmapped["confidence"].dropna().unique().tolist()
        print(f"  ⚠ {len(unmapped)} regulatory_signals with unmapped labels — "
              f"dropping. magnitudes={bad_mag} confidences={bad_conf}")
        signals = signals.dropna(subset=["mag_w", "conf_w"])
    signals["decay"] = np.exp(-DECAY_RATE * signals["days_ago"])
    signals["contribution"] = (
        signals["direction"] * signals["mag_w"] * signals["conf_w"] * signals["decay"]
    )

    # Aggregate per sector
    results = []
    for sector, group in signals.groupby("sector"):
        total_events = len(group)
        major_events = (group["magnitude"] == "major").sum()

        # Weighted sum / count
        raw_score = group["contribution"].sum() / max(1, total_events)

        # Clip to [-1, 1]
        reg_score = max(-1.0, min(1.0, raw_score))

        # Signal label
        if reg_score >= 0.3:
            signal = "TAILWIND"
        elif reg_score >= 0.1:
            signal = "FAVORABLE"
        elif reg_score > -0.1:
            signal = "NEUTRAL"
        elif reg_score > -0.3:
            signal = "HEADWIND"
        else:
            signal = "ADVERSE"

        results.append({
            "sector": sector,
            "reg_score": round(reg_score, 4),
            "reg_events": total_events,
            "reg_major_events": major_events,
            "reg_signal": signal,
        })

    return pd.DataFrame(results)


def compute_historical_scores(start_date=None, end_date=None, window_days=DEFAULT_WINDOW):
    """
    Compute monthly regulatory scores over a historical period.
    For backtesting. Returns DataFrame: date, sector, reg_score, ...
    """
    if start_date is None:
        start_date = "2023-06-01"
    if end_date is None:
        end_date = date.today().isoformat()

    # Generate monthly dates
    dates = pd.date_range(start=start_date, end=end_date, freq="MS")

    all_results = []
    for d in dates:
        eval_d = d.date()
        scores = compute_regulatory_scores(eval_date=eval_d, window_days=window_days)
        if not scores.empty:
            scores["date"] = eval_d.isoformat()
            all_results.append(scores)

    if all_results:
        return pd.concat(all_results, ignore_index=True)
    return pd.DataFrame()


def compute(dry_run=False, window_days=DEFAULT_WINDOW):
    """Main entry point. Compute today's scores and update macro_sector_signals."""
    today = date.today()
    scores = compute_regulatory_scores(eval_date=today, window_days=window_days)

    if scores.empty:
        print("Regulatory: no classified events in window — no scores to compute")
        return 0

    print(f"Regulatory Scores ({window_days}-day window, {today}):")
    print(f"{'Sector':30s} {'Score':>7s} {'Events':>7s} {'Major':>6s} {'Signal':>10s}")
    print("-" * 65)
    for _, r in scores.sort_values("reg_score", ascending=False).iterrows():
        print(f"{r['sector']:30s} {r['reg_score']:>+7.3f} {r['reg_events']:>7d} "
              f"{r['reg_major_events']:>6d} {r['reg_signal']:>10s}")

    if dry_run:
        print("\nDry run — not saving.")
        return len(scores)

    # Merge into macro_sector_signals
    snapshot = today.isoformat()

    # Read existing macro_sector_signals for today
    existing = read_sql(
        "SELECT sector, macro_score, macro_signal, macro_detail "
        "FROM macro_sector_signals WHERE snapshot_date = ?",
        params=[snapshot],
    )

    # Build output rows
    out_rows = []
    for _, r in scores.iterrows():
        # Find existing macro score for this sector
        existing_row = existing[existing["sector"] == r["sector"]]
        # When no prior macro_score for this sector, leave NULL rather than
        # fabricate a midpoint 50.0 — downstream readers (cockpit, scoring)
        # can then tell "missing" from "median." 2026-05-23: matches the
        # smart_money NaN-not-50 fix in the same audit.
        macro_score = existing_row.iloc[0]["macro_score"] if not existing_row.empty else None
        macro_signal = existing_row.iloc[0]["macro_signal"] if not existing_row.empty else "UNKNOWN"

        # Combine: macro_detail now includes regulatory info
        reg_detail = f"Regulatory: {r['reg_signal']} ({r['reg_events']} events, {r['reg_major_events']} major)"
        macro_detail = existing_row.iloc[0]["macro_detail"] if not existing_row.empty else ""
        combined_detail = f"{macro_detail} | {reg_detail}" if macro_detail else reg_detail

        out_rows.append({
            "sector": r["sector"],
            "snapshot_date": snapshot,
            "macro_score": macro_score,
            "macro_signal": macro_signal,
            "macro_detail": combined_detail[:500],
        })

    out = pd.DataFrame(out_rows)
    n = upsert_df(out, "macro_sector_signals")
    print(f"\nUpdated {n} rows in macro_sector_signals with regulatory scores")
    return len(scores)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="Lookback window in days")
    parser.add_argument("--historical", action="store_true", help="Compute monthly scores for backtesting")
    parser.add_argument("--start", default="2023-06-01", help="Start date for historical mode")
    args = parser.parse_args()

    if args.historical:
        df = compute_historical_scores(start_date=args.start, window_days=args.window)
        if not df.empty:
            print(f"\nHistorical scores: {len(df)} rows, {df['date'].nunique()} months, {df['sector'].nunique()} sectors")
            # Show summary
            pivot = df.pivot_table(index="date", columns="sector", values="reg_score")
            print(pivot.tail(6).to_string())
        else:
            print("No historical scores computed (insufficient classified events)")
    else:
        compute(dry_run=args.dry_run, window_days=args.window)
