#!/usr/bin/env python3
"""PreToolUse (Bash): Claude may not run a live order step. Only Amit and the scheduled jobs may (2026-11-03: a Close-all
Claude started without approval placed real orders even though the tool reported the call as rejected). Exit 2 blocks.
The second lock is sources/kite_pull.kite(): inside a Claude session its client refuses every broker write."""
import json
import re
import sys

BLOCKED = (
    r"options_live\s+(?:--\S+\s+)*(entry|buyback|closeall|testorder|amo)\b",   # run.sh options_live closeall, -m options_live entry
    r"/api/options/orders/(arm|fire)\b",                                   # arming or firing the AMO is Amit's
    r"\b(arm_amo|spawn_amo_if_armed)\s*\(",
    r"/api/options/live/(closeall|approve|resume)\b",                      # the cockpit's order and resume buttons
    r"api\.kite\.trade/(orders|gtt)",                                      # Kite's order API directly
    r"\b(run_step|STEPS\[)\s*\(?\s*[\"'](entry|buyback|closeall|testorder)",
    r"\bspawn_closeall\s*\(",
    r"options_live\s+set\s+(kill|mode)\b",                                 # the kill switch and mode are Amit's
    r"set_setting\(\s*[\"'](kill|mode)[\"']",
    r"\bset_kill\s*\(",
)


def main():
    try:
        command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    except ValueError:
        return 0
    if re.match(r"\s*(git|grep|rg|sed -n|cat|head|tail|ls)\b[^;&|]*$", command):    # reading or committing is not running
        return 0
    if command.lstrip().startswith(("python3 - <<", "cat >")) and "pytest" not in command and re.search(r"\.write\(|open\(.*[\"']w|cat >", command):
        return 0                                                            # editing source that names these steps
    for pattern in BLOCKED:
        if re.search(pattern, command):
            print(f"BLOCKED: live order steps, the kill switch and the mode are Amit's only ({pattern}). "
                  "Show him the numbers and let him act.", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
