"""
Plan 0026 phase 3 — write the valuation football field (signals/valuation.compute) to `valuation_ranges`.

signals/ never imports db (invariant 1), so the column-level write lives here.
Usage:  python -m output.valuation --sids KEIN,GRSE       # compute + write those names
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


def main():
    ap = argparse.ArgumentParser(description="Write the valuation football field")
    ap.add_argument("--sids", help="comma list of sids")
    ap.add_argument("--book", action="store_true", help="every candidate / held name in multibagger_book")
    ap.add_argument("--as-of", default=None)
    args = ap.parse_args()
    sids = book_sids() if args.book else [x.strip() for x in (args.sids or "").split(",") if x.strip()] or None
    if args.book and not sids:
        raise SystemExit("multibagger_book has no candidate or held names")
    df = v.compute(sids, args.as_of)
    print(v._format(df))
    print(f"\nwrote {write(df)} rows to valuation_ranges")


if __name__ == "__main__":
    main()
