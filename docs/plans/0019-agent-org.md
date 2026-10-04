# Plan 0019 — The agent org: one human CEO, every other seat an agent

**Status:** active — Phase 0–1 and §5b–5f live 2026-10-02 (every seat has run; Phase 2 = two weeks of memos, then tune) · **Decisions:** [ADR 0057](../decisions/0057-agent-org-roles-on-the-queue.md), [ADR 0058](../decisions/0058-ceo-interface-tune-behaviour-not-permissions.md) · **Builds on:** [plan 0016](0016-alpha-signal-mcp.md) (queue + MCP, ADR 0056), [plan 0017](0017-data-model-redesign.md) (`documents`, ADR 0054) · **Reference:** [org.md](../reference/org.md)

## 1. Why
Amit wants the fund run as an org: he is the CEO, every other role is an agent. The repo's history says the binding
constraint was never throughput. It was honesty (the pt_upside look-ahead, the HALC number, four factors failing
BY-FDR). Agents make hypotheses cheap, so they make plausible-but-wrong output cheap too. The org is therefore
designed around **gates, not headcount**: every seat has a charter, an output contract, a gate and a separate grader.

## 2. The design in one page
- **One registry:** `org.ROLES` (seat → type, reports_to, mission, deliverable, measures, gate, grader, cadence, model).
  Everything else is derived; `tests/test_org.py` enforces it.
- **Two kinds of agent seat.**
  - **Desk** seats run unattended. Each is a task kind on plan 0016's `llm_tasks` queue (`alpha_mcp/org_kinds.py`),
    exactly like a dossier: deterministic code builds a facts brief → a local `claude -p` worker running *as that role*
    answers → `alpha-work.submit` validates server-side → ingest stores the memo with an undo record.
  - **Builder** seats change code. They are subagent definitions (`.claude/agents/<role>.md`) spawned by a human-led
    session in a worktree. Gate: tests + the CEO's merge.
- **Storage:** no new table (ADR 0054). Memos are v3 `documents` rows (`source='org'`, doc types `org.*`). Asks and
  hypothesis cards are child documents; a CEO decision is a child `org.decision`.
- **Chain of command for ideas:** a hypothesis card from a seat that reports to the CIO waits in the CIO's queue
  (`org.card_queue`). Only a card the CIO forwards reaches the CEO inbox. Asks always reach the CEO.
- **Role isolation is server-side:** a kind carries `"role"`; alpha-work shows and leases it only to a worker whose
  `ALPHA_MCP_ROLE` matches. The pipeline's llm-worker never sees org kinds and vice versa.

| Seat | Type | Reports to | Cadence | Deliverable |
|---|---|---|---|---|
| CEO (Amit) | human | — | — | decisions on the inbox |
| Chief of Staff | desk | CEO | Sunday | board pack (emailed) |
| CIO | desk (opus, web) | CEO | Sunday | (1) a call per wired factor, card triage, asks; (2) market outlook + second pass on desk ideas |
| Sector Desk | desk (web) | CIO | Sunday | one view per sector (11 tasks), 1–3 researched ideas each, pick flags, cards |
| Quant Researcher | builder | CIO | on approval | factor + PIT twin + backtest + verdict |
| Risk Officer | desk | CEO | daily | book note: within-limits / watch / breach |
| Compliance | desk (opus) | CEO | daily | a grade (0–8) per memo |
| CTO | desk | CEO | Sunday | platform state + ranked backlog with owners |
| Data Engineer | desk + builder | CTO | daily | triage per health issue; fix PRs when spawned |
| Backend / Frontend Engineer | builder | CTO | on backlog | PR + tests (frontend: + design-review) |
| System Architect | builder | CTO | on change | ADR + change-locality table |
| AI & Tools Scout | desk (web) | CEO | Sunday | ≤3 gated recommendations; default "no change" |

## 3. Incentives (what replaces a salary)
Agents have objectives, not incentives. Three mechanisms outside the prompt:
1. **Doer ≠ grader.** Compliance scores every memo against the brief its author was given (grounded, actionable,
   in-charter, calibrated). Risk and Compliance report to the CEO, not the CIO.
2. **Selection on versions.** Charters are committed files. A charter change ships only if the seat's grades and
   first-pass rate hold; otherwise revert.
3. **Budget as salary.** `llm_usage` carries `org:<role>` rows (tasks + tokens per run); `mcp_calls.role` counts tool
   calls. `org.scorecard()` is the quarterly review: grow, cut or retire a seat.

## 4. Guardrails
- **Structural:** desk seats have no shell and no files. Reads go through read-only MCP servers. The only write is
  `submit` → the kind's ingest → `documents`. No org kind can touch a table the model reads, weights, config or cron.
- **Validation is code, not prompt:** closed enums and caps; every id must be one the brief listed; a figure in a
  narrative (anything with a unit or a decimal) must appear in the facts; tool-quoted figures go in `evidence`, and
  `evidence` may cite only the brief, the web with a url, or a tool the seat actually called (`mcp_calls` is the
  witness); no links outside `evidence`. Rejection reasons are kept in `output/org_worker.log`.
- **Untrusted text:** headlines and error messages in a brief are marked as data. The scout's web access can only
  end in a schema-checked memo.
- **Reversible:** every ingest returns an undo record; `python -m alpha_mcp.tasks rollback <kind> --since ...`.
- **Fails loudly:** a seat with work that produced nothing fails `cron_org` → pipeline_log → the health email.
- **Runs without agents:** the pipeline never waits on the org. Disable = remove one cron line.
- **Capital:** paper only. No seat can place or size an order.

## 5. Delivery (how the org reaches the CEO)
**Pull by default, push by exception, one page a week.**
- **Boardroom** — ops cockpit `/org`: inbox with Approve / Park / Reject, board pack, memos with grades, org chart
  with each seat's scorecard.
- **`alpha-ops.org` MCP tool** — the same data from any Claude session ("what does my CIO say this week?").
- **Board pack email** — Sunday, from the Chief of Staff; ntfy push when it carries decisions.
- **Urgent push** — only an ask marked `urgency: now` pushes on a weekday. Daily memos never email.

## 5b. Tuning a seat (added 2026-10-02, on Amit's request)
The Boardroom's **Employees & settings** tab edits each seat: on/off, schedule, model, thinking effort, web search,
submit budget, a standing directive, and the full prompt. Variables are an `org.settings` document; prompts are the
seat's own files (so git shows the edit); every save is a history version with restore and reset. Guardrails are not
settings: kinds, gate, schema and validator stay in code. "Run now" buttons start a seat or the whole org ad hoc.

## 5c. Research line, chat, and what budget means (added 2026-10-02, on Amit's request)
- **Outlook:** the CIO's second weekly memo (`org_cio_outlook`): macro, market stance, what to be careful about,
  pursue / hold / avoid per sector. Brief = official macro indicators, index returns, FII/DII flows, regime, sector
  table with the desk's views, the news brief; plus web search with sourced evidence.
- **Idea pipeline:** sector desk raises 1–3 researched ideas per sector → CIO second pass (conviction / watchlist /
  reject) → the CEO's **Outlook & ideas** tab. The model's rank and score are attached by the server. Advice only.
- **Web search** is on for the research seats (CIO, sector desk, scout; the quant-researcher builder has it too).
  This revises the original guardrail "only the scout has web": the write path is unchanged (schema-checked memo
  only), web figures must sit in `evidence` with a url, and pages are treated as untrusted data.
- **Live chat** with every seat (`org_chat.py`, Boardroom → Chat): read-only tools, streamed replies, cannot write.
- **Budget:** no token bill. The constraint is the subscription's 5-hour and weekly usage windows, shared with the
  pipeline and Amit's own sessions; the Boardroom shows the last reading.

## 5d. Work orders and richer chat (added 2026-10-02, on Amit's request)
- **Work orders** close the gap between "we agreed in chat" and "it got fixed": the employee writes the agreed
  fixes as a numbered work order → inbox approval → a Claude Code session runs `/work-order N` (builders in a
  worktree, tests, report) → status on the Boardroom's Work tab. Approval starts nothing; no seat runs code unattended.
- **Chat** got a seat sidebar, Markdown, and charts / diagrams the seat may add when they help (constrained chart
  spec and Mermaid, rendered and sanitised in the browser).
- Still open: letting an approved work order start its builder without a session (unattended code changes on a
  branch). Deliberately not built yet.

## 5e. The Boardroom as an installable app (added 2026-10-02, on Amit's request)
An installable web app, not a native one: one codebase, instant updates, and it forced the move to HTTPS. Served at
`https://alpha.rendezvous-app.duckdns.org/org` through the VM's existing nginx with a Let's Encrypt certificate.
Manifest + icons + a static-only service worker; Boardroom is the first tab of the phone's bottom bar; the chat goes
full screen on a phone; ntfy pushes deep-link into the app. A wrapped APK (Trusted Web Activity) is possible later
and needs nothing new on the server. The trading cockpit (port 3000) is still plain HTTP.

## 5f. House style: ELI5 (added 2026-10-02, on Amit's request)
"I don't want complicated jargon that slows down decision making." One style for every seat
(`.claude/routines/house-style.md`, editable from the Boardroom), modelled on a plain four-question explainer: what is
happening, why it matters, what to do, what to remember. Enforced in code: a required `eli5` block on every CEO-facing
memo and a gate that rejects jargon, code names and long sentences in anything addressed to the CEO. Technical detail
stays available underneath.

## 6. Phases
| # | Phase | State |
|---|---|---|
| 0 | Registry, charters, builder agents, plan + ADR | ✅ 2026-10-02 |
| 1 | Desk kinds on the queue, `run.sh org` cron 06:30 UTC, Boardroom, MCP tool, board email, first run of every seat | ✅ 2026-10-02 |
| 1b | Seat settings, research line (outlook + ideas), chat + history, work orders, ELI5 house style, phone app (§5b–5f) | ✅ 2026-10-02 |
| 1c | Run the approved work: work order #1 and the five approved asks (accruals sign audit first) | ⏳ |
| 2 | Two weeks of memos → Amit reviews grades, tunes charters, sets a token budget per seat | ⏳ |
| 3 | Hypothesis card → quant-researcher loop run end to end on one approved card | ⏳ |
| 4 | CEO thumbs on board packs and compliance grades (the grader's grader) | 💤 |
| 5 | Execution desk (real capital): order limits, human confirm on every order | 💤 not before plan 0011 engines |

**Done when:** two consecutive Sunday packs each lead to at least one CEO decision, the daily triage has named the
cause of an incident before Amit opened the health email, and one hypothesis card has gone card → verdict.

## 7. Decisions for Amit
- **D1 — models.** CIO and Compliance on opus, the rest sonnet. Cheaper: all sonnet.
- **D2 — schedule.** One cron, 06:30 UTC daily; weekly seats on Sunday. Move the weekly run if Sunday is wrong.
- **D3 — scout web access.** The scout has WebSearch/WebFetch; every other seat has none. Turn off = `"web": False`.
- **D4 — board email.** Reuses the health email sender (From shows "Alpha Signal Health").

## 8. Non-goals
An agent that edits weights, config, cron or production code unattended. LLM output as a ranking input. A message
bus, a vector store, a framework. Agent-to-agent chat: seats talk through documents.

## Implementation notes
- **2026-10-02:** built in one session. `org.py`, `alpha_mcp/org_kinds.py`, 8 charters in `.claude/routines/roles/`,
  5 builder agents in `.claude/agents/`, `run.sh org`, cockpit `/org`, `alpha-ops.org`, `tests/test_org.py`.
  `alpha_mcp/tasks.py` gained `kinds_for(worker)` (role-owned kinds) and `enqueue(items=...)`;
  `claimable_count()` now defaults to the pipeline kinds so the llm-worker's cron is unaffected.
- The triage brief runs the full health scan (`tools.health_report.gather`), about two minutes cold.
- Ad hoc runs (`python -m org run --role cio --adhoc`) are keyed by the clock and leave the scheduled period free.
- **Seat settings + Run now, 2026-10-02:** `org.seat()` (effective seat), `save_settings` / `reset_settings` /
  `restore_settings`, `prompt_version` stamped on memos; cockpit `/api/org/seat/{role}` and `/api/org/run`. Briefs now
  carry `already_raised_by_you` so a rerun does not repeat an open ask. D1 (models) and D3 (scout web) are now
  settings Amit can flip himself.
- **First run of every seat, 2026-10-02** (ad hoc for the weekly seats). What it changed in the design the same day:
  (1) the sector desk's 11 cards flooded the CEO inbox → cards from the CIO's reports now go through CIO triage;
  (2) the triage memo cited tools it had not called → evidence provenance is checked against `mcp_calls`;
  (3) sector memos were rejected for harmless small integers → bare small counts are free, figures with a unit or a
  decimal are not.
