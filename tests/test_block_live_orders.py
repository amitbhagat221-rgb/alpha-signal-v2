"""The hook that stops Claude running a live order step (.claude/hooks/block_live_orders.py)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "block_live_orders.py"


def rc(command):
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"tool_input": {"command": command}}), text=True,
                          capture_output=True).returncode


@pytest.mark.parametrize("command", [
    "./run.sh options_live closeall 2>&1 | tail -6",
    "cd x && /home/ubuntu/alpha-signal-v2/run.sh options_live entry NIFTY",
    "python -m options_live buyback --underlying NIFTY",
    "curl -X POST http://127.0.0.1:3001/api/options/live/closeall",
    "curl https://api.kite.trade/orders/regular -d x",
    "python -c 'import options_live as o; o.spawn_closeall()'",
    "python -m options_live set kill false",
    "python -m options_live set mode '\"auto\"'",
])
def test_blocked(command):
    assert rc(command) == 2


@pytest.mark.parametrize("command", [
    "./run.sh options_live record",
    "./run.sh options_live reconcile",
    "./run.sh options_live mark",
    "./run.sh options_live precheck",
    "python -m options_live set lots_cap '{\"NIFTY\": 5}'",
    "git commit -m 'options_live closeall fix'",
    "grep -n 'options_live closeall' HANDOFF.md",
    "python -m pytest tests/test_options_live.py",
])
def test_allowed(command):
    assert rc(command) == 0
