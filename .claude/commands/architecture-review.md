# Architecture review: explainability, hygiene, ease, scalability, expandability, enterprise grade

## Mission
Score alpha-signal-v2's architecture on six dimensions, with evidence. Then hand Amit a ranked fix list he can act on.
This is a **read-only review**. Do not change production code, config, cron, services or the DB. The only files you write are the report and the checklist bullet.

The system was rebuilt around ADR 0052 on 2026-09-27: 7 building blocks, 5 invariants, all plan 0015 phases shipped.
The review tests **the architecture as built** against that design and against what a well-run small quant shop would expect. It does not re-litigate the design.
A finding that says "the design says X, the code does Y" is the most valuable kind.

## Inputs (read first, in this order)
1. `README.md`, `CLAUDE.md`, `docs/reference/architecture.md` (the one-page target plus "Today").
2. `docs/decisions/0052-seven-building-blocks.md` and `docs/plans/0015-first-principles-architecture.md`, especially "Implementation notes". Those notes list known deviations and open items: record them, but don't re-report them as new findings.
3. `OPERATOR.md`, `HANDOFF.md`, `docs/plans/0000-checklist.md`.

Then go to code. The graphify MCP predates 2026-09-26, so verify every path it returns.

## The six dimensions
Score each 0–10 against the anchors below.
- Every score cites evidence: file:line, a command and its output, or a measured number.
- A score with no evidence is invalid.
- Where a dimension has a measurable test, run it. Don't estimate.

### 1. Explainability: can a person predict the system, and can the system explain itself?
- **Where-does-X-live test.** Write 12 questions before reading code. Examples: where a factor's weight lives; what runs before the email; what makes a table stale; where the pick gate is; how a host is rate-limited. Answer each from README and architecture.md only, then check the answer in code. Score = correct / 12.
- **Pick provenance.** Take one of today's LARGE and one of today's SMALL picks. Trace each final_score back to its factor values, then to the raw rows and dates they came from, then to the source and fetch time. Count the hops that need reading code instead of a query or page.
- **Doc–code drift.** Sample 20 factual claims from CLAUDE.md, OPERATOR.md and architecture.md, and count the false ones.
- **Naming and ownership.** Does every concept have one obvious owner? List every concept with two plausible homes.
- Anchors:
  - 3/10: needs tribal knowledge.
  - 6/10: docs mostly right; provenance needs code reading.
  - 9/10: ≥11/12 questions correct, a pick traceable by query alone, ≤1 false claim in 20.

### 2. Hygiene: is the codebase clean, and does it stay clean by construction?
- **Duplicated facts.** Anything stated in two or more places: ranges, tier lists, table names, model ids, cadences, SQL for one concept. Each one needs a named owner.
- **Dead code.** Before calling anything dead, check crontab, `run.sh`, PIPELINE_STEPS dynamic imports, templates/JS, `.claude/`, docs commands, and whether it is the only writer of a live table. "Unused" ≠ dead.
- **Write paths.** Raw `INSERT`/`UPDATE` outside `db.upsert_df`/`insert_df`; `INSERT OR REPLACE` on snapshot/state tables (violates CLAUDE.md); in-code `CREATE TABLE`.
- **Rules held by vigilance only.** For each CLAUDE.md rule: is it enforced by a test or by construction? Unenforced rules are findings.
- **Repo hygiene.**
  - untracked production-critical files (`git status`, `.gitignore`, anything cron or systemd uses)
  - stale comments that name removed modules
  - TODOs
  - unpinned dependencies (`requirements.txt` vs `pip freeze`)
- **Test health.** Count, runtime, and what invariants 1–5 have tests. List what could break with every test still green.
- Anchors:
  - 3/10: duplication everywhere, rules by memory.
  - 6/10: registries exist but leak.
  - 9/10: every invariant tested, no duplicated fact, no untracked prod file.

### 3. Ease: how cheap is it to change, run and recover?
- **Change locality, re-measured.** Measure these 10 scenarios today; for each, count the files and edit sites a developer must touch:
  - add a data source
  - add a table
  - add a factor (live + backtest + weight)
  - add a pipeline step
  - add a check
  - add a cockpit page
  - change a cadence or threshold
  - rename a factor
  - add a tier
  - replay a past date

  Compare with plan 0015 §4's before/after table: target ≤2, rename a core column 3.
- **Onboarding.** How many files, and roughly how many LOC, must a newcomer read to add a factor safely?
- **Operations.** Walk OPERATOR.md's recovery runbook: no email by 09:30 IST, one failed step, stale table, dead cookie. Is each step runnable as written? Use `DRY=1 ./run.sh <job>` and `--dry-run` only.
- **Local dev loop.** Can someone run the test suite and one offline step without production credentials or network? How long does it take?
- Anchors:
  - 3/10: most changes touch 5+ files.
  - 6/10: most ≤3, the runbook has gaps.
  - 9/10: all ≤2 as planned, every runbook step works, offline dev loop under 1 minute.

### 4. Scalability: what breaks first as the system grows?
- **Measure today's baselines:**
  - DB size and growth per month, per table (`sqlite_master` plus row counts over time)
  - `pipeline_log` durations: time to email and total run, 30-day p50/p90
  - `pit.load_raw` time and memory
  - screener step time
  - cockpit cold and warm latency on the heaviest routes (test ports only)
  - LLM calls per day and cost (`llm_usage`)
- **Project each scenario forward:** what breaks, when, and the first remedy.
  1. Universe 2.4K → 5K → 10K stocks.
  2. Factors 105 → 300.
  3. Hosts ×2.
  4. History ×3.
  5. Two runs per day.
  6. Ten cockpit users.
- **Find complexity hotspots:** per-sid Python loops, full-history loads, N+1 queries in `views.py`, single-writer SQLite contention, and the one harvest lock serialising everything.
- Anchors:
  - 3/10: breaks within 2× growth.
  - 6/10: survives 2×, 5× needs a redesign.
  - 9/10: 5× needs only known, cheap remedies.

### 5. Expandability: how far can it stretch without surgery?
For each extension, list every hard-coded assumption it would hit, then estimate the files touched:
- a second market (US equities, or the plan 0009 crypto cockpit): currency, calendar, sid scheme, IST/NSE assumptions, the tier rules
- a second engine or sleeve (plan 0011 compounder or special situations) sharing data but with its own model and book
- an intraday or weekly-only product
- an API consumer (read-only JSON for a second app)
- a second user or portfolio
- swapping SQLite for Postgres or DuckDB for one heavy dataset

Also judge whether the seven blocks are the right extension points: Host, Dataset, Node, Feature, Model, Check, View. Name any extension that fits none of them.
- Anchors:
  - 3/10: every extension is a fork.
  - 6/10: data layer extends, model and surfaces don't.
  - 9/10: each extension is a new block instance, not an edit.

### 6. Enterprise grade: would a hedge-fund engineering lead sign off?
Assess each item as present / partial / absent, with evidence:
- **Environments.** Production runs from a working checkout, with no staging and no release tags. How are changes promoted? How are they rolled back?
- **CI/CD.** Are tests run automatically on commit or merge? Is there a pre-deploy gate?
- **Reliability.**
  - Is there an email SLO, and how often was it met in the last 30 days?
  - retries, idempotency of every step
  - critical-path failure handling
  - graceful degradation when LLM credits or a host die
- **Observability.** Structured logs, metrics, alert routing, alert fatigue (count the alerts sent over 30 days), dashboards.
- **Security.**
  - network exposure of :3000 and :3001, and authentication
  - where secrets live and who can read them
  - SQL console guard
  - dependency CVEs, from pinned versions
- **Data governance.**
  - lineage
  - point-in-time and vintage correctness (plan 0015 found as-of approximate for revised sources)
  - quarantine
  - reproducibility: can yesterday's picks be reproduced bit-for-bit?
- **Backup/DR.** Is the backup verified by an actual test restore, and when did the last restore happen? What are the RPO and RTO?
- **Change management and audit.** ADRs, plans, commit discipline; who approved what; can each production change be traced to a decision?
- **Cost control.** LLM and infra spend caps.
- Anchors:
  - 3/10: hobby project.
  - 6/10: disciplined solo shop.
  - 9/10: could pass a light due-diligence review.

## Method
1. **Pre-register first.** Before reading code, write the 12 where-does-X-live questions and the 10 change scenarios into the report skeleton.
2. **Split the evidence work** across at most 4 read-only subagents (5 hit the usage limit). A workable split:
   - (a) explainability + ease
   - (b) hygiene
   - (c) scalability measurements
   - (d) expandability + enterprise

   Give each agent an explicit file-ownership list (it writes only to its own scratch notes), the safety rules below, and a ≤250-line report format with file:line citations.
3. **Verify.** Agent audit claims were wrong about 10% of the time. Re-verify every claim that affects a score or a top-10 finding in code or with read-only SQL, and drop anything you can't verify.
4. **Score, then rank findings** by impact × likelihood ÷ effort.
   - Impact is one of: wrong picks, missed or late email, silent data corruption, security exposure, lost change velocity.
   - Effort is S (< 1 session), M (1–3 sessions) or L (more than 3).

## Output
Write `docs/studies/architecture-review-<YYYY-MM-DD>.md`, at most about 300 lines, containing:
1. **Scorecard:** six rows of dimension, score /10, one-line verdict and the key evidence, plus an overall /60 and a one-paragraph summary.
2. **Per dimension:** the tests run with their measured numbers, what's good (keep doing), and the findings.
3. **Top 15 findings, ranked.** For each: what's wrong (with evidence), the concrete failure scenario, the fix, the effort, and which building block owns the fix.
4. **Enterprise gap list:** present / partial / absent per item in §6.
5. **Roadmap:** quick wins (S), structural work (M/L), and explicit non-goals — things that are enterprise-standard but not worth it for a solo research shop, each with a one-line reason.
6. **Scale-break table:** growth scenario → what breaks first → when → remedy.

Add a checklist bullet before starting (CLAUDE.md), and update it at the end with the overall score and the top 3 findings. Commit only the report and your checklist hunk: stage by name, and don't stage other sessions' edits.

## Safety (learned the hard way)
- **Production.** It runs from /home/ubuntu/alpha-signal-v2 on the 03:30 UTC cron through `run.sh morning`. Do not edit, merge, deploy or restart services.
- **The database.** It is live (about 8.6 GB). Open it read-only (`sqlite3 "file:data/alpha_signal.db?mode=ro"`), and keep heavy scans off the live file: use a copy made with `.backup` into the scratchpad.
- **No network.** For anything that could import a fetcher, use the `LD_PRELOAD` connect() shim: Python socket patching leaks, because yfinance uses libcurl. See memory `offline_network_isolation`. Never send email or push; `tools/health_report` without `--email`/`--push` is fine.
- **Cockpit tests.** Test ports only (not 3000/3001), with `COCKPIT_CACHE_DIR` in the scratchpad. Kill test servers by the PID from `ss -ltnp`. Never `pkill -f "uvicorn cockpit.app"`, and anchor any `pkill` pattern.
- **Concurrent sessions.** Check other live sessions first (`git status`, ListAgents).
- **Git rules.** No `git add .`/`-A`, no `--amend`.
- **Writing the report.** Keep numbers in tables, not prose. Say plainly what you could not measure and why.

## Done means
Amit can read the scorecard in two minutes, knows the three things most likely to hurt him, and can pick the next session's work straight from the ranked list. Every score traces to evidence someone else could re-run.
