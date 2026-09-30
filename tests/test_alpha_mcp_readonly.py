"""
alpha_mcp read-only guarantee (plan 0016 phase 1): once install_readonly() runs, no
path through db can write — INSERT, UPDATE and DDL all raise — while reads work.
The audit connection may INSERT INTO mcp_calls and nothing else.

install_readonly() swaps process-wide globals, so each check runs in a subprocess
against a fresh schema-built DB (never the live one).
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _schema_db(tmp_path):
    path = tmp_path / "ro.db"
    code = textwrap.dedent("""
        import db
        db.init_db()
        with db.get_db() as c:
            c.execute("INSERT INTO stocks (sid, ticker, name, cap_tier) VALUES ('RELI','RELIANCE','Reliance','LARGE')")
    """)
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True,
                   env={**os.environ, "ALPHA_DB": str(path), "ALPHA_RUNLOG_DB": str(path)})
    return path


def _run(path, code):
    env = {**os.environ, "ALPHA_DB": str(path), "ALPHA_RUNLOG_DB": str(path)}
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=ROOT, env=env,
                          capture_output=True, text=True)


def test_every_write_through_db_raises_after_install_readonly(tmp_path):
    path = _schema_db(tmp_path)
    r = _run(path, """
        from alpha_mcp import _core
        _core.install_readonly()
        import db, views
        assert db.read_sql("SELECT sid FROM stocks").sid.tolist() == ["RELI"]
        assert views.get_db is _core._ro_get_db
        for stmt in ("INSERT INTO stocks (sid, ticker, name) VALUES ('X','X','X')",
                     "UPDATE stocks SET name = 'y'",
                     "DELETE FROM stocks",
                     "CREATE TABLE evil (x)",
                     "DROP TABLE stocks"):
            try:
                with db.get_db() as c:
                    c.execute(stmt)
            except Exception as e:
                assert "readonly" in str(e).lower() or "read-only" in str(e).lower(), (stmt, e)
            else:
                raise SystemExit(f"write succeeded: {stmt}")
        df, err = db.safe_read_sql("SELECT COUNT(*) AS n FROM stocks")
        assert err is None and int(df.n[0]) == 1
        print("OK")
    """)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-2000:]


def test_audit_connection_can_only_insert_into_mcp_calls(tmp_path):
    path = _schema_db(tmp_path)
    r = _run(path, """
        import sqlite3
        from alpha_mcp import _core
        _core.install_readonly()
        _core.audit("research", "picks", {"a": 1}, 3, 12.5)
        import db
        assert db.scalar("SELECT COUNT(*) FROM mcp_calls") == 1
        c = sqlite3.connect(db.DB_PATH)
        c.set_authorizer(_core._audit_authorizer)
        for stmt in ("UPDATE mcp_calls SET tool = 'x'", "DELETE FROM mcp_calls",
                     "INSERT INTO stocks (sid, ticker, name) VALUES ('X','X','X')", "DROP TABLE mcp_calls"):
            try:
                c.execute(stmt)
            except sqlite3.DatabaseError:
                continue
            raise SystemExit(f"audit connection allowed: {stmt}")
        print("OK")
    """)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-2000:]


def test_servers_never_open_the_db_for_write_at_import(tmp_path):
    path = _schema_db(tmp_path)
    before = path.stat().st_mtime_ns
    r = _run(path, """
        import alpha_mcp.research, alpha_mcp.ops
        from alpha_mcp import research as R
        R.search_stocks("REL")
        print("OK")
    """)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-2000:]
    # the only permitted write is the audit row
    import sqlite3
    c = sqlite3.connect(path)
    assert c.execute("SELECT COUNT(*) FROM mcp_calls").fetchone()[0] == 1
    assert c.execute("SELECT COUNT(*) FROM stocks").fetchone()[0] == 1


def test_cap_and_jsonable():
    import math
    import pandas as pd
    from alpha_mcp._core import cap, jsonable
    out = jsonable({"df": pd.DataFrame({"a": [1.0, math.nan], "d": pd.to_datetime(["2026-01-01", None])}),
                    "f": 0.123456789, "big": 1e20})
    assert out["df"][1]["a"] is None and out["df"][0]["d"].startswith("2026-01-01")
    assert out["f"] == 0.123457
    big = {"as_of": "x", "items": [{"k": "v" * 50} for _ in range(10_000)]}
    capped = cap(big, max_chars=20_000)
    assert len(str(capped)) < 25_000 and capped["truncated"]["lists_cut"] == ["items"]
