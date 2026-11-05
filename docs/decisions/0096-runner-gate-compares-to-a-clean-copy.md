# ADR 0096 — The unattended runner merges on "no new failures", and leaves data and ranking work to a session

**Status:** accepted 2026-11-05 (Amit: "why are work orders not being executed … whats the point" → "yes fix all"). Amends ADR 0091's merge gate; plan [0032](../plans/0032-janitor-routines.md) stage 7.

## Decision
- **The suite gate compares against a clean copy.** Before judging an order, the runner runs the suite on an untouched worktree of the same commit; it blocks only on failures that copy does not have, re-run once to rule out a flake. A stray `data/` in a worktree is removed first.
- **The real-data check stays the pre-push suite.** If it refuses the push, the merge is reverted, so unverified code never stays on master.
- **Attempts are charged only for the order's own failures.** No Claude login, a suite that did not finish, another session's edits, a merge that would not apply or a refused push are the runner's faults: free, but capped at 5 starts. A crash leaves the order retryable. `--reset N` gives attempts back; only a person runs it.
- **Live-data work stays with a session.** Orders from the dq-auditor, or with a data-engineer or quant-researcher item, are refused: the worktree has no database.
- **The ranking's code is never merged unattended.** `signals/`, `scoring/`, `eligibility/`, `pit.py` and `portfolio_construction.py` need a pick diff on real data. An item there is left, the rest of the order proceeds; an order with nothing else is refused.
- **`--verify` runs everything up to the merge,** so a rule change can be proved on a real order first.

## Why
- ADR 0091 required the full suite to pass in a worktree. It cannot: measured 2026-11-05, clean master fails 35 tests there because there is no database. All four attempts on orders #2 and #3 stopped at that gate and used up their tries; nothing could ever merge. The check was never tried on a clean tree before it was relied on.
- Order #3's extra 14 failures came from an empty database its own test run left behind (14 fewer skips), not from its change.
- Proof: `--order 3 --verify` on 2026-11-05: 36 failures on the clean copy, 36 with the order, none new; 7 files, the two `signals/` items left. Merged by a session after importing every changed tool.

## Consequences
- A night costs one more suite run (about 9 minutes) per master commit.
- Tests that fail on the clean copy cannot catch an order's bug, which is why the pre-push suite remains the final check.
