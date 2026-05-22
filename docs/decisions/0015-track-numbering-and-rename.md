# 0015 — Track numbering and project-wide rename
**2026-05-22 · Accepted**

**Decision.** Three workstreams, numbered. Each named by what it delivers.

| Track | Name | Status |
|---|---|---|
| **Track 1** | **Foundation** | ✅ Done 2026-05-01 |
| **Track 2** | **Portfolio** | ⏳ Active |
| **Track 3** | **Factor model** | ⏳ Active |

**Notation.**

| Form | Meaning |
|---|---|
| `Track N` | Top-level workstream |
| `N.M` | Sequential phase (2.1 → 2.2 → 2.3) |
| `N.M a/b/c/d` | **Forks** — parallel sub-streams of one phase, ship in any order |
| `N.M ↔ P.Q` | **Cross-track parallel** — two phases meet at a shared artifact |

**Glyphs (project-wide).** ✅ done · ⏳ next/in-progress · 🚫 blocked · 💤 parked · ↔ integration point

## Why

C-track / D-track / F-track lettering was v1-legacy artifact. C and D were sequenced research → deployment phases; F was bolted on later. Six different sub-numbering schemes (C12/C13b, D14–D18, F1–F3, Phase A/B/C, F-A1–F-A4, F-C1–F-C4) all coexisted. The lettering carried no information and the inconsistency cost scanning time on every doc.

The decision question wasn't "what's the right naming?" but "should we have ONE convention or six?". One.

## Full mapping (canonical)

**Track 1 — Foundation** (was: engineering + C-phases)
- 1.1 v1 audit + rebuild plan
- 1.2 Tier infrastructure ← was C12
- 1.3 Stratified backtest + VIX regime ← was C13
- 1.4 36-month PIT reconstruction ← was C13b
- 1.5 v2 cutover (2026-05-01)

**Track 2 — Portfolio** (was: D-track / Intelligence track)
- 2.1 Small-cap quality gate ← was D14
- 2.2 Financial sub-model ← was D15
- 2.3 Cyclical overlay ← was D16
- 2.4 Segment models + portfolio ← was D17 — **↔ 3.3c**
- 2.5 XGBoost overlay ← was D18 — **↔ 3.3b**

**Track 3 — Factor model** (was: F-track)
- 3.1 Data acquisition ← was Phase A / F1
  - 3.1a Screener Premium ← was F-A1
  - 3.1b NSE F&O OI ← was F-A2
  - 3.1c Kite Connect ← was F-A3
  - 3.1d PIB + earnings call NLP ← was F-A4
- 3.2 Factor build, 50 factors ← was Phase B / F-B / F2
- 3.3 Factor model upgrade ← was Phase C / F-C / F3
  - 3.3a IC stability weighting ← was F-C1
  - 3.3b Orthogonalization ← was F-C2 — **↔ 2.5**
  - 3.3c Mean-variance portfolio ← was F-C3 — **↔ 2.4**
  - 3.3d Risk decomposition ← was F-C4

## What stays as-is

- **"C13b"** — a *dataset name* / *methodology proper noun*, not a track label. The validation that produced the signal map in [signal-weights.md](../reference/signal-weights.md) is and will always be "C13b". Leave in code comments (`tools/backtest_pit.py`, `tools/reconstruct_pit.py`), in ADRs that reference it (0005, 0007, 0010, 0011, 0012), and in `db.py` table descriptions.
- **Plan filenames** — `0001-mother-plan.md`, `0002-100-factors-and-model.md`, `0003-market-share-momentum-factor.md` keep their slugs. Numbering convention is for *phases*, not plan filenames.
- **ADR filenames** — write-once per convention. ADR 0009's filename `0009-factor-track-parallel-to-d-track.md` stays; its body is updated with a pointer to this ADR.
- **`BACKTEST_SIGNALS`** registry, signal names (`piotroski_f_score`, `roic`, `fcf_yield`) — code identifiers don't change.

## Migration scope (executed this commit)

Doc files rewritten:
- `docs/plans/0001-mother-plan.md` (D14–D18 → 2.1–2.5)
- `docs/plans/0002-100-factors-and-model.md` (Phase A/B/C → 3.1/3.2/3.3 with letter-suffix sub-phases)
- `docs/plans/0003-market-share-momentum-factor.md` (F-track → Track 3)
- `docs/plans/0004-consumer-demand-pulse.md` (F-track → Track 3)
- `docs/plans/README.md`
- `docs/reference/architecture.md`, `signal-weights.md`, `paid-data-sources.md`, `api-endpoints.md`, `data-playbook.md`
- `README.md`, `HANDOFF.md`
- `docs/decisions/0009-factor-track-parallel-to-d-track.md` (lightweight body edit + pointer here)
- `docs/decisions/0011-long-format-for-new-fundamentals-tables.md`, `docs/decisions/README.md`

Code refs rewritten (comments + user-facing labels only):
- `config.py` (factor module comments)
- `db.py` (table description strings referencing D15/D17)
- `signals/sales_growth_relative.py` (comment)
- `tools/backtest_pit.py`, `tools/reconstruct_pit.py` (F-track cluster comments)
- `cockpit/api.py` (group labels "F-track / Quality" → "Track 3 / Quality"; factor labels "ROIC (F-track)" → "ROIC (Track 3)")

New file: `docs/plans/0000-checklist.md` (aggregated status view, updated via `/handoff`).

## Rollback

Forward-only. The mapping table above is the historical record — old documents referencing C/D/F language can be translated via this table.

## Related

- ADR 0009 — original F-track parallel decision (body updated to use new terminology; this ADR is the canonical record of the *rename*)
- ADR 0011 — long-format fundamentals tables (also touched)
