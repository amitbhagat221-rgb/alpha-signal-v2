"""
Data model v3 — retire a legacy table (plan 0017, "rule for the drop step").

Exports the whole table to data/history/legacy/<table>.parquet, reads the file back and
checks it equals the table, records rows / sha256 / the CREATE statements in
data/history/legacy/manifest.json, and only then (with --drop) drops the table. The
schema.sql / tables.TABLES entries are removed in the same commit by hand.

    python -m datamodel.retire paper_trades paper_positions            # export + verify only
    python -m datamodel.retire paper_trades paper_positions --drop     # ... then drop

Restore: pd.read_parquet(path).to_sql(table, conn) after re-running the manifest's `create`.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

OUT = config.DB_PATH.parent / "history" / "legacy"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def export(c, table, out=OUT):
    """Write table → parquet, verify the round trip, return its manifest entry. Raises on any mismatch."""
    create = [r[0] for r in c.execute("SELECT sql FROM sqlite_master WHERE tbl_name=? AND sql IS NOT NULL ORDER BY type DESC", (table,))]
    if not create:
        raise SystemExit(f"{table}: no such table")
    df = pd.read_sql(f'SELECT * FROM "{table}"', c)
    as_text = []
    for col in df.columns:   # a column holding mixed types cannot be one parquet type: keep it, as text
        if df[col].dtype == object and df[col].dropna().map(type).nunique() > 1:
            df[col] = df[col].map(lambda v: None if v is None else str(v))
            as_text.append(col)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{table}.parquet"
    df.to_parquet(path, index=False)
    back = pd.read_parquet(path)
    pd.testing.assert_frame_equal(df, back, check_dtype=False)
    n = c.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    if n != len(back):
        raise SystemExit(f"{table}: {n} rows in the table, {len(back)} in the export")
    return {"rows": n, "file": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size, "create": create,
            "cast_to_text": as_text, "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tables", nargs="+")
    ap.add_argument("--drop", action="store_true", help="drop each table after its export is verified")
    a = ap.parse_args(argv)
    c = sqlite3.connect(str(config.DB_PATH), timeout=60)
    c.execute("PRAGMA busy_timeout=60000")
    mpath = OUT / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    for t in a.tables:
        entry = export(c, t)
        manifest[t] = entry
        mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True))
        print(f"{t}: {entry['rows']} rows → {entry['file']} ({entry['bytes']} bytes, sha256 {entry['sha256'][:12]}), verified")
    if a.drop:
        with c:
            for t in a.tables:
                c.execute(f'DROP TABLE "{t}"')
                manifest[t]["dropped_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                print(f"{t}: dropped")
        mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
