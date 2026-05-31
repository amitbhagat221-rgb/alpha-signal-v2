"""
Alpha Signal v2 — Sector Investment Dossier (Claude API) — Plan 0006 Phase D.

Per-sector daily narrative, parallel to the per-stock dossier (output/dossier.py).
Turns the deterministic sector_briefs + sector_force_breakdown + sector_metadata
into a horizon-aware read: thesis, bull/bear, what-to-watch (S/M/L), and the
tech/innovation drivers that purely-deterministic Phase B can't synthesise.

Same HARD hygiene contract as the stock dossier (HALC 2026-05-22):
  - Narrative fields carry NO raw numbers — calendar tokens (Q1/FY25/H1) only.
    Numbers hallucinate plausibly the moment the underlying signal moves.
  - The number scanner is shared verbatim with output.dossier so the two
    dossiers can never diverge on what counts as a leak.
  - Invalid dossiers are persisted with valid=0; the cockpit surfaces {} for
    them (mirror of get_dossier() returning {} for invalid stock dossiers).

Reads:  sector_briefs, sector_force_breakdown, sector_metadata (latest snapshot)
Writes: sector_dossiers (PK sector + snapshot_date), INSERT OR REPLACE

Requires ANTHROPIC_API_KEY env var (non-dry-run).

Usage:
    python -m output.sector_dossier              # all sectors, latest snapshot
    python -m output.sector_dossier --dry-run    # build prompts, no API calls
    python -m output.sector_dossier --sector Energy --limit 1
"""

import argparse
import json
import os
from datetime import datetime

from db import get_db, read_sql

# Reuse the stock-dossier number scanner verbatim — single source of truth for
# "what is a forbidden raw number". Calendar tokens (Q1/FY25/H1) are allowed
# there; everything else (%, ₹, decimals, multiples, ratios) is a violation.
from output.dossier import _scan_for_numbers


MODEL = "claude-sonnet-4-20250514"

# Narrative fields that must stay number-free. what_to_watch / *_case are lists.
_NARRATIVE_FIELDS = ("thesis", "bull_case", "bear_case",
                     "what_to_watch", "tech_innovation_drivers")


# ─────────────────────── Schema bootstrap ───────────────────────

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS sector_dossiers (
    sector                   TEXT NOT NULL,
    snapshot_date            TEXT NOT NULL,
    thesis                   TEXT,
    bull_case                TEXT,   -- JSON list of strings
    bear_case                TEXT,   -- JSON list of strings
    what_to_watch            TEXT,   -- JSON list of {horizon: S|M|L, item: str}
    tech_innovation_drivers  TEXT,   -- JSON list of strings
    conviction               TEXT,   -- HIGH / MEDIUM / LOW (sector tilt)
    valid                    INTEGER NOT NULL DEFAULT 0,
    validation_json          TEXT,
    model                    TEXT,
    generated_at             TEXT NOT NULL,
    PRIMARY KEY (sector, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_sector_dossiers_date ON sector_dossiers(snapshot_date);
"""


def _ensure_schema():
    with get_db() as conn:
        for stmt in CREATE_SQL.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)


# ─────────────────────── Validator ───────────────────────

def _iter_field_texts(dossier, field):
    """Yield the scannable strings for a narrative field (handles list shapes)."""
    val = dossier.get(field)
    if val is None:
        return
    if isinstance(val, list):
        for item in val:
            if isinstance(item, dict):
                yield str(item.get("item", ""))
            else:
                yield str(item)
    else:
        yield str(val)


def _validate_sector_dossier(dossier):
    """Scan narrative fields for forbidden raw numbers.

    Returns {ok, violations, validated_at}. Same policy as the stock dossier:
    any percentage / rupee / decimal / multiple / ratio in a narrative field is
    a violation; calendar tokens are allowed (handled by _scan_for_numbers).
    """
    violations = []
    for field in _NARRATIVE_FIELDS:
        for text in _iter_field_texts(dossier, field):
            for snippet, kind in _scan_for_numbers(text):
                violations.append({"field": field, "snippet": snippet, "kind": kind})
    return {
        "ok": len(violations) == 0,
        "violations": violations,
        "validated_at": datetime.now().isoformat(timespec="seconds"),
    }


# ─────────────────────── Context build ───────────────────────

def _build_sector_context(sector, snapshot_date):
    """Assemble the qualitative context for one sector from the deterministic
    sector tables. Numbers ARE present in the source text (driver values, event
    counts) — the prompt forbids echoing them and the validator catches leaks."""
    brief = read_sql(
        """
        SELECT bucket, macro_signal, macro_drivers, breadth_pct, n_picks_top30,
               top_picks, n_regulatory_30d, regulatory_summary
        FROM sector_briefs
        WHERE sector = ? AND snapshot_date = ?
        """,
        params=[sector, snapshot_date],
    )
    if brief.empty:
        return None
    b = brief.iloc[0].to_dict()

    def _loads(v, default):
        try:
            return json.loads(v) if v else default
        except (json.JSONDecodeError, TypeError):
            return default

    macro_drivers = _loads(b.get("macro_drivers"), [])
    top_picks = _loads(b.get("top_picks"), [])

    forces = read_sql(
        "SELECT force, direction, magnitude, summary "
        "FROM sector_force_breakdown WHERE sector = ? AND snapshot_date = ?",
        params=[sector, snapshot_date],
    )
    force_lines = []
    for _, r in forces.iterrows():
        dir_word = {"+": "tailwind", "-": "headwind"}.get(r["direction"], "neutral")
        force_lines.append(
            f"  - {r['force']} ({r['magnitude'] or '?'} {dir_word}): {r['summary'] or ''}"
        )

    # Long-horizon structural context from the auto-generated sector dossier.
    meta = read_sql(
        "SELECT payload FROM sector_metadata WHERE sector = ? ORDER BY source DESC LIMIT 1",
        params=[sector],
    )
    summary = ""
    growth_themes, segments, india_specific, cyclicality = [], [], "", ""
    if not meta.empty:
        p = _loads(meta.iloc[0]["payload"], {})
        summary = p.get("summary", "") or ""
        drivers = p.get("drivers", {}) or {}
        growth_themes = [d.get("item", "") for d in (drivers.get("growth") or [])][:5]
        segments = [s.get("name", s) if isinstance(s, dict) else s
                    for s in (p.get("segments") or [])][:6]
        india_specific = p.get("india_specific", "") or ""
        cyclicality = p.get("cyclicality", "") or ""

    return {
        "sector": sector,
        "snapshot_date": snapshot_date,
        "bucket": b.get("bucket"),
        "macro_signal": b.get("macro_signal"),
        "macro_drivers": [d.get("driver") for d in macro_drivers if d.get("driver")][:6],
        "top_picks": [p.get("ticker") for p in top_picks if p.get("ticker")][:5],
        "n_picks_top30": int(b.get("n_picks_top30") or 0),
        "n_regulatory_30d": int(b.get("n_regulatory_30d") or 0),
        "force_lines": force_lines,
        "summary": summary,
        "growth_themes": growth_themes,
        "segments": segments,
        "india_specific": india_specific,
        "cyclicality": cyclicality,
    }


def _build_prompt(ctx):
    forces_block = "\n".join(ctx["force_lines"]) or "  (no force signals today)"
    growth_block = "\n".join(f"  - {t}" for t in ctx["growth_themes"]) or "  (none on file)"
    picks = ", ".join(ctx["top_picks"]) or "(none in top-30 today)"
    drivers = ", ".join(ctx["macro_drivers"]) or "(none)"
    segments = ", ".join(str(s) for s in ctx["segments"]) or "(none)"
    return f"""You are an expert Indian equity strategist. Write a concise daily SECTOR dossier — treat the sector like a stock you cover.

SECTOR: {ctx['sector']}
MODEL READ TODAY: bucket = {ctx['bucket']} · macro stance = {ctx['macro_signal']} · {ctx['n_picks_top30']} stocks in today's top-30 ({picks})
ACTIVE MACRO DRIVERS (names only): {drivers}
REGULATORY ACTIVITY (last 30d): {ctx['n_regulatory_30d']} sector-tagged events
KEY SEGMENTS: {segments}
CYCLICALITY: {ctx['cyclicality'] or 'n/a'}

FORCES ACTING ON THE SECTOR (direction + strength + context):
{forces_block}

STRUCTURAL GROWTH THEMES (India-specific, from the sector knowledge base):
{growth_block}

SECTOR BACKGROUND: {ctx['summary'][:600]}
INDIA CONTEXT: {ctx['india_specific'][:300]}

═══════════════════════════════════════════════════════════════════
HARD RULES — violations are rejected by the validator:

1. NO raw numbers anywhere in any narrative field. NO percentages, NO rupee/
   crore amounts, NO multiples, NO ratios, NO event counts, NO market-share or
   CAGR figures. The source text above contains numbers — do NOT echo them.
2. Use QUALITATIVE magnitude words: substantial, broad-based, modest, nascent,
   accelerating, fading. Never invent a figure to sound concrete.
3. Reference forces and drivers BY THEME ("GatiShakti capex push", "China+1
   supply-chain shift"), not by value.
4. Calendar tokens (Q1, FY25, H1) are allowed; specific decimals/percentages
   are not.
5. Be specific to THIS sector — no generic boilerplate that would fit any sector.
═══════════════════════════════════════════════════════════════════

Respond in JSON with these exact keys:
- thesis: one sentence — the sector's current investment posture (NO NUMBERS)
- bull_case: 3 bullet strings (NO NUMBERS — qualitative)
- bear_case: 3 bullet strings (NO NUMBERS — qualitative)
- what_to_watch: 3 objects, each {{"horizon": "S"|"M"|"L", "item": "..."}} —
   S = next few weeks, M = this quarter/cycle, L = multi-year structural (NO NUMBERS)
- tech_innovation_drivers: 2-3 bullet strings on technology/innovation forces
   reshaping the sector (NO NUMBERS)
- conviction: HIGH / MEDIUM / LOW (the sector-level tilt)"""


# ─────────────────────── Driver ───────────────────────

def _call_claude(prompt):
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=MODEL, max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if "```" in text:
            blk = text.split("```")[1]
            if blk.startswith("json"):
                blk = blk[4:]
            return json.loads(blk)
        return {"raw_response": text}


def _persist(sector, snapshot_date, dossier, validation):
    valid = 1 if (dossier.get("thesis") and validation["ok"]) else 0
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO sector_dossiers (
                sector, snapshot_date, thesis, bull_case, bear_case,
                what_to_watch, tech_innovation_drivers, conviction,
                valid, validation_json, model, generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sector, snapshot_date,
                dossier.get("thesis"),
                json.dumps(dossier.get("bull_case") or []),
                json.dumps(dossier.get("bear_case") or []),
                json.dumps(dossier.get("what_to_watch") or []),
                json.dumps(dossier.get("tech_innovation_drivers") or []),
                dossier.get("conviction"),
                valid,
                json.dumps(validation),
                MODEL,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    return valid


def generate(snapshot_date=None, sectors=None, dry_run=False, limit=None):
    """Generate sector dossiers for snapshot_date (latest sector_briefs if None).

    Raises RuntimeError on missing API key (non-dry-run) or if every sector
    failed / produced 0 valid dossiers — so the pipeline logs FAILED instead of
    silently writing placeholders (CLAUDE.md silent-failure rule).
    """
    _ensure_schema()

    if not dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set — sector dossier generator cannot run. "
            "Check run_pipeline.sh exports or systemd env."
        )

    with get_db() as conn:
        if snapshot_date is None:
            row = conn.execute("SELECT MAX(snapshot_date) FROM sector_briefs").fetchone()
            if not row or not row[0]:
                raise RuntimeError("No sector_briefs data — cannot compute sector dossiers")
            snapshot_date = row[0]

    if sectors is None:
        df = read_sql(
            "SELECT DISTINCT sector FROM sector_briefs WHERE snapshot_date = ? ORDER BY sector",
            params=[snapshot_date],
        )
        sectors = list(df["sector"])
    if limit:
        sectors = sectors[:limit]

    print(f"Generating sector dossiers for {len(sectors)} sectors @ {snapshot_date}\n")
    n_valid = n_invalid = n_error = 0
    for sector in sectors:
        ctx = _build_sector_context(sector, snapshot_date)
        if ctx is None:
            print(f"  {sector}: no brief — skipped")
            continue
        prompt = _build_prompt(ctx)

        if dry_run:
            print(f"  {sector}: bucket={ctx['bucket']} · prompt={len(prompt)} chars · "
                  f"forces={len(ctx['force_lines'])} · growth_themes={len(ctx['growth_themes'])}")
            continue

        try:
            dossier = _call_claude(prompt)
            validation = _validate_sector_dossier(dossier)
            valid = _persist(sector, snapshot_date, dossier, validation)
            if valid:
                n_valid += 1
                print(f"  ✓ {sector}: {dossier.get('conviction','?')} — "
                      f"{str(dossier.get('thesis',''))[:70]}…")
            else:
                n_invalid += 1
                vio = validation["violations"][:4]
                print(f"  ⚠ {sector}: INVALID ({len(validation['violations'])} leaks) "
                      + ", ".join(f"{v['field']}:'{v['snippet']}'" for v in vio))
        except Exception as e:
            n_error += 1
            print(f"  ✗ {sector}: error: {str(e)[:120]}")

    if not dry_run:
        print(f"\nDone. {n_valid} valid / {n_invalid} invalid / {n_error} errored "
              f"({len(sectors)} sectors)")
        if len(sectors) > 0 and n_valid == 0:
            raise RuntimeError(
                f"Sector dossier generator produced 0 valid dossiers across "
                f"{len(sectors)} sectors — every call errored or failed validation. "
                f"Check API key, model availability, prompt compliance."
            )
    return n_valid


def compute(dry_run=False):
    """Pipeline entry point."""
    return generate(dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sector", help="Run one sector (smoke test)")
    parser.add_argument("--limit", type=int, help="Limit number of sectors")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    generate(
        sectors=[args.sector] if args.sector else None,
        dry_run=args.dry_run,
        limit=args.limit,
    )
