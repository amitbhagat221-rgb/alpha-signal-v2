# ADR 0051 — Roadmap-to-90 strategic decisions (D1–D12)

Status: accepted · 2026-07-11 · Owner: Amit (approved in-session)
Context: [Plan 0011](../plans/0011-roadmap-to-90.md) (roadmap), [Plan 0012](../_archive/plans/0012-sonnet-tasks-execution-and-factors.md) (Sonnet tranche), [return-prediction-2026-07-05-report.md](../studies/return-prediction-2026-07-05-report.md). Builds on ADR 0043 (weights are human decisions), 0047/0049 (clean panel), 0050.

## Context
The honest-return audit rated the shop ~60/100 (process 82, execution 45, engine breadth 35).
To compress the path to 90, Amit pre-authorized the twelve decisions that were otherwise
sequential human-gate bottlenecks. These convert "review each result later" into standing
rules with **pre-committed acceptance bars** — so execution auto-proceeds when evidence clears
the bar, without a second round-trip. They do NOT reverse-engineer any return target (the
cardinal rule); every bar is an evidence threshold, not an outcome quota.

## Decisions
| # | Decision | Acceptance bar / guard (auto-proceed IFF met) |
|---|---|---|
| D1 | Cadence: auto-adopt the `rebalance_sim` sweep winner into production | turnover ≤1.5%/day **AND** net_ann within 4pp of gross_ann **AND** corr vs current banded ≥0.90 (plan 0011 WS1.1) |
| D2 | Tier budgets: SMALL 45 / MID 30 / LARGE 25; LARGE = near-static passive ballast | file ADR; adopt IFF replay net-return ≥ current at ≤1.2× book vol |
| D3 | Conviction sizing: score-proportional within tier | adopt IFF study A1 shows top-bucket edge t≥1.5 in ≥1 tier; else flat weights (honest) |
| D4 | Pre-authorized wiring: `eps_revision_yoy` SMALL @0.08 (coverage ≥40%, max\|ρ\|<0.5); `value_composite` **swaps** book_to_price SMALL if it beats it and ρ<0.95 | ADR-0043 lens still applies: correct sign, BY-FDR context reported |
| D5 | Keep `pledge_quality` S 0.10 + `governance` M −0.14; **kill rule:** unwire on `factor_decay` recent-12 IC sign-flip | standing rule, closes the open rebaseline review |
| D6 | Engine 2 (compounder sleeve): greenlight; 25% paper-capital share at launch | charter research (WS3.0) first; ≥6mo paper before any real capital |
| D7 | Engine 3 (special situations): greenlight; 15% paper share at launch | research (WS4.0) first; ≥6mo paper before real capital |
| D8 | Agents CRO/CIO/PM/Research: read-only reporters, weekly/monthly crons | charters ADR (WS6.0); no autonomous weight/wiring changes |
| D9 | Regime overlay: build on research completion | acceptance: max-DD −10pp for ≤2pp CAGR give-up, walk-forward on survivorship-free history; else publish negative + drop |
| D10 | Options overlay: deferred until D2 LARGE ballast live | design research (WS7.3) as prerequisite |
| D11 | Guardrails reaffirmed: ≤10 hypotheses/month, no reverse-engineering to a target, dead ends stay dead | non-negotiable |
| D12 | Run the 4 deep-research dives back-to-back now: events → compounder charter → special situations → regime | reuse-first (memory + docs/reference); one build-candidate card per candidate |

## Consequences
- Plan 0011's human gates are pre-cleared; execution is now evidence-gated, not decision-gated.
- Honest trajectory unchanged: ~68 (cadence+budgets land) → ~76-78 (dives + D4 wirings + agents)
  → ~82-84 (engines paper-trading, first re-audit) → **90 declared only after two consecutive
  quarterly re-audits ≥88.** The ~10 points that are *demonstrated track record* (paper history,
  OOS anchors) cannot be decided into existence — the calendar produces them.
- `factor_decay` sign-flip becomes a live unwire trigger (D5) — first automated weight-removal
  rule in the system (previously all removals were manual per ADR 0043; this is a narrow,
  pre-authorized exception with a mechanical, non-discretionary condition).
