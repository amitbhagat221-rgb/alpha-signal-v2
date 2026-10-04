Run work order $ARGUMENTS from the Boardroom (plan 0019). A work order is the list of fixes Amit and one of his agent
employees agreed in chat; he has approved it in the inbox.

1. Read it: `python -m org work $ARGUMENTS` (venv active). It prints the items (title, what, where, done_when, owner,
   size), the open questions, the status, and the chat it came from. Read the chat: it is the context for the items.
   If no number was given, run `python -m org work` and ask which one.
2. If its status is not `approved`, `in_progress` or `blocked`, stop and say so. Amit approves work orders on the ops
   cockpit `/org` inbox (or `python -m org decide <doc_id> approve`). Never approve one yourself.
3. Add a bullet for it to `docs/plans/0000-checklist.md` (rule: checklist before work), then
   `python -m org work $ARGUMENTS --status in_progress`.
4. Do the items in order. For each one, start its `owner` builder agent (Agent tool, `subagent_type` = the owner seat:
   quant-researcher, data-engineer, backend-engineer, frontend-engineer or system-architect, with worktree isolation)
   and give it the item's title, what, where and done_when plus the relevant part of the chat. A size-S item you may do
   yourself. Every CLAUDE.md rule applies: no weight or production-default change, no cron or credential change, never
   two harvesters, no write to the live DB beyond what the item names (ask first for a backfill).
5. Check each item against its `done_when`, then run the suite:
   `PYTHONPATH=.devlib python -m pytest -q -p no:cacheprovider tests/`.
6. Report per item: done or not, files changed, how `done_when` was checked, test result. Do not commit or merge unless
   Amit asks. If an open question blocks an item, leave it and say so.
7. Record the outcome: `python -m org work $ARGUMENTS --status done --note "<one line per item>"`, or
   `--status blocked --note "<what is in the way>"`. The Boardroom's Work tab shows it.
