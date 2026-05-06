"""
Alpha Signal v2 — Parse corporate_actions and compute cumulative split/bonus factors.

For each (sid, ex_date) of a SPLIT or BONUS event, derive the price-adjustment ratio.
Store in split_adjustments table.

Usage downstream:
    For a historical close on date D, multiply by:
        adj_factor(sid, D) = Π split_ratio for all events with ex_date > D
    This gives the "split-adjusted close" comparable to current price.

Run:
    python -m tools.compute_splits
    python -m tools.compute_splits --dry-run
"""
import argparse
import re
from datetime import datetime

import pandas as pd

from db import get_db, read_sql, upsert_df


def parse_split_ratio(subject):
    """Parse split ratio from subject string. Returns the multiplier to apply to PRE-split prices.

    Examples:
      'Stock Split From Rs.10/- to Rs.5/-' → 0.5 (price halves)
      'Stock Split 1:5'                    → 0.2
      'Sub-Division of share from rs.10 to Rs.1' → 0.1
    """
    if not subject:
        return None
    s = subject.lower()

    # "From Rs X/- to Rs/Re Y/-" — covers both legacy "Stock Split From Rs.10/- to Rs.5/-"
    # and the canonical NSE "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share".
    # `r[se]\.?` matches Rs / Re (NSE writes "Re" when the value is 1).
    m = re.search(
        r"from\s+(?:r[se]\.?\s*)?(\d+(?:\.\d+)?)\s*/?-?\s*(?:per\s+share\s*)?to\s+(?:r[se]\.?\s*)?(\d+(?:\.\d+)?)",
        s,
    )
    if m:
        old_fv, new_fv = float(m.group(1)), float(m.group(2))
        if old_fv > 0:
            return new_fv / old_fv

    # "1:N" or "1 for N" patterns (split N:1 means N new for 1 old → factor = 1/N)
    m = re.search(r"(\d+)\s*:\s*(\d+)", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a == 1 and b > 1:
            return 1.0 / b
        if b == 1 and a > 1:
            return 1.0 / a

    return None


def parse_bonus_ratio(subject):
    """Parse bonus ratio. Returns the price-multiplier (always < 1).

    Examples:
      'Bonus 1:1' → 0.5  (1 free per 1 held → 2 total → price halves)
      'Bonus 1:2' → 1/3  (1 free per 2 held → 3:2 ratio → factor = 2/3)
      'Bonus 2:5' → 5/7  (2 free per 5 held → 7 total per 5 starting)
    """
    if not subject:
        return None
    s = subject.lower()
    m = re.search(r"(\d+)\s*:\s*(\d+)", s)
    if not m:
        return None
    free, held = int(m.group(1)), int(m.group(2))
    if held <= 0:
        return None
    return held / (held + free)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    actions = read_sql(
        "SELECT sid, symbol, ex_date, ind, subject FROM corporate_actions "
        "WHERE ind IN ('SPLIT', 'BONUS') AND sid IS NOT NULL "
        "ORDER BY sid, ex_date"
    )
    print(f"Loaded {len(actions)} SPLIT/BONUS rows from corporate_actions")

    parsed_rows = []
    unparsed = 0
    for _, row in actions.iterrows():
        ind = row["ind"]
        subject = row.get("subject", "") or ""
        if ind == "SPLIT":
            ratio = parse_split_ratio(subject)
            bonus = 1.0
        elif ind == "BONUS":
            bonus = parse_bonus_ratio(subject)
            ratio = bonus  # treat both the same way for cumulative factor
        else:
            continue

        if ratio is None or ratio <= 0 or ratio >= 1.0:
            unparsed += 1
            continue

        parsed_rows.append({
            "sid": row["sid"],
            "effective_date": row["ex_date"],
            "split_ratio": ratio if ind == "SPLIT" else 1.0,
            "bonus_ratio": ratio if ind == "BONUS" else 1.0,
            "subject": subject[:200],
        })

    print(f"Parsed: {len(parsed_rows)} usable; {unparsed} unparsable")

    if not parsed_rows:
        print("Nothing to write.")
        return

    df = pd.DataFrame(parsed_rows)

    # Compute cumulative factor per stock — most-recent-event has factor=1.0,
    # earlier events get cumulative product of all later events.
    df = df.sort_values(["sid", "effective_date"], ascending=[True, False])

    cumulative_factors = []
    current_sid = None
    cum = 1.0
    for _, row in df.iterrows():
        if row["sid"] != current_sid:
            current_sid = row["sid"]
            cum = 1.0
        # Apply this event going FORWARD; for dates BEFORE this event, multiply by ratio
        # Compute the factor that applies to dates before this ex_date
        factor_for_pre_dates = cum * row["split_ratio"] * row["bonus_ratio"]
        cumulative_factors.append(factor_for_pre_dates)
        cum = factor_for_pre_dates

    df["cumulative_factor"] = cumulative_factors
    df = df.sort_values(["sid", "effective_date"])

    # Show samples
    print("\nSample for top-3 most-event stocks:")
    counts = df.groupby("sid").size().sort_values(ascending=False)
    for sid in counts.head(3).index:
        sub = df[df["sid"] == sid]
        print(f"  {sid}: {len(sub)} events")
        for _, r in sub.head(5).iterrows():
            print(f"    {r['effective_date']} ratio={r['split_ratio']:.3f} bonus={r['bonus_ratio']:.3f} cum={r['cumulative_factor']:.4f} ({r['subject'][:50]})")

    if args.dry_run:
        print(f"\n[dry-run] would write {len(df)} rows to split_adjustments")
        return

    df_to_write = df[["sid", "effective_date", "split_ratio", "bonus_ratio", "cumulative_factor", "subject"]]
    n = upsert_df(df_to_write, "split_adjustments")
    print(f"\n→ wrote {n} rows to split_adjustments")


if __name__ == "__main__":
    main()
