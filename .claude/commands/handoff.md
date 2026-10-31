We're wrapping up.

0. Know your scope. Concurrent sessions share this tree, so `git status` mixes your work with
   theirs. From this conversation's own edits (Edit/Write/shell), list every path YOU changed
   and, for files others also touch (`HANDOFF.md`, the checklist, `CLAUDE.md`, `schema.sql`,
   `tables.py`, `feeds.py`, `cockpit/*`), which hunks are yours. Everything else is another
   session's: never stage, revert, stash, reset, checkout, reformat or "tidy" it. Unsure whether
   a hunk is yours → ask; never guess.

1. Update `HANDOFF.md` — merge, don't overwrite: it is shared. Re-read it right before writing;
   keep every other session's line that is still true, replace or drop only lines your work
   changed. Keep the shape (~15 lines of your own; prefix a line with your topic when several
   sessions are live):

   ```
   # HANDOFF
   Updated: YYYY-MM-DD | Branch: X (N unpushed) | HEAD: <sha> <subject>

   ## Left off
   2 sentences. The thing in your head when you closed the laptop.

   ## Pick up here
   1. Concrete next action with file ref
   2. Concrete next action with file ref
   3. Concrete next action with file ref

   ## Watch out
   - NEW gotchas only (carried-forward rules belong in CLAUDE.md)
   - Things git/code can't tell you

   ## Active plan
   docs/plans/NNNN-name.md (phase X)
   ```

1.5. Update `docs/plans/0000-checklist.md` to reflect anything that moved this session.
     Re-read it first (other sessions edit it too) and touch only your own bullets.
     Five mechanical rules:
       a. Phase shipped → flip glyph (⏳→✅) + update "Next 3"
       b. New roadmap-affecting ADR → add line under "Decisions changing roadmap"
       c. Phase deprioritized → glyph to 💤 under its track
       d. Plan archived → strip its items, add 1-line entry under "Recently archived"
       e. Phase started (work begun on a previously-coarse line) → expand it into named sub-items showing the active task with its sub-checklist, plus the queue behind it. Collapse back to a summary line once the phase completes.
     Update "Last updated" date in header. Cross-track parallels (↔) — both sides must agree.
     "Next 3" must name concrete actions with file refs, not generic phase labels.

1.6. Rules budget (CLAUDE.md "Keeping this file small"). A new landmine from this session goes
     where it belongs: `CLAUDE.md` only if any session could hit it, else the `.claude/rules/`
     file whose `paths:` cover the files involved — one clause + the ADR/test that holds the story.
     Then run `PYTHONPATH=.devlib python -m pytest -q -p no:cacheprovider tests/test_claude_md.py`.
     If it fails, rotate before committing: demote the least general CLAUDE.md rule to its area
     file, fold a rule now enforced by a test into "X — `tests/test_Y.py`", or merge two. Never
     drop a rule outright; report the word counts (CLAUDE.md + each area file) in the summary.

2. Check: any decisions made today that need an ADR in `docs/decisions/`? Propose them.
3. Check: any plans whose status changed (proposed → active → implemented)? Propose updates.
4. Stage your scope, then show me `git diff --cached --stat`, the staged diff, and the list of
   dirty paths you are deliberately leaving for other sessions. **Approval tiers (ADR 0086):** if
   the scope holds a Tier A path — `options_live.py`, `option_book.py`, the Kite order path,
   `factors.py` weight hunks, `config.py` (TIERS / PICK_GATE / MB_THESIS / weights), `run.sh`,
   `ops/crontab.txt`, a `schema.sql` drop, a migration that deletes or rewrites rows, secrets,
   a `datamodel` read switch of a ranking stage — don't commit until I approve. Otherwise
   (Tier B / C: code, data fixes with a measured pick diff, pages, probes, tests, docs) commit as
   soon as the pre-push suite passes and say so in the handoff; I veto by revert.
   Staging, own scope only:
   - A file only you changed: `git add -- <path>` (explicit paths; never `.`/`-A`/`-u`/a directory).
   - A shared file that also holds another session's hunks: stage only yours —
     `git diff -- <file> > <scratchpad>/own.patch`, delete the other session's hunks from the
     patch, `git apply --cached --recount <scratchpad>/own.patch`, check `git diff --cached -- <file>`.
     The working tree keeps their edits untouched.
   - If the index already held something before you staged (another session mid-commit): never
     commit it and never unstage it. Message that session first (`ListAgents`, then `SendMessage`:
     "commit or unstage X, I need to commit Y"). No answer in 10 minutes → commit through a
     temporary index so theirs stays exactly as it is:
     `export GIT_INDEX_FILE=<scratchpad>/idx && git read-tree HEAD && git add -- <own files> &&
     git apply --cached --recount <scratchpad>/own.patch && T=$(git write-tree) &&
     C=$(git commit-tree $T -p HEAD -F <scratchpad>/msg) && unset GIT_INDEX_FILE &&
     git update-ref HEAD $C`. Then, for each of YOUR files that nobody else had staged,
     `git reset -q -- <path>` so the shared index matches the new HEAD; for a shared file with
     their staged hunk, leave the index alone and tell them in HANDOFF.md "Watch out" that the
     index for <file> predates <sha> (they re-stage with `git diff --cached` → patch → `git reset
     -q -- <file>` → `git apply --cached`). Tier A scope still waits for me either way.
5. On approval: re-check `git diff --cached --name-only` is exactly your scope (another session
   may have staged since), then commit at once (subject line scoped per recent `git log` style,
   e.g. `feat(signals):` / `docs:` / `refactor:`). Never `git commit -a` or `git commit -- <path>`
   (both take the whole file, other sessions' hunks included). Body summarizes what shipped +
   what moved on the checklist. Co-Authored-By trailer per the global template. Then
   `git push origin <current-branch>`.
   - Never `--force` to master. Never `--no-verify`. Investigate pre-commit hook failures rather than bypassing.
   - Push rejected (another session pushed first)? Stop and report; never rebase, merge or stash over a shared dirty tree.
   - If the session touched code + docs + ADRs and they're logically separate, split into two commits (code first, then docs) — but a single commit is fine for cohesive sessions.

Be specific. Reference real files, commits, tables. No platitudes.
Don't reintroduce "What works" / "Don't do" / "Open questions" — those sections are gone.
