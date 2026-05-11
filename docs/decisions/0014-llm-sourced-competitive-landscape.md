# ADR 0014 — Competitive landscape sourced from LLM, includes private players

**Status:** Accepted
**Date:** 2026-05-11
**Owner:** Amit Bhagat
**Related:** ADR 0013 (industry drill), plan 0006 (sector intelligence), plan 0007 (market share momentum)
**Supersedes:** —

## Context

The "top players" view on `/sectors?industry=Aviation` until this session showed IndiGo at 100% market-cap share of the listed universe. Two problems:

1. **Listed-universe share misrepresents the industry.** Air India (Tata, private) carries ~26% of Indian domestic passenger share. Akasa Air (private) ~5%. BSNL in Telecom carries ~7.9% subscriber share — these state-owned or private-group competitors materially shape industry economics but show up nowhere in `stocks`.
2. **Listed-share denominator was wrong anyway.** Top-N's own mcap-sum was the denominator, so a single dominant ticker always rendered 100% even when other listed peers existed (since several had NaN mcaps).

Fixing (2) is a one-line denominator change. Fixing (1) requires real data on private players' shares — data we don't subscribe to and aren't going to scrape.

## Decision

**Generate a structured `competitive_landscape` per industry via LLM (Sonnet 4.6 + web search), persist in `sector_metadata.payload.competitive_landscape`, and render it as the primary "industry share" view on the cockpit. Keep listed-only share as a clearly-labeled secondary card.**

Specific shape:

```json
"competitive_landscape": {
  "share_basis": "Domestic passenger market share by passengers carried (DGCA, FY2025 / Oct 2025)",
  "as_of": "FY25 / Oct-2025",
  "players": [
    {"name": "IndiGo", "ticker": "INDIGO", "share_pct": 65.0, "listed": true,  "note": "LCC, dominant domestic & intl"},
    {"name": "Air India Group", "ticker": null, "share_pct": 26.0, "listed": false, "note": "Tata Group; post-Vistara merger"},
    {"name": "Akasa Air", "ticker": null, "share_pct": 5.0,  "listed": false, "note": "Rakesh Jhunjhunwala-backed LCC"},
    ...
  ]
}
```

Source: [tools/sector_narrative_fetcher.py](../../tools/sector_narrative_fetcher.py) — prompt explicitly requires private/unlisted majors (state-owned, foreign subsidiaries, group-unlisted) with `listed: false`, and instructs Claude **not** to normalize shares to 100% over listed-only (so the bars + a computed "Others / long tail" residual sum to ~100% of the real industry).

Listed players are enriched at read time by [cockpit/api.py:get_industry_competitive_landscape](../../cockpit/api.py): explicit ticker match against `stocks` joins the SID + our composite score so the row becomes clickable through to `/explorer/{sid}`. **Name-token fallback was tried and removed mid-session** (commit `903de71`) — it mapped "Reliance Jio" to `RCOM` (defunct Reliance Communications). Only explicit-ticker matches enrich.

## Trust model

LLM-sourced market shares are **best-effort, dated, and authoritative-by-citation** — not authoritative by maintenance. We trust them enough to surface in the UI for **understanding** an industry, but not enough to use as a direct input to **picking stocks**.

- **For understanding:** the values inform a researcher building a thesis. A wrong share by a few percentage points doesn't materially change the picture.
- **For picking stocks:** any factor consuming these values (plan 0007's market share momentum) must validate the signal via backtest before earning a weight — same gate as every other factor (ADR 0009).

Concretely:
- Each `competitive_landscape` carries a `share_basis` (what the % represents — passenger share, asset share, AUM, subscriber base, revenue) and an `as_of` period.
- The UI surfaces both fields prominently. No disclaimer beyond "Source: AI-curated narrative" — the `share_basis` + `as_of` are the disclaimer.
- Refresh cadence: quarterly. Cheap (~₹30 for the full 37-industry rerun via Sonnet+web-search), idempotent on `(sector, source)` PK, fetcher is `--skip-existing`-safe.

## Why include private players at all

The opposing argument: "we only model the listed universe; private players are noise for stock-picking."

Counter: the question the page answers is "what does this industry look like?", not "what listed names should I buy?". A view of aviation that omits Air India is wrong, full stop, regardless of whether Air India is investable. The page **separately** shows our model's listed picks below — the user can see both: the industry as it is, and our actionable subset within it.

For factor consumption: plan 0007 explicitly wants share-shift signals that include private competitors (gaining share *from* unlisted majors is a different signal than gaining share *from* listed peers). The data substrate has to support both questions.

## Consequences

**Positive:**
- `/sectors` now answers an analyst-grade question correctly. Aviation shows IndiGo 65% / Air India 26% / Akasa 5% / SpiceJet 2.6% / regional tail — not "IndiGo 100%".
- Same fix applies cleanly to Banking (HSBC India / StanChart India branches), Telecom (BSNL 7.9%, Jio 41% as private subsidiary), FMCG (Amul 4.2%, Patanjali 2.5%), Pharma (Serum Institute 3.8%, Intas 3.5%), Autos (Honda Motorcycle 13.5%, Toyota Kirloskar, Kia, JSW MG) — all surface with correct private-vs-listed badges.
- Plan 0007 (market share momentum) has a data substrate.

**Negative:**
- Values are LLM-generated, refreshed quarterly, and may drift from reality between refreshes. A regulator move or major merger between refreshes won't be reflected.
- The `share_basis` differs per industry (passenger share for Aviation, asset share for Banks, AUM for AMCs, subscribers for Telecom, revenue for FMCG). Numbers are NOT comparable across industries. The UI labels this clearly but a careless reader might miss it.
- Factor work on this data must be tagged "experimental" until backtested. No factor consumes it yet.
- Fuzzy name matching is forbidden. If the narrative omits a ticker for a listed name we have, that name won't be clickable from the competitive_landscape card — accepted trade-off to avoid wrong-link bugs.

## Alternatives considered

- **Subscribe to a paid market-share dataset (e.g. Euromonitor, Nielsen, sector-specific).** Rejected: cost-prohibitive (~₹10K-50K/mo per sector), license restrictions on display, coverage gaps for India-specific sectors (Quick commerce, UPI, B2B SaaS).
- **Manual curation by Amit.** Rejected: 37 industries × 8 players each = 296 fact rows, plus quarterly maintenance. Already explicitly committed to zero hand-curation budget for plan 0006.
- **Use only listed-mcap share with a disclaimer "private players not shown".** Rejected: a disclaimer is not a substitute for a correct picture.
- **Scrape per-source (DGCA for aviation, RBI for banks, TRAI for telecom, etc.).** Rejected: too many one-off sources, too much per-source schema work, no scale path. The whole point of LLM-sourcing is one prompt covers all 37 industries.

## Migration / rollback

- Forward-only. Schema change is additive (`competitive_landscape` is a new optional key inside the existing `sector_metadata.payload` JSON column). Old payloads without the field still render (the new card just doesn't show).
- Re-fetching is idempotent via `INSERT INTO sector_metadata ... ON CONFLICT(sector, source) DO UPDATE`. Rollback to listed-only is a UI toggle, not a data migration.
