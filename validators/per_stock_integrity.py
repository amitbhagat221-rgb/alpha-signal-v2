"""
Per-stock integrity validator — cross-source consistency assertions.

For every SID in daily_picks, run a battery of cross-source checks that catch
the HALC class of bug (narrative or one structured field contradicts another
structured field, no upstream check would notice).

Each check is a pure function: (row_dict) → ("PASS" | "WARN" | "FAIL", reason_or_None).

Plan 0005 Phase B. See docs/plans/0005-data-confidence-to-95.md.

Status semantics:
  • PASS — assertion holds OR data not present (no claim made = no contradiction)
  • WARN — assertion violated but not catastrophic (provenance unclear, etc.)
  • FAIL — hard contradiction. SID is bumped out of action_queue / morning_brief
           but retained in daily_picks for review with reasons.

Adding a new check: append to CHECKS at bottom of file. Each check must be
idempotent, tolerate missing fields (return PASS), and be fast (no I/O).
"""

import pandas as pd

from db import read_sql


# ─────────────────────── individual checks ───────────────────────


def pt_upside_consistency(row):
    """The HALC catcher.

    If we have both `price_target` and a `close` AND a published `pt_upside_pct`
    field, they must reconcile: pt_upside_pct ≈ (price_target - close) / close × 100,
    within 0.5pp. This is the exact bug from 2026-05-22 (HANDOFF): dossier said
    "16.5% downside at ₹1038" while 950/1038 = -8.5%.
    """
    pt = row.get("price_target")
    close = row.get("close")
    pt_upside = row.get("pt_upside_pct") or row.get("pt_upside")  # tolerate either name
    if pt is None or close is None or pt_upside is None:
        return "PASS", None
    try:
        pt = float(pt); close = float(close); pt_upside = float(pt_upside)
    except (TypeError, ValueError):
        return "PASS", None
    if close <= 0:
        return "PASS", None
    expected = ((pt - close) / close) * 100
    diff = abs(expected - pt_upside)
    if diff > 0.5:
        return "FAIL", f"pt_upside={pt_upside:.2f}% but PT={pt:.1f}/close={close:.1f} → {expected:.2f}% (Δ{diff:.2f}pp)"
    return "PASS", None


def consensus_requires_attribution(row):
    """consensus_signal non-NULL must be backed by total_analysts>0 OR price_target.
    Mirrors the gate in signals/consensus.py — defence in depth for any SID that
    somehow gets a consensus signal without attribution.
    """
    cs = row.get("consensus_signal")
    if cs is None or (isinstance(cs, float) and pd.isna(cs)):
        return "PASS", None
    n = row.get("total_analysts")
    has_n = n is not None and not (isinstance(n, float) and pd.isna(n)) and n > 0
    pt = row.get("price_target")
    has_pt = pt is not None and not (isinstance(pt, float) and pd.isna(pt))
    if has_n or has_pt:
        return "PASS", None
    return "FAIL", f"consensus_signal={cs:.3f} but no analyst attribution (n=NULL, PT=NULL)"


def f_score_range(row):
    """Piotroski F-score must be integer in [0, 9] when present."""
    f = row.get("f_score")
    if f is None or (isinstance(f, float) and pd.isna(f)):
        return "PASS", None
    try:
        f = float(f)
    except (TypeError, ValueError):
        return "PASS", None
    if not (0 <= f <= 9):
        return "FAIL", f"f_score={f} outside [0, 9]"
    return "PASS", None


def m_score_realistic(row):
    """Beneish M-score realistic range: typically -5 to +5. Outside that = junk input."""
    m = row.get("m_score")
    if m is None or (isinstance(m, float) and pd.isna(m)):
        return "PASS", None
    try:
        m = float(m)
    except (TypeError, ValueError):
        return "PASS", None
    if not (-10 <= m <= 10):
        return "FAIL", f"m_score={m:.2f} outside realistic [-10, +10]"
    return "PASS", None


def forward_pe_consistency(row):
    """forward_pe ≈ close / forward_eps when both present (within 5%)."""
    fpe = row.get("forward_pe")
    fe = row.get("forward_eps")
    close = row.get("close")
    for v in (fpe, fe, close):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "PASS", None
    try:
        fpe = float(fpe); fe = float(fe); close = float(close)
    except (TypeError, ValueError):
        return "PASS", None
    if fe == 0 or close <= 0:
        return "PASS", None
    expected = close / fe
    if expected == 0:
        return "PASS", None
    diff_pct = 100 * abs(fpe - expected) / abs(expected)
    if diff_pct > 5:
        return "WARN", f"forward_pe={fpe:.2f} vs close/forward_eps={expected:.2f} ({diff_pct:.1f}% off)"
    return "PASS", None


def eps_growth_requires_eps(row):
    """eps_growth_pct without forward_eps is unprovenanced growth."""
    g = row.get("eps_growth_pct")
    e = row.get("forward_eps")
    if g is None or (isinstance(g, float) and pd.isna(g)):
        return "PASS", None
    if e is not None and not (isinstance(e, float) and pd.isna(e)):
        return "PASS", None
    return "WARN", "eps_growth_pct present but forward_eps NULL — growth has no base"


def extreme_growth_clipped(row):
    """eps_growth_pct or revenue_growth_pct > 1000% is almost certainly a div-by-near-zero
    artifact (turnaround stocks). Should be clipped at the consumer or flagged.
    """
    for col in ("eps_growth_pct", "revenue_growth_pct"):
        v = row.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if abs(v) > 1000:
            return "WARN", f"{col}={v:.0f}% — likely div-by-near-zero artifact"
    return "PASS", None


def base_score_realistic(row):
    """base_score is a 0-1 weighted percentile rank. >1.0 or <0 = arithmetic broken."""
    bs = row.get("base_score")
    if bs is None or (isinstance(bs, float) and pd.isna(bs)):
        return "PASS", None
    try:
        bs = float(bs)
    except (TypeError, ValueError):
        return "PASS", None
    if bs < -0.001 or bs > 1.001:
        return "FAIL", f"base_score={bs:.3f} outside [0, 1]"
    return "PASS", None


CHECKS = [
    ("pt_upside_consistency",          pt_upside_consistency),
    ("consensus_requires_attribution", consensus_requires_attribution),
    ("f_score_range",                  f_score_range),
    ("m_score_realistic",              m_score_realistic),
    ("forward_pe_consistency",         forward_pe_consistency),
    ("eps_growth_requires_eps",        eps_growth_requires_eps),
    ("extreme_growth_clipped",         extreme_growth_clipped),
    ("base_score_realistic",           base_score_realistic),
]


# ─────────────────────── driver ───────────────────────


def validate_row(row):
    """Run all checks on a single dict-like row.
    Returns (status, reasons_pipe_separated). status in {"PASS","WARN","FAIL"}.
    """
    fails, warns = [], []
    for name, fn in CHECKS:
        try:
            s, reason = fn(row)
        except Exception as e:
            warns.append(f"{name}: check raised {type(e).__name__}")
            continue
        if s == "FAIL":
            fails.append(f"{name}: {reason}")
        elif s == "WARN":
            warns.append(f"{name}: {reason}")
    if fails:
        return "FAIL", " | ".join(fails + warns)
    if warns:
        return "WARN", " | ".join(warns)
    return "PASS", ""


def _augment_with_cross_source_fields(picks_df):
    """Merge in fields the screener doesn't natively carry on its picks DataFrame
    but that integrity checks need (PT, close, analyst attribution, fundamentals)."""
    sids = tuple(picks_df["sid"].tolist())
    if not sids:
        return picks_df
    placeholders = ",".join("?" * len(sids))

    # analyst_consensus
    ac = read_sql(
        f"SELECT sid, total_analysts, price_target, forward_eps "
        f"FROM analyst_consensus WHERE sid IN ({placeholders})",
        params=list(sids),
    )

    # consensus_signal (latest snapshot)
    cs = read_sql(
        f"SELECT sid, consensus_signal FROM consensus_signals "
        f"WHERE sid IN ({placeholders}) "
        f"AND snapshot_date = (SELECT MAX(snapshot_date) FROM consensus_signals)",
        params=list(sids),
    )

    # latest close
    px = read_sql(
        f"SELECT sid, close FROM stock_prices "
        f"WHERE sid IN ({placeholders}) "
        f"AND (sid, date) IN ("
        f"  SELECT sid, MAX(date) FROM stock_prices WHERE sid IN ({placeholders}) GROUP BY sid"
        f")",
        params=list(sids) + list(sids),
    )

    # piotroski f_score
    pio = read_sql(
        f"SELECT sid, f_score FROM piotroski_scores "
        f"WHERE sid IN ({placeholders}) "
        f"AND snapshot_date = (SELECT MAX(snapshot_date) FROM piotroski_scores)",
        params=list(sids),
    )

    # m_score from forensic
    fos = read_sql(
        f"SELECT sid, m_score FROM forensic_scores "
        f"WHERE sid IN ({placeholders}) "
        f"AND snapshot_date = (SELECT MAX(snapshot_date) FROM forensic_scores)",
        params=list(sids),
    )

    # Compute pt_upside_pct from PT and close
    merged = picks_df.copy()
    merged = merged.merge(ac, on="sid", how="left")
    merged = merged.merge(cs, on="sid", how="left", suffixes=("", "_cs"))
    merged = merged.merge(px, on="sid", how="left", suffixes=("", "_px"))
    merged = merged.merge(pio, on="sid", how="left")
    merged = merged.merge(fos, on="sid", how="left")

    # Derived: pt_upside_pct from PT/close. NB: the screener's consensus output
    # column is `consensus` (not consensus_signal), so the new merged
    # consensus_signal lives in its own column. Both are valid for the check.
    with pd.option_context("mode.chained_assignment", None):
        merged["pt_upside_pct"] = ((merged["price_target"] - merged["close"]) / merged["close"]) * 100

    return merged


def validate_picks(picks_df):
    """Validate every SID in picks_df. Returns DataFrame with columns:
        sid, integrity_status, integrity_reasons.
    `picks_df` should at minimum have a `sid` column and the screener-side
    fields (base_score, consensus if available). Other fields are merged from
    source tables here.
    """
    if picks_df is None or picks_df.empty:
        return pd.DataFrame(columns=["sid", "integrity_status", "integrity_reasons"])

    augmented = _augment_with_cross_source_fields(picks_df)

    statuses, reasons = [], []
    for _, row in augmented.iterrows():
        s, r = validate_row(row.to_dict())
        statuses.append(s)
        reasons.append(r)

    return pd.DataFrame({
        "sid": augmented["sid"],
        "integrity_status": statuses,
        "integrity_reasons": reasons,
    })


if __name__ == "__main__":
    # Smoke test: validate today's daily_picks
    picks = read_sql(
        "SELECT * FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)"
    )
    result = validate_picks(picks)
    by_status = result["integrity_status"].value_counts().to_dict()
    print(f"Validated {len(result)} picks: {by_status}")
    print()
    fails = result[result["integrity_status"] == "FAIL"]
    if not fails.empty:
        print(f"FAIL ({len(fails)}):")
        for _, r in fails.head(10).iterrows():
            print(f"  {r['sid']}: {r['integrity_reasons']}")
    warns = result[result["integrity_status"] == "WARN"]
    if not warns.empty:
        print(f"WARN ({len(warns)} — showing first 10):")
        for _, r in warns.head(10).iterrows():
            print(f"  {r['sid']}: {r['integrity_reasons']}")
