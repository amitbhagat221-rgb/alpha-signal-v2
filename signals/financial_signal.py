"""
Alpha Signal v2 — Financial Signal (Phase 2.2b — SKELETON)

⚠ STATUS: skeleton only. Phase 2.2a-ii (the Screener.in parser at
sources/banking_metrics.py) shipped 2026-05-29. Phase 2.2b — this module —
fills in the score computation, routing, and PIT helper.

Per-stock score for Banks + NBFCs (158 stocks). The main screener's quality
signals (Piotroski, accruals, ROIC) don't apply — banks have no inventory,
COGS, or operating margin in the conventional sense. This module replaces
them with banking-specific lens per Plan 0001 §2.2 + v1's financial_model
reference (alpha-signal/docs/financial_model_reference.md, 53 lines).

INPUTS (from `banking_metrics`, written by sources/banking_metrics.py):
  Quarterly:
    gross_npa_pct, net_npa_pct           — asset quality (40% of score)
    interest_earned, interest_expended   — for NII derivation
    net_interest_income                  — already computed in scrape
    pre_provision_op_profit, net_profit  — profitability inputs
  Annual:
    deposits, borrowings                 — for cost of funds + D/E
    book_value_per_share                 — for P/B
    cost_of_funds_pct                    — already computed in scrape
  Derived (this module):
    nim_pct          = 4 × NII_qtr / advances_latest × 100   [needs advances from fundamentals_screener]
    roa_pct          = 4 × net_profit_qtr / total_assets × 100
    pb_adj_pct       = price / adj_book_per_share
    de_ratio         = borrowings / equity                   [NBFCs]
    nii_growth_yoy   = NII_qtr / NII_qtr-4 - 1

SCORE FORMULA (Plan 0001 + ref doc):

  Asset Quality      (40%)  ← GNPA × NNPA × slippage_delta
  Profitability      (30%)  ← NIM × ROA × NII_growth
  Capital            (15%)  ← CAR / CRAR (gated on Phase 2.2c RBI fallback)
  Moat / Funding     (15%)  ← CASA (banks) or Cost of Funds (NBFCs)
                              CASA gated on Phase 2.2c; today use COF for both

Each component zscored within (industry, cap_tier) — same approach as the
main screener's _zscore_within_segment helper. Z-scores capped at ±3.

BENCHMARKS (cutoffs from ref doc — useful for diagnostics, not as a hard
gate; the score expresses *degree* of pass/fail, the screener can gate
later if desired):

  Banks      ROA ≥ 1.0% · NIM ≥ 3% · GNPA ≤ 3% · NNPA ≤ 1% · CASA ≥ 40% · CAR ≥ 15%
  NBFCs      NIM ≥ 6%  · GNPA ≤ 4% · D/E ≤ 4x · CRAR ≥ 18%

NBFC sub-segmentation (gold-loan / housing / MFI / consumer) — defer to
v1.5 of this signal. NIM benchmarks vary by sub-segment (gold ~12-18%,
housing 2-3%), so applying one cutoff is misleading. For Phase 2.2b ship
"NBFC: NIM ≥ 6%" as the single benchmark and surface sub-segment via the
cockpit page (Phase 2.2d).

OUTPUT TABLE (write to `financial_signal_scores`):

  sid, snapshot_date, industry, cap_tier,
  asset_quality_z, profitability_z, capital_z, funding_z,
  financial_signal,                  -- composite −3..+3 (clip)
  components_present,                -- 1-4, gates downstream display
  computed_at

ROUTING (Phase 2.2b also touches scoring/screener.py):
  - In `_load_signals`, for sid where industry IN ('Banks','NBFCs/Finance'):
      - REPLACE piotroski, accruals, value_composite contributions with
        financial_signal × <weight>
      - KEEP momentum, sentiment, smart_money, insider, regulatory, macro
        (face-valid for banks/NBFCs)
      - KEEP analyst consensus (works fine for banks)
  - Recommend weight: financial_signal at 0.45 (sum of replaced components).
    Tune post-PIT-backtest (Phase 2.2d).

PIT HELPER (tools/reconstruct_pit.py):
  - Add `financial_signal` column to daily_snapshots_pit
  - Reconstruct historical scores from `banking_metrics` filtered by
    period_end ≤ pit_date - filing_lag (use 75d for annual, 60d for
    quarterly to match other signals).
  - Required for the Phase 2.2d done gate (t-stat ≥ 2.0 within Financial
    Services subset, per Plan 0001).

USAGE (when implemented):
    python -m signals.financial_signal              # compute + save
    python -m signals.financial_signal --dry-run    # compute, don't write
    python -m signals.financial_signal --sid HDBK   # one stock

MIGRATION CHECKLIST (Phase 2.2b session):
  [ ] Add `financial_signal_scores` table to schema.sql + live DB
  [ ] Implement _load_data, _compute_score, _zscore_within_segment
  [ ] Add `financial_signal` to daily_snapshots_pit (`_COLUMN_MIGRATIONS`)
  [ ] Add PIT helper in tools/reconstruct_pit.py
  [ ] Touch scoring/screener.py for routing (one branch on industry)
  [ ] Add to PIPELINE_STEPS (after fetch_banking_metrics, before screener)
  [ ] BACKTEST_SIGNALS registry entry (db.py)
  [ ] Cockpit page (Phase 2.2d) — defer
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql

# Plan 0001 + ref doc benchmarks. Diagnostic only — score is z-scored,
# not gated. Sourced from MDPI 2025 (NIM β=+0.583, NNPA β=−0.251).
BANK_BENCHMARKS = {
    "roa_pct":      {"good": 1.0,  "caution": 0.5,  "bad": 0.0,  "direction": "higher"},
    "nim_pct":      {"good": 3.0,  "caution": 2.0,  "bad": 1.0,  "direction": "higher"},
    "gross_npa_pct":{"good": 3.0,  "caution": 5.0,  "bad": 10.0, "direction": "lower"},
    "net_npa_pct":  {"good": 1.0,  "caution": 2.0,  "bad": 4.0,  "direction": "lower"},
    "casa_pct":     {"good": 40.0, "caution": 30.0, "bad": 20.0, "direction": "higher"},
    "car_pct":      {"good": 15.0, "caution": 11.5, "bad": 9.0,  "direction": "higher"},
}
NBFC_BENCHMARKS = {
    "nim_pct":      {"good": 6.0,  "caution": 3.0,  "bad": 1.0,  "direction": "higher"},
    "gross_npa_pct":{"good": 4.0,  "caution": 6.0,  "bad": 10.0, "direction": "lower"},
    "de_ratio":     {"good": 4.0,  "caution": 6.0,  "bad": 10.0, "direction": "lower"},
    "crar_pct":     {"good": 18.0, "caution": 15.0, "bad": 12.0, "direction": "higher"},
}


def _NOT_YET_IMPLEMENTED():
    """Phase 2.2b implementation goes here.

    Sketch:
      1. Load latest quarterly + annual per sid from banking_metrics
      2. Join advances + total_assets from fundamentals_screener (for NIM, ROA)
      3. Compute components per BANK/NBFC benchmarks (z-score within segment)
      4. Weight: 40% asset_quality + 30% profitability + 15% capital + 15% funding
      5. Track components_present (degrade score if <3 of 4)
      6. Write to financial_signal_scores
    """
    raise NotImplementedError(
        "Phase 2.2b implementation pending. "
        "See module docstring for spec. "
        "Backfilled banking_metrics ready; verify with "
        "`sqlite3 data/alpha_signal.db \"SELECT COUNT(DISTINCT sid) FROM banking_metrics\"`"
    )


def main():
    _NOT_YET_IMPLEMENTED()


if __name__ == "__main__":
    main()
