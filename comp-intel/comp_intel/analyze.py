"""Benchmark engine — turn the stored jobs + comp records into percentile ranges,
sliced by role / location / firm, with an India↔UAE compare. Aggregate only."""

import pandas as pd

from comp_intel import store


def _read(table):
    with store.get_db() as conn:
        try:
            return pd.read_sql_query(f"SELECT * FROM {table}", conn)
        except Exception:
            return pd.DataFrame()


def _region(loc):
    s = (loc or "").lower()
    if any(k in s for k in ("uae", "dubai", "abu dhabi", "emirat")):
        return "UAE"
    if any(k in s for k in ("india", "bengaluru", "bangalore", "mumbai", "gurgaon",
                            "gurugram", "noida", "pune", "hyderabad", "chennai")):
        return "India"
    return "Other"


def _lakhs(x):
    return None if pd.isna(x) else round(x / 1e5, 1)


def _pcts(s):
    s = s.dropna()
    if s.empty:
        return None
    return {"n": int(s.size), "p25": _lakhs(s.quantile(.25)),
            "p50": _lakhs(s.quantile(.50)), "p75": _lakhs(s.quantile(.75))}


def benchmark(role=None):
    """Print a comp benchmark (₹ lakhs/year). Posted ranges (jobs) + total comp (records)."""
    out = []

    # --- posted ranges from live job postings ---
    jobs = _read("jobs")
    if not jobs.empty:
        jobs["mid_inr"] = jobs[["salary_inr_min", "salary_inr_max"]].mean(axis=1)
        if role:
            jobs = jobs[jobs["role_query"].str.contains(role, case=False, na=False)]
        jobs["region"] = jobs["location"].map(_region)
        out.append(("POSTED RANGES (job listings, ₹L/yr — noisy, employer-stated)", "mid_inr", jobs))

    # --- total comp from imported records ---
    recs = _read("comp_records")
    if not recs.empty:
        if role:
            recs = recs[recs["role"].fillna("").str.contains(role, case=False, na=False)]
        recs["region"] = recs["location"].map(_region)
        out.append(("TOTAL COMP (levels.fyi/AmbitionBox imports, ₹L/yr — base+bonus+stock)", "total_inr", recs))

    if not out:
        print("No data yet. Run `pull-jobs` and/or `import-comp` first.")
        return

    for header, col, df in out:
        print(f"\n=== {header} ===")
        if df.empty:
            print("  (no rows for this filter)")
            continue
        # overall + by region
        for label, sub in [("ALL", df)] + [(r, df[df.region == r]) for r in ("India", "UAE")]:
            p = _pcts(sub[col])
            if p:
                print(f"  {label:6s} n={p['n']:>4}  p25={p['p25']}  median={p['p50']}  p75={p['p75']}")
        # firm rollup (where tagged)
        firm = df[df["firm_tag"].notna()]
        if not firm.empty:
            print("  — by firm —")
            g = firm.groupby("firm_tag")[col].agg(["count", "median"]).sort_values("median", ascending=False)
            for fn, row in g.iterrows():
                print(f"     {fn:18s} n={int(row['count']):>3}  median={_lakhs(row['median'])}")

    # India↔UAE multiple (on whichever layer has both)
    for _, col, df in out:
        ind = df[df.region == "India"][col].median()
        uae = df[df.region == "UAE"][col].median()
        if pd.notna(ind) and pd.notna(uae) and ind:
            print(f"\n  India↔UAE: median {_lakhs(ind)}L vs {_lakhs(uae)}L  → {uae/ind:.1f}× "
                  f"(UAE also tax-free → larger net gap)")
            break
