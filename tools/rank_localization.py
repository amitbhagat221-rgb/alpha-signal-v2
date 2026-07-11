"""
Alpha Signal v2 — Rank-IC localization mini-study (plan 0012 A1 / WS1.4 prerequisite).

Read-only. Does the edge concentrate at the top of the rank, or is it spread
flat across the whole picked list? Answers this two ways:

  1. pick_outcomes lens: realized excess return by rank_at_pick bucket
     (1-5 / 6-10 / 11-20 / 21-50), per cap_tier, window_days=20.
  2. daily_snapshots_pit lens: a single-factor proxy (delivery_anomaly_z,
     SMALL only — the sole BY-FDR-robust factor) quintile-1 vs quintile-2
     mean fwd_return_20d over the latest 24 anchors.

Verdict rule (DECIDED, plan 0012 A1): "localizes" iff bucket 1-5 beats 6-10
with t >= 1.5 in >= 1 tier in the pick_outcomes lens. Otherwise flat weights
are honest and WS1.4 (conviction sizing) is CLOSED-NO.

Usage:
    python -m tools.rank_localization
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from scipy.stats import ttest_ind

from db import read_sql

OUT_PATH = PROJECT_ROOT / "docs" / "studies" / "rank-localization-2026-07.md"


def _to_md(df):
    """Minimal DataFrame->markdown table (avoids the optional 'tabulate' dep)."""
    if df.empty:
        return "_(no rows)_"
    cols = list(df.columns)
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join(
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
        for row in df.itertuples(index=False)
    )
    return "\n".join([header, sep, body])

RANK_BUCKETS = [(1, 5), (6, 10), (11, 20), (21, 50)]
TIERS = ["LARGE", "MID", "SMALL"]
N_ANCHORS = 24


def _bucket_label(lo, hi):
    return f"{lo}-{hi}"


def _bucket_for_rank(rank, buckets):
    for lo, hi in buckets:
        if lo <= rank <= hi:
            return _bucket_label(lo, hi)
    return None


def pick_outcomes_lens():
    """Bucket rank_at_pick, report n / mean / median excess return / hit rate
    per (cap_tier, bucket), plus a two-sample t-test of bucket 1-5 vs 6-10."""
    df = read_sql(
        "SELECT cap_tier, rank_at_pick, excess_return_pct FROM pick_outcomes "
        "WHERE window_days = 20 AND rank_at_pick IS NOT NULL "
        "AND excess_return_pct IS NOT NULL"
    )
    df["bucket"] = df["rank_at_pick"].apply(lambda r: _bucket_for_rank(r, RANK_BUCKETS))
    df = df.dropna(subset=["bucket"])

    rows = []
    t_rows = []
    for tier in TIERS:
        tdf = df[df["cap_tier"] == tier]
        for lo, hi in RANK_BUCKETS:
            label = _bucket_label(lo, hi)
            bdf = tdf[tdf["bucket"] == label]
            n = len(bdf)
            if n == 0:
                rows.append({"cap_tier": tier, "bucket": label, "n": 0,
                             "mean_excess": None, "median_excess": None, "hit_rate": None})
                continue
            mean_excess = float(bdf["excess_return_pct"].mean())
            median_excess = float(bdf["excess_return_pct"].median())
            hit_rate = float((bdf["excess_return_pct"] > 0).mean())
            rows.append({"cap_tier": tier, "bucket": label, "n": n,
                         "mean_excess": round(mean_excess, 4),
                         "median_excess": round(median_excess, 4),
                         "hit_rate": round(hit_rate, 4)})

        b1 = tdf[tdf["bucket"] == "1-5"]["excess_return_pct"]
        b2 = tdf[tdf["bucket"] == "6-10"]["excess_return_pct"]
        if len(b1) >= 2 and len(b2) >= 2:
            tstat, pval = ttest_ind(b1, b2, equal_var=False)
        else:
            tstat, pval = None, None
        t_rows.append({
            "cap_tier": tier, "n_1_5": len(b1), "n_6_10": len(b2),
            "t_stat": round(float(tstat), 3) if tstat is not None else None,
            "p_value": round(float(pval), 4) if pval is not None else None,
        })
    return pd.DataFrame(rows), pd.DataFrame(t_rows)


def pit_proxy_lens():
    """SMALL-only quintile-1 vs quintile-2 mean fwd_return_20d, ranked by
    delivery_anomaly_z, over the latest N_ANCHORS anchors."""
    anchors_df = read_sql(
        "SELECT DISTINCT snapshot_date FROM daily_snapshots_pit "
        "ORDER BY snapshot_date DESC LIMIT ?", params=[N_ANCHORS]
    )
    anchors = anchors_df["snapshot_date"].tolist()
    if not anchors:
        return pd.DataFrame(), pd.DataFrame()

    placeholders = ",".join("?" for _ in anchors)
    df = read_sql(
        f"SELECT snapshot_date, sid, delivery_anomaly_z, fwd_return_20d "
        f"FROM daily_snapshots_pit WHERE cap_tier = 'SMALL' "
        f"AND snapshot_date IN ({placeholders}) "
        f"AND delivery_anomaly_z IS NOT NULL AND fwd_return_20d IS NOT NULL",
        params=anchors,
    )

    q1_all, q2_all = [], []
    per_anchor = []
    for date, adf in df.groupby("snapshot_date"):
        if len(adf) < 10:
            continue
        adf = adf.copy()
        adf["quintile"] = pd.qcut(adf["delivery_anomaly_z"], 5, labels=False, duplicates="drop")
        if adf["quintile"].nunique() < 5:
            continue
        q1 = adf[adf["quintile"] == 4]["fwd_return_20d"]  # top quintile (highest delivery_anomaly_z)
        q2 = adf[adf["quintile"] == 3]["fwd_return_20d"]  # second quintile
        q1_all.extend(q1.tolist())
        q2_all.extend(q2.tolist())
        per_anchor.append({
            "snapshot_date": date, "n": len(adf),
            "q1_mean": round(float(q1.mean()), 4), "q2_mean": round(float(q2.mean()), 4),
        })

    summary = pd.DataFrame({
        "quintile": ["Q1 (top delivery_anomaly_z)", "Q2"],
        "n": [len(q1_all), len(q2_all)],
        "mean_fwd_return_20d": [
            round(float(np.mean(q1_all)), 4) if q1_all else None,
            round(float(np.mean(q2_all)), 4) if q2_all else None,
        ],
    })
    return summary, pd.DataFrame(per_anchor)


def write_report(bucket_df, t_df, pit_summary, pit_per_anchor):
    localizes = False
    winning_tier = None
    for _, row in t_df.iterrows():
        if row["t_stat"] is not None and row["t_stat"] >= 1.5:
            localizes = True
            winning_tier = row["cap_tier"]
            break

    lines = []
    lines.append("# Rank-IC localization mini-study (plan 0012 A1)\n")
    lines.append("Read-only study. Decides whether conviction sizing (WS1.4) is worth building: "
                  "does realized edge concentrate at the top of the rank, or is it flat across "
                  "the picked list?\n")
    lines.append("## Lens 1 — pick_outcomes (realized), window_days=20\n")
    lines.append("Bucket stats — n, mean/median excess_return_pct, hit rate:\n")
    lines.append(_to_md(bucket_df))
    lines.append("\n\nTwo-sample t-test, bucket 1-5 vs 6-10 (Welch, unequal variance):\n")
    lines.append(_to_md(t_df))
    lines.append("\n\n## Lens 2 — daily_snapshots_pit single-factor proxy (SMALL only)\n")
    lines.append(f"Ranked by `delivery_anomaly_z` (sole robust SMALL factor), latest {N_ANCHORS} "
                  "anchors, quintile-1 (top) vs quintile-2 mean `fwd_return_20d`. "
                  "**This is a single-factor proxy, not the model.**\n")
    lines.append(_to_md(pit_summary))
    lines.append("\n\nPer-anchor detail:\n")
    lines.append(_to_md(pit_per_anchor))
    lines.append("\n\n## Verdict\n")
    if localizes:
        lines.append(
            f"**Localizes.** Bucket 1-5 beats 6-10 with t >= 1.5 in {winning_tier} "
            "(pick_outcomes lens) — conviction sizing (WS1.4) has real evidence behind it and "
            "is worth prototyping, though the single-factor PIT proxy should be read as "
            "corroborating context, not proof, since it isolates one factor rather than the "
            "full model. A human should scope a conviction-weighting design before building."
        )
    else:
        lines.append(
            "**Flat.** No tier shows bucket 1-5 beating 6-10 with t >= 1.5 in the pick_outcomes "
            "lens — the realized edge does not measurably concentrate at the top of the rank. "
            "Flat weights are honest and **WS1.4 (conviction sizing) is CLOSED-NO** pending new "
            "evidence; the PIT single-factor proxy is reported for context only, not as an "
            "override, since a one-factor read can diverge from the full-model realized outcome."
        )
    lines.append("")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines))
    return localizes


def main():
    bucket_df, t_df = pick_outcomes_lens()
    pit_summary, pit_per_anchor = pit_proxy_lens()

    print("\n== Lens 1: pick_outcomes rank-bucket stats (window_days=20) ==\n")
    print(bucket_df.to_string(index=False))
    print("\n== Lens 1: t-test bucket 1-5 vs 6-10 ==\n")
    print(t_df.to_string(index=False))
    print("\n== Lens 2: daily_snapshots_pit delivery_anomaly_z quintile proxy (SMALL) ==\n")
    print(pit_summary.to_string(index=False))
    print()

    localizes = write_report(bucket_df, t_df, pit_summary, pit_per_anchor)
    print(f"Verdict: {'LOCALIZES' if localizes else 'FLAT — WS1.4 CLOSED-NO'}")
    print(f"Report written to {OUT_PATH}")


if __name__ == "__main__":
    main()
