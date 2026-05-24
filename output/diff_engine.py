"""
Alpha Signal v2 — Diff Engine

Compares two consecutive daily pipeline outputs to detect meaningful changes.
Produces ChangeEvent records for the cockpit Morning Brief and Action Queue.

Change types:
  ENTRY      — stock entered top 10 in its tier
  EXIT       — stock exited top 10
  UPGRADE    — rank improved 5+ positions
  DOWNGRADE  — rank worsened 5+ positions
  SIGNAL_FIRED — signal crossed threshold (weak→strong or strong→weak)
  REGIME_CHANGE — VIX regime shifted

Reads: daily_picks, daily_snapshots, regime_state
Writes: daily_changes

Usage:
    python -m output.diff_engine            # compute and save
    python -m output.diff_engine --dry-run  # show changes without saving
"""

import argparse
from datetime import date

import pandas as pd

from db import read_sql, get_db, insert_df

# Signal thresholds for "fired" detection
SIGNAL_THRESHOLDS = {
    "consensus_signal":  (0.4, 0.65, "Consensus"),
    "promoter_qoq":     (-0.5, 0.5, "Promoter Buying"),
    "piotroski_f":       (3, 6, "Piotroski F-Score"),
    "smart_money":       (30, 65, "Smart Money"),
    "earnings_yield":    (0.02, 0.06, "Earnings Yield"),
}

TOP_N = 10  # track entries/exits from top N per tier
RANK_MOVE_THRESHOLD = 5  # minimum rank change to flag


def _get_snapshot_dates():
    """Get the two most recent snapshot dates."""
    df = read_sql(
        "SELECT DISTINCT snapshot_date FROM daily_snapshots "
        "ORDER BY snapshot_date DESC LIMIT 2"
    )
    dates = df["snapshot_date"].tolist()
    if len(dates) < 2:
        return None, None
    return dates[0], dates[1]  # today, yesterday


def _get_pick_dates():
    """Get the two most recent pick dates."""
    df = read_sql(
        "SELECT DISTINCT pick_date FROM daily_picks "
        "ORDER BY pick_date DESC LIMIT 2"
    )
    dates = df["pick_date"].tolist()
    if len(dates) < 2:
        return None, None
    return dates[0], dates[1]


def _detect_rank_changes(today_date, yesterday_date):
    """Detect entries, exits, upgrades, and downgrades in top picks."""
    changes = []

    # Plan 0005 Phase B: exclude integrity-FAIL picks from rank-change diffs
    # so a FAIL never surfaces as a "new entry" or "upgrade" headline.
    today = read_sql(
        "SELECT dp.sid, dp.rank, dp.cap_tier, dp.final_score, s.ticker, s.name "
        "FROM daily_picks dp JOIN stocks s ON dp.sid = s.sid "
        "WHERE dp.pick_date = ? "
        "  AND (dp.integrity_status IS NULL OR dp.integrity_status != 'FAIL')",
        params=[today_date],
    )
    yesterday = read_sql(
        "SELECT dp.sid, dp.rank, dp.cap_tier, dp.final_score, s.ticker "
        "FROM daily_picks dp JOIN stocks s ON dp.sid = s.sid "
        "WHERE dp.pick_date = ? "
        "  AND (dp.integrity_status IS NULL OR dp.integrity_status != 'FAIL')",
        params=[yesterday_date],
    )

    if today.empty or yesterday.empty:
        return changes

    yesterday_map = yesterday.set_index("sid")[["rank", "cap_tier"]].to_dict("index")
    today_map = today.set_index("sid")[["rank", "cap_tier"]].to_dict("index")

    for _, row in today.iterrows():
        sid = row["sid"]
        ticker = row["ticker"]
        tier = row["cap_tier"]
        rank_today = row["rank"]
        score = row["final_score"]

        prev = yesterday_map.get(sid)

        if prev is None:
            # Brand new stock (shouldn't happen often — universe is static)
            if rank_today <= TOP_N:
                changes.append({
                    "change_type": "ENTRY", "severity": "HIGH", "color": "green",
                    "sid": sid, "cap_tier": tier,
                    "headline": f"{ticker} entered Top {TOP_N} {tier} Cap",
                    "detail": f"Rank #{int(rank_today)}, score {score:.3f}",
                })
            continue

        rank_yesterday = prev["rank"]

        # Entry into top N
        if rank_today <= TOP_N and rank_yesterday > TOP_N:
            changes.append({
                "change_type": "ENTRY", "severity": "HIGH", "color": "green",
                "sid": sid, "cap_tier": tier,
                "headline": f"{ticker} entered Top {TOP_N} {tier} Cap",
                "detail": f"Rank #{int(rank_yesterday)} → #{int(rank_today)} (score {score:.3f})",
            })

        # Exit from top N
        elif rank_today > TOP_N and rank_yesterday <= TOP_N:
            changes.append({
                "change_type": "EXIT", "severity": "HIGH", "color": "red",
                "sid": sid, "cap_tier": tier,
                "headline": f"{ticker} dropped out of Top {TOP_N} {tier} Cap",
                "detail": f"Rank #{int(rank_yesterday)} → #{int(rank_today)}",
            })

        # Significant rank improvement
        elif rank_yesterday - rank_today >= RANK_MOVE_THRESHOLD:
            changes.append({
                "change_type": "UPGRADE", "severity": "MEDIUM", "color": "green",
                "sid": sid, "cap_tier": tier,
                "headline": f"{ticker} rose {int(rank_yesterday - rank_today)} positions in {tier}",
                "detail": f"Rank #{int(rank_yesterday)} → #{int(rank_today)}",
            })

        # Significant rank decline
        elif rank_today - rank_yesterday >= RANK_MOVE_THRESHOLD:
            changes.append({
                "change_type": "DOWNGRADE", "severity": "MEDIUM", "color": "red",
                "sid": sid, "cap_tier": tier,
                "headline": f"{ticker} fell {int(rank_today - rank_yesterday)} positions in {tier}",
                "detail": f"Rank #{int(rank_yesterday)} → #{int(rank_today)}",
            })

    # Check for exits (stocks in yesterday's top N no longer in today at all)
    for sid, prev in yesterday_map.items():
        if prev["rank"] <= TOP_N and sid not in today_map:
            ticker = yesterday[yesterday["sid"] == sid]["ticker"].iloc[0]
            changes.append({
                "change_type": "EXIT", "severity": "HIGH", "color": "red",
                "sid": sid, "cap_tier": prev["cap_tier"],
                "headline": f"{ticker} removed from picks ({prev['cap_tier']})",
                "detail": f"Was rank #{int(prev['rank'])}",
            })

    return changes


def _detect_signal_changes(today_date, yesterday_date):
    """Detect signals that crossed thresholds between snapshots."""
    changes = []

    today = read_sql(
        "SELECT ds.*, s.ticker FROM daily_snapshots ds "
        "JOIN stocks s ON ds.sid = s.sid "
        "WHERE ds.snapshot_date = ?", params=[today_date]
    )
    yesterday = read_sql(
        "SELECT sid, consensus_signal, promoter_qoq, piotroski_f, "
        "smart_money, earnings_yield "
        "FROM daily_snapshots WHERE snapshot_date = ?", params=[yesterday_date]
    )

    if today.empty or yesterday.empty:
        return changes

    yesterday_map = yesterday.set_index("sid").to_dict("index")

    for _, row in today.iterrows():
        sid = row["sid"]
        ticker = row.get("ticker", sid)
        prev = yesterday_map.get(sid)
        if prev is None:
            continue

        for col, (weak_thresh, strong_thresh, signal_name) in SIGNAL_THRESHOLDS.items():
            val_today = row.get(col)
            val_yesterday = prev.get(col)

            if val_today is None or val_yesterday is None:
                continue
            if pd.isna(val_today) or pd.isna(val_yesterday):
                continue

            # Crossed from weak to strong
            if val_yesterday <= weak_thresh and val_today >= strong_thresh:
                changes.append({
                    "change_type": "SIGNAL_FIRED", "severity": "MEDIUM", "color": "green",
                    "sid": sid, "cap_tier": row.get("cap_tier"),
                    "headline": f"{ticker}: {signal_name} strengthened",
                    "detail": f"{val_yesterday:.2f} → {val_today:.2f}",
                })

            # Crossed from strong to weak
            elif val_yesterday >= strong_thresh and val_today <= weak_thresh:
                changes.append({
                    "change_type": "SIGNAL_FIRED", "severity": "MEDIUM", "color": "amber",
                    "sid": sid, "cap_tier": row.get("cap_tier"),
                    "headline": f"{ticker}: {signal_name} deteriorated",
                    "detail": f"{val_yesterday:.2f} → {val_today:.2f}",
                })

    return changes


def _detect_regime_change():
    """Detect if VIX regime changed (compares current vs previous VIX history)."""
    changes = []

    vix = read_sql(
        "SELECT date, vix FROM vix_history ORDER BY date DESC LIMIT 5"
    )
    if len(vix) < 2:
        return changes

    from config import VIX_REGIMES

    def _regime_for_vix(v):
        for regime, (lo, hi, _, _, _) in VIX_REGIMES.items():
            if lo <= v < hi:
                return regime
        return "NORMAL"

    regime_today = _regime_for_vix(vix.iloc[0]["vix"])
    regime_yesterday = _regime_for_vix(vix.iloc[1]["vix"])

    if regime_today != regime_yesterday:
        colors = {"CALM": "green", "NORMAL": "blue", "CAUTION": "amber", "CRISIS": "red"}
        changes.append({
            "change_type": "REGIME_CHANGE", "severity": "HIGH",
            "color": colors.get(regime_today, "amber"),
            "sid": None, "cap_tier": None,
            "headline": f"VIX regime shifted: {regime_yesterday} → {regime_today}",
            "detail": f"VIX {vix.iloc[0]['vix']:.1f} (was {vix.iloc[1]['vix']:.1f}). Allocation weights changed.",
        })

    return changes


def compute_changes(today=None, yesterday=None):
    """
    Compute all changes between two consecutive pipeline outputs.
    Returns list of ChangeEvent dicts.
    """
    all_changes = []

    # Get dates
    pick_today, pick_yesterday = _get_pick_dates()
    snap_today, snap_yesterday = _get_snapshot_dates()

    if today:
        pick_today = snap_today = today
    if yesterday:
        pick_yesterday = snap_yesterday = yesterday

    # Rank changes (entries, exits, upgrades, downgrades)
    if pick_today and pick_yesterday:
        all_changes.extend(_detect_rank_changes(pick_today, pick_yesterday))

    # Signal threshold crossings
    if snap_today and snap_yesterday:
        all_changes.extend(_detect_signal_changes(snap_today, snap_yesterday))

    # Regime changes
    all_changes.extend(_detect_regime_change())

    # Sort: high severity first, then by type
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    all_changes.sort(key=lambda c: (severity_order.get(c["severity"], 9), c["change_type"]))

    return all_changes


def compute(dry_run=False):
    """Pipeline entry point. Compute changes and save to daily_changes table."""
    today = date.today().isoformat()
    changes = compute_changes()

    print(f"Diff Engine: {len(changes)} changes detected")

    if changes:
        for c in changes[:10]:
            icon = {"green": "+", "red": "-", "amber": "~"}.get(c["color"], " ")
            print(f"  [{icon}] {c['severity']:6s} {c['headline']}")
        if len(changes) > 10:
            print(f"  ... and {len(changes) - 10} more")
    else:
        print("  No changes (need 2+ days of pipeline data for diffing)")

    if dry_run:
        print("\nDry run — not saving.")
        return len(changes)

    if changes:
        df = pd.DataFrame(changes)
        df["change_date"] = today

        # Clear today's changes first (idempotent re-run)
        with get_db() as conn:
            conn.execute("DELETE FROM daily_changes WHERE change_date = ?", (today,))

        n = insert_df(df, "daily_changes")
        print(f"Saved {n} changes to daily_changes")

    return len(changes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
