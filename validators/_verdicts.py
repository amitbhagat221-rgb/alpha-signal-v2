"""
The one trust_verdicts writer — shared by every Trust Pipeline gate.

trust_verdicts holds ONE row per (sid, source_table, source_key, datum_class,
snapshot_date) with one INTEGER column per gate (0=FAIL, 1=PASS,
2=PENDING_REVIEW). Each gate used to write its own row with `INSERT OR
REPLACE` + only its own gate column, which DELETES the row and so wiped every
other gate's result on the same key (0 of 297,649 rows had >1 gate populated,
2026-09-26 audit). This writer upserts instead:

    - sets ONLY the calling gate's column (other gates survive)
    - merges reasons_json per gate key (json_patch)
    - recomputes verdict_overall across all gate columns, worst wins:
      any 0 → QUARANTINED, else any 2 → PENDING_REVIEW, else any 1 → TRUSTED

source_key is built from the source table's REAL primary key (db._table_pk),
not a hand-written map.

With quarantine=True the rejected row is also appended to
<source_table>_quarantine in the same transaction (forensic columns
_q_failed_gate / _q_reason / _q_quarantined_at).
"""

import json
import sys
from datetime import datetime


GATE_COLS = (
    "gate_1_identity",
    "gate_2_plausibility",
    "gate_3_temporal",
    "gate_4_cross_source",
    "gate_5_unit",
    "gate_6_lineage",
    "gate_7_anchor",
)

_OVERALL_FOR_VALUE = {0: "QUARANTINED", 1: "TRUSTED", 2: "PENDING_REVIEW"}

_UPSERT_SQL = {}


def _upsert_sql(gate: str) -> str:
    if gate not in GATE_COLS:
        raise ValueError(f"unknown trust gate '{gate}' — expected one of {GATE_COLS}")
    if gate not in _UPSERT_SQL:
        # In ON CONFLICT DO UPDATE every SET expression sees the OLD row, so the
        # overall roll-up reads this gate from `excluded` and the rest from the
        # existing row.
        vals = ", ".join(f"excluded.{g}" if g == gate else f"trust_verdicts.{g}"
                         for g in GATE_COLS)
        _UPSERT_SQL[gate] = f"""
            INSERT INTO trust_verdicts
              (sid, source_table, source_key, datum_class, snapshot_date,
               {gate}, reasons_json, verdict_overall, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(sid, source_table, source_key, datum_class, snapshot_date)
            DO UPDATE SET
              {gate} = excluded.{gate},
              reasons_json = json_patch(COALESCE(trust_verdicts.reasons_json, '{{}}'),
                                        excluded.reasons_json),
              verdict_overall = CASE
                  WHEN 0 IN ({vals}) THEN 'QUARANTINED'
                  WHEN 2 IN ({vals}) THEN 'PENDING_REVIEW'
                  WHEN 1 IN ({vals}) THEN 'TRUSTED'
                  ELSE excluded.verdict_overall END,
              computed_at = excluded.computed_at
        """
    return _UPSERT_SQL[gate]


def source_key_for(source_table: str, row: dict, conn) -> str:
    """JSON {pk_col: value} for `row`, keyed on the table's real PK (falls back
    to ['sid'] for tables without a declared PK)."""
    from db import _table_pk
    pk_cols = _table_pk(source_table, conn) or ["sid"]
    return json.dumps({k: row.get(k) for k in pk_cols if k in row}, default=str)


def _quarantine_insert(conn, source_table: str, row: dict, gate: str, reason) -> None:
    payload = {
        **row,
        "_q_failed_gate":    gate,
        "_q_reason":         reason,
        "_q_quarantined_at": datetime.now().isoformat(timespec="seconds"),
    }
    cols = list(payload.keys())
    cols_sql = ",".join(f'"{c}"' for c in cols)
    conn.execute(
        f'INSERT INTO {source_table}_quarantine ({cols_sql}) '
        f'VALUES ({",".join("?" * len(cols))})',
        [payload[c] for c in cols],
    )


def _params(conn, v: dict) -> tuple:
    """One upsert parameter tuple; also appends the quarantine row if asked."""
    gate, value = v["gate"], v["value"]
    row = v.get("row") or {}
    source_key = v.get("source_key")
    if source_key is None:
        source_key = source_key_for(v["source_table"], row, conn)
    snapshot_date = v.get("snapshot_date") or datetime.now().date().isoformat()
    reasons = v.get("reasons") or {}
    if v.get("quarantine"):
        _quarantine_insert(conn, v["source_table"], row, gate, reasons.get("reason"))
    return (v["sid"], v["source_table"], source_key, v["datum_class"], snapshot_date,
            value, json.dumps({gate: reasons}, default=str),
            _OVERALL_FOR_VALUE.get(value, "PENDING_REVIEW"))


def write_verdict(gate, sid, source_table, datum_class, value, reasons=None, *,
                  source_key=None, row=None, snapshot_date=None,
                  quarantine=False) -> bool:
    """Record one gate verdict (and optionally quarantine `row`) atomically.

    gate:       a GATE_COLS column name, e.g. "gate_2_plausibility"
    value:      0 FAIL / 1 PASS / 2 PENDING_REVIEW
    reasons:    dict stored under reasons_json[gate]
    source_key: JSON string; built from `row` + the table's real PK when None
    quarantine: also append `row` to <source_table>_quarantine

    Best-effort: never raises (a verdict write must not crash a producer);
    returns False on failure so the caller can drop the row instead.
    """
    return write_verdicts([{
        "gate": gate, "sid": sid, "source_table": source_table,
        "datum_class": datum_class, "value": value, "reasons": reasons,
        "source_key": source_key, "row": row, "snapshot_date": snapshot_date,
        "quarantine": quarantine,
    }]) > 0


def write_verdicts(verdicts) -> int:
    """Batch form of write_verdict: one connection, one transaction.

    `verdicts` is an iterable of dicts with write_verdict's argument names as
    keys. Returns the number written (0 on failure — the batch rolls back).
    """
    verdicts = list(verdicts)
    if not verdicts:
        return 0
    from db import get_db
    try:
        with get_db() as conn:
            by_gate = {}
            for v in verdicts:
                _upsert_sql(v["gate"])          # validate gate name up front
                by_gate.setdefault(v["gate"], []).append(_params(conn, v))
            for gate, params in by_gate.items():
                conn.executemany(_upsert_sql(gate), params)
        return len(verdicts)
    except Exception as e:
        first = verdicts[0]
        print(f"  ⚠ write_verdicts failed ({len(verdicts)} × {first.get('gate')} "
              f"on {first.get('source_table')}/{first.get('sid')}): {e}", file=sys.stderr)
        return 0
