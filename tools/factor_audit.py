"""
Alpha Signal v2 — Factor audit sheet (plan 0020, P0).

Read-only. One row per (factor, tier) for every factor in factors.FACTORS, built
from what is stored: the PIT panel (daily_snapshots_pit), the eligibility SQL on
the registry entry, the input tables' newest dates and the evidence table
(pit_ic_by_tier_v2). Nothing is recomputed: this says where to look, the hand
recompute (plan 0020 P1) says whether the formula is right.

Flags, in plain words:
    DEAD            no stock in the tier has a value at the latest anchor
    COVERAGE_DROP   coverage fell below 60% of what it was a year ago
    BELOW_ELIGIBLE  under 90% of the stocks the eligibility SQL names have a value
    CONSTANT        every stock carries the same value
    EDGE_PILE       over 2% of values sit exactly on a pit_range bound
    STALE_INPUT     an input table's newest row is older than its allowance
    NO_EVIDENCE     no backtest row for this tier
    THIN_EVIDENCE   fewer than 20 anchors behind the t-stat
    OLD_EVIDENCE    the evidence row is more than 90 days old
    WRONG_SIGN      wired, and the weight's sign is opposite to the evidence
    BELOW_BAR       wired, and |t| < 1.5 on this tier

Usage:
    python -m tools.factor_audit                 # flagged rows only
    python -m tools.factor_audit --all           # every row
    python -m tools.factor_audit --wired         # the wired (factor, tier) pairs
    python -m tools.factor_audit --md FILE       # full sheet as markdown
    python -m tools.factor_audit --json
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import factors
import tables
from config import PICKABLE_TIERS
from db import read_sql

COVERAGE_DROP = 0.6        # same band as checks/model.py
ELIGIBLE_FLOOR = 0.9
EDGE_SHARE = 0.02
MIN_ANCHORS = 20           # ADR 0049: n ≥ 20 anchors
EVIDENCE_MAX_AGE_DAYS = 90
WIRE_BAR = 1.5
DEFAULT_STALE_DAYS = 45


def _panel():
    """The latest anchor, and the anchors of the month one year before it (old weekly
    anchors carry only the weekly factors, so a single prior anchor is not comparable:
    a factor's year-ago coverage is its best coverage in that window)."""
    latest = read_sql("SELECT MAX(snapshot_date) AS d FROM daily_snapshots_pit").iloc[0]["d"]
    df = read_sql("SELECT * FROM daily_snapshots_pit WHERE snapshot_date = ? OR snapshot_date BETWEEN "
                  "date(?, '-400 days') AND date(?, '-365 days')", params=[latest, latest, latest])
    return latest, df[df["snapshot_date"] == latest], df[df["snapshot_date"] != latest]


def _input_ages(today):
    """{table: days since its newest row}, for every input table with a date column."""
    ages = {}
    for producer in factors.PIT_PRODUCERS:
        for t in factors.producer_tables(producer):
            col = (tables.TABLES.get(t) or {}).get("date_col")
            if t in ages or not col:
                continue
            newest = read_sql(f"SELECT MAX({col}) AS d FROM {t}").iloc[0]["d"]
            ages[t] = (pd.Timestamp(today) - pd.Timestamp(str(newest)[:10])).days if newest else None
    return ages


def _evidence():
    """{(signal, tier): row} — tools.backtest_pit.evidence()."""
    from tools.backtest_pit import evidence
    return {(r.signal, r.cap_tier): r for r in evidence().itertuples()}


def _full_market():
    """{(signal, tier): t} on universe + dead names (tools.backtest_pit.FULL_MARKET rows)."""
    from tools.backtest_pit import FULL_MARKET
    df = read_sql("SELECT signal, cap_tier, t_stat FROM pit_ic_by_tier_v2 WHERE source LIKE ?", params=[FULL_MARKET + "%"])
    return {(r.signal, r.cap_tier): r.t_stat for r in df.itertuples()}


def _eligible(spec):
    try:
        return set(read_sql(spec["eligible_sql"])["sid"])
    except Exception as e:          # a broken eligibility SQL is itself a finding
        return e


def audit():
    latest, now, then = _panel()
    prior = f"{then['snapshot_date'].min()}..{then['snapshot_date'].max()}"
    today = pd.Timestamp.now().normalize()
    ages, evidence, full = _input_ages(today), _evidence(), _full_market()
    weights = factors.SIGNAL_WEIGHTS
    rows = []
    for sid, f in factors.FACTORS.items():
        col = factors.pit_column(sid)
        key = f.get("weight_key", sid)
        inputs = {t: ages.get(t) for t in factors.producer_tables(f.get("producer"))}
        stale = [f"{t} {a}d" for t, a in inputs.items()
                 if a is not None and a > (tables.TABLES.get(t) or {}).get("stale_days", DEFAULT_STALE_DAYS)]
        eligible = _eligible(f["eligibility"]) if "eligibility" in f else None
        for tier in PICKABLE_TIERS:
            w = weights.get(tier, {}).get(key, 0) if not f.get("tiers") or tier in f["tiers"] else 0
            if w and factors.signal_for(key, tier) != sid:
                w = 0
            row = {"factor": sid, "tier": tier, "status": factors.status(sid), "weight": w, "column": col,
                   "cadence": f["cadence"], "flags": []}
            flags = row["flags"]
            t_now = now[now["cap_tier"] == tier]
            if col in now.columns and len(t_now):
                v = pd.to_numeric(t_now[col], errors="coerce")
                t_then = then[then["cap_tier"] == tier]
                cov = v.notna().mean()
                cov_then = t_then[col].notna().groupby(t_then["snapshot_date"]).mean().max() if len(t_then) else float("nan")
                vals = v.dropna()
                row.update(coverage=round(cov, 3), coverage_1y=round(cov_then, 3), distinct=int(vals.nunique()))
                if cov == 0:
                    flags.append("DEAD")
                else:
                    if cov_then > 0 and cov < COVERAGE_DROP * cov_then:
                        flags.append("COVERAGE_DROP")
                    if vals.nunique() <= 1:
                        flags.append("CONSTANT")
                    lo, hi = f.get("pit_range") or (None, None)
                    if lo is not None and vals.nunique() > 3:
                        edge = ((vals - lo).abs() < 1e-9).mean() + ((vals - hi).abs() < 1e-9).mean()
                        row["edge_share"] = round(edge, 3)
                        if edge > EDGE_SHARE:
                            flags.append("EDGE_PILE")
                    row["top_value_share"] = round(vals.value_counts(normalize=True).iloc[0], 3)
                if isinstance(eligible, set):
                    in_tier = set(t_now["sid"]) & eligible
                    have = set(t_now.loc[v.notna(), "sid"])
                    row.update(eligible=len(in_tier), eligible_covered=len(in_tier & have),
                               covered_not_eligible=len(have - eligible))
                    if in_tier and len(in_tier & have) / len(in_tier) < ELIGIBLE_FLOOR and cov > 0:
                        flags.append("BELOW_ELIGIBLE")
            else:
                row["column"] = f"{col} (not in panel: {f['cadence']})"
            if isinstance(eligible, Exception):
                flags.append(f"ELIGIBILITY_SQL_ERROR: {eligible}")
            if stale:
                flags.append("STALE_INPUT")
                row["stale_inputs"] = ", ".join(stale)
            ev = evidence.get((sid, tier))
            if f["cadence"] in ("monthly", "weekly"):
                if ev is None:
                    flags.append("NO_EVIDENCE")
                else:
                    age = (today - pd.Timestamp(ev.computed_at[:10])).days
                    row.update(t_stat=ev.t_stat, mean_ic=ev.mean_ic, anchors=ev.n_periods,
                               evidence_source=ev.source, evidence_age_days=age, t_full_market=full.get((sid, tier)))
                    if (ev.n_periods or 0) < MIN_ANCHORS:
                        flags.append("THIN_EVIDENCE")
                    if age > EVIDENCE_MAX_AGE_DAYS:
                        flags.append("OLD_EVIDENCE")
                    if w and ev.t_stat is not None:
                        if w * ev.t_stat < 0:
                            flags.append("WRONG_SIGN")
                        elif abs(ev.t_stat) < WIRE_BAR:
                            flags.append("BELOW_BAR")
            rows.append(row)
    return {"as_of": latest, "compared_with": prior, "rows": rows}


_COLS = ["factor", "tier", "status", "weight", "coverage", "coverage_1y", "eligible", "eligible_covered",
         "distinct", "t_stat", "t_full_market", "anchors", "evidence_age_days", "flags"]


def _table(rows):
    df = pd.DataFrame(rows).reindex(columns=_COLS)
    df["flags"] = df["flags"].apply(lambda fl: " ".join(x.split(":")[0] for x in fl))
    df["weight"] = df["weight"].apply(lambda w: f"{w:+.2f}" if w else "")
    return df.fillna("")


def _md(df):
    """A DataFrame as a markdown table (pandas' to_markdown needs tabulate, not in the venv)."""
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    return "\n".join(lines + ["| " + " | ".join(map(str, r)) + " |" for r in df.itertuples(index=False)])


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--wired", action="store_true")
    ap.add_argument("--md")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = audit()
    rows = out["rows"]
    if args.json:
        print(json.dumps(out, default=str))
        return
    if args.md:
        counts = pd.Series([x.split(":")[0] for r in rows for x in r["flags"]]).value_counts()
        Path(args.md).write_text(
            f"# Factor audit sheet — panel anchor {out['as_of']} (compared with {out['compared_with']})\n\n"
            f"Generated by `python -m tools.factor_audit --md`. {len(rows)} (factor, tier) rows, "
            f"{sum(1 for r in rows if r['flags'])} flagged.\n\n## Flags\n\n{_md(counts.rename_axis('flag').reset_index(name='rows'))}\n\n"
            f"## Wired\n\n{_md(_table([r for r in rows if r['weight']]))}\n\n"
            f"## All\n\n{_md(_table(rows))}\n")
        print(f"wrote {args.md}")
        return
    show = [r for r in rows if (r["weight"] if args.wired else (args.all or r["flags"]))]
    print(f"Factor audit — panel anchor {out['as_of']}, compared with {out['compared_with']}\n")
    print(_table(show).to_string(index=False))
    print(f"\n{sum(1 for r in rows if r['flags'])} of {len(rows)} (factor, tier) rows flagged.")


if __name__ == "__main__":
    main()
