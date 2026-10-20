"""
Plan 0026 phase 3 — write the valuation football field (signals/valuation.compute) to `valuation_ranges`.

signals/ never imports db (invariant 1), so the column-level write lives here.
Pipeline step `compute_valuation_ranges` (daily, after the email) calls compute(): every field is rebuilt on
the latest close for the names the desk shows one for (desk_sids()), so "price vs field" never lags the prices.
Usage:  python -m output.valuation                         # the desk's names (what the daily step runs)
        python -m output.valuation --sids KEIN,GRSE       # compute + write those names
        python -m output.valuation --book                  # every multibagger_book candidate / held name
"""

import argparse

import db
from signals import valuation as v


def write(df):
    """Column-level upsert into valuation_ranges (PK sid, as_of, method). Returns rows written."""
    if df is None or df.empty:
        raise RuntimeError("valuation.write: nothing to write")
    return db.upsert_df(df[v.COLUMNS].astype({"as_of": str}), "valuation_ranges")


def book_sids():
    rows = db.rows("SELECT sid FROM multibagger_book WHERE status IN ('candidate', 'held')")
    return [r["sid"] for r in rows]


def desk_sids():
    """Every name the multibagger desk shows a field for: the candidate / held names plus the newest thesis
    run's top 100 (the funnel cards), sorted."""
    rows = db.rows("SELECT sid FROM multibagger_book WHERE status IN ('candidate', 'held') UNION "
                   "SELECT sid FROM multibagger_scores WHERE thesis_stage = 'top100' AND snapshot_date = "
                   "(SELECT MAX(snapshot_date) FROM multibagger_scores WHERE thesis_score IS NOT NULL)")
    return sorted(r["sid"] for r in rows)


def compute():
    """Pipeline step: rebuild and write the field for every desk name on the latest close. Raises when the desk has
    no names (an empty thesis run and an empty book is broken input, not a quiet day)."""
    sids = desk_sids()
    if not sids:
        raise RuntimeError("valuation: no desk names (multibagger_book has no candidate / held and no thesis top 100)")
    df = v.compute(sids)
    n = write(df)
    print(f"valuation_ranges: {n} rows for {df['sid'].nunique()} of {len(sids)} desk names, as of {df['as_of'].iloc[0]}")
    return n


def main():
    ap = argparse.ArgumentParser(description="Write the valuation football field")
    ap.add_argument("--sids", help="comma list of sids")
    ap.add_argument("--book", action="store_true", help="every candidate / held name in multibagger_book")
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args()
    if not args.sids and not args.book and args.as_of is None:
        compute()
        return
    sids = book_sids() if args.book else [x.strip() for x in (args.sids or "").split(",") if x.strip()] or desk_sids()
    if args.book and not sids:
        raise SystemExit("multibagger_book has no candidate or held names")
    df = v.compute(sids, args.as_of)
    print(v._format(df))
    print(f"\nwrote {write(df)} rows to valuation_ranges")


if __name__ == "__main__":
    main()
