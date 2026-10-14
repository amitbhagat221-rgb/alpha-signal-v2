---
paths:
  - "checks/**"
  - "validators/**"
  - "views.py"
  - "health.py"
  - "tools/health_report.py"
  - "tools/freshness_watchdog.py"
  - "tools/data_sanity.py"
  - "tools/dq_probes.py"
  - "tests/test_check_drills.py"
  - "tests/test_checks.py"
---
# Health checks

**One state, many surfaces (ADR 0059)**
- Daily health email 04:00 UTC + URGENT push on CRITICAL (ntfy via `NTFY_TOPIC` in `~/.config/alpha-signal/secrets.env`; without it the URGENT email still fires). `tools/health_report.py` feeds terminal, email, push, MCP and the ops page.
- Every check answers ONE of the five questions in `checks.THEMES` and declares `theme` / `message` / `why` / `fix` in plain words, on the check itself (`checks/custom.py`, or `checks/system.SYSTEM_CHECKS`; a system area is one `(facts, verdicts)` pair in `checks/system.AREAS`).
- `checks/report.gather()` builds the ONE state; a surface renders it and never decides severity itself. `python -m tools.health_report --catalog` lists every check. Reference: [health-checks](../../docs/reference/health-checks.md).

**A check must be able to fail (ADR 0060)**
- A daily check fails today because the world changed, and proves it with a fire drill in `tests/test_check_drills.py` (the suite fails without one). A rule that only breaks when code or a registry changes is a test, not a check.
- Factor checks read what the ranking used (`checks/model.py`, scope from `factors.SIGNAL_WEIGHTS`) — never hand-list factors. Catalog capped at 30. The picks email runs the `picks` checks before sending and carries a banner when one fails.
- `freshness_watchdog` covers DB tables AND file outputs (`config.FILE_OUTPUTS`).

**Per-pick wording (ADR 0061)**
- The per-pick number is `eligible_coverage`, worded only by `views.pick_data` ("Data 84% · Partial"); thresholds in `config.PICK_GATE`. UHS and gates 3–7 are retired.
- A stored analyst target is judged by ONE check, `ANALYST_TARGET_IMPLAUSIBLE` (rules in `validators/plausibility.py`: `PT_CLOSE_RATIO` and the average inside its own low–high), applied at both writers and in the check.
