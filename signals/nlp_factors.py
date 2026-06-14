"""
Alpha Signal v2 — Earnings-call NLP factors (Plan 0002 §3.2.4).

Turns the per-document `nlp_scores` enriched layer into three per-stock factors,
each as-of-date resolved on the **look-ahead-safe availability date** (the real BSE
filing dt_tm carried into nlp_scores.available_date — Next-3 #1c, NOT the
first-of-month doc_date proxy which leads the true filing by ~2 weeks):

    #34 earnings_call_tone_qoq     net_tone(latest) − net_tone(prior call)   (tone momentum)
    #36 forward_looking_intensity  forward-looking phrases / 1k words, latest call
    #37 uncertainty_word_density   LM-uncertainty hits / words × 100, latest call

Per stock we take the MOST RECENT transcript available as-of the eval date, within a
freshness window (a concall older than FRESH_DAYS is stale → no current read → NaN).
QoQ additionally needs the prior call's tone. Names with no recent transcript get NaN
(genuine "no data" — renormalised away by the screener, like iv_skew for non-F&O —
NOT 0, which would be a real reading).

Injectable `nlp` frame so the live path and the PIT path
(tools/reconstruct_pit.py:pit_nlp_factors) run identical logic.

Sign hypotheses (the backtest decides): tone_qoq POSITIVE (improving tone → better
fwd returns); uncertainty_word_density NEGATIVE (hedged/evasive calls → worse);
forward_looking_intensity ambiguous (growth signalling vs over-promising).

Reads:  nlp_scores (doc_type='transcript')
Returns: DataFrame[sid, earnings_call_tone_qoq, forward_looking_intensity, uncertainty_word_density]

Usage:
    python -m signals.nlp_factors          # compute live + print stats
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from db import read_sql

FRESH_DAYS = 400   # a concall older than this carries no current read (≈ 4 missed quarters)
OUT_COLS = ["sid", "earnings_call_tone_qoq",
            "forward_looking_intensity", "uncertainty_word_density"]


def compute_nlp_factors(
    nlp: pd.DataFrame | None = None,
    as_of_date: str | None = None,
    universe_sids: list | None = None,
) -> pd.DataFrame:
    """Per-sid latest-call NLP factors as-of `as_of_date`, look-ahead-safe.

    `nlp` is injectable for PIT — a frame with [sid, available_date (or doc_date),
    net_tone, uncertainty_density, forward_looking_intensity]; the live path loads
    it from nlp_scores. Filters available_date ≤ as_of and within FRESH_DAYS.
    """
    eval_iso = as_of_date or date.today().isoformat()
    lo = (date.fromisoformat(eval_iso) - timedelta(days=FRESH_DAYS)).isoformat()

    if nlp is None:
        nlp = read_sql(
            "SELECT sid, doc_date, available_date, net_tone, "
            "uncertainty_density, forward_looking_intensity "
            "FROM nlp_scores WHERE doc_type = 'transcript'")

    if nlp is None or len(nlp) == 0:
        out = pd.DataFrame(columns=OUT_COLS)
    else:
        a = nlp.copy()
        avail_src = a["available_date"] if "available_date" in a.columns else a["doc_date"]
        a["avail"] = avail_src.fillna(a["doc_date"]).astype(str).str.slice(0, 10)
        a = a[(a["avail"] > lo) & (a["avail"] <= eval_iso)]
        a = a.dropna(subset=["sid"]).sort_values(["sid", "avail"])
        if len(a) == 0:
            out = pd.DataFrame(columns=OUT_COLS)
        else:
            # position from the end within each sid: 0 = latest available call, 1 = prior
            a["from_end"] = a.groupby("sid").cumcount(ascending=False)
            latest = a[a["from_end"] == 0]
            prior = (a[a["from_end"] == 1][["sid", "net_tone"]]
                     .rename(columns={"net_tone": "tone_prior"}))
            out = latest[["sid", "net_tone", "forward_looking_intensity",
                          "uncertainty_density"]].merge(prior, on="sid", how="left")
            out["earnings_call_tone_qoq"] = out["net_tone"] - out["tone_prior"]
            out = out.rename(columns={"uncertainty_density": "uncertainty_word_density"})
            out = out[OUT_COLS]

    if universe_sids is not None:
        out = (pd.DataFrame({"sid": list(dict.fromkeys(universe_sids))})
               .merge(out, on="sid", how="left"))
    return out[OUT_COLS].reset_index(drop=True)


if __name__ == "__main__":
    res = compute_nlp_factors()
    print(f"nlp_factors — {len(res):,} stocks with a transcript in the trailing {FRESH_DAYS}d")
    for c in OUT_COLS[1:]:
        s = res[c].dropna()
        if len(s):
            print(f"  {c:28s} n={len(s):4d}  mean={s.mean():+.3f}  "
                  f"p10={s.quantile(.1):+.3f}  p90={s.quantile(.9):+.3f}")
    names = read_sql("SELECT sid, name FROM stocks")
    j = res.dropna(subset=["earnings_call_tone_qoq"]).merge(names, on="sid", how="left")
    if len(j):
        pd.set_option("display.width", 200)
        print("\n=== most-improved tone QoQ ===")
        print(j.nlargest(6, "earnings_call_tone_qoq")[
            ["name", "earnings_call_tone_qoq", "forward_looking_intensity", "uncertainty_word_density"]
        ].to_string(index=False))
        print("\n=== most-deteriorated tone QoQ ===")
        print(j.nsmallest(6, "earnings_call_tone_qoq")[
            ["name", "earnings_call_tone_qoq", "forward_looking_intensity", "uncertainty_word_density"]
        ].to_string(index=False))
