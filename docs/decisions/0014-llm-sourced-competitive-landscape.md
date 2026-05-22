# 0014 — Competitive landscape sourced from LLM, includes private players
**2026-05-11 · Accepted**

**Decision.** Generate per-industry `competitive_landscape` via Sonnet 4.6 + web search, persist in `sector_metadata.payload.competitive_landscape`, render as primary "industry share" view. Keep listed-only share as a clearly-labeled secondary card.

**Shape.**
```json
{
  "share_basis": "Domestic passenger market share (DGCA FY25)",
  "as_of": "FY25 / Oct-2025",
  "players": [
    {"name":"IndiGo","ticker":"INDIGO","share_pct":65,"listed":true},
    {"name":"Air India Group","ticker":null,"share_pct":26,"listed":false},
    ...
  ]
}
```

**Why.** Aviation showing "IndiGo 100%" was wrong — Air India (~26%), Akasa (~5%), BSNL in Telecom (~7.9%) materially shape industry economics but aren't in `stocks`. Buying a market-share dataset costs ~₹10-50K/mo per sector. Manual curation = 37 industries × ~8 players × quarterly maintenance = no.

**Trust model.** Best-effort, dated, authoritative-by-citation — not maintained.
- **For understanding** an industry: trust enough to surface in UI
- **For picking stocks**: any factor using these values must validate via backtest (same gate as every other factor, ADR 0009)
- Refresh quarterly (~₹30 for full 37-industry rerun, idempotent on `(sector, source)`)

**Listed enrichment is strict-ticker-only.** Name-token fallback was tried then removed (commit `903de71`) — it mapped "Reliance Jio" → defunct `RCOM`. If narrative omits the ticker, the player stays non-clickable Private. Accepted trade-off vs wrong-link bugs.

**Per-industry `share_basis` differs.** Passenger share (Aviation), asset share (Banks), AUM (AMCs), subscribers (Telecom), revenue (FMCG). **Not comparable across industries.** UI labels it; careless readers may miss.

**Related.** ADR 0013 (industry drill, parent) · plan 0003 (factor consumption gated by backtest)
