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
    A datum class that is a stored column (bank ratios, Piotroski) reads its hard
    range and review band from the one column registry, checks/ranges.py, via
    DATUM_COLUMNS. PLAUSIBILITY_RANGES keeps only segment priors for write-time
    quantities: keyed by (datum_class, segment) where segment is cap_tier
    ("LARGE"/"MID"/"SMALL") or fund category ("equity_fund"/"debt_fund") or "*".

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


# Datum classes that ARE a stored column take their hard range and review band
# from the ONE column registry (checks/ranges.py: `range` → hard, `typical` →
# extreme) — the same range health, the sanity audit and the integrity checks use.
DATUM_COLUMNS = {
    "bank_gnpa_pct": ("banking_metrics", "gross_npa_pct"),
    "bank_nnpa_pct": ("banking_metrics", "net_npa_pct"),
    "bank_nim_pct":  ("banking_metrics", "nim_pct"),
    "bank_cof_pct":  ("banking_metrics", "cost_of_funds_pct"),
    "bank_roa_pct":  ("banking_metrics", "roa_pct"),
    "bank_car_pct":  ("banking_metrics", "car_pct"),
    "bank_casa_pct": ("banking_metrics", "casa_pct"),
    "piotroski_f":   ("piotroski_scores", "f_score"),
}

# Segment priors for write-time quantities that are not one stored column (or
# whose prior differs by segment): (datum_class, segment) →
# ((hard_lo, hard_hi), (extreme_lo, extreme_hi)). Hard: outside → auto-quarantine
# (almost-certainly broken data). Extreme: outside extreme but inside hard →
# TRUSTED_PENDING_REVIEW.
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

    # ─── Earnings growth ───
    # Turnaround years are real but >500% is usually base-effect from a tiny
    # prior; extreme >200% flags the case for review.
    ("eps_growth_pct", "*"): ((-200, +500), (-100, +200)),
}


def _ranges_for(datum_class, segment, fallback_segment):
    ranges = PLAUSIBILITY_RANGES.get((datum_class, segment))
    if ranges is None and segment != fallback_segment:
        ranges = PLAUSIBILITY_RANGES.get((datum_class, fallback_segment))
    if ranges is None and datum_class in DATUM_COLUMNS:
        from checks.ranges import bounds, typical
        table, column = DATUM_COLUMNS[datum_class]
        ranges = (bounds(table, column), typical(table, column))
    return ranges


def verify_plausibility(
    datum_class: str,
    value,
    segment: str = "*",
    fallback_segment: str = "*",
) -> PlausibilityVerdict:
    """Check `value` against the registered range for (datum_class, segment).

    Lookup order:
        (datum_class, segment) → (datum_class, fallback_segment)
        → DATUM_COLUMNS (checks/ranges.py) → UNDEFINED

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

    # Lookup: segment prior → fallback segment → the column registry
    ranges = _ranges_for(datum_class, segment, fallback_segment)
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
    from validators._verdicts import write_verdict
    if verdict.status == "OUT_OF_RANGE_HARD":
        # Row goes to <source_table>_quarantine + gate_2_plausibility=0.
        write_verdict("gate_2_plausibility", sid, source_table, datum_class, 0,
                      _plausibility_reasons(verdict), row=row,
                      snapshot_date=snapshot_date, quarantine=True)
        return "QUARANTINED"
    if verdict.status == "EXTREME":
        # Allow live write but mark the verdict — UHS Plausibility dim shows
        # a degraded score and Live Issues Inbox surfaces the row.
        write_verdict("gate_2_plausibility", sid, source_table, datum_class, 2,
                      _plausibility_reasons(verdict), row=row, snapshot_date=snapshot_date)
        return "WRITE_LIVE_WITH_WARN"
    if verdict.status == "PASS":
        write_verdict("gate_2_plausibility", sid, source_table, datum_class, 1,
                      _plausibility_reasons(verdict), row=row, snapshot_date=snapshot_date)
        return "WRITE_LIVE"
    # UNDEFINED / NULL_VALUE: pass through silently — caller's NULL handling applies.
    return "PASS_THROUGH"


def record_pt_plausibility_fail(sid, snapshot_date, reason, source_table="consensus_signals"):
    """Record a per-sid gate_2_plausibility=0 verdict for an implausible PT.

    Lightweight verdict-only write (no quarantine-table row) used by the stored-
    PT sweep — so the stock's per-sid UHS Plausibility dim drops to reflect the
    rejected target. Idempotent per (sid, source_table, datum_class, snapshot)."""
    import json
    from validators._verdicts import write_verdict
    write_verdict("gate_2_plausibility", sid, source_table, "pt_upside_pct", 0,
                  {"reason": reason}, source_key=json.dumps({"sid": sid}),
                  snapshot_date=snapshot_date)


def _plausibility_reasons(verdict: PlausibilityVerdict) -> dict:
    return {
        "status": verdict.status,
        "value": str(verdict.value),
        "hard": list(verdict.hard_range) if verdict.hard_range else None,
        "extreme": list(verdict.extreme_range) if verdict.extreme_range else None,
        "segment": verdict.segment,
        "reason": verdict.reason,
    }
