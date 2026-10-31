# Plan 0032 — Janitor routines: the data bug fixer, the code janitor, the data simplifier

**Status:** active 2026-10-31 (Amit: "yes to all please implement the plan"; calls J1–J6 in [ADR 0085](../decisions/0085-janitor-routines-probe-seat-order.md)). Owner: Amit. Builds on plan [0019](0019-agent-org.md) (the org), plan [0027](0027-forensic-data-audit.md) (the error classes), plan [0030](0030-v3-read-switch.md) / [ADR 0084](../decisions/0084-v3-read-switch-go-stop-rule-no-new-tables.md) (the target schema the simplifier points at). Explainers: [the Anthropic story](../research/0021-claude-code-routines-explainer.html), [the plain-words version for us](../research/0022-janitor-routines-for-alpha-signal.html).

## Why
Cleaning never has a date. Anthropic's Claude Code team gave it one: about twelve daily routines that open draft changes a human merges or rejects, with the instruction tuned on every miss. For us the clutter is 188 registered tables, 110 tools and a backlog of data faults that only research agents reading filings have found. The org already has the three parts a janitor needs (a probe on cron, a seat that judges, a work order Amit approves); this plan points them at maintenance.

## The shape of every janitor
| Part | What it sees | Who | Can it change anything |
|---|---|---|---|
| Probe | code or data | a Python job in `run.sh org` (Sunday) or the morning run (daily) | no: facts with the query or scan behind each |
| Seat | the facts | a desk seat (no shell, read-only SQL door); the server re-runs its counts | no: a memo |
| Work order | the memo | Amit presses "Make work order" or the server drafts it (J3); `/work-order N` runs it in a worktree | yes, on a branch Amit merges |

## Stages
| # | Janitor | Built | Done when |
|---|---|---|---|
| 1 | **Data Bug Fixer** — plan 0027 classes as `tools/dq_probes.RULES` (`forensic`), a planted fault each; the pick-touching rules daily as `DATA_FAULT_IN_PICK_INPUTS` (`checks/faults.py`); J3 drafted fix orders | 2026-10-31: classes 1–5, 8 (7 rules, 7 plants); the daily check with its fire drill; `_draft_fix_order` + test | the first drafted order is approved and run; classes 6, 7, 9, 11 (text: wrong sector tag, mis-tagged event, pending merger, resignation reason) have a probe or a written "seat's own digging" note |
| 2 | **Quarantine + impact** — a `data_quarantine` row set the screener masks on a re-run, so a drafted order carries a measured pick diff before the fix | — | the first order's pick diff is attached by the tool, not by hand |
| 3 | **Code Janitor** — `tools/code_probes.py` (unreferenced tools, factors on the bench with no reader, `run.sh` cases absent from the crontab, config flags unchanged 90 days, tests that cannot fail, steps that fail then pass on rerun, near-duplicate helpers), a `code-janitor` desk seat under the CTO (`org.ROLES`, charter, `org_code_sweep` kind, `tests/test_org.py` row), the "sticker" (`run_events` line on a suspect, 90 days of silence = dead, J6) | — | the first weekly memo lists candidates with evidence; the first deletion order is merged; a reverted deletion is recorded against the seat |
| 4 | **Data Simplifier** — a structural probe in the CTO's weekly review: tables with no declared reader, columns no factor or page reads, one concept in two tables that disagree (the MMTC / GOCL reconcile outliers), producers writing to tables nothing reads; proposals placed in plan 0017's target schema | — (gated on plan 0030 stages 0–2) | the memo proposes retire / merge per concept and nothing new appears outside the D2 mapping |
| 5 | **The scorecard** — per seat: proposals accepted / rejected / reverted within 30 days, on the compliance grade and the Boardroom | — | visible on `/org` for every janitor |

## What Amit does
Monday, about ten minutes: read the memo on `/org`, approve or reject the drafted order. Every other week, about half an hour: `/work-order N` in a session, then merge. Nothing else runs without that.

## Decisions (ADR 0085)
J1 order as above · J2 this plan · J3 the server drafts the fix order · J4 no unattended stickers yet · J5 Sunday memos on the stronger model, pick-touching data rules daily · J6 dead = no reference + 90 days of silence; a revert within 30 days counts against the seat.

## Implementation notes
- **2026-10-31 — stage 1 built.** `tools/dq_probes.py`: 7 `forensic` rules (plan 0027 #1 pre-demerger annuals, #2 vendor share count 2x+ from Screener's, #3 annual 400+ days older than the newest quarter, #4 quarter revenue 1.5x+ from Screener sales, #5 a holder filing listing under half the holders of its neighbours, #8 other income above PBT and 3x the year before, #8 net profit above 1.5x PBT), each with a planted fault; `pick_rules()` / `daily()`; the scratch copy now holds `transcripts` and `nlp_scores` (the 2026-10-08 rule had broken the drill silently). Live on 2026-10-31: #1 6 of 10 demerged stocks (BHIL, HEGL, IGLY, TREI …) scored on pre-demerger annuals; #2 34 vendor counts 2–10x out (TEMB, SIGM, ELI, UNTD 10x); #3 159 stocks whose newest annual is FY25 or older against a 2026 quarter; #4 62 quarters (ESPL 6,458x: a units error); #5 8 filings; #8 7 one-off years and 23 tax write-backs. `checks/faults.py` `DATA_FAULT_IN_PICK_INPUTS` (WARN; 4 of 13 pick-touching rules fire today) with its drill in `tests/test_check_drills.py`. `alpha_mcp.org_kinds._draft_fix_order` + `org.save_work_order(parent=)`, `org.work_order_doc_id`; `work_order_schema()` shared with `org_chat`. Fire drill 2026-10-31: 14 of 14 planted faults caught (the holder-list plant first wiped the whole filing, which the rule rightly ignores: a missing filing is a coverage fault, a thin one is this rule's). Tests: `tests/test_dq_audit.py` (+1), 89 pass across the four touched files.
- **2026-10-31 — approval tiers ([ADR 0086](../decisions/0086-approval-tiers-default-yes-veto-window.md)).** Drafted fix orders are Tier B: they approve themselves 48 h after the memo unless Amit parks or rejects them in the inbox; `org.work_orders()` derives the status, the inbox shows the date. Code-janitor deletion orders (stage 3) will be Tier B too; anything touching weights, config, cron or stored data is Tier A.
- **Next:** the first Sunday memo (2026-11-02) should carry the forensic findings and, for any called real + picks, a drafted order in the inbox. Then stage 2 (quarantine) so the order's pick diff is measured, and stage 3.
