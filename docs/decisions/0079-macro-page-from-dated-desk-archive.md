# 0079 — The macro page is assembled from a dated, append-only desk archive

Date: 2026-10-17 · Status: accepted · Plan: 0028

**Decision.** Every part of the /macro page (daily brief, written note, RBI stance, hot spots, chapters, the Deeper
shelf, regime, house view, playbooks, external readings) and every industry explainer is a row in `desk_snapshots`
keyed by (snapshot_date, part, item, version). Saving is append-only: an identical payload is a no-op, a changed one
is a new version. The cockpit renders the page at request time from the newest version of each part on or before the
chosen "As of" date; a part with nothing that early shows its earliest version under a banner.

**Why.** Amit asked that nothing be lost and that every part have a date filter. One store with one reader gives the
filter to every part for free, keeps old versions for scoring the house view later, and lets a style fix apply to the
whole history (the brief is stored as data and rendered by the template, not as HTML).

**Rules.**
- The daily brief is computed point-in-time (`output/macro_desk.py`): data dated on or before the date; IIP and CPI
  only once published. A past date can be rebuilt (method `retrospective`); live runs are `live`, hand-written `manual`.
- Written prose (the brief note) carries no figures; the validator is `tools/sector_explainer.prose_digits`.
- `desk_archive.save(conn=...)` never commits: the caller owns the transaction (a dry run once wrote 79 rows when it did).
- The page is framed (`/macro` → `/macro/frame`) so its stylesheet never touches the cockpit's; cockpit links in it
  carry `target="_top"`.

**Not chosen.** A generated static HTML file per day (the archive would be files, not queryable, and a fix would not
reach old days); separate tables per part (eleven tables, eleven readers, no shared As-of).
