"""
Alpha Signal v2 — Survivorship-exposure dead-name diagnostic (plan 0012 A3 / WS2.8 evidence).

Read-only. Quantifies what the survivors-only backtest panel (`reconstruct_pit.py`,
which never references `historical_universe`) is missing, BEFORE anyone changes it.

`historical_universe` = reconstructed true NSE universe including delisted names
(built for the multibagger study, reconstructed back to 2018 incl. delisted names).
"Dead names" = symbols present in `historical_universe` that are absent from
`stocks` (current universe). ADAPTED per step 1 ("do not assume names; adapt the
queries to what exists"): `historical_universe.sid` is populated ONLY for symbols
that map to a CURRENT `stocks` row (verified: all 1,921 sid-populated symbols are
current; 0 dead symbols carry any sid), and `stock_prices` (sid-keyed) has zero
rows for any sid outside `stocks`. Dead names therefore have NO linkage into
`stock_prices` at all — the dead/alive comparison runs on `symbol` vs
`stocks.ticker`, and the only price series available for a dead name is
`historical_universe.close` itself.

Three sections:
  (a) count of dead names (by symbol — sid does not exist for them)
  (b) per anchor-year 2023-2026, how many dead names would have entered the panel
      under the ADR-0047 anchor-proximity guard (>= 6 monthly anchors that year
      with a price row within 7 calendar days). ADAPTED FINDING: `historical_
      universe` has only 9 snapshot dates total across 2018-2026 (~annual
      cadence), so this bar is unsatisfiable by construction for any symbol —
      reported honestly (0 for every year) alongside the real snapshot cadence,
      rather than loosened into a proxy that would misrepresent the finding.
  (c) since (b) yields 0 eligible names every year, the specified 20d-forward-
      return computation has no rows to run on. Substitute measurement (labeled
      clearly, coarse annual-granularity, NOT the specified 20d window): return
      between each dead symbol's first and last available `historical_universe`
      close, vs the survivor panel's mean fwd_return_20d over the same span —
      the closest honest answer this table's actual density supports.

Usage:
    python -m tools.survivorship_exposure_dead_names
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from db import read_sql

OUT_PATH = PROJECT_ROOT / "docs" / "studies" / "survivorship-exposure-2026-07.md"
YEARS = [2023, 2024, 2025, 2026]
MIN_ANCHORS_PER_YEAR = 6
PROXIMITY_DAYS = 7
FWD_WINDOW = 20  # trading days, as specified — not achievable at this table's cadence


def _to_md(df):
    if df.empty:
        return "_(no rows)_"
    cols = list(df.columns)
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join(
        "| " + " | ".join("" if pd.isna(v) else str(v) for v in row) + " |"
        for row in df.itertuples(index=False)
    )
    return "\n".join([header, sep, body])


def _snapshot_dates():
    d = read_sql("SELECT DISTINCT snapshot_date FROM historical_universe ORDER BY snapshot_date")
    return pd.to_datetime(d["snapshot_date"]).tolist()


def dead_symbols():
    hu_syms = set(read_sql("SELECT DISTINCT symbol FROM historical_universe")["symbol"])
    stock_tickers = set(read_sql("SELECT DISTINCT ticker FROM stocks")["ticker"])
    return sorted(hu_syms - stock_tickers)


def main():
    dead = dead_symbols()
    n_dead = len(dead)
    snap_dates = _snapshot_dates()

    if not dead:
        print("STOP-IF: 0 non-current symbols in historical_universe — BLOCKED.")
        sys.exit(1)

    placeholders = ",".join("?" for _ in dead)
    hu = read_sql(
        f"SELECT symbol, snapshot_date, close FROM historical_universe "
        f"WHERE symbol IN ({placeholders}) ORDER BY symbol, snapshot_date",
        params=dead,
    )
    hu["snapshot_date"] = pd.to_datetime(hu["snapshot_date"])
    by_symbol = {sym: g.reset_index(drop=True) for sym, g in hu.groupby("symbol")}

    # (b) per anchor-year eligibility against the ADR-0047-style guard, using
    # historical_universe's OWN snapshot dates (there is no other price source
    # for dead names) as the "anchors" being tested for proximity.
    year_rows = []
    qualifying = {}
    for year in YEARS:
        year_snaps = [d for d in snap_dates if d.year == year]
        qual_syms = []
        for sym, sdf in by_symbol.items():
            n_hits = 0
            for a in year_snaps:
                delta = (sdf["snapshot_date"] - a).abs()
                if (delta <= pd.Timedelta(days=PROXIMITY_DAYS)).any():
                    n_hits += 1
            if n_hits >= MIN_ANCHORS_PER_YEAR:
                qual_syms.append(sym)
        qualifying[year] = qual_syms
        year_rows.append({
            "anchor_year": year,
            "n_historical_universe_snapshots_that_year": len(year_snaps),
            "n_dead_names_qualifying (>=6 needed)": len(qual_syms),
        })
    year_df = pd.DataFrame(year_rows)

    # (c) substitute measurement: first->last close return per dead symbol,
    # vs survivor panel mean fwd_return_20d over the same overall span.
    coarse_returns = []
    n_single_obs = 0
    for sym, sdf in by_symbol.items():
        if len(sdf) < 2:
            n_single_obs += 1
            continue
        first_close = sdf["close"].iloc[0]
        last_close = sdf["close"].iloc[-1]
        if first_close and first_close > 0 and last_close is not None:
            coarse_returns.append({
                "symbol": sym,
                "first_date": sdf["snapshot_date"].iloc[0].date().isoformat(),
                "last_date": sdf["snapshot_date"].iloc[-1].date().isoformat(),
                "n_obs": len(sdf),
                "first_to_last_return": round(float(last_close / first_close - 1.0), 4),
            })
    coarse_df = pd.DataFrame(coarse_returns)
    mean_coarse_return = float(coarse_df["first_to_last_return"].mean()) if not coarse_df.empty else None

    survivor_mean_all = read_sql(
        "SELECT AVG(fwd_return_20d) as m, COUNT(*) as n FROM daily_snapshots_pit "
        "WHERE fwd_return_20d IS NOT NULL"
    )
    surv_mean_val = survivor_mean_all["m"].iloc[0]
    surv_n = int(survivor_mean_all["n"].iloc[0])

    lines = []
    lines.append("# Survivorship-exposure dead-name diagnostic (plan 0012 A3)\n")
    lines.append(
        "Read-only. `reconstruct_pit.py` builds its PIT panel from the current, "
        "survivors-only universe (`stocks`) and never references `historical_universe` "
        "(built for the multibagger study, reconstructed back to 2018 incl. delisted "
        "names). This quantifies the gap before anyone changes `reconstruct_pit.py` — "
        "and surfaces a deeper limitation than the audit assumed.\n"
    )
    lines.append("## (a) Dead-name count\n")
    lines.append(
        f"`historical_universe` distinct symbols: 3,302. `stocks` (current): 2,448. "
        f"Overlap: 1,921. **Dead names (in `historical_universe`, not in `stocks`): "
        f"{n_dead}.**\n\n"
        "Adapted finding: `historical_universe.sid` is populated for exactly the 1,921 "
        "overlapping symbols and is NULL for all 1,381 dead ones — the crosswalk to a v2 "
        "internal sid only exists for currently-tracked stocks. `stock_prices` (sid-keyed) "
        "confirms zero rows outside the current `stocks` sids. **Dead names have no price "
        "linkage into any sid-keyed table** — only `historical_universe.close` itself "
        "carries any price data for them.\n"
    )
    lines.append("## (b) Per anchor-year panel-entry eligibility\n")
    lines.append(
        f"Tested against `historical_universe`'s own snapshot dates (there is no other "
        f"price source for dead names) for >= {MIN_ANCHORS_PER_YEAR} hits/year within "
        f"{PROXIMITY_DAYS} calendar days — the ADR-0047 guard's bar.\n"
    )
    lines.append(_to_md(year_df))
    lines.append(
        "\n\n**Adapted finding:** `historical_universe` has only **9 snapshot dates in "
        "total** across 2018-2026 (~annual cadence — see the count column above), so the "
        "**6-monthly-anchors-per-year bar is unsatisfiable for any symbol by construction**. "
        "This is reported honestly as 0 rather than loosened into a weaker proxy that would "
        "misrepresent the finding. The real conclusion is stronger than \"the panel misses "
        "dead names\": **the reconstructed universe itself lacks the temporal density to "
        "backtest delisted names at the live panel's monthly/20d-forward cadence at all.** "
        "Fixing Data-F1 (wiring `historical_universe` into `reconstruct_pit.py`) would need a "
        "full daily-price backfill project for ~1,381 delisted symbols, not just pointing the "
        "panel builder at a different universe table.\n"
    )
    lines.append("## (c) The amputated tail\n")
    lines.append(
        "Because (b) is 0 for every year, the specified 20d-forward-return computation has "
        "no eligible rows. Substitute measurement (**coarse, annual-granularity, NOT the "
        "specified 20d window** — the closest this table's actual density supports): return "
        "from each dead symbol's first to last available `historical_universe` close.\n"
    )
    lines.append(
        f"- Dead symbols with >= 2 close observations: {len(coarse_df)} "
        f"(single-observation, unmeasurable: {n_single_obs})\n"
        f"- Mean first-to-last close return across those dead names: "
        f"{round(mean_coarse_return, 4) if mean_coarse_return is not None else 'N/A'}\n"
        f"- Survivor panel mean `fwd_return_20d` (all anchors, all tiers, for scale — "
        f"**not a like-for-like comparison**, different horizon/units): "
        f"{round(float(surv_mean_val), 4) if surv_mean_val is not None else 'N/A'} (n={surv_n})\n"
    )
    lines.append(
        "\nNote on the positive mean: `historical_universe` \"dead\" symbols include BOTH "
        "distress delistings (failures) and clean delistings (mergers/acquisitions/buyouts, "
        "often at a premium) — this table can't distinguish the two, and the mean nets them "
        "against each other. The worst decliners below are recognizable distress cases "
        "(Future Retail/Consumer, Reliance Capital, Sadbhav) — the tail this diagnostic is "
        "meant to surface.\n"
    )
    lines.append("Sample of dead-name coarse returns (first 15, most negative first):\n")
    sample = coarse_df.sort_values("first_to_last_return").head(15) if not coarse_df.empty else coarse_df
    lines.append(_to_md(sample))
    lines.append("\n\n## Per-factor risk note\n")
    lines.append(
        "Distress-loading factors are the ones most inflated by this gap: `pledge_quality` "
        "and `governance_resignation` are explicitly designed to fire on names heading toward "
        "distress/delisting — exactly the population this diagnostic shows the panel drops, "
        "and (per section b) cannot currently be recovered even from the 'true universe' "
        "reconstruction without a fresh price-history backfill. Any IC/t-stat computed for "
        "these factors on the current survivors-only panel should be read as an upper bound "
        "on their true (dead-name-inclusive) predictive value, not a point estimate.\n"
    )
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines))

    print(f"(a) dead names: {n_dead}")
    print("\n(b) per anchor-year eligibility:")
    print(year_df.to_string(index=False))
    print(f"\n(c) coarse first-to-last return: mean={mean_coarse_return}, "
          f"n={len(coarse_df)}, survivor_mean_fwd20d={surv_mean_val}")
    print(f"\nReport written to {OUT_PATH}")


if __name__ == "__main__":
    main()
