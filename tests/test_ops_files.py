"""Ops wiring is versioned and can't drift silently (architecture review F13).

ops/crontab.txt is the v2 part of the crontab; every line must go through run.sh
(CLAUDE.md) or be the backup script, and name a job run.sh knows. When the live
crontab is readable (on the VM), it must match the committed copy."""
import pathlib
import re
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _v2_lines(text):
    return [l.strip() for l in text.splitlines()
            if l.strip() and not l.lstrip().startswith("#") and "alpha-signal-v2" in l]


def test_every_cron_line_goes_through_run_sh_with_a_known_job():
    jobs = set(re.findall(r"^\s{4}([a-z_]+)\)", (ROOT / "run.sh").read_text(), re.M))
    lines = _v2_lines((ROOT / "ops/crontab.txt").read_text())
    assert lines
    for l in lines:
        m = re.search(r"alpha-signal-v2/run\.sh (\w+)", l)
        assert m or "alpha-signal-v2/backup_db.sh" in l, l
        if m:
            assert m.group(1) in jobs, (m.group(1), sorted(jobs))


def test_live_crontab_matches_the_committed_copy():
    if not shutil.which("crontab"):
        return
    live = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if live.returncode != 0:
        return                                   # not on the VM / no crontab
    assert _v2_lines(live.stdout) == _v2_lines((ROOT / "ops/crontab.txt").read_text()), \
        "crontab changed — update ops/crontab.txt (crontab -l | grep alpha-signal-v2)"


def test_backup_scripts_are_tracked():
    out = subprocess.run(["git", "ls-files", "backup_db.sh", "backup_secrets.sh", "run.sh",
                          "ops/systemd/alpha-cockpit.service"],
                         cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert len(out) == 4, out
