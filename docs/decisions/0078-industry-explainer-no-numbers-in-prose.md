# ADR 0078 — The industry explainer: twelve cards, no numbers in prose, written on the subscription

**Status:** accepted · 2026-10-16 · plan 0016 P5 (`sector_narrative` kind)

## Decision

1. Every industry gets a twelve-card plain-words explainer (`sector_metadata.payload.explainer`): tea-stall version and business-model "doors", the value chain as a kitchen with "who stands where" bands, end markets, a ₹100 P&L walk with "does this line matter", a cycle clock with timeline and four hands, a macro wiring table, bottlenecks, a rulebook, five forces, a results-call cheat sheet, lead indicators with a three-sign rule and a call, tell-a-friend, glossary. It replaces the collapsed "More context" block, the parent-sector macro contributors and the parent-sector regulatory feed on Sectors › Industry Detail.
2. **Prose fields carry no digits** except years and calendar tokens (FY25, Q1). `tools/sector_explainer.validate_explainer` rejects the rest. Numbers live only in structured fields a reader can see are illustrative (the ₹100 walk, force scores) or that the cockpit fills live (dial readings from `macro_history`, cheat-sheet medians from `fundamentals_screener`, the model's score). Same reason as the dossier rule: an LLM hallucinates plausible figures.
3. The explainer is **written by a Claude Code session on the subscription** (`--print-prompt` → answer → `--ingest`), not by the paid API: the API account had no credit on 2026-10-16 and plan 0016 D1/D2 put LLM work on the subscription anyway. The API route stays in the tool as a fallback.
4. The v1 story (value chain, segments, competitive landscape, trend bullets) is kept inside the same payload; the page shows the story's date next to the model's date so a reader can tell a five-month-old figure from today's.

## Consequences

- Dials are mapped to existing macro series only; China producer prices, European gas and container freight have no feed yet and show "no feed" until one is added through `hosts.HOSTS`.
- Regulatory events are the parent sector's, filtered by the explainer's keywords, until the event classifier tags an industry.
- A per-stock "door" tag (commodity / specialty / contract …) is the next step; until then doors list example tickers only.
- Refresh cadence: quarterly, or when the clock position changes; `python -m tools.sector_explainer --missing` lists what is unwritten.
- All 38 explainers are archived in `docs/research/0013-industry-explainers.json`; `--restore` rebuilds the DB rows from it. `tools/sector_narrative_fetcher.save_payload` carries the explainer keys over on a story refresh (it used to replace the whole payload).
- They were written without web search, from the writers' knowledge plus the prompt's headlines: 2025–26 events in the timelines are unverified and deserve a check on the next refresh.

