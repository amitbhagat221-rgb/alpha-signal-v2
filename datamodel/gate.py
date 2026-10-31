"""
Plan 0030 parity gate: a legacy table against its v3 compatibility view, row for row.

For each legacy table of the concept, on the newest N dates: the row count of the legacy
table and of the view, and the rows present in one but not the other (EXCEPT both ways,
over every legacy column). The view body is inlined as a CTE, so the gate needs no DDL
and runs read-only on the live DB. Exit 1 on any difference.

REAL columns are compared at 10 significant digits: the mirror keeps attrs as JSON, and
SQLite's json_object writes a float with 15 significant digits, so a score such as
0.4452032108513916 comes back as 0.445203210851392 (measured 2026-10-31: every row of
3 dates differed only there, and at 12 digits 3 rows still fell on a rounding boundary).
Nothing a reader shows carries more than 6. `--exact` compares bit for bit, to see it.

    python -m datamodel.gate decisions                 # newest 3 dates
    python -m datamodel.gate decisions --dates 10
    python -m datamodel.gate decisions --all           # whole table (slow on picks)
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from datamodel import compat  # noqa: E402


def _cols(conn, table):
    return [(r[1], (r[2] or "").upper()) for r in conn.execute(f"PRAGMA table_info({table})")]


def check_table(conn, table, view, date_col, dates=3, whole=False, exact=False):
    """→ {table, dates, legacy, view, missing_in_view, extra_in_view, sample}."""
    typed = _cols(conn, table)
    cols = [c for c, _t in typed]
    collist = ", ".join(f"[{c}]" if exact or t != "REAL" else f"printf('%.10g', [{c}]) AS [{c}]" for c, t in typed)
    if whole:
        where, params = "1 = 1", []
    else:
        ds = [r[0] for r in conn.execute(f"SELECT DISTINCT {date_col} FROM {table} ORDER BY 1 DESC LIMIT ?", (dates,))]
        where, params = f"{date_col} IN ({', '.join('?' * len(ds))})" if ds else "0", ds
    cte = f"WITH {view} AS ({compat.body(view)})"
    n_legacy = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]
    n_view = conn.execute(f"{cte} SELECT COUNT(*) FROM {view} WHERE {where}", params).fetchone()[0]
    missing = conn.execute(f"{cte} SELECT {collist} FROM {table} WHERE {where} EXCEPT SELECT {collist} FROM {view} WHERE {where}",
                           params + params).fetchall()
    extra = conn.execute(f"{cte} SELECT {collist} FROM {view} WHERE {where} EXCEPT SELECT {collist} FROM {table} WHERE {where}",
                         params + params).fetchall()
    sample = None
    if missing or extra:
        row = (missing or extra)[0]
        sample = ("legacy-only " if missing else "view-only ") + str(dict(zip(cols, row)))[:300]
    return {"table": table, "view": view, "dates": None if whole else params, "legacy": n_legacy, "view_rows": n_view,
            "missing_in_view": len(missing), "extra_in_view": len(extra), "sample": sample}


def run(concept, dates=3, whole=False, path=None, exact=False):
    uri = f"file:{path or config.DB_PATH}?mode=ro"
    out = []
    with sqlite3.connect(uri, uri=True) as conn:
        for table, (view, date_col) in compat.VIEWS[concept].items():
            out.append(check_table(conn, table, view, date_col, dates, whole, exact))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("concept", choices=compat.CONCEPTS)
    ap.add_argument("--dates", type=int, default=3)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--exact", action="store_true", help="bit-for-bit on REAL columns too")
    a = ap.parse_args()
    bad = 0
    for r in run(a.concept, a.dates, a.all, exact=a.exact):
        ok = r["legacy"] == r["view_rows"] and not r["missing_in_view"] and not r["extra_in_view"]
        bad += not ok
        span = "whole table" if r["dates"] is None else f"{len(r['dates'])} dates {min(r['dates'])}..{max(r['dates'])}" if r["dates"] else "no rows"
        print(f"  {'PASS' if ok else 'FAIL':4s} {r['table']:20s} {span:34s} legacy {r['legacy']:>8,}  view {r['view_rows']:>8,}"
              f"  legacy-only {r['missing_in_view']:,}  view-only {r['extra_in_view']:,}")
        if r["sample"]:
            print(f"       e.g. {r['sample']}")
    print(f"\n{a.concept}: {'PASS' if not bad else f'FAIL ({bad} table(s))'}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
