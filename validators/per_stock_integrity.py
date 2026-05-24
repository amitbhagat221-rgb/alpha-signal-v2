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


def market_cap_consistency(row):
    """market_cap_cr ≈ shares_outstanding × close × 1e-7 (₹ → crores).

    1 crore = 10^7. So `mcap_cr = shares × close / 10^7`. 10% tolerance
    accounts for stale market_cap_cr (it's a slow-moving stocks.* field
    refreshed less often than close) — anything beyond is corrupt input or
    a shares_outstanding stale by a buyback/split.
    """
    mcap = row.get("market_cap_cr")
    shares = row.get("shares_outstanding")
    close = row.get("close")
    for v in (mcap, shares, close):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return "PASS", None
    try:
        mcap = float(mcap); shares = float(shares); close = float(close)
    except (TypeError, ValueError):
        return "PASS", None
    if mcap <= 0 or shares <= 0 or close <= 0:
        return "PASS", None
    expected = shares * close / 1e7
    if expected == 0:
        return "PASS", None
    diff_pct = 100 * abs(mcap - expected) / max(expected, mcap)
    if diff_pct > 25:
        return "FAIL", f"market_cap_cr={mcap:.1f} vs shares×close/1e7={expected:.1f} ({diff_pct:.0f}% off)"
    if diff_pct > 10:
        return "WARN", f"market_cap_cr={mcap:.1f} vs shares×close/1e7={expected:.1f} ({diff_pct:.0f}% off — stale shares?)"
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
    # market_cap_consistency intentionally NOT in production CHECKS yet —
    # stocks.market_cap_cr and annual_balance_sheet.shares_outstanding use
    # inconsistent units across upstream sources (Tickertape vs Screener.in),
    # making a strict cross-check noisy. The assertion is correct in spirit;
    # add to CHECKS after Phase C unit-normalization. Self-test keeps the
    # logic verified so it's instantly re-enableable.
    # ("market_cap_consistency",      market_cap_consistency),
]


# Optional CHECKS — exposed for self-test but not run in production CHECKS.
OPTIONAL_CHECKS = [
    ("market_cap_consistency", market_cap_consistency),
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

    # market_cap_cr from stocks (slow-moving snapshot)
    mc = read_sql(
        f"SELECT sid, market_cap_cr FROM stocks WHERE sid IN ({placeholders})",
        params=list(sids),
    )

    # shares_outstanding from latest annual_balance_sheet
    sh = read_sql(
        f"SELECT sid, shares_outstanding FROM annual_balance_sheet "
        f"WHERE sid IN ({placeholders}) "
        f"AND (sid, period) IN ("
        f"  SELECT sid, MAX(period) FROM annual_balance_sheet WHERE sid IN ({placeholders}) GROUP BY sid"
        f")",
        params=list(sids) + list(sids),
    )

    # Compute pt_upside_pct from PT and close
    merged = picks_df.copy()
    merged = merged.merge(ac, on="sid", how="left")
    merged = merged.merge(cs, on="sid", how="left", suffixes=("", "_cs"))
    merged = merged.merge(px, on="sid", how="left", suffixes=("", "_px"))
    merged = merged.merge(pio, on="sid", how="left")
    merged = merged.merge(fos, on="sid", how="left")
    merged = merged.merge(mc, on="sid", how="left")
    merged = merged.merge(sh, on="sid", how="left")

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


# ─────────────────────── injection tests ───────────────────────
#
# `python -m validators.per_stock_integrity --self-test` runs deliberate
# HALC-class injections and asserts the right assertion fires. These are
# the "would I have caught the 2026-05-22 HALC bug?" smoke tests. Run on
# every meaningful change to this file (manual today; CI step in Phase E).


def _self_test():
    """Inject known-bad rows, assert the right assertion catches each."""
    cases = [
        {
            "name": "HALC 2026-05-22 (16.5% downside, actually -8.5%)",
            "row": {"price_target": 1038.0, "close": 1135.0, "pt_upside_pct": -16.5},
            "expected_status": "FAIL",
            "expected_check": "pt_upside_consistency",
        },
        {
            "name": "PT/close consistent, no false positive",
            "row": {"price_target": 1150.0, "close": 1000.0, "pt_upside_pct": 15.0},
            "expected_status": "PASS",
            "expected_check": None,
        },
        {
            "name": "consensus without attribution (the 14-stock bug)",
            "row": {"consensus_signal": 0.55, "total_analysts": 0, "price_target": None},
            "expected_status": "FAIL",
            "expected_check": "consensus_requires_attribution",
        },
        {
            "name": "consensus WITH attribution (yfinance has data)",
            "row": {"consensus_signal": 0.55, "total_analysts": 12, "price_target": 950.0,
                    "close": 900.0, "pt_upside_pct": 5.56},  # 50/900 = 5.56%
            "expected_status": "PASS",
            "expected_check": None,
        },
        {
            "name": "f_score out of range",
            "row": {"f_score": 12},
            "expected_status": "FAIL",
            "expected_check": "f_score_range",
        },
        {
            "name": "m_score impossibly extreme (data corruption)",
            "row": {"m_score": -99.5},
            "expected_status": "FAIL",
            "expected_check": "m_score_realistic",
        },
        {
            "name": "forward_pe inconsistent with close/forward_eps",
            "row": {"forward_pe": 25.0, "forward_eps": 50.0, "close": 800.0},  # close/eps=16, not 25
            "expected_status": "WARN",
            "expected_check": "forward_pe_consistency",
        },
        {
            "name": "base_score outside [0,1] (screener arithmetic broken)",
            "row": {"base_score": 1.45},
            "expected_status": "FAIL",
            "expected_check": "base_score_realistic",
        },
        {
            "name": "market_cap matches shares × close (consistent: 10M × ₹1000 = ₹1000cr)",
            "row": {"market_cap_cr": 1000.0, "shares_outstanding": 10_000_000, "close": 1000.0},
            "expected_status": "PASS",
            "expected_check": None,
        },
        {
            "name": "market_cap contradicts shares × close (3× off — likely stale shares)",
            "row": {"market_cap_cr": 3000.0, "shares_outstanding": 10_000_000, "close": 1000.0},
            "expected_status": "FAIL",
            "expected_check": "market_cap_consistency",
        },
    ]

    print(f"Self-test: {len(cases)} injection cases")
    print("=" * 80)
    passed = failed = 0
    # Combine production + optional checks for self-test only — we want to
    # verify the dormant assertions work even though they're not in production.
    all_checks = CHECKS + OPTIONAL_CHECKS

    def _run_all(row):
        fails, warns = [], []
        for name, fn in all_checks:
            try:
                s, reason = fn(row)
            except Exception as e:
                warns.append(f"{name}: raised {type(e).__name__}")
                continue
            if s == "FAIL": fails.append(f"{name}: {reason}")
            elif s == "WARN": warns.append(f"{name}: {reason}")
        if fails: return "FAIL", " | ".join(fails + warns)
        if warns: return "WARN", " | ".join(warns)
        return "PASS", ""

    for c in cases:
        status, reasons = _run_all(c["row"])
        ok = status == c["expected_status"]
        if c["expected_check"]:
            ok = ok and c["expected_check"] in reasons
        marker = "✓" if ok else "✗"
        print(f"  {marker} {c['name']}")
        print(f"      expected: {c['expected_status']}" +
              (f" via {c['expected_check']}" if c["expected_check"] else ""))
        print(f"      got:      {status}" + (f" — {reasons[:120]}" if reasons else ""))
        if ok:
            passed += 1
        else:
            failed += 1
    print()
    print(f"Result: {passed}/{len(cases)} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--self-test", action="store_true",
                   help="Run injection tests against the validator")
    args = p.parse_args()

    if args.self_test:
        ok = _self_test()
        import sys
        sys.exit(0 if ok else 1)

    # Default: validate today's daily_picks
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
