# ADR 0086 — Approval tiers: Tier A asks every time, Tier B is yes by default after a 48-hour veto window, Tier C needs no approval

**Status:** accepted 2026-10-31 (Amit: "i feel i am the bottleneck … how to avoid this in future" → "agreed"). Amends ADR 0058 (no unattended builder runs) for Tier B, and the `/handoff` commit gate. Follows ADR 0051's precedent (D1–D12 pre-cleared with acceptance bars; evidence-gated, not decision-gated).

## Decision
- **Tier A — Amit, every time:** live money and orders (`options_live.py`, `option_book.py`, the Kite order path, `option_live_settings`), factor weights and the model config (`factors.SIGNAL_WEIGHTS`, `config.TIERS` / `PICK_GATE` / `MB_THESIS`), deleting or overwriting stored data (a `DROP`, a `DELETE`, a backfill that rewrites), `run.sh` and the crontab, secrets, a merge that changes the published picks by more than the bar (**proposed bar: 3 of the top 10 in any tier on the 3-date identical-ranks check**; change it here), spend above the budget (**proposed: ₹5,000 a month in paid data or API**).
- **Tier B — yes by default after 48 hours:** everything a work order can hold that is not Tier A: data fixes whose pick diff was measured under the bar, code cleanup that passes the tests, cockpit pages, probes, docs, charters. The order sits in the inbox with its tier and the date it approves itself; Park or Reject inside 48 hours stops it. Silence is a yes, recorded as "approved by default".
- **Tier C — no approval:** read-only studies, measurements, memos, explainers, research prompts.
- **Every plan decision carries its default and its effect date** ("proposed: yes · takes effect 2026-11-14 unless you say no"). A plan never waits on a question whose answer is written next to it. Older than two weeks → the default applies and the plan notes say "decided by default".
- **The commit gate follows the tiers.** A session whose scope holds only Tier B and C paths commits when the pre-push suite passes and says so in the handoff; Tier A paths keep "show me the staged diff first". If the index already holds another session's staged work, message that session first (ListAgents / SendMessage); no answer in 10 minutes → commit through a temporary index (`GIT_INDEX_FILE`, recipe in `.claude/commands/handoff.md`), never by unstaging theirs.
- **Tier B work orders may run unattended** (amends ADR 0058 for Tier B only): a builder session in a worktree, judged by the tests, the budget test and the pick-diff gate, leaving a one-paragraph summary and the diff. Amit reviews outcomes, not requests. Not built yet: the first month runs Tier B through `/work-order` by hand to see the revert rate.

## Why
- Three gates Amit set stall the machinery when he is away: ADR 0058, plan-level D decisions, and the handoff "don't commit until I approve". On 2026-10-31 a built-and-tested janitor stage sat uncommitted because the index held another session's staged hunks.
- ADR 0051 showed the alternative works: pre-cleared bars, evidence decides, Amit vetoes.
- The cost is bounded: a Tier B change he would have vetoed goes through and is reverted; the janitor scorecard counts reverts within 30 days (ADR 0085 J6). Tier A is where the money and the picks are, and it does not move.

## Consequences
- `org.work_orders()` derives "approved" for a Tier B order with no decision after `org.VETO_HOURS` = 48; the inbox stops listing it and shows the self-approval date while it waits. Orders without a tier (before this ADR) stay Tier A.
- `org_kinds.work_order_schema` carries `tier`; a seat writing an order sets it by the list above; the server's drafted fix orders (ADR 0085 J3) are Tier B with the pick-diff step first.
- Follow-up: a Monday decision slot on `/org` listing every open plan D with its default and effect date; unattended Tier B builder runs after the first month's revert count.
