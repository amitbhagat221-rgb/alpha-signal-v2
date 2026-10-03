"""
Model checks (ADR 0060): is today's ranking built on healthy factor inputs, and did
it move like a ranking should?

Both read what the screener ACTUALLY used — `pit_replay_snapshots.inputs_json`, the
per-stock factor values frozen every day right after the ranking — and derive their
scope from the factor registry (`factors.SIGNAL_WEIGHTS`), so a factor wired
tomorrow is covered tomorrow. They judge today against the factor's own recent
history, never against a hand-set number per factor.

    factor_inputs()       each wired (tier, factor): coverage collapsed, or every
                          stock carrying one value
    ranking_stability()   each pickable tier: rank correlation of today's scores
                          with the previous day's
"""

import json

import pandas as pd

BASELINE_DAYS = 20          # trailing frozen days a factor is compared with
MIN_BASELINE_DAYS = 5       # fewer than this = too young to judge (reported, not passed)
COVERAGE_DROP = 0.6         # today's coverage below 60% of its usual = collapsed (the feed-volume band)
HEAVY_WEIGHT = 0.15         # a broken input carrying this much of a tier's weight = act today
MIN_RANK_CORRELATION = 0.6  # 150 days of history: median 0.95-0.99, 0.37-0.66 on the day the model changed
MIN_COMMON_STOCKS = 30


def _frozen_inputs(days, as_of):
    """Per-stock frozen screener inputs of the last `days` freeze dates up to
    `as_of`: DataFrame[snapshot_date, cap_tier, <screener columns…>]."""
    from db import read_sql
    df = read_sql(
        "SELECT snapshot_date, cap_tier, inputs_json FROM pit_replay_snapshots WHERE snapshot_date IN "
        "(SELECT DISTINCT snapshot_date FROM pit_replay_snapshots WHERE snapshot_date <= ? "
        " ORDER BY snapshot_date DESC LIMIT ?)",
        params=[as_of, days])
    if df.empty:
        return df
    values = pd.DataFrame([json.loads(j) for j in df.pop("inputs_json")], index=df.index)
    return df.join(values.drop(columns=[c for c in ("cap_tier", "snapshot_date") if c in values.columns]))


def factor_inputs(as_of=None):
    """One verdict over every wired (tier, factor). A pair is unhealthy when its
    coverage of the tier fell below COVERAGE_DROP of its trailing median, or when
    every stock has the same value and that is not its normal state.
    `as_of`: judge an earlier pick date (what would this check have said then)."""
    import factors
    from checks import CRITICAL, WARN
    from db import read_sql

    pick_date = read_sql("SELECT MAX(pick_date) AS d FROM daily_picks WHERE pick_date <= ?",
                         params=[as_of or "9999"]).iloc[0]["d"]
    df = _frozen_inputs(BASELINE_DAYS + 1, as_of or "9999")
    if df.empty or pick_date is None:
        return {"n_bad": 0, "n_total": 0}
    today = df["snapshot_date"].max()
    if today != pick_date:
        return {"n_bad": 1, "n_total": 1, "severity": WARN,
                "sample": f"the picks are for {pick_date} but the newest frozen inputs are {today} (pit_replay_freeze did not run)"}

    bad, heavy, judged, young = [], False, 0, []
    for tier, weights in factors.SIGNAL_WEIGHTS.items():
        t = df[df["cap_tier"] == tier]
        if not (t["snapshot_date"] == today).any():
            bad.append(f"{tier}: no stock of this tier in today's frozen inputs")
            heavy, judged = True, judged + 1
            continue
        for key, weight in weights.items():
            col = factors.SCREENER_TIER_COLS.get((key, tier)) or factors.SCREENER_COLS[key]
            by_day = t.groupby("snapshot_date")[col] if col in t.columns else None
            if by_day is None:
                bad.append(f"{tier} {key}: column '{col}' is missing from the frozen inputs")
                heavy, judged = heavy or abs(weight) >= HEAVY_WEIGHT, judged + 1
                continue
            coverage = by_day.apply(lambda s: s.notna().mean())
            distinct = by_day.nunique()
            if coverage[today] == 0:                    # dead today: no history needed to say so
                bad.append(f"{tier} {key} (weight {weight:+.2f}) has no value for any stock")
                heavy, judged = heavy or abs(weight) >= HEAVY_WEIGHT, judged + 1
                continue
            # compare with the days the factor was alive (a day before it existed is not a baseline)
            alive = coverage.drop(today)[lambda c: c > 0].index
            if len(alive) < MIN_BASELINE_DAYS:
                young.append(f"{tier} {key}")
                continue
            judged += 1
            base_cov, base_distinct = coverage[alive].median(), distinct[alive].median()
            problem = None
            if coverage[today] < COVERAGE_DROP * base_cov:
                problem = f"covers {coverage[today]:.0%} of the tier (usually {base_cov:.0%})"
            elif distinct[today] <= 1 < base_distinct:
                problem = "has the same value for every stock"
            if problem:
                bad.append(f"{tier} {key} (weight {weight:+.2f}) {problem}")
                heavy = heavy or abs(weight) >= HEAVY_WEIGHT
    sample = "; ".join(bad[:4]) or None
    if young and not bad:
        sample = f"too little history to judge: {', '.join(young[:4])}"
    return {"n_bad": len(bad), "n_total": judged, "sample": sample,
            "severity": CRITICAL if heavy else WARN}


def ranking_stability(as_of=None):
    """Rank correlation of today's final scores with the previous pick date's, per
    pickable tier. A ranking moves a little every day; a sharp break with no model
    change behind it means an input changed under it."""
    from config import PICKABLE_TIERS
    from db import read_sql

    df = read_sql(
        "SELECT pick_date, cap_tier, sid, final_score FROM daily_picks WHERE pick_date IN "
        "(SELECT DISTINCT pick_date FROM daily_picks WHERE pick_date <= ? ORDER BY pick_date DESC LIMIT 2)",
        params=[as_of or "9999"])
    days = sorted(df["pick_date"].unique())
    if len(days) < 2:
        return {"n_bad": 0, "n_total": 0}
    bad, judged = [], 0
    for tier in PICKABLE_TIERS:
        w = df[df["cap_tier"] == tier].pivot(index="sid", columns="pick_date", values="final_score").dropna()
        if len(w) < MIN_COMMON_STOCKS:
            continue
        judged += 1
        corr = w[days[0]].corr(w[days[1]], method="spearman")
        if not corr >= MIN_RANK_CORRELATION:            # NaN (a constant score) is a break too
            bad.append(f"{tier}: rank correlation {corr:.2f} between {days[0]} and {days[1]}")
    return {"n_bad": len(bad), "n_total": judged, "sample": "; ".join(bad) or None}
