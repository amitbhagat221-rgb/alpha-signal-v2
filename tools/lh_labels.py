"""
Plan 0024 (long-horizon model) — shared forward-return labels  (READ-ONLY on the DB).

One row per (sid, snapshot_date) for every MONTHLY anchor of daily_snapshots_pit
(tools.backtest_pit._is_month_start_anchor), with:

  fwd_21, fwd_63, fwd_126, fwd_252   pit.forward_returns at those horizons (trading
                                      sessions). Entry = close of the first session after
                                      the anchor, adjusted closes, entry/exit proximity
                                      guards. NULL where the horizon has not elapsed or a
                                      guard fails.
  fwd_20                              the same at 20 sessions — only to check against the
                                      panel's stored fwd_return_20d (they should be equal).
  fwd_next_anchor                     holding-period return from anchor k to anchor k+1:
                                      entry = first session after anchor k, exit = first
                                      session after anchor k+1 (h_k = market sessions
                                      between those two entries, same function, same
                                      guards). NULL for the last anchor.
  h_next_anchor                       that h_k.

The book simulator (H3) chains fwd_next_anchor month to month.

Writes data/lh/labels.parquet. Never writes the DB (opens it with mode=ro).

Usage:
    python -m tools.lh_labels            # build + sanity check
    python -m tools.lh_labels --check    # sanity check an existing file only
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pit  # noqa: E402
from tools.backtest_pit import _is_month_start_anchor  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
OUT_DIR = PROJECT_ROOT / "data" / "lh"
OUT = OUT_DIR / "labels.parquet"
HORIZONS = (21, 63, 126, 252)


def ro_conn():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def monthly_anchors(conn):
    dates = pd.read_sql("SELECT DISTINCT snapshot_date FROM daily_snapshots_pit", conn)["snapshot_date"]
    return sorted(d for d in dates if _is_month_start_anchor(pd.Timestamp(d).date()))


def load_prices(conn):
    """The inputs of pit.forward_returns: the same rows as pit.RAW_SQL['prices'] (close > 0),
    only the columns the label reads."""
    px = pd.read_sql("SELECT sid, date, close FROM stock_prices WHERE close > 0 ORDER BY sid, date", conn)
    adj = pd.read_sql(pit.RAW_SQL["adjustments"], conn)
    return px, adj


def build():
    conn = ro_conn()
    anchors = monthly_anchors(conn)
    print(f"{len(anchors)} monthly anchors {anchors[0]} → {anchors[-1]}")
    ph = ",".join("?" * len(anchors))
    panel = pd.read_sql(f"SELECT sid, snapshot_date, cap_tier, fwd_return_20d FROM daily_snapshots_pit "
                        f"WHERE snapshot_date IN ({ph})", conn, params=anchors)
    print(f"panel rows at anchors: {len(panel):,}")
    px, adj = load_prices(conn)
    conn.close()
    print(f"prices {len(px):,} rows, {px['sid'].nunique():,} sids, {px['date'].min()} → {px['date'].max()}; "
          f"adjustments {len(adj):,}")

    cal = np.sort(px["date"].unique())
    first_after = {a: int(np.searchsorted(cal, a, side="right")) for a in anchors}

    out = []
    for i, a in enumerate(anchors):
        hs = list(HORIZONS) + [20]
        h_next = None
        if i + 1 < len(anchors):
            nxt = anchors[i + 1]
            if first_after[nxt] < len(cal):            # the entry after anchor k+1 has happened
                h_next = first_after[nxt] - first_after[a]
                hs.append(h_next)
        fr = pit.forward_returns(pd.Timestamp(a).date(), px, adj, tuple(sorted(set(hs))))
        g = panel[panel["snapshot_date"] == a][["sid", "snapshot_date", "cap_tier", "fwd_return_20d"]]
        rec = g[["sid"]].merge(fr, on="sid", how="left")
        row = g.copy().reset_index(drop=True)
        for h in HORIZONS + (20,):
            col = f"fwd_return_{h}d"
            row[f"fwd_{h}"] = rec[col].values if col in rec else np.nan
        col = f"fwd_return_{h_next}d" if h_next else None
        row["fwd_next_anchor"] = rec[col].values if col and col in rec else np.nan
        row["h_next_anchor"] = h_next if h_next else np.nan
        out.append(row)
        print(f"  {a}: n={len(row):5d}  " + " ".join(
            f"{h}:{row[f'fwd_{h}'].notna().sum()}" for h in HORIZONS) +
            f"  next(h={h_next}):{row['fwd_next_anchor'].notna().sum()}", flush=True)

    lab = pd.concat(out, ignore_index=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lab.drop(columns=["fwd_return_20d"]).to_parquet(OUT, index=False)
    print(f"wrote {OUT} ({len(lab):,} rows)")
    sanity(lab)
    return lab


def sanity(lab=None):
    if lab is None:
        lab = pd.read_parquet(OUT)
        conn = ro_conn()
        st = pd.read_sql("SELECT sid, snapshot_date, fwd_return_20d FROM daily_snapshots_pit", conn)
        conn.close()
        lab = lab.merge(st, on=["sid", "snapshot_date"], how="left")
    res = {}
    for c in ("fwd_20", "fwd_21"):
        chk = lab[[c, "fwd_return_20d"]].dropna()
        d = (chk[c] - chk["fwd_return_20d"]).abs()
        res[c] = {"n": int(len(chk)), "pearson": round(float(chk[c].corr(chk["fwd_return_20d"])), 4),
                  "spearman": round(float(chk[c].corr(chk["fwd_return_20d"], method="spearman")), 4),
                  "median_abs_diff": round(float(d.median()), 5),
                  "share_exact_equal": round(float((d < 1e-4).mean()), 4)}
        print(f"sanity {c} vs panel fwd_return_20d: {res[c]}")
    # fwd_next_anchor spans 19-23 sessions, so it should track fwd_21 closely (same entry).
    chk = lab[["fwd_next_anchor", "fwd_21"]].dropna()
    res["next_vs_21"] = {"n": int(len(chk)), "pearson": round(float(chk["fwd_next_anchor"].corr(chk["fwd_21"])), 4),
                         "median_abs_diff": round(float((chk["fwd_next_anchor"] - chk["fwd_21"]).abs().median()), 5)}
    print(f"sanity fwd_next_anchor vs fwd_21: {res['next_vs_21']}")
    h = lab.drop_duplicates("snapshot_date")["h_next_anchor"].dropna()
    print(f"h_next_anchor sessions: min {h.min():.0f} median {h.median():.0f} max {h.max():.0f}")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        sanity()
    else:
        build()


if __name__ == "__main__":
    main()
