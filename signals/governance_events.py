"""
Alpha Signal v2 — Governance/forensic event factors off the BSE announcement stream.

`governance_resignation` — weighted trailing-365d density of senior-officer and
auditor resignation/cessation events. The BSE `subcategory` IS the signal here (no
PDF parse needed, unlike Credit Rating whose up/down-grade direction lives only in
the attachment): statutory-auditor and CFO resignations are documented distress/fraud
precursors; MD/CEO/Chairman exits flag leadership instability; director / company-
secretary churn is weaker governance noise. Each event is weighted by seniority/
forensic-relevance and summed over the trailing year.

Hypothesis (sign decided by the backtest): a cluster of senior resignations predicts
NEGATIVE forward returns. Dual-use — even if the cross-sectional IC is weak, the raw
intensity is a cockpit forensic red-flag (cf. the Rajesh Exports steady-state-fraud
miss, which our YoY/distress detectors — Beneish/Altman/Sloan — could not see).

Look-ahead-safe: anchored on `dt_tm` (the announcement timestamp), filtered ≤ as_of.
Injectable frame so the live path and the PIT path
(tools/reconstruct_pit.py:pit_governance_resignation) run identical logic. Stock-
agnostic; no sector exclusion (governance events apply to every sector incl. financials).

Coverage caveat: the BSE stream reaches ~90% of the universe; the ~10% NSE-only names
never appear here, so they score 0 (treated as "no flag" — a real exit we can't see is
mis-scored clean). Acceptable for a candidate; most large/liquid names are BSE-listed.

Reads:  bse_announcements (resignation/cessation subcategories)
Returns: DataFrame[sid, governance_resignation]

Usage:
    python -m signals.governance_events     # compute live + print stats
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from db import read_sql

# Subcategory → forensic-seniority weight. Auditor exit is the strongest red flag;
# CFO next; MD/CEO/Chairman = leadership instability; director/CS/cessation = churn.
# 'Appointment of Statutory Auditor/s' is deliberately EXCLUDED (neutral/positive).
RESIGNATION_WEIGHTS = {
    "Resignation of Statutory Auditors":                    3.0,
    "Change in Auditors":                                   3.0,
    "Resignation of Chief Financial Officer (CFO)":         2.5,
    "Resignation of Managing Director":                     2.0,
    "Resignation of Chief Executive Officer (CEO)":         2.0,
    "Resignation of Chairman":                              2.0,
    "Resignation of Chairman and Managing Director":        2.0,
    "Resignation of Director":                              1.0,
    "Resignation of Company Secretary / Compliance Officer": 1.0,
    "Cessation":                                            1.0,
}
WINDOW_DAYS = 365
INTENSITY_CLIP = (0.0, 12.0)   # cap pathological churn; most non-zero values are 1–4


def compute_governance_resignation(
    announcements: pd.DataFrame | None = None,
    universe_sids: list | None = None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """Weighted trailing-365d senior-resignation intensity per sid, as of as_of_date.

    `announcements` is injectable for PIT — a frame with [sid, subcategory, ev_date]
    (or raw `dt_tm`); the live path loads it from bse_announcements filtered ≤ as_of.
    If `universe_sids` is given, the result is reindexed to the full universe with 0
    for names that had no qualifying event (so the backtest gets the flagged-vs-
    unflagged contrast, not just the gradient among flagged names).
    """
    cols = ["sid", "governance_resignation"]
    eval_iso = as_of_date or date.today().isoformat()
    lo = (date.fromisoformat(eval_iso) - timedelta(days=WINDOW_DAYS)).isoformat()

    if announcements is None:
        subcats = ", ".join("'" + s.replace("'", "''") + "'" for s in RESIGNATION_WEIGHTS)
        dc = f"AND date(dt_tm) <= '{as_of_date}'" if as_of_date else ""
        announcements = read_sql(
            f"SELECT sid, subcategory, date(dt_tm) AS ev_date FROM bse_announcements "
            f"WHERE sid IS NOT NULL AND dt_tm IS NOT NULL "
            f"AND subcategory IN ({subcats}) {dc}")

    if announcements is None or len(announcements) == 0:
        out = pd.DataFrame(columns=cols)
    else:
        a = announcements[["sid", "subcategory"]].copy()
        dcol = "ev_date" if "ev_date" in announcements.columns else "dt_tm"
        a["ev_date"] = announcements[dcol].astype(str).str.slice(0, 10)
        a = a[(a["ev_date"] > lo) & (a["ev_date"] <= eval_iso)]
        a["w"] = a["subcategory"].map(RESIGNATION_WEIGHTS).fillna(0.0)
        out = (a.groupby("sid")["w"].sum()
               .rename("governance_resignation").reset_index())
        out["governance_resignation"] = out["governance_resignation"].clip(*INTENSITY_CLIP).round(3)

    if universe_sids is not None:
        out = (pd.DataFrame({"sid": list(dict.fromkeys(universe_sids))})
               .merge(out, on="sid", how="left"))
        out["governance_resignation"] = out["governance_resignation"].fillna(0.0)

    return out[cols].reset_index(drop=True)


if __name__ == "__main__":
    res = compute_governance_resignation()
    s = res["governance_resignation"]
    print(f"governance_resignation — {len(res):,} stocks with a qualifying resignation "
          f"event in the trailing {WINDOW_DAYS}d")
    if len(s):
        print(f"  intensity: mean={s.mean():.2f}  median={s.median():.2f}  "
              f"max={s.max():.2f}  >=3 (auditor/multi)={(s >= 3).sum()}")
        # quick look at the top red-flags
        from db import read_sql as _r
        names = _r("SELECT sid, name FROM stocks")
        top = res.sort_values("governance_resignation", ascending=False).head(10).merge(names, on="sid", how="left")
        print("  top-10 intensity:")
        for _, r in top.iterrows():
            print(f"    {r['sid']:6s} {str(r.get('name'))[:34]:34s} {r['governance_resignation']:.2f}")
