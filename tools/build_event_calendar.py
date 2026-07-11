"""
Alpha Signal v2 — tools/build_event_calendar.py — event_calendar table (WS4.1, plan 0013 A3).

Normalizes the two in-house, survivorship-safe event types (demerger, buyback) into
one append-only table B1/B2 read. In-house only — no fetch, no scrape (plan 0013 rule 4).

The ONLY DB write in plan 0013: CREATE TABLE IF NOT EXISTS + INSERT OR IGNORE. Never
UPDATE/DELETE/DROP any table (plan 0013 rule 5).

demerger: bse_announcements rows with subcategory IN ('Scheme of Arrangement',
'Amalgamation / Merger / Demerger') AND headline matching demerger/de-merger/demerge
(case-insensitive) — Scheme-of-Arrangement is broader than demergers, the headline
filter isolates them; amalgamation-only schemes without a demerger headline are
excluded by design. sid mapped via tools.sid_crosswalk when the raw column is NULL.

buyback: corporate_actions rows with ind='BUYBACK'. record_date = ex_date (the
in-house record-date PROXY — the true tender record date may differ; B2's study
treats ex_date as day0).

`event_calendar`'s PK (sid, event_type, announce_date) can't dedupe buyback rows on
its own — every buyback row has announce_date=NULL by design, and SQLite (like
standard SQL) treats NULL != NULL in a UNIQUE index, so INSERT OR IGNORE alone would
re-duplicate buybacks on every re-run. Population is idempotent anyway: this script
pre-filters against existing (sid, event_type, record_date) rows before inserting, so
re-running adds 0 rows in practice even though the DB-level PK can't enforce it for
NULL-announce_date rows.

Usage:
    python -m tools.build_event_calendar
"""
from __future__ import annotations

from db import get_db, insert_df, read_sql
from tools.sid_crosswalk import scrip_cd_to_sid

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS event_calendar (
    sid TEXT, event_type TEXT, event_subtype TEXT, announce_date TEXT,
    record_date TEXT, source TEXT, loaded_at TEXT,
    PRIMARY KEY (sid, event_type, announce_date)
);
"""


def _ensure_table():
    with get_db() as conn:
        conn.execute(_CREATE_SQL)


def _demerger_events():
    df = read_sql(
        "SELECT sid, scrip_cd, subcategory, date(dt_tm) AS announce_date FROM bse_announcements "
        "WHERE subcategory IN ('Scheme of Arrangement', 'Amalgamation / Merger / Demerger') "
        "AND dt_tm IS NOT NULL AND ("
        "lower(headline) LIKE '%demerger%' OR lower(headline) LIKE '%de-merger%' "
        "OR lower(headline) LIKE '%demerge%')")

    crosswalk = scrip_cd_to_sid()
    sid = df["sid"].where(df["sid"].notna(), df["scrip_cd"].map(crosswalk))
    out = df.assign(sid=sid).dropna(subset=["sid"])
    return out.rename(columns={"subcategory": "event_subtype"}).assign(
        event_type="demerger", record_date=None, source="bse_announcements")[
        ["sid", "event_type", "event_subtype", "announce_date", "record_date", "source"]]


def _buyback_events():
    df = read_sql(
        "SELECT sid, subject, ex_date FROM corporate_actions "
        "WHERE ind='BUYBACK' AND sid IS NOT NULL AND ex_date IS NOT NULL")
    return df.assign(
        event_type="buyback", event_subtype=df["subject"].fillna(""),
        announce_date=None, record_date=df["ex_date"], source="corporate_actions")[
        ["sid", "event_type", "event_subtype", "announce_date", "record_date", "source"]]


def populate() -> dict:
    """Insert new demerger/buyback rows. Idempotent — see module docstring re: the
    buyback NULL-announce_date PK caveat. Returns {'demerger': n_inserted, 'buyback': n_inserted}."""
    _ensure_table()
    now = read_sql("SELECT datetime('now') AS t")["t"][0]
    existing = read_sql("SELECT sid, event_type, announce_date, record_date FROM event_calendar")
    existing_demerger = set(zip(existing.loc[existing.event_type == "demerger", "sid"],
                                 existing.loc[existing.event_type == "demerger", "announce_date"]))
    existing_buyback = set(zip(existing.loc[existing.event_type == "buyback", "sid"],
                                existing.loc[existing.event_type == "buyback", "record_date"]))

    result = {}
    for event_type, df, key_cols, existing_keys in (
        ("demerger", _demerger_events(), ("sid", "announce_date"), existing_demerger),
        ("buyback", _buyback_events(), ("sid", "record_date"), existing_buyback),
    ):
        keys = list(zip(df[key_cols[0]], df[key_cols[1]]))
        fresh = df.loc[[k not in existing_keys for k in keys]].drop_duplicates(subset=list(key_cols))
        fresh = fresh.assign(loaded_at=now)
        result[event_type] = insert_df(fresh, "event_calendar")
    return result


if __name__ == "__main__":
    counts = populate()
    print(f"event_calendar populated: {counts}")
    print(read_sql("SELECT event_type, COUNT(*) n FROM event_calendar GROUP BY event_type"))
