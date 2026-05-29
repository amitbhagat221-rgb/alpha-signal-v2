"""Sector brief aggregator — Plan 0006 Phase A.

Joins macro + model + regulatory data per sector into one snapshot row,
then assigns a bucket ∈ {BOOMING, LIKELY, HEADWIND, QUIET} that drives the
/sectors front-door digest.

Runs nightly after `screener` (needs latest daily_picks). Persists into
`sector_briefs` (one row per sector per snapshot_date).

Data-source caveats (2026-05-29 audit, documented in plan 0006):
  - FII/DII tables in v2 are INDEX-LEVEL only. `fii_dii_cash_flow` has
    `category` ∈ {FII, DII, Client} but no sector column. Phase A stores
    NULL for fii_net_30d / dii_net_30d; sector-level flow attribution is
    out of scope for v1.
  - regulatory_signals (not regulatory_events) carries the sector tag and
    direction classification. Joined to events for the published_at filter.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import pandas as pd

from db import get_db, read_sql


def _parse_macro_drivers(detail: str | None) -> list[dict]:
    """Parse macro_detail like 'iip_capital_goods: +3.2% YoY | core_cement: +13.5% YoY'
    into [{driver, value, unit, direction, raw}, …].

    Direction is the sign of the parsed number (or explicit '+' / '-' prefix).
    Falls back to raw string if a chunk doesn't parse cleanly.
    """
    if not detail or not isinstance(detail, str):
        return []
    out: list[dict] = []
    for chunk in detail.split("|"):
        chunk = chunk.strip()
        if ":" not in chunk:
            continue
        key, _, val = chunk.partition(":")
        key, val = key.strip(), val.strip()
        m = re.search(r"([+\-]?)([0-9,]+(?:\.[0-9]+)?)\s*(%|Cr|cr|₹)?", val)
        if not m:
            out.append({"driver": key, "value": None, "unit": None, "direction": None, "raw": val})
            continue
        sign, num, unit = m.group(1), m.group(2), m.group(3) or ""
        try:
            value_f = float(num.replace(",", ""))
        except ValueError:
            out.append({"driver": key, "value": None, "unit": unit, "direction": None, "raw": val})
            continue
        if sign == "-":
            value_f = -value_f
            direction = "-"
        elif sign == "+":
            direction = "+"
        else:
            direction = "+" if value_f > 0 else ("-" if value_f < 0 else "neutral")
        out.append({
            "driver": key,
            "value": value_f,
            "unit": unit,
            "direction": direction,
            "raw": val,
        })
    return out


def _classify(macro_score, breadth_pct) -> str:
    """Bucket per plan 0006 Phase A.

    BOOMING  = macro_score ≥ 60 AND breadth_pct ≥ 50
    LIKELY   = macro_score ≥ 60 AND breadth_pct < 50  (tailwind, model not in yet)
    HEADWIND = macro_score < 40
    QUIET    = everything else (including unknowns)
    """
    if macro_score is None or pd.isna(macro_score):
        return "QUIET"
    if breadth_pct is None or pd.isna(breadth_pct):
        return "QUIET"
    if macro_score >= 60 and breadth_pct >= 50:
        return "BOOMING"
    if macro_score >= 60 and breadth_pct < 50:
        return "LIKELY"
    if macro_score < 40:
        return "HEADWIND"
    return "QUIET"


def _to_native(v):
    """Convert NumPy scalars and NaN to Python primitives for sqlite3 bindings."""
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if hasattr(v, "item"):
        return v.item()
    return v


def build_sector_briefs(snapshot_date: str | None = None) -> int:
    """Compute and upsert sector briefs for snapshot_date. Returns row count written.

    If snapshot_date is None, anchors on the latest pick_date in daily_picks.
    """
    with get_db() as conn:
        if snapshot_date is None:
            row = conn.execute("SELECT MAX(pick_date) FROM daily_picks").fetchone()
            if not row or not row[0]:
                raise RuntimeError("No daily_picks data — cannot compute sector briefs")
            snapshot_date = row[0]

    # ── Universe scale ──
    base = read_sql("""
        SELECT s.sector,
               COUNT(*) AS n_stocks,
               ROUND(SUM(s.market_cap_cr) / 1e7, 0) AS mcap_total_cr
        FROM stocks s
        WHERE s.sector IS NOT NULL AND s.ticker IS NOT NULL
        GROUP BY s.sector
    """)
    if base.empty:
        raise RuntimeError("Empty stocks universe — cannot compute sector briefs")

    # ── Latest macro snapshot ──
    macro = read_sql("""
        SELECT sector, macro_score, macro_signal, macro_detail
        FROM macro_sector_signals
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM macro_sector_signals)
    """)
    base = base.merge(macro, on="sector", how="left")

    # ── Model view from picks on snapshot_date ──
    picks_agg = read_sql(
        """
        SELECT dp.sector,
               ROUND(100.0 * SUM(CASE WHEN dp.final_score >= 0.55 THEN 1 ELSE 0 END) / COUNT(*), 1) AS breadth_pct,
               ROUND(
                 SUM(dp.final_score * s.market_cap_cr) / NULLIF(SUM(s.market_cap_cr), 0),
                 3
               ) AS avg_score
        FROM daily_picks dp
        JOIN stocks s ON s.sid = dp.sid
        WHERE dp.pick_date = ? AND dp.sector IS NOT NULL
        GROUP BY dp.sector
        """,
        params=[snapshot_date],
    )
    base = base.merge(picks_agg, on="sector", how="left")

    # ── Top-30 picks per sector (the actionable cut) ──
    top_picks = read_sql(
        """
        SELECT dp.sector, s.ticker, dp.rank, dp.final_score
        FROM daily_picks dp
        JOIN stocks s ON s.sid = dp.sid
        WHERE dp.pick_date = ? AND dp.rank <= 30 AND dp.sector IS NOT NULL
        ORDER BY dp.sector, dp.rank
        """,
        params=[snapshot_date],
    )
    counts_by_sector: dict[str, int] = {}
    picks_by_sector: dict[str, list[dict]] = {}
    if not top_picks.empty:
        for _, r in top_picks.iterrows():
            sec = r["sector"]
            counts_by_sector[sec] = counts_by_sector.get(sec, 0) + 1
            lst = picks_by_sector.setdefault(sec, [])
            if len(lst) < 5:
                lst.append({
                    "ticker": r["ticker"],
                    "rank": int(r["rank"]),
                    "score": float(r["final_score"]),
                })
    base["n_picks_top30"] = base["sector"].map(lambda s: counts_by_sector.get(s, 0))
    base["top_picks"] = base["sector"].map(lambda s: picks_by_sector.get(s, []))

    # ── Regulatory pulse (last 30 days, sector-tagged) ──
    since = (datetime.fromisoformat(snapshot_date) - timedelta(days=30)).date().isoformat()
    reg = read_sql(
        """
        SELECT rs.sector, rs.direction, COUNT(*) AS n
        FROM regulatory_signals rs
        JOIN regulatory_events re ON re.event_id = rs.event_id
        WHERE rs.is_regulatory = 1
          AND date(re.published_at) >= ?
        GROUP BY rs.sector, rs.direction
        """,
        params=[since],
    )
    reg_counts_by_sector: dict[str, int] = {}
    reg_summary_by_sector: dict[str, dict] = {}
    if not reg.empty:
        for _, r in reg.iterrows():
            sec = r["sector"]
            reg_counts_by_sector[sec] = reg_counts_by_sector.get(sec, 0) + int(r["n"])
            dkey = str(r["direction"]) if r["direction"] is not None else "unknown"
            reg_summary_by_sector.setdefault(sec, {})[dkey] = int(r["n"])
    base["n_regulatory_30d"] = base["sector"].map(lambda s: reg_counts_by_sector.get(s, 0))
    base["regulatory_summary"] = base["sector"].map(lambda s: reg_summary_by_sector.get(s, {}))

    # ── Derived: parsed macro drivers + bucket ──
    base["macro_drivers"] = base["macro_detail"].map(_parse_macro_drivers)
    base["bucket"] = base.apply(
        lambda r: _classify(r.get("macro_score"), r.get("breadth_pct")), axis=1
    )

    # ── Write — INSERT OR REPLACE (snapshot table per CLAUDE.md) ──
    now = datetime.now().isoformat(timespec="seconds")
    written = 0
    with get_db() as conn:
        for _, r in base.iterrows():
            conn.execute(
                """
                INSERT OR REPLACE INTO sector_briefs (
                    sector, snapshot_date,
                    n_stocks, mcap_total_cr,
                    macro_score, macro_signal, macro_drivers,
                    breadth_pct, avg_score,
                    n_picks_top30, top_picks,
                    n_regulatory_30d, regulatory_summary,
                    fii_net_30d, dii_net_30d,
                    bucket, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["sector"], snapshot_date,
                    int(r["n_stocks"]),
                    _to_native(r.get("mcap_total_cr")),
                    _to_native(r.get("macro_score")),
                    r.get("macro_signal") if not (isinstance(r.get("macro_signal"), float) and pd.isna(r.get("macro_signal"))) else None,
                    json.dumps(r["macro_drivers"] or []),
                    _to_native(r.get("breadth_pct")),
                    _to_native(r.get("avg_score")),
                    int(r["n_picks_top30"] or 0),
                    json.dumps(r["top_picks"] or []),
                    int(r["n_regulatory_30d"] or 0),
                    json.dumps(r["regulatory_summary"] or {}),
                    None,  # fii_net_30d — RESERVED, see plan 0006
                    None,  # dii_net_30d — RESERVED, see plan 0006
                    r["bucket"],
                    now,
                ),
            )
            written += 1
    return written


def compute(snapshot_date: str | None = None) -> int:
    """Pipeline entry point. Returns row count (pipeline.py logs `rows`)."""
    return build_sector_briefs(snapshot_date=snapshot_date)


if __name__ == "__main__":
    import sys
    sd = sys.argv[1] if len(sys.argv) > 1 else None
    n = compute(sd)
    print(f"sector_briefs: wrote {n} rows")
