"""
Alpha Signal v2 — Macro Sector Signal (the live Sectors read)

One engine, two tables: the per-sector score is `pit.pit_macro_sector` — the same
function the PIT twin (`macro_sector_signals_pit`, tools/reconstruct_pit.py) and the
wired sector_tilt factor's macro leg use — run on `macro_history` as of today with
`macro_sector_map` (indicator → sector, direction, weight; 90-day moves of daily
market series). This step only puts that score in display form:

    display score = clip(50 + DISPLAY_SCALE × pit score, 0, 100)
    label         = TAILWIND ≥ 70 · FAVORABLE ≥ 55 · NEUTRAL ≥ 45 · HEADWIND ≥ 30 · ADVERSE

(pit score +0.5 → FAVORABLE, −0.5 → HEADWIND: roughly the top and bottom quarter of
its history). It used to be a second model — monthly official labels in
`macro_indicators` through a hard-coded sector map — whose only inputs for
Financials, Information Technology and Communication Services were GST and credit
growth. Those two have no feed (dropped, not faked, on 2026-09-27), so from 2026-09-28
those three sectors had no macro row and signals/regulatory.py wrote them UNKNOWN.

Every GICS sector in `stocks` gets a row; a sector the engine cannot score is a
run_events item failure, and no sector scored at all raises.

Reads:  macro_history, macro_sector_map, stocks
Writes: macro_sector_signals

Usage:
    python -m signals.macro
    python -m signals.macro --dry-run
"""

import argparse
from datetime import date

import pandas as pd

import runlog
from db import read_sql, upsert_df

DISPLAY_SCALE = 10      # display points per unit of pit_macro_sector's score


def _sector_signal(score):
    if score >= 70: return "TAILWIND"
    if score >= 55: return "FAVORABLE"
    if score >= 45: return "NEUTRAL"
    if score >= 30: return "HEADWIND"
    return "ADVERSE"


def display_score(pit_score):
    """pit_macro_sector's signed score on the Sectors page's 0–100 scale (50 = no tilt)."""
    return round(min(100.0, max(0.0, 50.0 + DISPLAY_SCALE * float(pit_score))), 1)


def _detail(drivers):
    """'bank_nifty: +4.1% in 90d (tailwind) | us_10y: +3.0% in 90d (headwind)' — the raw
    move first (signals/sector_briefs parses it), then what it means for the sector."""
    parts = []
    for d in drivers:
        effect = d["pct_change"] * d["direction"]
        word = "tailwind" if effect > 0 else "headwind" if effect < 0 else "flat"
        parts.append(f"{d['indicator_id']}: {d['pct_change']:+.1f}% in 90d ({word})")
    return " | ".join(parts)


def sector_reads(macro_hist, macro_map, sectors, as_of):
    """DataFrame[sector, macro_score, macro_signal, macro_detail] for `sectors` as of
    `as_of` — pit_macro_sector in display form. A sector it cannot score is left out."""
    from pit import pit_macro_sector
    hist = macro_hist[macro_hist["date"] <= as_of.isoformat()]
    rows = []
    for r in pit_macro_sector(hist, macro_map, sectors, as_of):
        if r["macro_score"] is None:
            continue
        score = display_score(r["macro_score"])
        rows.append({"sector": r["sector"], "macro_score": score,
                     "macro_signal": _sector_signal(score),
                     "macro_detail": _detail(r["drivers"])[:500]})
    return pd.DataFrame(rows, columns=["sector", "macro_score", "macro_signal", "macro_detail"])


def compute(dry_run=False, as_of=None):
    """Score every stocks sector from macro history and save to macro_sector_signals."""
    as_of = as_of or date.today()
    from pit import RAW_SQL
    macro_hist = read_sql(RAW_SQL["macro_hist"])
    macro_map = read_sql(RAW_SQL["macro_map"])
    sectors = sorted(read_sql("SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL")["sector"])
    if macro_map.empty or not sectors:
        raise RuntimeError("signal_macro: macro_sector_map or stocks.sector is empty — nothing to score")

    df = sector_reads(macro_hist, macro_map, sectors, as_of)
    if df.empty:
        raise RuntimeError(f"signal_macro: no sector scored as of {as_of} — macro_history has no "
                           f"90-day moves for the macro_sector_map indicators")
    for s in sorted(set(sectors) - set(df["sector"])):
        runlog.item_failed("signal_macro", s, "no macro reading: none of its macro_sector_map "
                           "indicators has a 90-day move in macro_history")
    df.insert(1, "snapshot_date", as_of.isoformat())

    print(f"Macro Sector: {len(df)} of {len(sectors)} sectors scored")
    for _, r in df.iterrows():
        print(f"  {r['sector']:30s} {r['macro_score']:5.1f}  {r['macro_signal']}")

    if dry_run:
        print("\nDry run — not saving.")
        return len(df)

    n = upsert_df(df, "macro_sector_signals")
    print(f"Saved {n} rows to macro_sector_signals")
    return n


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
