"""
Unit / Type Contract Gate — Trust Pipeline Gate 5, Plan 0007 Phase 4.

Catches the pt_upside %-vs-fraction class — a producer writes a value in one
unit (percent, e.g. 75.0 meaning 75%), a consumer reads it expecting another
(fraction, e.g. 0.75). Both pass plausibility individually. The mismatch is
silent until you spot a pick that's mysteriously over/under-weighted on a
factor.

ARCHITECTURE
    Producer side:  upsert_df asserts the writer's column matches the declared
                    UNIT_CONTRACTS unit. Mismatch raises UnitMismatchError —
                    LOUD, blocks the write. Different from Gates 1-4 which
                    quarantine; here the contract violation is a bug in the
                    code itself, not in the data.

    Consumer side:  db.read_typed(table, col, expected_unit) asserts the
                    column's declared unit matches the reader's expectation.
                    Mismatch raises UnitMismatchError.

UNIT_CONTRACTS LIVES IN lineage.py
    Same registry as FACTOR_LINEAGE — keep them co-located so editors see
    them together. This file imports it for use.

UNITS
    pct_100              0..100 (or -100..+1000 for ratios like pt_upside_pct)
    ratio_1              0..1   (or -1..+10)
    inr_crore            ₹ in crores
    inr_lakh             ₹ in lakhs
    inr_raw              ₹ raw rupees
    days                 calendar days
    timestamp_iso        ISO 8601 string
    timestamp_unix       Unix epoch seconds (int)
    sid                  Tickertape SID (TEXT, opaque)
    ticker               NSE ticker (TEXT, opaque)

USAGE — PRODUCER
    df = my_fetcher_returns_a_frame()
    assert_unit_contract(df, "consensus_signals", expected_units={
        "pt_upside": "pct_100",
        "eps_growth": "pct_100",
    })  # raises UnitMismatchError if declared and mismatched

USAGE — CONSUMER
    df = read_typed("consensus_signals", ["pt_upside"], expected_units={
        "pt_upside": "pct_100",
    })  # asserts unit; raises if registry says ratio_1
"""

from typing import Optional


class UnitMismatchError(Exception):
    """Raised when a producer or consumer declares a unit incompatible with
    the registered contract in lineage.UNIT_CONTRACTS."""
    pass


def get_unit(table: str, col: str) -> Optional[str]:
    """Look up the registered unit for (table, col). Returns None if undeclared."""
    try:
        from lineage import UNIT_CONTRACTS
    except ImportError:
        return None
    return UNIT_CONTRACTS.get((table, col))


def assert_unit(table: str, col: str, expected_unit: str) -> None:
    """Assert (table, col) is registered as `expected_unit`. Raises if mismatch.

    No-op (returns silently) if the column isn't registered yet — undeclared
    units default to "trust the caller". Add to UNIT_CONTRACTS to enforce.
    """
    declared = get_unit(table, col)
    if declared is None:
        return
    if declared != expected_unit:
        raise UnitMismatchError(
            f"{table}.{col}: registered unit is '{declared}' but reader/writer "
            f"expects '{expected_unit}'. Either update the producer/consumer "
            f"or update lineage.UNIT_CONTRACTS."
        )


def assert_frame_units(df, table: str, expected_units: dict) -> None:
    """Assert each column in `expected_units` matches the registered unit.

    Producer-side helper, called inside db.upsert_df. `expected_units` maps
    column name → expected unit string.
    """
    if df is None or len(df) == 0:
        return
    for col, expected in expected_units.items():
        if col not in df.columns:
            continue
        assert_unit(table, col, expected)


def units_for_table(table: str) -> dict:
    """All registered unit declarations for a table. Returns {col: unit}."""
    try:
        from lineage import UNIT_CONTRACTS
    except ImportError:
        return {}
    return {col: unit for (t, col), unit in UNIT_CONTRACTS.items() if t == table}


def _record_unit_verdict(sid: str, source_table: str, source_key: str,
                          datum_class: str, status: int, reason: str,
                          snapshot_date: Optional[str] = None):
    """Persist a gate_5 verdict to trust_verdicts (best-effort; never raises)."""
    import json
    from datetime import datetime
    from db import get_db

    snapshot_date = snapshot_date or datetime.now().date().isoformat()
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trust_verdicts
                  (sid, source_table, source_key, datum_class, snapshot_date,
                   gate_5_unit, reasons_json, verdict_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, source_table, source_key, datum_class, snapshot_date,
                 status,
                 json.dumps({"gate_5_unit": {"reason": reason}}),
                 "TRUSTED" if status == 1 else "QUARANTINED"),
            )
    except Exception as e:
        import sys
        print(f"  ⚠ _record_unit_verdict failed: {e}", file=sys.stderr)
