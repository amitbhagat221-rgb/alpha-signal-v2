"""
PIT replay validator — Phase E (Plan 0005), Slice A.

The "prove the pipeline still works" guarantee. Freeze the inputs + outputs of
the live scoring pipeline at a point in time, then re-run on demand to detect
silent drift from code changes (a producer rewrite, a scoring tweak, a renamed
column). Catches the HALC class of bug: today's picks look fine, but unbeknown
to anyone the screener now produces different ranks than it did yesterday.

USE
    python -m tools.pit_replay freeze                # snapshot today's pipeline
    python -m tools.pit_replay replay                # replay latest frozen
    python -m tools.pit_replay replay --date 2026-05-25
    python -m tools.pit_replay list                  # show frozen dates + status

WHAT'S CAPTURED PER FREEZE
    pit_replay_snapshots — one row per sid:
      • output: rank, final_score, cap_tier, plus ALL *_adj contributions
      • inputs: every signal that fed score_universe (f_score, accruals, consensus,
                promoter, forensic.penalty, smart_money, momentum, earnings_yield,
                book_to_price, weight_coverage, eligible_coverage, price_rows,
                fundamental_coverage)

REPLAY = LOAD frozen inputs → call score_universe(df) → diff against frozen output.
Pure function on captured df; no live DB reads (except eligibility constants).
That makes the test 100% deterministic — any drift is real code drift.

DRIFT POLICY (PASS / WARN / FAIL)
    For each cap_tier:
      • Top-30 jaccard overlap — 1.0 perfect, <0.95 WARN, <0.85 FAIL
      • Max rank shift for shared sids — ≤2 OK, ≤5 WARN, >5 FAIL
      • Max abs(score diff) — ≤2% OK, ≤5% WARN, >5% FAIL
    Overall verdict = worst of the three across tiers.
"""

import argparse
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import get_db, read_sql

# Signal columns that score_universe reads. Order matters — must match
# what _load_signals() produces so a frozen df can be rebuilt and re-scored.
INPUT_COLS = [
    "sid", "ticker", "name", "sector", "cap_tier",
    "f_score", "accruals", "consensus", "promoter", "penalty",
    "smart_money", "mom_6m", "mom_12m", "earnings_yield", "book_to_price",
    "price_rows", "quarters_present", "fundamental_coverage",
]

# Output columns we persist per pick.
OUTPUT_COLS = [
    "rank", "final_score", "base_score", "penalty",
    "weight_coverage", "eligible_coverage",
]


def _git_sha() -> str:
    """Short HEAD sha if we're in a git repo; '?' otherwise."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, cwd=Path(__file__).resolve().parent.parent
        ).decode().strip()
    except Exception:
        return "?"


def _ensure_schema():
    """Create pit_replay_snapshots if absent."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pit_replay_snapshots (
                snapshot_date    TEXT NOT NULL,
                sid              TEXT NOT NULL,
                rank             INTEGER,
                final_score      REAL,
                cap_tier         TEXT,
                output_json      TEXT,   -- full row's *_adj, base_score, penalty, etc
                inputs_json      TEXT,   -- frozen signal-table values
                frozen_at        TEXT NOT NULL,
                frozen_by_commit TEXT,
                PRIMARY KEY (snapshot_date, sid)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pit_replay_date ON pit_replay_snapshots(snapshot_date)")


def _run_live_pipeline():
    """Call screener._load_signals() + score_universe(). Returns (input_df, scored_df).
    No daily_picks write — we want the in-memory result, not the DB side effect."""
    from scoring import screener
    input_df = screener._load_signals()
    scored_df = screener.score_universe(input_df.copy())
    return input_df, scored_df


# ─── Historical reconstruction ───
# For pre-today freezes we don't have signal tables (piotroski_scores, accruals_scores, etc)
# as they were on that date — only the raw inputs in daily_snapshots_pit. We map raw cols
# to the score_universe input shape; composites we can't reconstruct (accruals_signal,
# promoter_signal, forensic.penalty, smart_money) get NaN and score_universe normalizes
# by the weight that *did* contribute. This is a known coverage gap — the validator catches
# score_universe code drift but not signal-composite drift for historical dates. Production
# (today's) freeze uses the full pipeline and has no such gap.
PIT_TO_INPUT_COLS = {
    "piotroski_f": "f_score",
    "mom_6m": "mom_6m",
    "mom_12m": "mom_12m",
    "earnings_yield": "earnings_yield",
    "book_to_price": "book_to_price",
    "consensus_signal_combined": "consensus",
    # Plan 0005 Phase E "full fix" (2026-05-25) — composite signals now persisted
    # in daily_snapshots_pit by reconstruct_pit, so historical replays cover all
    # 8 screener inputs end-to-end.
    "accruals_signal": "accruals",
    "promoter_signal": "promoter",
    "forensic_penalty": "penalty",
    "smart_money_score": "smart_money",
}


def _run_historical_pipeline(snapshot_date: str):
    """Build input_df from daily_snapshots_pit for the given date, run score_universe."""
    from scoring import screener
    cols = list(PIT_TO_INPUT_COLS.keys())
    pit_df = read_sql(
        f"""SELECT sid, cap_tier, {', '.join(cols)}
            FROM daily_snapshots_pit WHERE snapshot_date = ?""",
        params=[snapshot_date],
    )
    if pit_df.empty:
        return None, None
    # Join in ticker/name/sector from stocks (universe-static, OK to use current)
    meta = read_sql("SELECT sid, ticker, name, sector FROM stocks")
    df = pit_df.merge(meta, on="sid", how="left").rename(columns=PIT_TO_INPUT_COLS)
    # Smart_money is persisted on 0-100 scale; screener._load_signals divides by 100.
    if "smart_money" in df.columns:
        df["smart_money"] = pd.to_numeric(df["smart_money"], errors="coerce") / 100.0
    # Defensive fill — if reconstruct_pit hasn't backfilled a composite for this
    # date yet (or signal was missing), score_universe normalizes by weight.
    for col in ("accruals", "promoter", "penalty", "smart_money", "consensus"):
        if col not in df.columns:
            df[col] = pd.NA
    # price_rows / quarters_present / fundamental_coverage aren't in PIT either, but
    # score_universe needs them only for COVERAGE math (not scoring). Stub at the live
    # values so the eligibility math doesn't crash.
    df["price_rows"] = 252  # ≥ MIN_PRICE_ROWS=60 — historical stocks all had trading history
    df["quarters_present"] = 8
    df["fundamental_coverage"] = 1.0
    input_df = df[[
        "sid", "ticker", "name", "sector", "cap_tier",
        "f_score", "accruals", "consensus", "promoter", "penalty",
        "smart_money", "mom_6m", "mom_12m", "earnings_yield", "book_to_price",
        "price_rows", "quarters_present", "fundamental_coverage",
    ]]
    scored_df = screener.score_universe(input_df.copy())
    return input_df, scored_df


def freeze(snapshot_date: str | None = None, historical: bool = False) -> int:
    """Compute pipeline output and persist input+output snapshot.
    For today: uses live pipeline (full composite signals).
    For historical: uses daily_snapshots_pit raw cols (NaN for un-reconstructable composites).
    Returns rows written."""
    _ensure_schema()
    snapshot_date = snapshot_date or date.today().isoformat()
    is_historical = historical or snapshot_date < date.today().isoformat()
    print(f"Freezing pipeline snapshot for {snapshot_date} ({'historical' if is_historical else 'live'}) ...")

    if is_historical:
        input_df, scored_df = _run_historical_pipeline(snapshot_date)
        if input_df is None:
            print(f"  No daily_snapshots_pit rows for {snapshot_date}.")
            return 0
    else:
        input_df, scored_df = _run_live_pipeline()
    if scored_df.empty:
        print("  scored_df empty — nothing to freeze.")
        return 0

    frozen_at = datetime.now().isoformat(timespec="seconds")
    sha = _git_sha()

    # Build the per-sid rows. INPUT side comes from input_df; OUTPUT side from scored_df.
    # Keep sid as a column (not index) so it serializes; lookup via to_dict().
    inp_by_sid = {row["sid"]: row.to_dict() for _, row in input_df.iterrows()}
    rows = []
    for _, r in scored_df.iterrows():
        sid = r["sid"]
        inp = {}
        src = inp_by_sid.get(sid, {})
        for c in INPUT_COLS:
            v = src.get(c)
            inp[c] = None if (v is None or (isinstance(v, float) and pd.isna(v))) else (v.item() if hasattr(v, "item") else v)
        # Outputs: pull every numeric field score_universe set.
        out = {}
        for c in OUTPUT_COLS:
            v = r.get(c)
            out[c] = None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)
        # Also stash every *_adj column that's present (per-signal contribution).
        for c in scored_df.columns:
            if c.endswith("_adj") and c not in out:
                v = r[c]
                out[c] = None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)

        rows.append((
            snapshot_date, sid,
            int(r["rank"]) if pd.notna(r.get("rank")) else None,
            float(r["final_score"]) if pd.notna(r.get("final_score")) else None,
            r.get("cap_tier"),
            json.dumps(out, default=str),
            json.dumps(inp, default=str),
            frozen_at, sha,
        ))

    with get_db() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO pit_replay_snapshots
               (snapshot_date, sid, rank, final_score, cap_tier,
                output_json, inputs_json, frozen_at, frozen_by_commit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )

    print(f"  Wrote {len(rows)} rows to pit_replay_snapshots ({snapshot_date}, sha {sha})")
    return len(rows)


def _load_frozen(snapshot_date: str):
    """Return (input_df, output_df) reconstructed from the frozen snapshot."""
    df = read_sql(
        "SELECT * FROM pit_replay_snapshots WHERE snapshot_date = ?",
        params=[snapshot_date],
    )
    if df.empty:
        return None, None
    inp_records = [json.loads(s) for s in df["inputs_json"]]
    out_records = [json.loads(s) for s in df["output_json"]]
    inp_df = pd.DataFrame(inp_records)
    out_df = pd.DataFrame(out_records)
    out_df["sid"] = df["sid"].values
    out_df["rank"] = df["rank"].values
    out_df["final_score"] = df["final_score"].values
    out_df["cap_tier"] = df["cap_tier"].values
    return inp_df, out_df


def _diff_tier(frozen_top: pd.DataFrame, current_top: pd.DataFrame) -> dict:
    """Compute jaccard, max rank shift, max score diff between two top-N pick frames."""
    fset = set(frozen_top["sid"])
    cset = set(current_top["sid"])
    union = fset | cset
    inter = fset & cset
    jaccard = len(inter) / len(union) if union else 1.0
    shared = list(inter)
    if shared:
        f_idx = frozen_top.set_index("sid").loc[shared]
        c_idx = current_top.set_index("sid").loc[shared]
        max_rank_shift = int((f_idx["rank"] - c_idx["rank"]).abs().max())
        score_diffs = (f_idx["final_score"] - c_idx["final_score"]).abs()
        denom = f_idx["final_score"].abs().clip(lower=1e-9)
        max_score_pct = float((score_diffs / denom).max() * 100)
    else:
        max_rank_shift = None
        max_score_pct = None
    return {
        "frozen_n": len(fset),
        "current_n": len(cset),
        "shared": len(inter),
        "jaccard": round(jaccard, 4),
        "max_rank_shift": max_rank_shift,
        "max_score_diff_pct": None if max_score_pct is None else round(max_score_pct, 2),
    }


def _classify(diffs: dict[str, dict]) -> str:
    """Combine per-tier diffs into a single verdict."""
    verdicts = []
    for tier, d in diffs.items():
        if d["jaccard"] < 0.85:
            verdicts.append("FAIL")
        elif d["jaccard"] < 0.95:
            verdicts.append("WARN")
        elif d["max_rank_shift"] is not None and d["max_rank_shift"] > 5:
            verdicts.append("FAIL")
        elif d["max_rank_shift"] is not None and d["max_rank_shift"] > 2:
            verdicts.append("WARN")
        elif d["max_score_diff_pct"] is not None and d["max_score_diff_pct"] > 5:
            verdicts.append("FAIL")
        elif d["max_score_diff_pct"] is not None and d["max_score_diff_pct"] > 2:
            verdicts.append("WARN")
        else:
            verdicts.append("PASS")
    if "FAIL" in verdicts: return "FAIL"
    if "WARN" in verdicts: return "WARN"
    return "PASS"


def replay(snapshot_date: str | None = None, top_n: int = 30) -> int:
    """Replay a frozen snapshot — recompute via current code, compare. Returns 0 on PASS."""
    _ensure_schema()
    if snapshot_date is None:
        last = read_sql("SELECT MAX(snapshot_date) AS d FROM pit_replay_snapshots")
        snapshot_date = last.iloc[0]["d"] if not last.empty else None
        if not snapshot_date:
            print("No frozen snapshots. Run `python -m tools.pit_replay freeze` first.")
            return 1

    frozen_inp, frozen_out = _load_frozen(snapshot_date)
    if frozen_inp is None:
        print(f"No frozen snapshot for {snapshot_date}.")
        return 1

    print(f"Replaying snapshot {snapshot_date} (top-{top_n} per tier)...")
    from scoring import screener

    # Rebuild df in the shape score_universe() expects.
    df = frozen_inp.copy()
    # Ensure dtype for object cols that came in as Python None from JSON (smart_money etc).
    for c in ("accruals", "promoter", "penalty", "smart_money", "consensus"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    current_scored = screener.score_universe(df)

    # Per-tier top-N comparison. Coerce rank/final_score to numeric — frozen rows may
    # have None for rank when no signals contributed (object dtype from JSON breaks nsmallest).
    frozen_out["rank"] = pd.to_numeric(frozen_out["rank"], errors="coerce")
    frozen_out["final_score"] = pd.to_numeric(frozen_out["final_score"], errors="coerce")
    current_scored["rank"] = pd.to_numeric(current_scored["rank"], errors="coerce")
    current_scored["final_score"] = pd.to_numeric(current_scored["final_score"], errors="coerce")
    diffs = {}
    for tier in ["LARGE", "MID", "SMALL"]:
        f_top = (frozen_out[(frozen_out["cap_tier"] == tier) & frozen_out["rank"].notna()]
                 .nsmallest(top_n, "rank")[["sid", "rank", "final_score"]])
        c_top = (current_scored[(current_scored["cap_tier"] == tier) & current_scored["rank"].notna()]
                 .nsmallest(top_n, "rank")[["sid", "rank", "final_score"]])
        diffs[tier] = _diff_tier(f_top, c_top)

    verdict = _classify(diffs)

    print(f"\n  Verdict: {verdict}   (sha frozen: {frozen_out['cap_tier'].iloc[0] and _git_sha_at_freeze(snapshot_date)})")
    for tier, d in diffs.items():
        print(f"  {tier:6s}  jaccard={d['jaccard']:.3f}  "
              f"shared={d['shared']}/{d['frozen_n']}  "
              f"max_rank_shift={d['max_rank_shift']}  "
              f"max_score_diff={d['max_score_diff_pct']}%")

    # Show specific changes if WARN/FAIL
    if verdict != "PASS":
        print(f"\n  Diff detail — sids that moved in/out of top-{top_n}:")
        for tier in ["LARGE", "MID", "SMALL"]:
            f_top = frozen_out[frozen_out["cap_tier"] == tier].nsmallest(top_n, "rank")
            c_top = current_scored[current_scored["cap_tier"] == tier].nsmallest(top_n, "rank")
            dropped = set(f_top["sid"]) - set(c_top["sid"])
            added = set(c_top["sid"]) - set(f_top["sid"])
            if dropped or added:
                print(f"    {tier}: dropped {sorted(dropped)[:5]}  added {sorted(added)[:5]}")

    return 0 if verdict == "PASS" else (1 if verdict == "WARN" else 2)


def _git_sha_at_freeze(snapshot_date: str) -> str:
    r = read_sql(
        "SELECT frozen_by_commit FROM pit_replay_snapshots WHERE snapshot_date = ? LIMIT 1",
        params=[snapshot_date],
    )
    return r.iloc[0]["frozen_by_commit"] if not r.empty else "?"


def replay_all(top_n: int = 30) -> int:
    """Replay every frozen snapshot. Returns 0 if all PASS, else worst exit code.
    Used by the pre-push git hook and (eventually) nightly CI."""
    _ensure_schema()
    dates = read_sql(
        "SELECT DISTINCT snapshot_date FROM pit_replay_snapshots ORDER BY snapshot_date"
    )["snapshot_date"].tolist()
    if not dates:
        print("No frozen snapshots to replay.")
        return 0
    worst = 0
    summary = []
    for d in dates:
        rc = replay(snapshot_date=d, top_n=top_n)
        summary.append((d, rc))
        worst = max(worst, rc)
    print("\n══════ Multi-date summary ══════")
    for d, rc in summary:
        label = "PASS" if rc == 0 else ("WARN" if rc == 1 else "FAIL")
        print(f"  {d}  {label}")
    print(f"Overall: {'PASS' if worst==0 else ('WARN' if worst==1 else 'FAIL')}")
    return worst


def replay_status():
    """Return dict summary for cockpit tile / CI integration.
    Runs replay against the most recent frozen snapshot (lightweight, ~10s)."""
    _ensure_schema()
    last = read_sql("SELECT MAX(snapshot_date) AS d FROM pit_replay_snapshots")
    if last.empty or last.iloc[0]["d"] is None:
        return {"verdict": "NEVER_RUN", "snapshot_date": None, "frozen_at": None, "diffs": {}}
    d = last.iloc[0]["d"]
    # Run silently and capture the diff
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = replay(snapshot_date=d)
    out = buf.getvalue()
    verdict = "PASS" if rc == 0 else ("WARN" if rc == 1 else "FAIL")
    meta = read_sql(
        "SELECT MIN(frozen_at) frozen_at, MIN(frozen_by_commit) sha, COUNT(DISTINCT snapshot_date) n_frozen "
        "FROM pit_replay_snapshots"
    ).iloc[0].to_dict()
    return {
        "verdict": verdict,
        "snapshot_date": d,
        "frozen_at": meta.get("frozen_at"),
        "frozen_by_commit": meta.get("sha"),
        "n_frozen_dates": int(meta.get("n_frozen") or 0),
        "raw_output": out,
    }


def list_snapshots():
    """Print all frozen dates with row counts + commit sha."""
    _ensure_schema()
    df = read_sql("""
        SELECT snapshot_date,
               COUNT(*) AS n_rows,
               COUNT(DISTINCT cap_tier) AS n_tiers,
               MIN(frozen_at) AS frozen_at,
               MIN(frozen_by_commit) AS sha
        FROM pit_replay_snapshots
        GROUP BY snapshot_date
        ORDER BY snapshot_date DESC
    """)
    if df.empty:
        print("No frozen snapshots yet.")
        return
    print(df.to_string(index=False))


def main():
    p = argparse.ArgumentParser(description="PIT replay validator (Plan 0005 Phase E)")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_freeze = sub.add_parser("freeze", help="Persist today's pipeline snapshot")
    p_freeze.add_argument("--date", help="Override snapshot date (default: today)")
    p_replay = sub.add_parser("replay", help="Recompute + diff vs a frozen snapshot")
    p_replay.add_argument("--date", help="Snapshot date (default: latest frozen)")
    p_replay.add_argument("--top-n", type=int, default=30, help="Top N picks per tier to diff")
    p_all = sub.add_parser("replay-all", help="Replay every frozen snapshot (CI mode)")
    p_all.add_argument("--top-n", type=int, default=30)
    sub.add_parser("list", help="List frozen snapshots")
    args = p.parse_args()

    if args.cmd == "freeze":
        freeze(snapshot_date=args.date)
    elif args.cmd == "replay":
        sys.exit(replay(snapshot_date=args.date, top_n=args.top_n))
    elif args.cmd == "replay-all":
        sys.exit(replay_all(top_n=args.top_n))
    elif args.cmd == "list":
        list_snapshots()


if __name__ == "__main__":
    main()
