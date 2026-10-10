# The agent org — how it works

Plan [0019](../plans/0019-agent-org.md) · ADR [0057](../decisions/0057-agent-org-roles-on-the-queue.md). The CEO is the
only human. Every other seat is an agent defined by one entry in `org.ROLES`.

## Daily flow (cron `run.sh org`, 06:30 UTC)
1. For each desk seat due today, in `org.RUN_ORDER`: build its brief (`alpha_mcp/org_kinds.build`) and queue it in
   `llm_tasks` (once per period).
2. Run `claude -p` as that role (`org.run_role`): subscription login, no shell, MCP tools only. It claims its own
   kinds, reads the brief plus `alpha-research` / `alpha-ops`, and submits a memo.
3. `alpha-work.submit` validates (schema, listed ids, grounded numbers, no links) and stores the memo in `documents`
   with child documents for each ask and hypothesis card.
4. The CIO's review triages the desks' hypothesis cards: only a forwarded card reaches the CEO inbox.
5. Compliance grades the new memos; on Sunday the Chief of Staff writes the board pack; `org.deliver_all` emails it.

Daily seats: data-engineer (triage), risk-officer, compliance. Sunday adds: dq-auditor, sector-desk, cio, cto, ai-scout,
chief-of-staff.

## Commands
```bash
python -m org roster                      # the org chart
python -m org run                         # what cron runs: every seat due today
python -m org run --role cio --adhoc      # one seat now; leaves its scheduled period free
python -m org inbox                       # asks + hypothesis cards awaiting the CEO
python -m org decide 123 approve --note "go"
python -m org decide 123 --option 1      # an ask with options: choose the second (implies approve)
python -m org scorecard                   # per seat, 30 days: done, first-pass, grade, tokens
python -m org board --send                # print / re-send the latest board pack
python -m org work                        # work orders and their status
python -m org work 3                      # one work order with the chat it came from
python -m org_chat cio "question"         # one chat turn from the terminal
python -m alpha_mcp.tasks rollback org_cio_review --since 2026-10-04T00:00   # undo a seat's memos
tail output/org_worker.log                # one JSON line per seat run
```
Read it: ops cockpit **/org** (Boardroom), or the `alpha-ops.org` MCP tool from any Claude session.

## Looking back: older memos and past chats
- **Memos tab:** a date range (From / To), an employee filter, and quick links (Today, 7 days, 30 days, All time). The
  filter is the page's query string (`/org?mfrom=2026-09-01&mto=2026-09-30&mrole=cio#memos`), read by
  `org.memos(since, until, role)`. With no filter the tab shows the newest 40 of the last 14 days; a filtered page shows
  up to 150 and says so when there are more.
- **Chat history:** *Chat history* at the top of the employee list shows every past conversation with everyone;
  *History* in a chat's header shows that employee's. Open one to read it; sending a message continues it (the CLI
  session is resumed) and it becomes the current conversation again. `org_chat.conversations(role=None)`,
  `org_chat.history(role, conv)`. Nothing is ever deleted: every message is an `org.chat` document.

## House style: explain it like I'm five
Every seat writes for a clever friend who does not work in finance or software. The style lives in ONE file,
`.claude/routines/house-style.md`, added to every memo prompt and every chat (edit it on the Boardroom: Employees &
settings → **House style**). Two parts are code, not prompt (`alpha_mcp/org_kinds.py`):
- every CEO-facing memo opens with an **`eli5`** block: `what` is happening, `why` it matters, what to `do`, what to
  `remember` (and an optional everyday comparison, `like`). The page, the email and the memo list lead with it.
- the **ELI5 gate** checks the block, the headline, asks, and everything addressed to the CEO (the whole outlook, sector
  views and ideas, the risk note's comments, the board pack): no trade jargon (`_JARGON`, each with its plain
  alternative), no code names like `book_to_price`, no sentence over ~26 words. A memo that fails comes back to the seat
  with the offending word and the plain way to say it. Detail fields (an engineer naming a step, the CIO's factor calls)
  and `evidence` stay free.
To add or relax a banned term, edit `_JARGON`; the test `test_every_ceo_facing_memo_needs_a_plain_words_block_and_no_jargon`
covers the gate.

## The research line: ideas and the outlook
- **Sector desk** (web on): one view per sector, and one to three **investment ideas** with a stock-specific reason,
  catalyst and risk. An idea must be a stock the model ranks in that sector; the server attaches the model's own tier,
  rank, score and published flag (`org_kinds._model_rows`), so those numbers never come from the agent's text. A sector
  memo is refused unless the desk looked a stock up in that run.
- **CIO** (web on) writes two memos: the investment review (factor calls, card triage) and the **market outlook**
  (`org_cio_outlook`): macro, market stance and horizon, what to be careful about, a pursue / hold / avoid call per
  sector with what would change its mind, and the **second pass** on every desk idea: conviction, watchlist or reject.
- **You** read the result on the Boardroom's **Outlook & ideas** tab (`org.ideas()`), and the board pack carries it.
  Ideas are advice. They never change a rank or the book.
- Run just the outlook: `python -m org run --role cio --kind org_cio_outlook --adhoc`.

## Chat with a seat (Boardroom → Chat, or `python -m org_chat <role> "question"`)
One `claude -p` turn per message, as that seat (`org_chat.py`): its charter, its recent memos, your recent decisions
on its items, read-only `alpha-research` / `alpha-ops` tools, and web search if the seat has it. Replies stream.
A chat **cannot write**: no `alpha-work`, no shell, no files. An instruction given in chat binds the seat's scheduled
memos only once you save it as the seat's standing directive. Transcripts are `org.chat` documents; the CLI session
lives under `~/.alpha_org_chat`.

## Work orders: from a chat to a fix
1. Chat with an employee and agree what to fix. Press **Make work order**: the employee writes the agreed list
   (`org_chat.make_work_order`: title, summary, items with what / where / done_when / owner seat / size, and the open
   questions). It is checked and stored as an `org.work_order` document with a number.
2. It appears in the **Inbox** and on the **Work** tab as *awaiting approval*. Approving starts nothing.
3. In a Claude Code session in the repo: **`/work-order N`** (`.claude/commands/work-order.md`). The session reads the
   order and the chat it came from (`python -m org work N`, or the `alpha-ops.org(work_order=N)` tool), starts each
   item's owner builder agent in a worktree, runs the tests and reports. It refuses an order that is not approved.
4. The session records the outcome: `python -m org work N --status done --note "..."` (or `in_progress`, `blocked`,
   `cancelled`). The Work tab shows it. Merging stays with the CEO.

Chat replies render Markdown. A seat may add a **chart** (a fenced `chart` block with a small JSON spec, drawn with
Chart.js) or a **diagram** (a fenced `mermaid` block) when it helps; chart numbers must come from a tool result or
a memo, and the source is printed under the chart. The reply is sanitised in the browser (DOMPurify).

## The Boardroom as a phone app
- **Address:** `https://alpha.rendezvous-app.duckdns.org/org` (nginx site `ops/nginx/alpha-ops.conf` → uvicorn on
  127.0.0.1:3001; Let's Encrypt certificate, renewed by `certbot.timer`). The plain `http://<vm-ip>:3001` still works.
- **Install on Android:** open the address in Chrome, sign in, then menu → *Install app* (or *Add to Home screen*).
  It opens full screen on `/org`. Long-press the icon for shortcuts to Inbox, Chat, Outlook and Work orders.
- **What makes it an app:** `cockpit/static/boardroom/` (manifest, icons, `sw.js`, `offline.html`), linked from
  `cockpit_ops/templates/ops_base.html`; the worker is served at `/sw.js`. It caches static assets only: pages and
  `/api/` are never cached. On a phone the Chat tab takes the whole screen.
- **Notifications:** ntfy pushes carry a link (`org.BOARDROOM_URL`) that opens the inbox or the board pack.
- **Changing the address:** create the new name (for example a DuckDNS subdomain that points at the VM), change
  `server_name` in `/etc/nginx/sites-available/alpha-ops`, run `sudo certbot --nginx -d <name>`, and set
  `BOARDROOM_URL` in `org.py`. Reinstall the app from the new address.

## What "budget" means here
There is no per-token bill: every seat runs on the Claude subscription. The real budget is the subscription's two
usage meters (a rolling 5-hour window and a weekly one), **shared** with the pipeline's LLM steps and your own Claude
Code sessions. The Boardroom shows the last reading (`org.note_subscription`). "Max memos per run" in Settings is only
a safety stop on one run. The scorecard's tokens per seat tell you who uses the allowance; if the meter runs hot, move
a seat to a cheaper model, a slower schedule, or switch it off. If the allowance runs out, seats fail loudly
(`cron_org` FAILED) and the morning dossiers are at risk too, since they use the same subscription.

## Changing how a seat behaves (Boardroom → Employees & settings → Settings)
| Setting | Seats | Where it lives |
|---|---|---|
| Active (on/off), schedule, model, thinking effort, web search, submit budget | desk | `documents` row `org.settings` (key = role); `org.seat(role)` applies it over `org.ROLES` |
| Standing directive (a short instruction added to every brief) | desk | same row |
| Prompt (the charter) | desk | the file `.claude/routines/roles/<id>.md` — the page rewrites it, so `git diff` shows the edit |
| Prompt + model | builder (and the data engineer's fix mode) | the body and `model:` line of `.claude/agents/<id>.md` |

Every save keeps the variables and the prompt text in the settings row: that is the **history**, with **Restore** per
version and **Reset to default** (the seat as it was before its first edit). A change applies from the seat's next
run. Each memo is stamped with `prompt_version` (a hash of prompts + directive + model), so grades can be compared
before and after a change.

**Not editable, by design:** the seat's kinds, its gate, the memo schema, the number / id / link / evidence checks and
the rules appended to every prompt. A prompt can change what a seat says, not what it is allowed to write.

**Run now:** "Run all seats now" or "Run this seat now" starts an ad hoc run (`org run --adhoc --no-deliver`) under
the org lock. It leaves the scheduled period free and sends no email. CLI: `python -m org run --role cio --adhoc`.

## Adding a desk seat
1. `org.ROLES` entry (`type: desk`, cadence, model, `kinds`, mission, deliverable, measures, gate, graded_by) and its
   place in `RUN_ORDER`.
2. Charter: `.claude/routines/roles/<id>.md` (who the seat is, how to work, what each memo field means).
3. `alpha_mcp/org_kinds._SPECS` entry: the brief builder and the result schema.
`tests/test_org.py` fails until all three agree. A builder seat is a `ROLES` entry plus `.claude/agents/<id>.md`.

## Starting a builder
In a Claude Code session: "spawn the quant-researcher agent on card #123 in a worktree". The agent file carries the
seat's rules. The CEO reviews and merges.

## Where things are
| Thing | Place |
|---|---|
| Registry, runner, memo store, scorecard, delivery | `org.py` |
| Briefs, validators, ingest | `alpha_mcp/org_kinds.py` |
| Charters (desk) / agent files (builder) | `.claude/routines/roles/` · `.claude/agents/` |
| Memos, asks, cards, decisions, grades | `documents` where `source='org'` (doc types `org.*`) |
| Per-seat usage | `llm_usage.step = 'org:<role>'`, `mcp_calls.role`, `llm_tasks.claimed_by` |
| Run log | `output/org_worker.log`, `output/org.log`, `pipeline_log.step_name = 'cron_org'` |

## When a seat misbehaves
- **Memo rejected repeatedly** (`llm_tasks.status = 'failed'`, error `invalid: ...`): read the reason
  (`grep '"event": "invalid"' output/org_worker.log` keeps every rejection). Usually an ungrounded figure, an id
  not in the brief, or evidence citing a tool the seat did not call. Fix the charter or widen the brief, then
  `python -m alpha_mcp.tasks retry <kind>`.
- **A bad memo got through:** `rollback` the kind since that time, then tighten the validator in `org_kinds`.
- **Seat produced nothing:** `output/org_worker.log` has the CLI's error. A subscription limit shows up here.
- **Turn the org off:** remove the `run.sh org` line from the crontab and `ops/crontab.txt`. Nothing else depends on it.

## The data-quality auditor (weekly, plan 0020)

`dq-auditor` looks for data that is wrong while looking right. Two halves:

- **Probes, code only** (`python -m tools.dq_probes`): every statement column factors read against Screener, which
  Screener item each other column agrees with, values that cannot be real, copied price days and unexplained jumps,
  each weight against its evidence, an independent recompute of simple factors, one table profiled per week. A
  finding is a claim plus the SQL that shows it. `--drill` plants seven known faults in a scratch copy and proves
  the probes catch them; a missed plant is reported in the brief.
- **The seat** (`org_dq_audit`, Sunday): gives every finding one call (real / does-not-reproduce / known /
  needs-more-data) and may add up to five findings of its own.

How it is kept honest:
- Two findings in every brief are false on purpose (a rule that passes, written up as failing, with its real query).
  The seat is told to run each query before calling it.
- After the memo is accepted the server re-runs every finding's query and records each call that did not match
  (`score` on the memo; "calls right" on the seat's scorecard in the Boardroom and in its next brief).
- An own finding needs a single SELECT returning `n_bad`; the server runs it and refuses the memo when the count
  differs from the one stated.
- Compliance grades the memo, as for every seat.

A confirmed finding becomes a permanent probe rule, health check or test, so next week's audit has to find
something new. `dq_probes.KNOWN` lists what a second look settled.
