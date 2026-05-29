"""Sector force decomposition — Plan 0006 Phase B.

Sits on top of sector_briefs (Phase A). For each sector x date, emits one row
per force in {macro, regulation, tech}. Market is reserved (v2 FII/DII data
is index-level only).

Each force row stores:
  direction  ∈ {+, -, neutral, None}
  magnitude  ∈ {strong, moderate, weak, None}
  summary    — 1-2 sentences for the cockpit UI
  detail     — JSON, structured breakdown for drill-down

Designed to be cheap: one query per force across all sectors, then write.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd

from db import get_db, read_sql


# ── helpers ──────────────────────────────────────────────────────────────────

def _to_native(v):
    if v is None:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    if hasattr(v, "item"):
        return v.item()
    return v


_MAG_RANK = {"major": 3, "moderate": 2, "minor": 1}


# ── Macro force ──────────────────────────────────────────────────────────────

def _macro_force(snapshot_date: str) -> dict[str, dict]:
    """Per-sector macro force from sector_briefs.macro_drivers.

    Direction = mode of driver directions. Summary = top 2 drivers joined.
    """
    df = read_sql(
        "SELECT sector, macro_score, macro_drivers FROM sector_briefs WHERE snapshot_date=?",
        params=[snapshot_date],
    )
    out: dict[str, dict] = {}
    for _, r in df.iterrows():
        drivers = json.loads(r["macro_drivers"] or "[]")
        if not drivers:
            continue
        # Direction from majority sign of drivers with a parsed value
        signs = [d.get("direction") for d in drivers if d.get("direction") in ("+", "-")]
        if not signs:
            direction = "neutral"
        else:
            direction = "+" if signs.count("+") >= signs.count("-") else "-"
        # Magnitude maps off the sector's overall macro_score band
        score = r.get("macro_score")
        if score is None or pd.isna(score):
            magnitude = None
        elif score >= 70 or score < 30:
            magnitude = "strong"
        elif score >= 60 or score < 40:
            magnitude = "moderate"
        else:
            magnitude = "weak"
        # Summary — top 2 drivers by absolute value
        scored = sorted(
            [d for d in drivers if isinstance(d.get("value"), (int, float))],
            key=lambda d: abs(d["value"]),
            reverse=True,
        )[:2]
        if scored:
            summary = " · ".join(
                f"{d['driver']} {d.get('raw') or (f'{d['value']:+g}{d.get('unit','')}'.rstrip())}"
                for d in scored
            )
        else:
            summary = " · ".join(d.get("raw") or d.get("driver", "") for d in drivers[:2])
        out[r["sector"]] = {
            "direction": direction,
            "magnitude": magnitude,
            "summary": summary[:280],
            "detail": {"drivers": drivers},
        }
    return out


# ── Regulation force ────────────────────────────────────────────────────────

def _regulation_force(snapshot_date: str) -> dict[str, dict]:
    """Per-sector regulation force from regulatory_signals + events (last 30d)."""
    since = (datetime.fromisoformat(snapshot_date) - timedelta(days=30)).date().isoformat()

    # Count by direction + magnitude per sector
    counts = read_sql(
        """
        SELECT rs.sector, rs.direction, rs.magnitude, COUNT(*) AS n
        FROM regulatory_signals rs
        JOIN regulatory_events re ON re.event_id = rs.event_id
        WHERE rs.is_regulatory = 1
          AND date(re.published_at) >= ?
          AND rs.sector IS NOT NULL
        GROUP BY rs.sector, rs.direction, rs.magnitude
        """,
        params=[since],
    )

    # Top event per sector by magnitude (for the summary line)
    top_events = read_sql(
        """
        WITH ranked AS (
            SELECT rs.sector, rs.direction, rs.magnitude, rs.ai_reasoning, re.published_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY rs.sector
                       ORDER BY CASE rs.magnitude
                                  WHEN 'major' THEN 3 WHEN 'moderate' THEN 2 WHEN 'minor' THEN 1
                                  ELSE 0 END DESC,
                                re.published_at DESC
                   ) AS r
            FROM regulatory_signals rs
            JOIN regulatory_events re ON re.event_id = rs.event_id
            WHERE rs.is_regulatory = 1
              AND date(re.published_at) >= ?
              AND rs.sector IS NOT NULL
        )
        SELECT sector, direction, magnitude, ai_reasoning FROM ranked WHERE r = 1
        """,
        params=[since],
    )
    top_by_sector = {
        r["sector"]: {
            "direction": r["direction"],
            "magnitude": r["magnitude"],
            "ai_reasoning": r["ai_reasoning"],
        }
        for _, r in top_events.iterrows()
    } if not top_events.empty else {}

    out: dict[str, dict] = {}
    for sec, grp in counts.groupby("sector"):
        pos = int(grp[grp["direction"] == 1]["n"].sum())
        neg = int(grp[grp["direction"] == -1]["n"].sum())
        neu = int(grp[grp["direction"] == 0]["n"].sum())
        total = pos + neg + neu
        if total == 0:
            continue
        if pos > neg * 1.2:
            direction = "+"
        elif neg > pos * 1.2:
            direction = "-"
        else:
            direction = "neutral"
        # Magnitude = highest magnitude present (major > moderate > minor)
        mag_rank = [_MAG_RANK.get(m, 0) for m in grp["magnitude"].dropna()]
        top_mag = max(mag_rank) if mag_rank else 0
        magnitude = {3: "strong", 2: "moderate", 1: "weak"}.get(top_mag)
        # Summary — pull the top event's ai_reasoning
        top = top_by_sector.get(sec, {})
        summary = (top.get("ai_reasoning") or "")[:280] or f"{total} regulatory events in 30d ({pos}↑ / {neg}↓)"
        out[sec] = {
            "direction": direction,
            "magnitude": magnitude,
            "summary": summary,
            "detail": {
                "n_events_30d": total,
                "by_direction": {"positive": pos, "negative": neg, "neutral": neu},
                "top_event": top,
            },
        }
    return out


# ── Tech / innovation force ──────────────────────────────────────────────────

# Sectors with no sector-level row in sector_metadata fall back to a constituent
# industry's dossier. Mapping is conservative — only sectors we know lack a
# direct row need a fallback. Verified 2026-05-29.
_TECH_FALLBACK = {
    "Financials": "Banks",
}


def _tech_force(snapshot_date: str) -> dict[str, dict]:
    """Per-sector tech/innovation force from sector_metadata.drivers.growth.

    Filters to structural + policy items (durable themes), takes top 2.
    """
    df = read_sql(
        """
        SELECT sector, industry, payload
        FROM sector_metadata
        WHERE source = 'auto'
          AND sector IN (SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL)
        """
    )
    by_sector: dict[str, dict] = {}
    for _, r in df.iterrows():
        try:
            payload = json.loads(r["payload"])
        except (json.JSONDecodeError, TypeError):
            continue
        by_sector[r["sector"]] = payload

    # Fallback rows — lookup by industry
    df_ind = read_sql(
        """
        SELECT sector, industry, payload
        FROM sector_metadata
        WHERE source = 'auto'
          AND industry IN ({})
        """.format(",".join("?" * len(_TECH_FALLBACK))),
        params=list(_TECH_FALLBACK.values()),
    )
    industry_payloads = {}
    for _, r in df_ind.iterrows():
        try:
            industry_payloads[r["industry"]] = json.loads(r["payload"])
        except (json.JSONDecodeError, TypeError):
            continue

    out: dict[str, dict] = {}
    # Iterate the 11 canonical sectors
    sectors = sorted(
        read_sql(
            "SELECT DISTINCT sector FROM stocks WHERE sector IS NOT NULL AND ticker IS NOT NULL"
        )["sector"].tolist()
    )

    for sec in sectors:
        payload = by_sector.get(sec)
        source_label = "sector"
        if not payload and sec in _TECH_FALLBACK:
            payload = industry_payloads.get(_TECH_FALLBACK[sec])
            source_label = f"industry:{_TECH_FALLBACK[sec]}"
        if not payload:
            continue

        growth = payload.get("drivers", {}).get("growth") or []
        durable = [g for g in growth if g.get("type") in ("structural", "policy")]
        if not durable:
            durable = growth[:2]  # fall back to whatever's there
        top = durable[:2]
        if not top:
            continue

        # Direction is '+' for growth themes by definition. Magnitude reflects
        # whether the dossier has multiple distinct themes (broad) or just one.
        magnitude = "strong" if len(durable) >= 3 else ("moderate" if len(durable) >= 1 else "weak")
        summary_parts = [g["item"] for g in top if g.get("item")]
        summary = " · ".join(summary_parts)[:280]
        out[sec] = {
            "direction": "+",
            "magnitude": magnitude,
            "summary": summary,
            "detail": {
                "themes": top,
                "all_growth_count": len(growth),
                "source": source_label,
            },
        }
    return out


# ── Orchestration ────────────────────────────────────────────────────────────

def build_sector_forces(snapshot_date: str | None = None) -> int:
    """Compute and upsert force breakdown rows. Returns total rows written.

    market force is intentionally skipped in v1 (no sector-level FII/DII data).
    """
    with get_db() as conn:
        if snapshot_date is None:
            row = conn.execute(
                "SELECT MAX(snapshot_date) FROM sector_briefs"
            ).fetchone()
            if not row or not row[0]:
                raise RuntimeError("No sector_briefs data — run compute_sector_briefs first")
            snapshot_date = row[0]

    forces = {
        "macro":      _macro_force(snapshot_date),
        "regulation": _regulation_force(snapshot_date),
        "tech":       _tech_force(snapshot_date),
    }

    now = datetime.now().isoformat(timespec="seconds")
    written = 0
    with get_db() as conn:
        for force_name, by_sector in forces.items():
            for sector, payload in by_sector.items():
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sector_force_breakdown (
                        sector, snapshot_date, force,
                        direction, magnitude, summary, detail, computed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sector, snapshot_date, force_name,
                        payload.get("direction"),
                        payload.get("magnitude"),
                        payload.get("summary"),
                        json.dumps(payload.get("detail") or {}),
                        now,
                    ),
                )
                written += 1
    return written


def compute(snapshot_date: str | None = None) -> int:
    """Pipeline entry point. Returns row count."""
    return build_sector_forces(snapshot_date=snapshot_date)


if __name__ == "__main__":
    import sys
    sd = sys.argv[1] if len(sys.argv) > 1 else None
    n = compute(sd)
    print(f"sector_force_breakdown: wrote {n} rows")
