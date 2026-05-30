"""
Plausibility Gate — Trust Pipeline Gate 2, Plan 0007 Phase 3.

A datum-of-record may parse, may be fresh, may pass identity verification — and
still be impossible. CCAVENUE's pt_upside of +33,522% is the canonical case. The
plausibility gate encodes domain priors per (datum_class, segment) and routes
out-of-range values to quarantine with a CLIP_AND_WARN policy on extreme rows.

POLICY
    HARD range [lo, hi] — values outside this range are almost-certainly
                          parse-errors or source bugs. Auto-quarantine.
    EXTREME range [elo, ehi] (subset of HARD) — values outside extreme but
                          inside hard are unusual but possibly real (e.g. a
                          legitimate small-cap PT upside of 150% during a
                          merger). Status = TRUSTED_PENDING_REVIEW; row lives
                          but appears in Live Issues Inbox.
    PASS — value in extreme range. Normal write path.

RANGES
    Hand-curated from domain priors + historic bug analysis. Keyed by
    (datum_class, segment) where segment is cap_tier ("LARGE"/"MID"/"SMALL")
    or industry tag ("Banks"/"NBFCs / Finance") or fund category
    ("equity_fund"/"debt_fund") or "*" for universal.

USAGE
    from validators.plausibility import verify_plausibility, route_on_plausibility
    v = verify_plausibility("pt_upside_pct", value=33522.0, segment="SMALL")
    # v.status ∈ {"PASS", "EXTREME", "OUT_OF_RANGE_HARD", "UNDEFINED"}
    if v.status == "OUT_OF_RANGE_HARD":
        quarantine_row(...)
"""

from collections import namedtuple
from typing import Optional


PlausibilityVerdict = namedtuple(
    "PlausibilityVerdict",
    ["status", "value", "hard_range", "extreme_range", "segment", "reason"],
)


# (datum_class, segment) → ((hard_lo, hard_hi), (extreme_lo, extreme_hi))
# Hard range: outside → auto-quarantine (almost-certainly broken data)
# Extreme range: outside extreme but inside hard → TRUSTED_PENDING_REVIEW
PLAUSIBILITY_RANGES = {
    # ─── Analyst-derived prices ───
    # Verified from 2026-05-28 CCAVENUE incident: yfinance returned +33,522%
    # upside for a thin-coverage SMALL cap. Hard cap [-90, +200] is generous
    # for genuine small-cap distress / merger spikes; extreme [-60, +150]
    # flags anything beyond clearly-real range.
    ("pt_upside_pct", "LARGE"): ((-50, +100), (-30, +60)),
    ("pt_upside_pct", "MID"):   ((-60, +120), (-40, +80)),
    ("pt_upside_pct", "SMALL"): ((-90, +200), (-60, +150)),
    ("pt_upside_pct", "*"):     ((-90, +500), (-60, +200)),  # fallback

    # ─── Mutual fund NAV day-over-day change ───
    # 2026-05-23 Franklin India Short Term Income wound-up: NAV jumped
    # 1,628 → 4,383 in one day (+169%). Hard cap ±15% catches that and
    # genuine 1-day market crashes (CCO India 2020 = ~10%). Equity-fund
    # categories slightly looser than debt.
    ("nav_dod_change_pct", "equity_fund"): ((-15, +15), (-8, +8)),
    ("nav_dod_change_pct", "debt_fund"):   ((-3,  +3),  (-1, +1)),
    ("nav_dod_change_pct", "gold_fund"):   ((-10, +10), (-5, +5)),
    ("nav_dod_change_pct", "*"):           ((-20, +20), (-10, +10)),

    # ─── Banking metrics ───
    # GNPA > 20% is almost always a parse error (consolidated/standalone
    # mix-up). UCO Bank's all-time worst was ~24% (2018 Q1) so we don't
    # auto-quarantine at 20 but anything beyond 35 is virtually impossible.
    ("bank_gnpa_pct",  "*"): ((0, 35), (0, 20)),
    ("bank_nnpa_pct",  "*"): ((0, 15), (0, 8)),
    ("bank_nim_pct",   "*"): ((-2, 20), (0, 10)),
    ("bank_cof_pct",   "*"): ((0, 25), (3, 15)),
    ("bank_roa_pct",   "*"): ((-10, 8), (-3, 3)),
    # Capital adequacy ratio — by RBI mandate must be ≥9%; if we see <5%
    # something is broken (bank would have been liquidated).
    ("bank_car_pct",   "*"): ((5, 35), (8, 25)),
    ("bank_casa_pct",  "*"): ((0, 100), (10, 80)),

    # ─── Shareholding fields ───
    ("promoter_pct",   "*"): ((0, 100),  (0, 100)),
    ("pledge_pct",     "*"): ((0, 100),  (0, 100)),
    ("fii_pct",        "*"): ((0, 100),  (0, 100)),
    ("dii_pct",        "*"): ((0, 100),  (0, 100)),

    # ─── Earnings + value ratios ───
    # EPS growth: turnaround years are real but >500% is usually base-effect
    # from a tiny prior; extreme >200% flags the case for review.
    ("eps_growth_pct",   "*"): ((-200, +500), (-100, +200)),
    ("revenue_growth_pct","*"): ((-90,  +500), (-50,  +200)),
    ("earnings_yield_pct","*"): ((-50,  +50),  (-20,  +25)),
    ("book_to_price",     "*"): ((0,    20),   (0,    5)),
    ("price_to_earnings", "*"): ((-100, 500),  (1,    150)),

    # ─── Forensic / quality ───
    # Piotroski 0-9 is the schema range; hard outside is parse error.
    ("piotroski_f",   "*"): ((0, 9), (0, 9)),
    ("altman_z",      "*"): ((-5, 15), (0.5, 8)),
    ("beneish_m",     "*"): ((-5, 2), (-3.5, -0.5)),

    # ─── Momentum + delivery ───
    ("mom_6m_adj",    "*"): ((-5, 5), (-3, 3)),     # vol-scaled
    ("mom_12m_adj",   "*"): ((-5, 5), (-3, 3)),
    ("delivery_pct",  "*"): ((0, 100), (10, 90)),
    ("delivery_anomaly_z", "*"): ((-5, 5), (-3, 3)),

    # ─── Price + volume ───
    # No useful universal hard range on stock close — caught at the
    # source-of-truth level (NSE bhavcopy is Gate 7 anchor in Phase 6).
    # Day-over-day change is more meaningful as a temporal-continuity
    # check (Gate 3); plausibility just catches the impossible.
    ("close_price",    "*"): ((0.01, 1_000_000), (0.5, 200_000)),
    ("volume_shares",  "*"): ((0, 1e12), (0, 1e10)),

    # ─── Composite scores ───
    # final_score is the screener's 0-1 normalised; outside [0,1] is bug.
    ("final_score",    "*"): ((0, 1.01), (0, 1)),
}


def verify_plausibility(
    datum_class: str,
    value,
    segment: str = "*",
    fallback_segment: str = "*",
) -> PlausibilityVerdict:
    """Check `value` against the registered range for (datum_class, segment).

    Lookup order:
        (datum_class, segment) → (datum_class, fallback_segment) → UNDEFINED

    Returns PlausibilityVerdict with status:
        PASS                 — value within extreme range
        EXTREME              — value within hard but outside extreme
        OUT_OF_RANGE_HARD    — value outside hard → quarantine
        UNDEFINED            — no range registered for this class → pass-through
        NULL_VALUE           — value is None / NaN → caller handles separately
    """
    # NULL handling — separate signal from a hard-fail.
    if value is None:
        return PlausibilityVerdict("NULL_VALUE", value, None, None, segment,
                                    "value is None")
    try:
        import math
        v = float(value)
        if math.isnan(v):
            return PlausibilityVerdict("NULL_VALUE", value, None, None, segment,
                                        "value is NaN")
    except (TypeError, ValueError):
        return PlausibilityVerdict("UNDEFINED", value, None, None, segment,
                                    f"value '{value}' is not numeric")

    # Lookup
    key = (datum_class, segment)
    ranges = PLAUSIBILITY_RANGES.get(key)
    if ranges is None and segment != fallback_segment:
        ranges = PLAUSIBILITY_RANGES.get((datum_class, fallback_segment))
    if ranges is None:
        return PlausibilityVerdict("UNDEFINED", v, None, None, segment,
                                    f"no range registered for ({datum_class}, {segment})")

    hard, extreme = ranges
    if v < hard[0] or v > hard[1]:
        return PlausibilityVerdict("OUT_OF_RANGE_HARD", v, hard, extreme, segment,
                                    f"value {v} outside hard range {hard}")
    if v < extreme[0] or v > extreme[1]:
        return PlausibilityVerdict("EXTREME", v, hard, extreme, segment,
                                    f"value {v} outside extreme range {extreme}")
    return PlausibilityVerdict("PASS", v, hard, extreme, segment,
                                f"value {v} within extreme range {extreme}")


def route_on_plausibility(
    verdict: PlausibilityVerdict,
    source_table: str,
    row: dict,
    sid: str,
    datum_class: str,
    snapshot_date: Optional[str] = None,
) -> str:
    """Dispatch a row based on its plausibility verdict.

    Returns: "WRITE_LIVE" | "WRITE_LIVE_WITH_WARN" | "QUARANTINED" | "PASS_THROUGH"

    Caller's pattern:
        v = verify_plausibility(...)
        decision = route_on_plausibility(v, ...)
        if decision == "QUARANTINED":
            return  # already in quarantine table
        # else write to live as normal
    """
    if verdict.status == "OUT_OF_RANGE_HARD":
        # Quarantine + record verdict
        from validators.identity_check import quarantine_row, record_verdict, IdentityVerdict
        # Reuse the same quarantine_row helper — it doesn't care which gate
        # failed, just that a row should not reach the live table. We mark
        # gate_2_plausibility=0 via a fresh trust_verdicts write below.
        _quarantine_for_plausibility(source_table, row, sid, datum_class, verdict, snapshot_date)
        return "QUARANTINED"
    if verdict.status == "EXTREME":
        # Allow live write but mark the verdict — UHS Plausibility dim shows
        # a degraded score and Live Issues Inbox surfaces the row.
        _record_plausibility_verdict(sid, source_table, row, datum_class, verdict,
                                      gate_value=2, overall="PENDING_REVIEW", snapshot_date=snapshot_date)
        return "WRITE_LIVE_WITH_WARN"
    if verdict.status == "PASS":
        _record_plausibility_verdict(sid, source_table, row, datum_class, verdict,
                                      gate_value=1, overall="TRUSTED", snapshot_date=snapshot_date)
        return "WRITE_LIVE"
    # UNDEFINED / NULL_VALUE: pass through silently — caller's NULL handling applies.
    return "PASS_THROUGH"


def _quarantine_for_plausibility(source_table, row, sid, datum_class, verdict, snapshot_date):
    """Atomic write: append row to <source_table>_quarantine + insert
    trust_verdicts with gate_2_plausibility=0 + verdict_overall=QUARANTINED."""
    from datetime import datetime
    import json
    from db import get_db

    from validators.identity_check import _likely_pk_cols

    snapshot_date = snapshot_date or datetime.now().date().isoformat()
    mirror_table = f"{source_table}_quarantine"
    forensic = {
        "_q_failed_gate":     "gate_2_plausibility",
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
        "gate_2_plausibility": {
            "status": verdict.status,
            "value": str(verdict.value),
            "hard": list(verdict.hard_range) if verdict.hard_range else None,
            "extreme": list(verdict.extreme_range) if verdict.extreme_range else None,
            "segment": verdict.segment,
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
                   gate_2_plausibility, reasons_json, verdict_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, source_table, source_key, datum_class, snapshot_date,
                 0, json.dumps(reasons_blob), "QUARANTINED"),
            )
    except Exception as e:
        import sys
        print(f"  ⚠ _quarantine_for_plausibility failed for {source_table}/{sid}: {e}",
              file=sys.stderr)


def _record_plausibility_verdict(sid, source_table, row, datum_class, verdict,
                                  gate_value, overall, snapshot_date):
    """For PASS / EXTREME rows: persist the verdict so UHS roll-up can read it."""
    from datetime import datetime
    import json
    from db import get_db
    from validators.identity_check import _likely_pk_cols

    snapshot_date = snapshot_date or datetime.now().date().isoformat()
    source_key = json.dumps(
        {k: row.get(k) for k in _likely_pk_cols(source_table) if k in row},
        default=str,
    )
    reasons_blob = {
        "gate_2_plausibility": {
            "status": verdict.status,
            "value": str(verdict.value),
            "hard": list(verdict.hard_range) if verdict.hard_range else None,
            "extreme": list(verdict.extreme_range) if verdict.extreme_range else None,
            "segment": verdict.segment,
            "reason": verdict.reason,
        }
    }
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trust_verdicts
                  (sid, source_table, source_key, datum_class, snapshot_date,
                   gate_2_plausibility, reasons_json, verdict_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, source_table, source_key, datum_class, snapshot_date,
                 gate_value, json.dumps(reasons_blob), overall),
            )
    except Exception as e:
        import sys
        print(f"  ⚠ _record_plausibility_verdict failed for {source_table}/{sid}: {e}",
              file=sys.stderr)
