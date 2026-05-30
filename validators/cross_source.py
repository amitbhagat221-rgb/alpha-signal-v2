"""
Cross-Source Reconciliation Gate — Trust Pipeline Gate 4, Plan 0007 Phase 4.

For datum classes with ≥2 sources, compute pairwise agreement and surface
DIVERGENT_SILENT cases — values that pass plausibility individually but
disagree across sources. Tickertape's `forecast_history.price` returning
today's close (labelled as historic analyst PT) is the canonical case:
the row passes range, freshness, schema, and null checks; only a comparison
against analyst_consensus or broker_recommendations PT for the same SID
reveals it's the wrong value.

POLICY
    PASS                — sources agree within tolerance
    DIVERGENT_TOLERATED — disagreement within elevated tolerance (NOT a fail
                          but a degraded consistency dim)
    DIVERGENT_SILENT    — disagreement beyond elevated tolerance with no
                          loud alert mechanism → quarantine the OFFENDING
                          row (caller decides which source to mistrust;
                          default is the row currently being written)
    UNDEFINED           — no cross-source rule registered
    INSUFFICIENT_DATA   — only 1 source available

DATUM CLASSES + SOURCES
    pt_target_price     → yfinance (analyst_consensus.price_target)
                         + tickertape forecast_history.price (per-FY)
                         + moneycontrol broker_recommendations.target_price
    stock_close         → NSE bhavcopy (stock_prices.close, the anchor)
                         + yfinance (stock_prices with source='yfinance')
    eps_growth_pct      → yfinance + tickertape

USAGE
    from validators.cross_source import verify_cross_source
    v = verify_cross_source(
        sid="RELI", datum_class="pt_target_price",
        new_value=1450.0, new_source="yfinance",
        snapshot_date="2026-05-30",
    )
    if v.status == "DIVERGENT_SILENT":
        # Quarantine the new row
"""

from collections import namedtuple
from datetime import datetime
from typing import Optional


CrossSourceVerdict = namedtuple(
    "CrossSourceVerdict",
    ["status", "value", "peer_values", "max_disagreement_pct", "tolerance_pct",
     "elevated_tolerance_pct", "reason"],
)


# Per-datum-class cross-source rules.
# tolerance_pct:           below → PASS
# elevated_tolerance_pct:  between tol and elev → DIVERGENT_TOLERATED
#                          above elev → DIVERGENT_SILENT
# peers: list of {table, value_col, sid_col, date_col, filter, lookback_days}
#         describing where to look up the peer value(s) for the same SID.
CROSS_SOURCE_RULES = {
    # The forecast_history.price contamination class. yfinance and broker_recs
    # are the trusted sources; Tickertape forecast_history.price has been
    # confirmed contaminated (ADR 0020). Until we delete that column, the
    # cross-source check should auto-flag a forecast_history value within
    # 5% of today's close as DIVERGENT_SILENT (classic "PT equals price"
    # bug pattern).
    "pt_target_price": {
        "tolerance_pct":           20,   # PTs across analysts can spread 10-20%
        "elevated_tolerance_pct":  40,   # outside extreme disagreement
        "peers": [
            {"table":     "analyst_consensus",
             "value_col": "price_target",
             "sid_col":   "sid",
             "date_col":  "fetched_at",
             "filter":    None,
             "lookback_days": 30},
            {"table":     "broker_recommendations",
             "value_col": "target_price",
             "sid_col":   "sid",
             "date_col":  "reco_date",
             "filter":    None,
             "lookback_days": 90},
        ],
    },
    # stock_close — NSE bhavcopy is the anchor (Phase 6 will formalize this);
    # yfinance must agree within 0.5%. If yfinance disagrees, it's likely
    # the wrong stock (rebrand, ticker recycling) or a stale snapshot.
    "stock_close": {
        "tolerance_pct":           0.5,
        "elevated_tolerance_pct":  2.0,
        "peers": [
            {"table":     "stock_prices",
             "value_col": "close",
             "sid_col":   "sid",
             "date_col":  "date",
             "filter":    "source = 'nse_bhavcopy' OR source IS NULL",
             "lookback_days": 3},
        ],
    },
    # eps_growth — tolerance is wider because point-in-time vs trailing
    # methodologies legitimately differ across yfinance / Tickertape.
    "eps_growth_pct": {
        "tolerance_pct":           15,
        "elevated_tolerance_pct":  35,
        "peers": [
            {"table":     "consensus_signals",
             "value_col": "eps_growth",
             "sid_col":   "sid",
             "date_col":  "snapshot_date",
             "filter":    None,
             "lookback_days": 14},
        ],
    },
}


def verify_cross_source(
    sid: str,
    datum_class: str,
    new_value,
    new_source: Optional[str] = None,
    snapshot_date: Optional[str] = None,
    peer_values: Optional[list] = None,
) -> CrossSourceVerdict:
    """Compare `new_value` (from `new_source`) to peer source values for the
    same (sid, datum_class). Returns CrossSourceVerdict.

    `peer_values` — caller pre-fetched list of comparable values. If None,
    helper queries CROSS_SOURCE_RULES[datum_class].peers automatically.

    Forecast_history pt_target_price special case: if `new_source` is
    'tickertape_forecast_history' AND `peer_values` contains the latest
    close price (within 5% of new_value), this is the PT_EQUALS_PRICE
    contamination pattern — auto-quarantine regardless of other peers.
    """
    cfg = CROSS_SOURCE_RULES.get(datum_class)
    if cfg is None:
        return CrossSourceVerdict("UNDEFINED", new_value, [], None, None, None,
                                    f"no rule registered for {datum_class}")
    if new_value is None:
        return CrossSourceVerdict("UNDEFINED", new_value, [], None, None, None,
                                    "new_value is None")
    try:
        v = float(new_value)
    except (TypeError, ValueError):
        return CrossSourceVerdict("UNDEFINED", new_value, [], None, None, None,
                                    f"new_value '{new_value}' not numeric")

    if peer_values is None:
        peer_values = _fetch_peer_values(sid, datum_class, cfg, snapshot_date)

    # Filter NULLs and self-source if we can identify it
    peers = [float(p) for p in peer_values if p is not None]
    if len(peers) == 0:
        return CrossSourceVerdict("INSUFFICIENT_DATA", v, [], None,
                                    cfg["tolerance_pct"], cfg["elevated_tolerance_pct"],
                                    "no peer values available")

    # PT_EQUALS_PRICE pattern detection — special case for forecast_history
    if datum_class == "pt_target_price" and new_source == "tickertape_forecast_history":
        close_proxy = _fetch_latest_close(sid)
        if close_proxy is not None and close_proxy > 0:
            close_diff_pct = abs(v - close_proxy) / close_proxy * 100
            if close_diff_pct < 5:
                return CrossSourceVerdict(
                    "DIVERGENT_SILENT", v, peers, close_diff_pct, 5,
                    cfg["elevated_tolerance_pct"],
                    f"forecast_history pt={v} matches close={close_proxy} within {close_diff_pct:.1f}% — "
                    "PT_EQUALS_PRICE contamination (ADR 0020)",
                )

    # Pairwise disagreement vs each peer
    disagreements = []
    for p in peers:
        if p == 0:
            continue
        disagreement_pct = abs(v - p) / abs(p) * 100
        disagreements.append(disagreement_pct)
    if not disagreements:
        return CrossSourceVerdict("INSUFFICIENT_DATA", v, peers, None,
                                    cfg["tolerance_pct"], cfg["elevated_tolerance_pct"],
                                    "all peers were zero")
    max_dis = max(disagreements)
    tol = cfg["tolerance_pct"]
    elev = cfg["elevated_tolerance_pct"]

    if max_dis <= tol:
        return CrossSourceVerdict("PASS", v, peers, max_dis, tol, elev,
                                    f"max disagreement {max_dis:.1f}% ≤ {tol}%")
    if max_dis <= elev:
        return CrossSourceVerdict("DIVERGENT_TOLERATED", v, peers, max_dis, tol, elev,
                                    f"max disagreement {max_dis:.1f}% between {tol}% and {elev}%")
    return CrossSourceVerdict("DIVERGENT_SILENT", v, peers, max_dis, tol, elev,
                                f"max disagreement {max_dis:.1f}% > {elev}%")


def _fetch_peer_values(sid, datum_class, cfg, snapshot_date):
    """Query each peer source for recent value(s) for this SID."""
    from db import read_sql
    as_of = snapshot_date or datetime.now().date().isoformat()
    out = []
    for peer in cfg["peers"]:
        try:
            where = f"{peer['sid_col']} = ? AND {peer['date_col']} >= date(?, '-{peer['lookback_days']} days')"
            if peer.get("filter"):
                where += f" AND ({peer['filter']})"
            df = read_sql(
                f"""
                SELECT {peer['value_col']} AS v
                FROM {peer['table']}
                WHERE {where}
                  AND {peer['value_col']} IS NOT NULL
                ORDER BY {peer['date_col']} DESC
                LIMIT 5
                """,
                params=[sid, as_of],
            )
            if not df.empty:
                out.extend([float(x) for x in df["v"] if x is not None])
        except Exception:
            continue
    return out


def _fetch_latest_close(sid):
    """Most-recent close from stock_prices for the SID (any source)."""
    from db import read_sql
    try:
        df = read_sql(
            "SELECT close FROM stock_prices WHERE sid=? ORDER BY date DESC LIMIT 1",
            params=[sid],
        )
        if df.empty:
            return None
        return float(df.iloc[0]["close"])
    except Exception:
        return None


def route_on_cross_source(
    verdict: CrossSourceVerdict,
    source_table: str,
    row: dict,
    sid: str,
    datum_class: str,
    snapshot_date: Optional[str] = None,
) -> str:
    """Returns 'WRITE_LIVE' | 'WRITE_LIVE_WITH_WARN' | 'QUARANTINED' | 'PASS_THROUGH'."""
    if verdict.status == "DIVERGENT_SILENT":
        _quarantine_for_cross_source(source_table, row, sid, datum_class, verdict, snapshot_date)
        return "QUARANTINED"
    if verdict.status in ("DIVERGENT_TOLERATED", "PASS"):
        gate_value = 2 if verdict.status == "DIVERGENT_TOLERATED" else 1
        overall = "PENDING_REVIEW" if verdict.status == "DIVERGENT_TOLERATED" else "TRUSTED"
        _record_cross_source_verdict(sid, source_table, row, datum_class, verdict,
                                       gate_value, overall, snapshot_date)
        return "WRITE_LIVE_WITH_WARN" if verdict.status == "DIVERGENT_TOLERATED" else "WRITE_LIVE"
    return "PASS_THROUGH"


def _quarantine_for_cross_source(source_table, row, sid, datum_class, verdict, snapshot_date):
    import json
    from db import get_db
    from validators.identity_check import _likely_pk_cols

    snapshot_date = snapshot_date or datetime.now().date().isoformat()
    mirror_table = f"{source_table}_quarantine"
    forensic = {
        "_q_failed_gate":     "gate_4_cross_source",
        "_q_reason":          verdict.reason,
        "_q_quarantined_at":  datetime.now().isoformat(timespec="seconds"),
    }
    payload = {**row, **forensic}
    cols = list(payload.keys())
    placeholders = ",".join("?" * len(cols))
    cols_sql = ",".join(f'"{c}"' for c in cols)
    insert_sql = f'INSERT INTO {mirror_table} ({cols_sql}) VALUES ({placeholders})'
    source_key = json.dumps(
        {k: row.get(k) for k in _likely_pk_cols(source_table) if k in row},
        default=str,
    )
    reasons_blob = {
        "gate_4_cross_source": {
            "status": verdict.status,
            "value": str(verdict.value),
            "peer_values": [str(p) for p in verdict.peer_values],
            "max_disagreement_pct": str(verdict.max_disagreement_pct),
            "tolerance_pct": verdict.tolerance_pct,
            "elevated_tolerance_pct": verdict.elevated_tolerance_pct,
            "reason": verdict.reason,
        }
    }
    try:
        with get_db() as conn:
            conn.execute(insert_sql, [payload[c] for c in cols])
            conn.execute(
                """
                INSERT OR REPLACE INTO trust_verdicts
                  (sid, source_table, source_key, datum_class, snapshot_date,
                   gate_4_cross_source, reasons_json, verdict_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, source_table, source_key, datum_class, snapshot_date,
                 0, json.dumps(reasons_blob), "QUARANTINED"),
            )
    except Exception as e:
        import sys
        print(f"  ⚠ _quarantine_for_cross_source failed for {source_table}/{sid}: {e}",
              file=sys.stderr)


def _record_cross_source_verdict(sid, source_table, row, datum_class, verdict,
                                   gate_value, overall, snapshot_date):
    import json
    from db import get_db
    from validators.identity_check import _likely_pk_cols

    snapshot_date = snapshot_date or datetime.now().date().isoformat()
    source_key = json.dumps(
        {k: row.get(k) for k in _likely_pk_cols(source_table) if k in row},
        default=str,
    )
    reasons_blob = {
        "gate_4_cross_source": {
            "status": verdict.status,
            "value": str(verdict.value),
            "peer_values": [str(p) for p in verdict.peer_values],
            "max_disagreement_pct": str(verdict.max_disagreement_pct),
            "tolerance_pct": verdict.tolerance_pct,
            "elevated_tolerance_pct": verdict.elevated_tolerance_pct,
            "reason": verdict.reason,
        }
    }
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trust_verdicts
                  (sid, source_table, source_key, datum_class, snapshot_date,
                   gate_4_cross_source, reasons_json, verdict_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, source_table, source_key, datum_class, snapshot_date,
                 gate_value, json.dumps(reasons_blob), overall),
            )
    except Exception as e:
        import sys
        print(f"  ⚠ _record_cross_source_verdict failed for {source_table}/{sid}: {e}",
              file=sys.stderr)
