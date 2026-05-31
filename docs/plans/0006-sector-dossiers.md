# Plan 0006 — Sector dossiers (sector-as-stock daily read)

**Status**: implemented · proposed 2026-05-29 · **A + B + C shipped 2026-05-29 · D + E shipped 2026-05-31** · archive ~2026-06-30
**Goal**: turn `/sectors` from a useless 47-card industry heatmap into a daily narrative read shaped like a stock dossier — horizon-aware, with tailwinds/headwinds decomposed by force (regulation, tech, market, macro), and a curated bucketed digest at the front door.
**Total estimated effort**: ~4-6 sessions across 5 phases. Phases A-C are the MVP and ship the new UX; D and E are quality upgrades.

---

## Why this plan

Today's `/sectors` front door is a grid of 47 industry cards (avg_score, breadth_pct, top-3 tickers). It surfaces a *lot* of data and answers no question. Two real complaints captured 2026-05-29:

1. **47 cards, no anchor.** Eye can't decide where to start; nothing tells you which sector deserves attention today.
2. **Wrong question.** A prior attempt (Macro × Model alignment scatter + alignment table) was also rejected — the conflict-detection framing isn't what the reader wants. The reader wants the sector treated *like a stock*: small/medium/long horizon view, what to watch for, what's booming, what's likely to boom, headwinds/tailwinds split by source (regulation / tech / innovation / markets / macro).

The data layer is **not** the gap. We already have most raw materials:

- `sector_metadata` — 48 auto-generated dossiers with `summary`, `value_chain`, `drivers` (revenue/cost/growth), `regulators`, `cyclicality`, `segments`, `india_specific`, `trend_bullets`
- `macro_sector_signals.macro_detail` — structured driver lines like `iip_capital_goods: +3.2% YoY | core_cement: +13.5% YoY`
- `regulatory_events` — 31K events with `title`, `summary`, `ministry`, `published_at`
- `daily_picks` — per-stock model output, sector-joinable
- FII/DII sector flow (14:00 forward cron)

What's missing is **synthesis + presentation**, not data.

---

## Target shape (v1 ASCII mockup)

```
INDIAN SECTORS — 29 MAY 2026

🔥 BOOMING NOW                                            picks today
   Capital Goods                                                10
     ↑ IIP capital goods +3.2%, cement +13.5%, steel +6.9%
     ABB, LART, BHEL, POWERINDIA, INTLCONV

🌱 LIKELY TO BOOM (catalysts visible, model not in yet)
   Real Estate                                                  2
     Tailwind 75 · 2 picks · REIT inflow + festive demand approaching

⚠️ HEADWINDS                                              risk
   Energy                                                       6
     ↓ Crude weak, refinery margins compressed
     Model still picking here — RELIANCE, BPCL, IOC

──────────────────────────────────────────────────────────────────
BY FORCE — what's pushing which sector

📜 Regulation              ⚡ Tech / Innovation
  + GatiShakti                + EV charging infra
    → Capital Goods             → Power, Auto Components
  − 28% GST gaming            + GenAI capex
    → Comm Services             → IT (recipient)

📈 Markets                  🏛 Macro
  + FII +₹4,500cr (1w)        + IIP mfg +1.5%, capital +3.2%
    → Financials, Cap Goods     + Credit +11.5%, GST ₹183K cr
──────────────────────────────────────────────────────────────────

⏱ Horizons (medium-term lens — quarterly cycle).
    Review weekly; don't react daily.
```

Click any sector row → existing `/sectors?sector=X#per-sector` detail panel (unchanged).

---

## Phase A — Sector-brief aggregator (MVP backbone)  ✅ shipped 2026-05-29
**Effort**: 1 session. **Pure backend; no UX yet.**

Build the data spine the new page needs.

### Deliverables
1. New file `signals/sector_briefs.py` with `build_sector_briefs(snapshot_date)`:
   - JOIN `macro_sector_signals` (latest) + `daily_picks` (latest) + `stocks` + `regulatory_events` (last 30d) + FII/DII sector flow
   - Per sector: `n_stocks`, `mcap_total_cr`, `macro_score`, `macro_signal`, `macro_drivers` (parsed list of dicts), `breadth_pct`, `avg_score`, `n_picks_top30`, `top_picks` (capped at 5), `n_regulatory_30d`, `fii_net_30d`, `dii_net_30d`
   - Classifier → `bucket` ∈ {`BOOMING`, `LIKELY`, `HEADWIND`, `QUIET`} via rule:
     - BOOMING = macro ≥ 60 AND breadth ≥ 50
     - LIKELY = macro ≥ 60 AND breadth < 50 (catalysts visible, model not in yet)
     - HEADWIND = macro < 40
     - QUIET = everything else
2. New table `sector_briefs` (PK: sector + date) persisting the result. Schema in `schema.sql`.
3. New pipeline step `compute_sector_briefs` registered in `config.PIPELINE_STEPS` (non-critical, runs after picks).

### Done when
- `SELECT * FROM sector_briefs WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM sector_briefs)` returns 1 row per sector with all fields populated.
- Bucket distribution is reasonable (≥ 1 in BOOMING + LIKELY combined on a typical day; not all 11 in QUIET).

---

## Phase B — Force decomposition (raw → grouped)  ✅ shipped 2026-05-29
**Effort**: 1 session.

**Finding**: v2's `fii_dii_cash_flow` table is index-level only (`category` ∈ {FII,DII,Client}, no sector column). Phase B emits zero market-force rows; the `sector_force_breakdown.force = 'market'` slot is reserved. Phase C's cockpit UI renders an explicit "attribution pending" placeholder. Sector-level FII/DII attribution is out of scope for v1.

Turn the per-sector raw data into the four force columns the UI needs.

### Deliverables
1. Macro force: parse `macro_detail` strings into structured `(driver, value, direction)` tuples — already semi-structured (`iip_capital_goods: +3.2% YoY`); deterministic regex.
2. Regulation force: bucket `regulatory_events` by `ministry` → sector mapping table (`sector_regulator_map`); compute `regulation_impact` (+/-/neutral) from event sentiment (use existing `classifier_status` or rule-based by ministry).
3. Market force: pull `fii_net_30d`, `dii_net_30d` per sector from the 14:00 forward-cron tables. Direction = sign of net flow.
4. Tech/innovation force: pull from `sector_metadata.drivers.growth` array — these are the auto-generated growth theme bullets. Honest gap: LLM-generated; some will be re-skinned macro. The proper signal arrives in Phase D.
5. Output schema: `sector_force_breakdown` (sector + date + force + direction + summary text + linked sectors).

### Done when
- Each of the 4 forces returns at least one tagged sector with direction + summary text.
- A spot-check on Capital Goods shows: regulation (GatiShakti / PLI), tech (EV infra), market (FII flow), macro (IIP capital goods). At least 3 of 4 forces populated for a "BOOMING" sector.

---

## Phase C — Cockpit front door  ✅ shipped 2026-05-29
**Effort**: 1 session. **The visible UX win.**

Replace the heatmap tab with the digest layout. Keep tabs 2 and 3 (Industry Detail, Rotation) unchanged.

### Deliverables
1. New cockpit function `cockpit/api.py:get_sector_digest()` — reads `sector_briefs` + `sector_force_breakdown`, returns structured JSON for template.
2. Rewrite Tab 1 of `cockpit/templates/sectors.html`:
   - Top: BOOMING / LIKELY / HEADWIND grouped sector rows with picks count + ticker list + macro driver one-liner.
   - Middle: BY FORCE 2×2 grid (📜 Regulation · ⚡ Tech · 📈 Markets · 🏛 Macro).
   - Bottom: static horizon footnote.
3. Rename Tab 1 label from "Heatmap" → "Today" (keep anchor `heatmap` for URL backward-compat).
4. Each sector row clickable → `/sectors?sector=X#per-sector` (existing detail panel, unchanged).
5. Subtitle on page updated: "11 sectors · what's booming today, what's about to."

### Done when
- `/sectors` front door fits one screen, anchored on 3-5 bucket entries.
- Test on a quiet day (all QUIET): UX still works ("no clear leader today — review BY FORCE").
- The 47-card heatmap is gone; nothing in the cockpit links to a deleted view.

---

## Phase D — LLM-narrated thesis (per sector)
**Effort**: 1-2 sessions. **Quality upgrade — fills the tech/innovation gap.**

Per-sector daily narrative parallel to the stock dossier.

### Deliverables
1. New table `sector_dossiers` (PK: sector + date) with LLM-generated fields:
   - `thesis` (1 sentence)
   - `bull_case` (3 bullets)
   - `bear_case` (3 bullets)
   - `what_to_watch` (3 bullets, each horizon-tagged: S / M / L)
   - `tech_innovation_drivers` (2-3 bullets — this is what purely-deterministic Phase B can't synthesise)
2. New file `output/sector_dossier.py` mirroring `output/dossier.py` patterns. Same hygiene contract: **no raw numbers in narrative fields** (calendar tokens like Q1/FY25/H1 OK; specific decimals/percentages/rupee amounts/multiples not — they hallucinate plausibly).
3. New pipeline step `compute_sector_dossiers` — 11 LLM calls/night, ~₹3-5 in API cost, ~30s wall-clock.
4. Cockpit rendering: under each sector row in the bucket, show `thesis` + `what_to_watch` (collapsed; click to expand bull/bear/tech).

### Done when
- Each sector has a thesis + 3 watch-items + 2-3 tech drivers, generated nightly.
- `output/sector_dossier.py` validator catches raw-number hallucinations; cockpit shows `{}` for invalid dossiers (mirror stock-dossier pattern from HALC 2026-05-22).
- A pick-quality reviewer can read `/sectors` in 90 seconds and walk away with 1-2 concrete watch items.

---

## Phase E — Per-sector horizon scores (deferred)
**Effort**: 1-2 sessions. **The final piece of "sector-like-stock".**

Today the horizon framing is a static footnote ("medium-term lens"). Phase E makes each sector display **S / M / L** horizon strengths individually.

### Deliverables
1. New factor file `signals/sector_momentum.py`:
   - Short: 1m sector ETF / index return relative to NIFTY
   - Medium: 3m, breadth_pct trend (last 4 weeks)
   - Long: 12m vs. macro cycle position (using `macro_history`)
2. Per-sector horizon scores in `sector_briefs`: `horizon_short`, `horizon_medium`, `horizon_long` ∈ {strong, neutral, weak}.
3. Cockpit: render as 3 small badges next to each sector name (similar to stock dossier horizon strip).
4. PIT helper for sector momentum (required by CLAUDE.md "ship factor + PIT as one unit" rule).

### Done when
- Each sector has 3 horizon badges visible.
- A "booming now" sector with weak L horizon visibly stands out (different framing than one with strong L).
- Sector momentum factor registered in `BACKTEST_SIGNALS`.

---

## Sequencing & integration points

- **Phase A blocks Phase B and Phase C.** A is pure backend, ships in one session.
- **Phase B + Phase C can ship together** if a session has bandwidth — Phase B output is consumed by Phase C template.
- **Phase D is independent** of Phase E. D can ship before E.
- **Phase E** requires sector momentum factor — that overlaps with [plan 0002 §3.2](0002-100-factors-and-model.md) factor build. Register in `BACKTEST_SIGNALS`.

## Cross-references
- [plan 0002](0002-100-factors-and-model.md) — sector momentum factor (Phase E)
- [ADR 0017](../decisions/0017-factor-library-two-tier-registry.md) — factor registry rules apply to sector_momentum
- Stock-dossier pattern (`output/dossier.py`) — copy hygiene contract for `output/sector_dossier.py`

## Out of scope (v1)
- Industry-level dossiers (the 47 sub-industries). Keep industry detail in Tab 2 unchanged; v1 dossier shape is at the **sector** level only.
- Per-sector LLM regeneration on demand from cockpit — keep nightly batch only.
- Cross-sector comparison view ("show Capital Goods vs. Industrials side by side") — feature creep; revisit if requested.
