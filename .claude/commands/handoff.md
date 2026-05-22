We're wrapping up.

1. Overwrite `HANDOFF.md` with exactly 3 sections (~15 lines total):

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
     Five mechanical rules:
       a. Phase shipped → flip glyph (⏳→✅) + update "Next 3"
       b. New roadmap-affecting ADR → add line under "Decisions changing roadmap"
       c. Phase deprioritized → glyph to 💤 under its track
       d. Plan archived → strip its items, add 1-line entry under "Recently archived"
       e. Phase started (work begun on a previously-coarse line) → expand it into named sub-items showing the active task with its sub-checklist, plus the queue behind it. Collapse back to a summary line once the phase completes.
     Update "Last updated" date in header. Cross-track parallels (↔) — both sides must agree.
     "Next 3" must name concrete actions with file refs, not generic phase labels.

2. Check: any decisions made today that need an ADR in `docs/decisions/`? Propose them.
3. Check: any plans whose status changed (proposed → active → implemented)? Propose updates.
4. Show me the diff. Don't commit until I approve.

Be specific. Reference real files, commits, tables. No platitudes.
Don't reintroduce "What works" / "Don't do" / "Open questions" — those sections are gone.
