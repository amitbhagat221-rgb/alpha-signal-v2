"""Plan 0030: test rows for the Decisions concept go in the way production writes them — the legacy
table and, through datamodel/decisions.py, the v3 tables — so a reader under either flag sees them
and the offline suite exercises the writers. A hand-built test schema gets the v3 tables and the
compatibility views from the v3 part of schema.sql."""
import sqlite3

import pandas as pd

import db
from datamodel import decisions

V3_MARK = "-- Data model v3"
_DATE = {"daily_picks": "pick_date", "portfolio_weights": "asof_date"}


def v3_schema(conn):
    """The v3 tables + compatibility views (IF NOT EXISTS) on a DB built by hand."""
    text = db.SCHEMA_PATH.read_text()
    i = text.index(V3_MARK)
    conn.executescript(text[text.rfind("\n", 0, i) + 1:])


def _conn(target):
    if isinstance(target, sqlite3.Connection):
        return target, False
    return sqlite3.connect(target), True


def seed(target, table, rows):
    """`rows` (dicts or tuples with `cols`) into a legacy Decisions table and its v3 twin. `target`: a
    connection or a DB path. Commits when it opened the connection."""
    conn, own = _conn(target)
    frame = pd.DataFrame(rows)
    db.upsert_df(frame, table, conn=conn)
    if table == "pick_outcomes":
        decisions.write_pick_outcomes(conn, frame)
    elif table == "portfolio_outcomes":
        decisions.write_portfolio_outcomes(conn, frame)
    else:
        dcol = _DATE[table]
        for d, g in frame.groupby(dcol):
            existing = pd.read_sql_query(f"SELECT * FROM {table} WHERE {dcol} = ?", conn, params=[d])
            if table == "daily_picks":
                decisions.write_picks(conn, d, existing)
            else:
                decisions.write_book_weights(conn, d, existing)
    if own:
        conn.commit()
        conn.close()


def clear(conn, table="daily_picks"):
    """Empty a legacy Decisions table and the v3 rows that stand for it."""
    conn.execute(f"DELETE FROM {table}")
    conn.execute({"daily_picks": "DELETE FROM picks", "portfolio_weights": "DELETE FROM book_weights",
                  "pick_outcomes": "DELETE FROM outcomes WHERE entity_id IN (SELECT entity_id FROM entities WHERE kind='security')",
                  "portfolio_outcomes": "DELETE FROM outcomes WHERE entity_id IN (SELECT entity_id FROM entities WHERE kind='portfolio')"}[table])
