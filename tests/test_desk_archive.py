"""desk_snapshots: append-only, versioned, as-of reads (plan 0028)."""
import sqlite3
from pathlib import Path

import pytest

from output import desk_archive as A

SCHEMA = Path(__file__).resolve().parents[1] / "schema.sql"


@pytest.fixture()
def conn(tmp_path):
    c = sqlite3.connect(tmp_path / "t.db")
    ddl = SCHEMA.read_text()
    start = ddl.index("CREATE TABLE IF NOT EXISTS desk_snapshots")
    end = ddl.index(";", ddl.index("CREATE INDEX IF NOT EXISTS idx_desk_snapshots_part")) + 1
    c.executescript(ddl[start:end])
    yield c
    c.close()


def test_save_is_append_only_and_idempotent(conn):
    assert A.save("brief", {"verdict": "a"}, "2026-10-12", conn=conn) == 1
    assert A.save("brief", {"verdict": "a"}, "2026-10-12", conn=conn) == 1          # identical: no new row
    assert A.save("brief", {"verdict": "b"}, "2026-10-12", conn=conn) == 2          # changed: new version, old kept
    assert conn.execute("SELECT COUNT(*) FROM desk_snapshots").fetchone()[0] == 2


def test_latest_reads_as_of(conn):
    A.save("brief", {"v": 1}, "2026-10-05", conn=conn)
    A.save("brief", {"v": 2}, "2026-10-12", conn=conn)
    A.save("brief", {"v": 3}, "2026-10-16", conn=conn, sources=[{"title": "x", "url": "https://example.org"}])
    assert A.latest("brief", as_of="2026-10-11", conn=conn)["payload"] == {"v": 1}
    assert A.latest("brief", as_of="2026-10-12", conn=conn)["payload"] == {"v": 2}
    top = A.latest("brief", conn=conn)
    assert top["payload"] == {"v": 3} and top["sources"][0]["url"] == "https://example.org"
    assert A.latest("brief", as_of="2026-09-01", conn=conn) is None
    assert A.dates("brief", conn=conn) == ["2026-10-05", "2026-10-12", "2026-10-16"]


def test_items_are_separate(conn):
    A.save("chapter", {"t": "rbi"}, "2026-10-17", item="in-4", conn=conn)
    A.save("chapter", {"t": "oil"}, "2026-10-17", item="in-5", conn=conn)
    assert A.latest("chapter", "in-4", conn=conn)["payload"] == {"t": "rbi"}
    assert A.dates("chapter", "in-5", conn=conn) == ["2026-10-17"]
    s = {r["part"]: r for r in A.summary(conn=conn)}
    assert s["chapter"]["items"] == 2


def test_unknown_part_or_method_raises(conn):
    with pytest.raises(ValueError):
        A.save("brieff", {}, "2026-10-17", conn=conn)
    with pytest.raises(ValueError):
        A.save("brief", {}, "2026-10-17", method="guess", conn=conn)


def test_backfill_is_idempotent(conn):
    from tools.desk_archive_backfill import backfill
    export = {"built": "2026-10-17",
              "brief_snapshots": [{"date": "2026-10-12", "regime": "Reflation", "regime_month": "2026-08", "oil": "red"},
                                  {"date": "2026-10-16", "regime": "Reflation", "regime_month": "2026-08", "oil": "red"}],
              "brief_today": {"date": "2026-10-16", "verdict": "v", "html": "<p>x</p>"},
              "hotspots": {"date": "2026-10-17", "rows": [], "sources": [{"title": "t", "url": "https://e.org"}]},
              "chapters": [{"id": "in-4", "track": "India", "title": "RBI", "html": "<p>r</p>", "sources": []}],
              "external": [{"reading": "r", "value": "v", "source": "s", "url": "https://e.org", "checked": "2026-10-17"}],
              "house_view": [{"case": "base"}], "playbook": {"oil": {}}}
    first = backfill(export, conn, include_explainers=False)
    assert first["brief"] == 2 and first["chapter"] == 1 and first["regime"] == 2
    second = backfill(export, conn, include_explainers=False)
    assert sum(second.values()) == 0
    assert A.latest("brief", as_of="2026-10-13", conn=conn)["method"] == "retrospective"
    assert A.latest("brief", conn=conn)["payload"]["verdict"] == "v"
