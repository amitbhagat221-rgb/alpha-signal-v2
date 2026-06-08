"""comp-intel CLI.

    python -m comp_intel.cli pull-jobs [--role "market risk"] [--location "Bengaluru, India"]
    python -m comp_intel.cli import-comp <file.csv> [--source levels.fyi]
    python -m comp_intel.cli benchmark [--role "market risk"]
    python -m comp_intel.cli stats
"""

import argparse
import sys
import time
from pathlib import Path

# allow `python -m comp_intel.cli` from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from comp_intel import store, analyze


def cmd_pull_jobs(args):
    from comp_intel.sources import jobs_jobspy
    store.init_db()
    roles = [args.role] if args.role else config.ROLE_QUERIES
    locs = [args.location] if args.location else config.LOCATIONS
    total = 0
    for role in roles:
        for loc in locs:
            try:
                n = jobs_jobspy.pull(role, loc)
                total += n
                print(f"  [{role!r} @ {loc!r}] +{n} new")
            except Exception as e:
                print(f"  [{role!r} @ {loc!r}] ERROR {type(e).__name__}: {str(e)[:90]}")
            time.sleep(3)   # be gentle on the portals
    print(f"\nDone. {total} new postings stored.")


def cmd_import_comp(args):
    from comp_intel.sources import comp_csv
    store.init_db()
    n = comp_csv.import_csv(args.file, source=args.source)
    print(f"Imported {n} comp records from {args.file} (source={args.source}).")


def cmd_benchmark(args):
    analyze.benchmark(role=args.role)


def cmd_stats(args):
    store.init_db()
    import pandas as pd
    with store.get_db() as conn:
        for t in ("jobs", "comp_records"):
            n = pd.read_sql_query(f"SELECT COUNT(*) c FROM {t}", conn)["c"][0]
            print(f"  {t:14s} {n} rows")


def main():
    p = argparse.ArgumentParser(prog="comp-intel", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    pj = sub.add_parser("pull-jobs", help="scrape live postings via JobSpy")
    pj.add_argument("--role"); pj.add_argument("--location")
    pj.set_defaults(func=cmd_pull_jobs)

    ic = sub.add_parser("import-comp", help="import a total-comp CSV export")
    ic.add_argument("file"); ic.add_argument("--source", default="manual")
    ic.set_defaults(func=cmd_import_comp)

    bm = sub.add_parser("benchmark", help="print percentile benchmark")
    bm.add_argument("--role")
    bm.set_defaults(func=cmd_benchmark)

    st = sub.add_parser("stats", help="row counts")
    st.set_defaults(func=cmd_stats)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
