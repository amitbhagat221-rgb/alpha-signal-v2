# ADR 0061 — Retire the UHS trust score and the dead gates; the data behind a pick is its factor coverage

**Status:** accepted 2026-10-03 (Amit: "yes retire uhs and the dead gates … but still I would need some sort of score to understand") · **Supersedes:** ADR 0033 (Trust Pipeline + UHS), ADR 0037 (per-stock UHS; its PT plausibility sweep stays) · **Builds on:** ADR 0060

**Decision.** The Unified Health Score is retired: no per-pick, factor, table or system score is computed, and the
reader-side pick gate is integrity only (`views.PICK_GATE_SQL`). Gates 3 (continuity), 4 (cross-source), 5 (units
as a verdict), 6 (lineage) and 7 (anchor) are retired as verdict writers; the two write-time gates that quarantine
bad rows before they are written — identity and plausibility (`validators/_verdicts.GATES`) — stay, and the health
report fires if either goes silent. The number a reader sees instead is one the ranking already produces:
**`eligible_coverage`, the share of the factor weight that applies to this stock which was backed by a real value**,
worded once in `views.pick_data` ("Data 86% · Partial · ranked on 6 of 7 factors, missing consensus"). The gate's
thresholds live once in `config.PICK_GATE`.

## Why
- The score barely varied: 1,769 picks on 2026-10-02 took three distinct values, 97–98 for almost all. Two of its
  five parts were never measured; a third was a constant.
- Gates 3/4/5 ran once by hand on 2026-05-31 and were never scheduled. Gate 7's step ran daily for four months and
  never wrote a verdict (it compared NSE closes with NSE closes). Gates 4 and 7 are the daily feed reconcile
  (`tools/reconcile.py`) by another name.
- The live gates check analyst, broker, banking and MF tables, none of which the ranking reads
  (`pit.features_at`), so the score measured the wrong tables.
- It did harm: on eight Tuesdays (4 Aug – 29 Sep 2026) the gate hid 4–16 SMALL picks, one ranked 15th, because
  their Yahoo price target failed plausibility ("PT 1309 vs close 61") — a field the ranking has not used since
  ADR 0045.
- `eligible_coverage` is what the screener's own gate (`_pick_eligible`, ADR 0021) is built on: per stock, already
  stored, 62–100% across today's picks, and it says exactly what it is.

## What changed
- Removed pipeline steps `compute_health_score`, `anchor_audit`, `update_uhs_calibration`; the screener no longer
  calls `batch_write_pick_uhs`. `scoring/health_score.py`, `scoring/confidence.py`, `tools/trust_backfill.py`,
  `tools/anchor_audit.py`, `validators/temporal_continuity.py`, `validators/cross_source.py` → `_archive/`.
  `validators/unit_contract.py` stays: its unit registry guards every `db.insert_df`.
- `factors.FACTORS` lost `uhs_tables` / `freshness_table`; `config.TRUST_BANDS` → `config.PICK_GATE`.
- Surfaces: stock page badge + "Data" tab, picks email footer, dossier prompt ("DATA BEHIND THIS PICK", with the
  missing factors banned from the narrative), MCP `picks.eligible_coverage` and `stock.data`, org desk brief
  `data_coverage`. The ops Health page's trust card is gone; `TRUST_GATE_DORMANT` now watches the two live gates.
- Health checks `TRUST_SYSTEM_LOW` and `PICKS_BLOCKED` retired (13 checks remain + the data families).
- Tables `health_score`, `uhs_calibration_log`, `external_anchors` and `daily_picks.uhs_*` stay as history; nothing
  writes them. The regression fixture for the 2026-05-23 forecast contamination now guards the extractor itself.

## Consequences
- Published picks change only in that a stock is no longer hidden for a bad price target; today 0 picks were hidden.
- `datamodel/sync.py` keeps mirroring `health_score` into `check_results` ('uhs') and `picks.uhs`: that mirror is
  where the history lives once the legacy tables are dropped. No new rows arrive, parity stays equal, nothing to do.
- An old `daily_picks` row has `uhs_score`; a new one has NULL. Readers use `eligible_coverage`.
