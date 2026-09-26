"""
One-time import of v1 archive CSVs into v2 tables.

Reads (read-only) from /home/ubuntu/alpha-signal/data/ per CLAUDE.md
("v1 is LIVE on cron — never touch ~/alpha-signal/"). All writes are to
v2 SQLite via INSERT OR IGNORE so re-running is safe.

Sources imported:
  • insider_archive.csv (123K rows / Feb-May 2026)  →  insider_trades
  • article_scores_*.csv (46 daily files)            →  sentiment_scores
    (each daily file has per-article VADER scores; we aggregate per-sid)

Usage:
    python -m sources.v1_archive_import --source insider
    python -m sources.v1_archive_import --source sentiment
    python -m sources.v1_archive_import --source all
"""

import argparse
import glob
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from db import insert_df, read_sql, get_db

V1_DATA = Path("/home/ubuntu/alpha-signal/data")


def _sid_map():
    df = read_sql("SELECT sid, ticker FROM stocks WHERE ticker IS NOT NULL")
    return dict(zip(df.ticker.str.upper(), df.sid))


def import_insider():
    """v1 insider_archive.csv → v2 insider_trades."""
    src = V1_DATA / "insider/insider_archive.csv"
    if not src.exists():
        print(f"  {src} not found — skipping")
        return 0
    print(f"[insider] loading {src} ...", flush=True)
    raw = pd.read_csv(src, low_memory=False)
    print(f"[insider] raw rows: {len(raw)}", flush=True)

    sids = _sid_map()
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Map columns — v1 uses 'matched_symbol' (already universe-validated) when present
    raw["sym"] = raw["matched_symbol"].fillna(raw["symbol"]).astype(str).str.upper().str.strip()
    raw["sid"] = raw["sym"].map(sids)
    matched = raw.dropna(subset=["sid"])
    print(f"[insider] mapped to v2 universe: {len(matched)} of {len(raw)}", flush=True)

    matched = matched.copy()
    matched["trade_date_clean"] = pd.to_datetime(matched["date"], errors="coerce").dt.date
    matched = matched.dropna(subset=["trade_date_clean"])

    out = pd.DataFrame({
        "sid": matched["sid"],
        "symbol": matched["sym"],
        "company_name": matched["company_name"].astype(str).str[:200],
        "person": matched["person"].astype(str).str[:200],
        "person_category": matched["category_person"].astype(str).str[:80],
        "transaction_type": matched["transaction_type"].astype(str).str[:40],
        "shares": pd.to_numeric(matched["shares"], errors="coerce"),
        "value_lakhs": pd.to_numeric(matched["value_lakhs"], errors="coerce"),
        "trade_date": matched["trade_date_clean"].astype(str),
        "source": matched["source"].fillna("v1_archive").astype(str).str[:80],
        "fetched_at": fetched_at,
    })

    print(f"[insider] writing {len(out)} rows via INSERT OR IGNORE ...", flush=True)
    written = insert_df(out, "insider_trades")
    print(f"[insider] DONE — {written} new rows written ({len(out) - written} dupes ignored)", flush=True)
    return written


def import_sentiment():
    """v1 article_scores_YYYY-MM-DD.csv → v2 sentiment_scores.

    Each v1 daily CSV is per-article scores with symbols_str listing matched
    stocks. We explode that to per-sid and aggregate 7d/30d windows per
    snapshot date. Writes one snapshot per source file.
    """
    files = sorted(glob.glob(str(V1_DATA / "sentiment/article_scores_*.csv")))
    if not files:
        print("  No article_scores files in v1 — skipping")
        return 0
    print(f"[sentiment] {len(files)} daily snapshot files: {Path(files[0]).name} → {Path(files[-1]).name}", flush=True)

    sids = _sid_map()

    # Load all article snapshots into one frame (each has snapshot_date stamped)
    all_articles = []
    for f in files:
        try:
            df = pd.read_csv(f, low_memory=False)
        except Exception as e:
            print(f"[sentiment] skip {f}: {e}", flush=True)
            continue
        snap = Path(f).stem.replace("article_scores_", "")
        df["snapshot_date"] = snap
        all_articles.append(df)
    if not all_articles:
        return 0
    art = pd.concat(all_articles, ignore_index=True)
    art["pub_date"] = pd.to_datetime(art["published_at"], errors="coerce").dt.date
    art = art.dropna(subset=["pub_date", "sentiment_compound"])
    print(f"[sentiment] total article-rows across snapshots: {len(art)}", flush=True)

    # Explode symbols_str into rows (one per stock per article)
    art["symbols_list"] = art["symbols_str"].fillna("").str.split(",")
    art_x = art.explode("symbols_list")
    art_x["sym"] = art_x["symbols_list"].astype(str).str.upper().str.strip()
    art_x["sid"] = art_x["sym"].map(sids)
    art_x = art_x.dropna(subset=["sid"])
    print(f"[sentiment] articles × sids (after explode + map): {len(art_x)}", flush=True)

    # For each (snapshot_date, sid) compute today/7d/30d windows
    out_rows = []
    for snap, snap_grp in art_x.groupby("snapshot_date"):
        snap_d = pd.to_datetime(snap).date()
        d7 = snap_d - timedelta(days=7)
        d30 = snap_d - timedelta(days=30)
        for sid, g in snap_grp.groupby("sid"):
            row = {"sid": sid, "snapshot_date": snap}
            today_g = g[g["pub_date"] == snap_d]
            w7 = g[g["pub_date"] >= d7]
            w30 = g[g["pub_date"] >= d30]
            if len(today_g):
                row["sentiment_today"] = round(today_g["sentiment_compound"].mean(), 4)
                row["articles_today"] = int(len(today_g))
            if len(w7):
                row["sentiment_7d"] = round(w7["sentiment_compound"].mean(), 4)
                row["articles_7d"] = int(len(w7))
            if len(w30):
                row["sentiment_30d"] = round(w30["sentiment_compound"].mean(), 4)
                row["articles_30d"] = int(len(w30))
            if "sentiment_7d" in row and "sentiment_30d" in row:
                row["sentiment_momentum"] = round(row["sentiment_7d"] - row["sentiment_30d"], 4)
            # Latest headline within the snapshot window
            latest = g.sort_values("pub_date", ascending=False).iloc[0]
            row["latest_headline"] = str(latest.get("title", ""))[:200]
            out_rows.append(row)

    if not out_rows:
        return 0
    out = pd.DataFrame(out_rows)
    # Schema columns + defaults
    for c in ["sentiment_today", "articles_today", "sentiment_7d", "articles_7d",
              "sentiment_30d", "articles_30d", "sentiment_momentum", "latest_headline"]:
        if c not in out.columns:
            out[c] = None
    out = out[["sid", "snapshot_date", "sentiment_today", "articles_today",
               "sentiment_7d", "articles_7d", "sentiment_30d", "articles_30d",
               "sentiment_momentum", "latest_headline"]]
    print(f"[sentiment] writing {len(out)} (sid, snapshot_date) rows ...", flush=True)
    written = insert_df(out, "sentiment_scores")
    print(f"[sentiment] DONE — {written} new rows written ({len(out) - written} dupes ignored)", flush=True)
    return written


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True, choices=["insider", "sentiment", "all"])
    args = p.parse_args()
    if args.source in ("insider", "all"):
        import_insider()
    if args.source in ("sentiment", "all"):
        import_sentiment()


if __name__ == "__main__":
    main()
