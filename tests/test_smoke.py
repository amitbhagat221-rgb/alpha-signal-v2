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


def test_news_published_at_parses():
    """Catches the sentiment bug: published_at can be ISO8601 with 'T' or space-separated."""
    import pandas as pd
    from db import read_sql
    df = read_sql("SELECT published_at FROM news_articles WHERE published_at IS NOT NULL LIMIT 5000")
    if df.empty:
        return  # no news yet — not a regression
    pd.to_datetime(df["published_at"], format="ISO8601")  # raises if any row malformed


if __name__ == "__main__":
    tests = [
        ("modules import", test_all_pipeline_modules_import),
        ("dry-run executes", test_dry_run_executes),
        ("critical steps marked", test_critical_steps_marked),
        ("news published_at parses", test_news_published_at_parses),
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
