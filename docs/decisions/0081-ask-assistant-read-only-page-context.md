# 0081 — The Ask assistant: one read-only `claude -p` turn per question, sent with the page

**Status:** accepted · 2026-10-17 · plan: none (checklist "Ask" bullet)

**Decision.** Every page of both cockpits carries an Ask panel (`base.html` → `static/ask.js`). Each question is sent
with the page it was asked on (URL, title, visible `<main>` text resent only when it changed, the selection, and on a
stock page the stock named from the URL). The server (`ask.py`) runs one `claude -p` turn per question on the Claude
subscription, streamed by `org_chat.cli_stream`, which the Boardroom seat chat shares. The assistant can read
everything and change nothing:

- alpha-research + alpha-ops MCP (`sql` reaches every table and view), WebSearch/WebFetch;
- Read/Grep/Glob under the repo only, granted by ONE `Read(/<repo>/**)` allow rule in `dontAsk` mode. Allowing
  `Grep`/`Glob` bare lets them search any path (tested live 2026-10-17: a canary outside the repo was found);
  the Read rule scopes all three. Env/secret/auth/DB files inside the repo are denied by name;
- no shell, no edit, no write tools.

Transcripts are `org.assistant` documents (one row per message, keyed `conv:NNNN`). The turn runs in its own thread,
so a reply finishes and is saved when the browser leaves the page; the panel shows "still answering" on the next one.
Only the text after the last tool call is saved as the answer; text written before a lookup is a passing note.

## Why
- Amit has "a ton of questions" on every page. Copying numbers into a separate chat loses the context; the page text
  plus the stock id lets "what's the capex situation in this business" work as typed.
- The subscription CLI already powered the Boardroom chat with the same MCP tools: no new API spend, no new
  dependency, one streaming parser for both.
- Read-only is the safety model, not prompt instructions: the tool list and permission rules make writes impossible.

## Rejected
- **The paid API with a custom tool loop:** duplicates the MCP servers and costs per token; the API balance is empty.
- **A shell tool for ad-hoc SQL:** `sql` over MCP is already read-only and logged in `mcp_calls`.
- **Storing as `org.ask`:** that type is the seats' questions to the CEO; the first test put two chat lines in the
  Boardroom inbox (deleted).
- **Streaming every text block as the answer:** the model's pre-lookup note ("Need depreciation recent …") showed as
  the whole reply on PONNIERODE (fixed eb9d593).

## Consequences
- Each question spends subscription quota (Fast = Sonnet ≈ 15–40 s; Deep = Opus). Usage lands in `llm_usage`
  (step `ask`).
- A new file tool or MCP server for the assistant must keep the read-only property; `tests/test_ask.py` checks the
  tool list, the single Read rule and the doc type.
