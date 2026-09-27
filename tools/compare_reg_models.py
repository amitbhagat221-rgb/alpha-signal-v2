"""Agreement gate for downgrading the regulatory deep-classify model.

Runs a sample of already-Haiku-passed regulatory events through BOTH the
current deep model (hosts.HOSTS["anthropic"]["models"]["regulatory_deep"], Sonnet today) and the
candidate cheap model (Haiku), using the exact production CLASSIFY_PROMPT and
parser, then reports field-level agreement.

GATE (per the 2026-07-21 checklist bullet): flip the config flag ONLY if
agreement ≥90% on BOTH `direction` (per matched sector row) and parse success.
Sector-name agreement is reported for information (renames are tolerable;
direction flips are not — direction feeds regulatory_sector_signal #35).

Costs real API tokens (~200 events × 2 models ≈ $0.40 est.) — needs credits.
Usage:
    python -m tools.compare_reg_models            # default n=200
    python -m tools.compare_reg_models --n 50     # cheaper smoke run
Read-only w.r.t. the DB: writes NOTHING to regulatory_signals/events; only
llm_usage rows (step=compare_reg_models*) and a JSON report in output/.
"""

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from db import read_sql
from output._llm import llm_text
from hosts import HOSTS
from sources.regulatory_classifier import (
    CLASSIFY_PROMPT, _parse_classification,
)

CANDIDATE_MODEL = "claude-haiku-4-5-20251001"
GATE = 0.90
REPORT_PATH = Path(__file__).resolve().parent.parent / "output"


def _classify_with(client, model, ev):
    prompt = CLASSIFY_PROMPT.format(
        title=str(ev["title"])[:300], summary=str(ev.get("summary") or "")[:1000],
        source=ev["source"], published_at=ev["published_at"],
    )
    text = llm_text(prompt, model, f"compare_reg_models[{model.split('-')[1]}]",
                    max_tokens=512, client=client).strip()
    # Production's parser, not llm_json: the gate measures what the live
    # classifier would parse (leading fence only).
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return _parse_classification(text)


def _sector_dirs(cls):
    """{sector_name: direction} from a parsed classification (or {})."""
    if not cls:
        return {}
    return {
        str(s.get("sector", "?")): int(s.get("direction", 0) or 0)
        for s in cls.get("sectors_affected", []) or []
    }


def main(n=200, delay=0.2):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY not set — cannot run the gate.")
    import anthropic
    client = anthropic.Anthropic()

    base_model = HOSTS["anthropic"]["models"]["regulatory_deep"]
    if base_model == CANDIDATE_MODEL:
        raise RuntimeError(
            "hosts.HOSTS['anthropic']['models']['regulatory_deep'] is already the candidate model — "
            "nothing to compare. Gate must run BEFORE flipping the flag.")

    # Sample events the production pipeline actually deep-classified —
    # i.e. Haiku-prefilter passers — most recent first for distribution realism.
    events = read_sql(
        "SELECT event_id, title, summary, source, published_at FROM regulatory_events "
        "WHERE classifier_status = 'classified' AND title IS NOT NULL "
        "ORDER BY published_at DESC LIMIT ?", params=[n],
    )
    if events.empty:
        raise RuntimeError("No classified regulatory_events to sample.")
    print(f"Comparing {base_model} vs {CANDIDATE_MODEL} on {len(events)} events...")

    rows = []
    for i, (_, ev) in enumerate(events.iterrows(), 1):
        try:
            base = _classify_with(client, base_model, ev)
            time.sleep(delay)
            cand = _classify_with(client, CANDIDATE_MODEL, ev)
            time.sleep(delay)
        except Exception as e:
            print(f"  [{i}/{len(events)}] API error ({e}) — skipping event")
            continue
        bd, cd = _sector_dirs(base), _sector_dirs(cand)
        common = set(bd) & set(cd)
        rows.append({
            "event_id": ev["event_id"],
            "base_parsed": base is not None,
            "cand_parsed": cand is not None,
            "base_sectors": sorted(bd), "cand_sectors": sorted(cd),
            "n_common_sectors": len(common),
            "n_direction_match": sum(1 for s in common if bd[s] == cd[s]),
            "base_stage": (base or {}).get("stage"),
            "cand_stage": (cand or {}).get("stage"),
        })
        if i % 20 == 0:
            print(f"  [{i}/{len(events)}] done")

    if not rows:
        raise RuntimeError("Every comparison call failed — no verdict (credits?).")

    n_ev = len(rows)
    parse_ok = sum(r["cand_parsed"] for r in rows) / n_ev
    both = [r for r in rows if r["base_parsed"] and r["cand_parsed"]]
    n_common = sum(r["n_common_sectors"] for r in both)
    n_dir = sum(r["n_direction_match"] for r in both)
    dir_agree = (n_dir / n_common) if n_common else 0.0
    # Jaccard on sector-name sets, averaged (informational)
    jac = [
        len(set(r["base_sectors"]) & set(r["cand_sectors"])) /
        max(len(set(r["base_sectors"]) | set(r["cand_sectors"])), 1)
        for r in both
    ]
    sector_jaccard = sum(jac) / len(jac) if jac else 0.0
    stage_agree = (
        sum(1 for r in both if r["base_stage"] == r["cand_stage"]) / len(both)
        if both else 0.0
    )
    verdict = "PASS" if (parse_ok >= GATE and dir_agree >= GATE) else "FAIL"

    report = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "base_model": base_model, "candidate_model": CANDIDATE_MODEL,
        "n_events": n_ev, "gate": GATE,
        "candidate_parse_rate": round(parse_ok, 4),
        "direction_agreement_on_common_sectors": round(dir_agree, 4),
        "n_common_sector_pairs": n_common,
        "sector_name_jaccard_mean": round(sector_jaccard, 4),
        "stage_agreement": round(stage_agree, 4),
        "verdict": verdict,
        "rows": rows,
    }
    out = REPORT_PATH / f"compare_reg_models_{datetime.now():%Y-%m-%d}.json"
    out.write_text(json.dumps(report, indent=2, default=str))

    print("\n=== Agreement report ===")
    print(f"  events compared:        {n_ev}")
    print(f"  candidate parse rate:   {parse_ok:.1%}  (gate ≥{GATE:.0%})")
    print(f"  direction agreement:    {dir_agree:.1%}  on {n_common} matched sector pairs  (gate ≥{GATE:.0%})")
    print(f"  sector-name jaccard:    {sector_jaccard:.1%}  (informational)")
    print(f"  stage agreement:        {stage_agree:.1%}  (informational)")
    print(f"  VERDICT: {verdict}")
    if verdict == "PASS":
        print(f"  → flip hosts.HOSTS['anthropic']['models']['regulatory_deep'] to {CANDIDATE_MODEL} "
              f"(saves ~$0.7/day est.)")
    else:
        print("  → keep Sonnet; do NOT flip the flag. Consider a richer prompt or a bigger sample.")
    print(f"  Full report: {out}")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200, help="events to sample (default 200)")
    ap.add_argument("--delay", type=float, default=0.2, help="sleep between calls")
    args = ap.parse_args()
    main(n=args.n, delay=args.delay)
