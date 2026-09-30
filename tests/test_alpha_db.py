"""
ALPHA_DB (plan 0017 stage 0): one env var points every DB path at a copy — config,
db, the DuckDB replica and runlog — so gates and migrations never touch the live DB.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_alpha_db_redirects_every_path(tmp_path):
    target = tmp_path / "copy.db"
    env = {**os.environ, "ALPHA_DB": str(target)}
    env.pop("ALPHA_RUNLOG_DB", None)
    out = subprocess.run(
        [sys.executable, "-c",
         "import config, db, runlog; print(config.DB_PATH); print(db.DB_PATH); "
         "print(db.DUCK_PATH); print(runlog.DB_PATH)"],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout.split()
    assert out == [str(target), str(target), str(target.with_suffix(".duckdb")), str(target)]


def test_regression_fixtures_never_open_the_live_db():
    src = (ROOT / "tools" / "regression_fixtures.py").read_text()
    assert "_use_scratch_db()" in src.split("def main():")[1]
