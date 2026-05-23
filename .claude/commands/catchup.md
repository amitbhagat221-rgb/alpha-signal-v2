Read `HANDOFF.md`. Read `docs/plans/0000-checklist.md`. Read the active plan it points to in `docs/plans/`.
Run `git status` and `git log --oneline -5`.

Run `python -m tools.health_report` and put its output verbatim at the very top of the report (before sections 1-4). This is the system pulse — if it shows CRITICAL issues, name them in **Watch out** explicitly.

Then in 4 short sentences:
1. **Left off** — where I am
2. **Pick up** — the next concrete action
3. **Watch out** — anything blocking or non-obvious (incl. any CRITICAL from health report)
4. **This session** — name the specific checklist item(s) we're working on (quote the bullet + its parent phase, e.g. "Track 3.2 → cash_conversion_cycle → signals/cash_conversion_cycle.py"). If the session goal isn't already a bullet on the checklist, say so explicitly so we can decide whether to add it before starting.

Flag if HANDOFF.md is older than 48 hours or git is dirty unexpectedly.
Don't propose work yet — situation report only.
