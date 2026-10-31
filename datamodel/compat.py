"""
Data model v3 read switch (plan 0030, ADR 0084): compatibility views and the per-concept flag.

Each legacy table of a switched concept has a view `v3_<table>` over the v3 tables that
reproduces it column for column (same names, same order, same types). A reader never
changes its SQL: when `config.DATA_MODEL[<concept>]` is "new", the read helpers in
`db` (read_sql, rows, one, scalar) and `views.native_rows` rewrite the legacy name to
the view name. Flip the flag back and every reader is on the legacy table again.

Writers are not touched: the producers keep writing the legacy tables and
`datamodel/sync.py` mirrors them, until the stage's drop commit (≥ 14 days after the
switch, after a Parquet export).

    python -m datamodel.compat --ensure      # create the views on config.DB_PATH (idempotent DDL; db.init_db does it too)
    python -m datamodel.gate decisions       # parity: legacy vs view on the newest dates

Stage 1 (Decisions): daily_picks, pick_outcomes, portfolio_weights, portfolio_outcomes.
pipeline_log stays legacy: step_runs holds terminal rows only (RUNNING rows are collapsed),
so a view cannot reproduce it; its readers move by rewrite in stage 1 part 2.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

# concept → {legacy table: (view name, date column of the legacy table)}; the view bodies live in
# schema.sql (one definition, so a DB built from the schema carries them) and are read by body().
VIEWS = {
    "decisions": {
        "daily_picks": ("v3_daily_picks", "pick_date"),
        "pick_outcomes": ("v3_pick_outcomes", "pick_date"),
        "portfolio_weights": ("v3_portfolio_weights", "asof_date"),
        "portfolio_outcomes": ("v3_portfolio_outcomes", "asof_date"),
    },
}

_BODY = re.compile(r"CREATE VIEW IF NOT EXISTS (v3_\w+) AS\n(.*?);\n", re.S)


def bodies():
    """{view name: SELECT body} from schema.sql."""
    return dict(_BODY.findall(config.SCHEMA_PATH.read_text()))


def body(view):
    try:
        return bodies()[view]
    except KeyError:
        raise KeyError(f"{view}: no CREATE VIEW in schema.sql") from None


CONCEPTS = tuple(VIEWS)


def legacy_tables(concept):
    return tuple(VIEWS[concept])


def view_name(table):
    for concept in VIEWS.values():
        if table in concept:
            return concept[table][0]
    return None


def _switched():
    """{legacy table: view} for every concept whose flag is 'new'."""
    out = {}
    for concept, tables in VIEWS.items():
        if config.DATA_MODEL.get(concept) == "new":
            out.update({t: v for t, (v, _d) in tables.items()})
    return out


_READ = re.compile(r"^\s*(WITH|SELECT)\b", re.I)


def rewrite(sql):
    """A read statement with every switched legacy name replaced by its view. Writes,
    PRAGMAs and names inside identifiers are left alone; with no concept switched the
    statement is returned as it is (no cost on the default path)."""
    sw = _switched()
    if not sw or not isinstance(sql, str) or not _READ.match(sql):
        return sql
    pat = re.compile(r"(?<![\w.\[\"'])(" + "|".join(map(re.escape, sw)) + r")(?![\w\]\"'])")
    return pat.sub(lambda m: sw[m.group(1)], sql)


def resolve(table):
    """The name a reader should use for `table` today: the view when its concept is 'new'."""
    return _switched().get(table, table)


def ddl():
    """CREATE VIEW statements for every compatibility view (all concepts, idempotent)."""
    return [f"CREATE VIEW IF NOT EXISTS {v} AS {body(v)}" for tables in VIEWS.values() for v, _d in tables.values()]


def ensure_views(conn):
    for stmt in ddl():
        conn.execute(stmt)


def main():
    import argparse
    import sqlite3
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ensure", action="store_true", help="create the views on config.DB_PATH")
    ap.add_argument("--show", action="store_true", help="print the DDL")
    a = ap.parse_args()
    if a.show or not a.ensure:
        print(";\n\n".join(ddl()) + ";")
        print(f"\nflags: {config.DATA_MODEL}")
        return
    with sqlite3.connect(str(config.DB_PATH), timeout=60) as conn:
        ensure_views(conn)
    print(f"views ensured on {config.DB_PATH}: " + ", ".join(v for t in VIEWS.values() for v, _d in t.values()))


if __name__ == "__main__":
    main()
