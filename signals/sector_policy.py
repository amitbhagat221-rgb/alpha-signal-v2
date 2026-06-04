"""
Alpha Signal v2 — Sector Policy Signal (curated event store + monthly PIT score)

The policy / budget / scheme dimension can't be backtested from a live feed
(events are episodic and low-N), so we BUILD the history explicitly: a curated
`policy_events` store seeded with known major India policy events, plus a
monthly `sector_policy_pit` aggregation (age-decayed net tailwind per sector).
New events get appended to SEED over time (or harvested from regulatory_events),
and the monthly run re-derives the PIT score → history accumulates from day one.

  seed()     — (re)load the curated events into policy_events (idempotent upsert)
  compute()  — backfill sector_policy_pit: for each month-end, decayed sum of
               direction×magnitude over events in a trailing window.

Magnitudes are CURATED (0–3) and necessarily subjective — this is a scaffold to
size policy tailwinds, not a precise factor. Sector = GICS (matches stocks.sector).

Usage:
    python -m signals.sector_policy --seed
    python -m signals.sector_policy            # backfill sector_policy_pit
    python -m signals.sector_policy --dry-run
"""

import argparse

import numpy as np
import pandas as pd

from db import get_db, read_sql, upsert_df

HALF_LIFE_M = 12      # event impact halves every 12 months
WINDOW_M = 24         # events older than this drop out of the score

# Curated seed — major India policy / budget / scheme events, GICS-mapped.
# (date, sector, type, direction, magnitude, title)
SEED = [
    ("2020-05-13", "Industrials", "THEME", +1, 2.0, "Atmanirbhar Bharat — domestic-manufacturing push"),
    ("2020-11-11", "Information Technology", "PLI", +1, 2.0, "PLI for IT hardware / electronics (large-scale)"),
    ("2020-11-11", "Health Care", "PLI", +1, 2.0, "PLI for bulk drugs / APIs (China+1)"),
    ("2020-11-11", "Materials", "PLI", +1, 1.5, "PLI for specialty steel / chemicals"),
    ("2021-02-01", "Industrials", "BUDGET", +1, 3.0, "Budget FY22 — capex ₹5.5L cr, infra thrust"),
    ("2021-02-01", "Financials", "BUDGET", +1, 1.5, "Budget FY22 — bad-bank / ARC, bank recap"),
    ("2021-09-15", "Consumer Discretionary", "PLI", +1, 2.0, "Auto & auto-components PLI (₹26k cr)"),
    ("2021-09-15", "Communication Services", "REGULATION", +1, 1.5, "Telecom relief package — AGR moratorium"),
    ("2022-02-01", "Industrials", "BUDGET", +1, 3.0, "Budget FY23 — capex ₹7.5L cr (+35%)"),
    ("2022-02-01", "Real Estate", "BUDGET", +1, 1.0, "Budget FY23 — affordable housing allocation"),
    ("2022-05-21", "Materials", "TARIFF", -1, 2.0, "15% steel export duty (margin/volume hit)"),
    ("2022-07-01", "Energy", "TARIFF", -1, 1.5, "Windfall tax on fuel exports / crude"),
    ("2022-09-01", "Energy", "THEME", +1, 1.0, "Ethanol-blending acceleration (E20)"),
    ("2023-02-01", "Industrials", "BUDGET", +1, 3.0, "Budget FY24 — capex ₹10L cr (+33%), defense up"),
    ("2023-02-01", "Real Estate", "BUDGET", +1, 1.0, "Budget FY24 — PM Awas +66%"),
    ("2023-06-15", "Information Technology", "THEME", +1, 2.0, "Semiconductor mission — Micron Gujarat fab"),
    ("2023-09-01", "Industrials", "ORDER", +1, 2.5, "Defense indigenization — record order book, positive lists"),
    ("2023-11-01", "Industrials", "ORDER", +1, 2.0, "Railway capex surge — Vande Bharat / track orders"),
    ("2024-02-01", "Utilities", "BUDGET", +1, 2.0, "Interim Budget FY25 — rooftop solar (PM Surya Ghar)"),
    ("2024-02-01", "Energy", "THEME", +1, 1.5, "Green hydrogen / renewable thrust"),
    ("2024-02-01", "Industrials", "BUDGET", +1, 2.5, "Interim Budget FY25 — capex ₹11.1L cr"),
    ("2024-07-23", "Consumer Discretionary", "BUDGET", +1, 1.5, "Budget FY25 — customs cut on mobiles/gold, jobs scheme"),
    ("2024-07-23", "Materials", "TARIFF", +1, 1.0, "Budget FY25 — gold/precious-metal duty cut"),
    ("2025-02-01", "Consumer Discretionary", "BUDGET", +1, 2.5, "Budget FY26 — income-tax relief, consumption boost"),
    ("2025-02-01", "Consumer Staples", "BUDGET", +1, 1.5, "Budget FY26 — rural / consumption support"),
    ("2025-02-01", "Industrials", "BUDGET", +1, 2.0, "Budget FY26 — capex continuity, infra"),
    ("2025-04-01", "Information Technology", "TARIFF", -1, 1.5, "US tariff / global-trade uncertainty — IT spend caution"),
    ("2025-04-01", "Materials", "TARIFF", -1, 1.0, "US tariff uncertainty — export-metal risk"),
]


def seed(dry_run=False):
    df = pd.DataFrame(SEED, columns=["event_date", "sector", "event_type",
                                     "direction", "magnitude", "title"])
    df["source"] = "curated_seed_2026-06"
    print(f"Policy seed: {len(df)} events, {df['sector'].nunique()} sectors, "
          f"{df['event_date'].min()}..{df['event_date'].max()}")
    if dry_run:
        return len(df)
    n = upsert_df(df, "policy_events")
    print(f"Seeded {n} rows to policy_events")
    return n


def compute(dry_run=False):
    """Backfill sector_policy_pit: monthly age-decayed net tailwind per sector."""
    ev = read_sql("SELECT event_date, sector, direction, magnitude FROM policy_events")
    if ev.empty:
        # auto-seed on first run so the table is never empty/stale
        seed(dry_run=dry_run)
        ev = read_sql("SELECT event_date, sector, direction, magnitude FROM policy_events")
        if ev.empty:
            raise RuntimeError("policy_events empty after seed — check SEED")
    ev["event_date"] = pd.to_datetime(ev["event_date"])
    ev["impact"] = ev["direction"] * ev["magnitude"]
    sectors = sorted(ev["sector"].unique())

    start = (ev["event_date"].min()).to_period("M").to_timestamp("M")
    # cap at the last COMPLETED month-end (≤ today) — no future-dated PIT rows
    month_ends = pd.date_range(start, pd.Timestamp.now(), freq="ME")

    rows = []
    for me in month_ends:
        age_m = (me.year - ev["event_date"].dt.year) * 12 + (me.month - ev["event_date"].dt.month)
        in_win = (age_m >= 0) & (age_m <= WINDOW_M)
        sub = ev[in_win].copy()
        if sub.empty:
            continue
        sub["decay"] = 0.5 ** (age_m[in_win] / HALF_LIFE_M)
        sub["w"] = sub["impact"] * sub["decay"]
        agg = sub.groupby("sector").agg(policy_score=("w", "sum"), n_events=("w", "size"))
        for sector in sectors:
            ps = float(agg.loc[sector, "policy_score"]) if sector in agg.index else 0.0
            ne = int(agg.loc[sector, "n_events"]) if sector in agg.index else 0
            rows.append({"sector": sector, "snapshot_date": me.date().isoformat(),
                         "policy_score": round(ps, 3), "n_events": ne})

    df = pd.DataFrame(rows)
    print(f"Policy PIT: {len(df)} rows across {df['snapshot_date'].nunique()} month-ends "
          f"({df['snapshot_date'].min()}..{df['snapshot_date'].max()})")
    latest = df[df["snapshot_date"] == df["snapshot_date"].max()].sort_values("policy_score", ascending=False)
    print("  latest month, net policy tailwind by sector:")
    for _, r in latest.iterrows():
        if r["n_events"]:
            print(f"    {r['sector']:24s} {r['policy_score']:+.2f}  ({r['n_events']} active)")
    if dry_run:
        print("Dry run — not saving.")
        return len(df)
    n = upsert_df(df, "sector_policy_pit")
    print(f"Saved {n} rows to sector_policy_pit")
    return n


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", action="store_true", help="(re)load curated events into policy_events")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.seed:
        seed(dry_run=args.dry_run)
    else:
        compute(dry_run=args.dry_run)
