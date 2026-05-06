"""
Smoke test: import every pipeline module and verify the orchestrator can dry-run.

Run:  python -m tests.test_smoke
or:   pytest tests/test_smoke.py

This is the cheapest test that would have caught the two bugs found during the v2
transition (stale architecture doc claiming fetchers were unbuilt; sentiment.py
breaking on ISO8601 published_at strings). It does NOT execute fetchers or
signals — it only ensures imports + step registration are intact.
"""
import importlib
import subprocess
import sys

from config import PIPELINE_STEPS


def test_all_pipeline_modules_import():
    """Every module referenced in PIPELINE_STEPS must import and expose its function."""
    failed = []
    for step in PIPELINE_STEPS:
        try:
            mod = importlib.import_module(step["module"])
            assert hasattr(mod, step["function"]), (
                f"{step['module']} missing function '{step['function']}'"
            )
        except Exception as e:
            failed.append(f"{step['name']} ({step['module']}): {type(e).__name__}: {e}")
    assert not failed, "Module import failures:\n" + "\n".join(failed)


def test_dry_run_executes():
    """`python pipeline.py --dry-run` must exit 0 and list all configured steps."""
    result = subprocess.run(
        [sys.executable, "pipeline.py", "--dry-run"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"dry-run failed: {result.stderr}"
    out = result.stdout + result.stderr
    for step in PIPELINE_STEPS:
        assert step["name"] in out, f"step '{step['name']}' missing from dry-run output"


def test_critical_steps_marked():
    """The three critical steps (bhavcopy, quality_gate, screener) must stay critical."""
    by_name = {s["name"]: s for s in PIPELINE_STEPS}
    for name in ("fetch_bhavcopy", "quality_gate", "screener"):
        assert by_name[name]["critical"], f"step '{name}' must be critical=True"


def test_flow_overview_returns_layers_and_failures():
    """get_flow_overview() must return the layered structure the /flow page
    iterates over — and a `failures` list that excludes healthy steps."""
    from cockpit.api import get_flow_overview
    overview = get_flow_overview()
    assert "layers" in overview and isinstance(overview["layers"], list)
    assert "failures" in overview and isinstance(overview["failures"], list)
    assert overview["step_count"] == sum(len(l["steps"]) for l in overview["layers"])
    for f in overview["failures"]:
        assert f["last_status"] in ("FAILED", "ABORTED")


def test_rerun_step_rejects_unknown_step():
    """rerun_step must refuse to spawn a subprocess for a step name not in PIPELINE_STEPS."""
    from cockpit.api import rerun_step
    result = rerun_step("definitely_not_a_real_step")
    assert result["ok"] is False
    assert "unknown step" in result["error"].lower()


def test_news_published_at_parses():
    """Catches the sentiment bug: published_at can be ISO8601 with 'T' or space-separated."""
    import pandas as pd
    from db import read_sql
    df = read_sql("SELECT published_at FROM news_articles WHERE published_at IS NOT NULL LIMIT 5000")
    if df.empty:
        return  # no news yet — not a regression
    pd.to_datetime(df["published_at"], format="ISO8601")  # raises if any row malformed


def test_upsert_df_preserves_untouched_columns():
    """Catches the upsert_df bug fixed in 88a2fa9: a partial column write
    (e.g. `reconstruct_pit --signal X`) must not null the other columns
    sharing the same PK row. Verifies INSERT ... ON CONFLICT DO UPDATE is in
    effect, not the legacy INSERT OR REPLACE path."""
    import sqlite3
    import pandas as pd
    from db import upsert_df, _PK_CACHE

    conn = sqlite3.connect(":memory:")
    table = "_upsert_regression_test"
    _PK_CACHE.pop(table, None)  # avoid stale cache from any prior run
    conn.executescript(f"""
        CREATE TABLE {table} (
            sid TEXT,
            snapshot_date TEXT,
            col_a REAL,
            col_b REAL,
            PRIMARY KEY (sid, snapshot_date)
        );
    """)

    upsert_df(
        pd.DataFrame([{"sid": "X", "snapshot_date": "2026-05-01", "col_a": 1.0, "col_b": 2.0}]),
        table, conn=conn,
    )
    upsert_df(
        pd.DataFrame([{"sid": "X", "snapshot_date": "2026-05-01", "col_a": 99.0}]),
        table, conn=conn,
    )

    row = conn.execute(f"SELECT col_a, col_b FROM {table}").fetchone()
    assert row == (99.0, 2.0), f"col_b nulled by partial upsert: got {row}"
    _PK_CACHE.pop(table, None)
    conn.close()


if __name__ == "__main__":
    tests = [
        ("modules import", test_all_pipeline_modules_import),
        ("dry-run executes", test_dry_run_executes),
        ("critical steps marked", test_critical_steps_marked),
        ("flow overview shape", test_flow_overview_returns_layers_and_failures),
        ("rerun rejects unknown step", test_rerun_step_rejects_unknown_step),
        ("news published_at parses", test_news_published_at_parses),
        ("upsert_df preserves untouched cols", test_upsert_df_preserves_untouched_columns),
    ]
    failed = 0
    for label, fn in tests:
        try:
            fn()
            print(f"  ✓  {label}")
        except AssertionError as e:
            print(f"  ✗  {label}  — {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗  {label}  — {type(e).__name__}: {e}")
            failed += 1
    sys.exit(1 if failed else 0)
