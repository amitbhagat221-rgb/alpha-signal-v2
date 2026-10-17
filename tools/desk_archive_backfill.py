"""Backfill desk_snapshots from what exists today (plan 0028): the macro mockup's export and the industry explainers.

    python -m tools.desk_archive_backfill --export docs/research/0014-macro-mockup-src/desk_export.json
    python -m tools.desk_archive_backfill --export ... --dry-run

Idempotent: desk_archive.save stores an identical payload only once, so a rerun adds nothing.
Methods: past brief and regime snapshots are 'retrospective' (recomputed from data dated on or before each date);
written content (latest brief verdict, chapters, hot spots, house view, explainers) is 'manual'; computed tables are 'live'.
"""
import argparse
import json
import sys

import db
from output import desk_archive as A


def backfill(export, conn, include_explainers=True):
    n = {}
    def put(part, payload, date, item="", sources=None, method="manual"):
        before = conn.execute("SELECT COUNT(*) FROM desk_snapshots").fetchone()[0]
        A.save(part, payload, date, item=item, sources=sources, method=method, conn=conn)
        after = conn.execute("SELECT COUNT(*) FROM desk_snapshots").fetchone()[0]
        n[part] = n.get(part, 0) + (after - before)

    snaps = export["brief_snapshots"]
    latest = export["brief_today"]["date"]
    for sn in snaps:
        if sn["date"] == latest:
            put("brief", {**sn, "verdict": export["brief_today"]["verdict"], "html": export["brief_today"]["html"]}, sn["date"], method="manual")
        else:
            put("brief", sn, sn["date"], method="retrospective")
        put("regime", {"regime": sn["regime"], "data_month": sn["regime_month"]}, sn["date"], method="retrospective" if sn["date"] != latest else "live")
    hs = export["hotspots"]
    put("hotspots", {k: v for k, v in hs.items() if k != "sources"}, hs["date"], sources=hs["sources"])
    for ch in export["chapters"]:
        put("chapter", {"title": ch["title"], "track": ch["track"], "html": ch["html"]}, export["built"], item=ch["id"], sources=ch["sources"] or None)
    put("external", export["external"], export["built"], sources=[{"title": r["source"], "url": r["url"]} for r in export["external"]])
    put("house_view", export["house_view"], export["built"])
    put("playbook", export["playbook"], export["built"], method="live")
    if include_explainers:
        for sector, payload in conn.execute("SELECT sector, payload FROM sector_metadata WHERE source = 'auto'").fetchall():
            p = json.loads(payload)
            if p.get("explainer"):
                put("industry_explainer", p["explainer"], (p.get("explainer_generated_at") or export["built"])[:10], item=sector)
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="backfill desk_snapshots")
    ap.add_argument("--export", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    export = json.load(open(a.export, encoding="utf-8"))
    with db.get_db() as conn:
        if a.dry_run:
            # validate against the real data without leaving anything behind: the table is created inside the
            # transaction (SQLite DDL is transactional) when it does not exist yet, then everything is rolled back
            conn.execute("BEGIN")
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'desk_snapshots'").fetchone():
                ddl = open(__import__("pathlib").Path(__file__).resolve().parents[1] / "schema.sql").read()
                start = ddl.index("CREATE TABLE IF NOT EXISTS desk_snapshots")
                block = ddl[start:ddl.index(";", ddl.index("CREATE INDEX IF NOT EXISTS idx_desk_snapshots_part")) + 1]
                block = "\n".join(line.split("--")[0] for line in block.splitlines())   # comments may contain ';'
                for stmt in block.split(";"):
                    if stmt.strip():
                        conn.execute(stmt)
            n = backfill(export, conn)
            summ = A.summary(conn=conn)
            conn.rollback()
            print("dry run, nothing kept. Would add rows by part:", n)
            for r in summ:
                print(f"  {r['part']:20} items {r['items']:3}  dates {r['days']:3}  {r['first']} → {r['last']}  rows {r['rows']}")
            return 0
        n = backfill(export, conn)
    print("added rows by part:", n)
    for r in A.summary():
        print(f"  {r['part']:20} items {r['items']:3}  dates {r['days']:3}  {r['first']} → {r['last']}  rows {r['rows']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
