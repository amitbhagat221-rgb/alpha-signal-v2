"""
Row quarantine with a measured pick impact (plan 0032 stage 2, ADR 0085).

A `data_quarantine` row names a stored row the data-quality audit distrusts: (table, sid, and
optionally a row key). Nothing is deleted or edited. The screener can be run with those rows
masked out of its raw inputs, in memory, and the difference between that ranking and the
stored one is the fault's measured impact: that number goes on the drafted fix order before
anyone fixes anything (`alpha_mcp.org_kinds._draft_fix_order`). The live morning run masks
nothing unless `config.QUARANTINE["apply_live"]` is set (Tier A: it changes the picks).

    python -m tools.quarantine add quarterly_income TEMB,SIGM --rule "0027 #4" --reason "revenue 6,458x Screener"
    python -m tools.quarantine list
    python -m tools.quarantine impact                 # mask every open quarantine, re-rank, diff vs the stored picks
    python -m tools.quarantine release 3 4            # the rows were fixed at the source

The mask: `mask_raw(raw)` drops the quarantined sids' rows from every raw frame whose SQL reads
the quarantined table (`pit.RAW_SQL`), with a row key narrowing it to one period / date when
given; `pit.features_at` calls it when a quarantine is active.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

ACTIVE = None          # {table: {sid: [row_key dict | None, ...]}} masked in this process; None = the stored open rows if apply_live
TOP_N = 30


def now():
    return datetime.now().isoformat(timespec="seconds")


# ─────────────────────────── the register ───────────────────────────

def add(table, sids, rule=None, reason=None, finding_id=None, order_number=None, row_key=None, conn=None):
    """Quarantine `sids`' rows of `table` (every row, or the ones matching `row_key`, a dict of
    column → value). Returns the new row ids. A sid already open under the same rule is not added twice."""
    from db import get_db
    from contextlib import nullcontext
    ids = []
    with (nullcontext(conn) if conn is not None else get_db()) as c:
        for sid in sorted({s for s in sids if s}):
            dup = c.execute("SELECT id FROM data_quarantine WHERE table_name=? AND sid=? AND rule IS ? AND row_key IS ? AND released_at IS NULL",
                            (table, sid, rule, json.dumps(row_key) if row_key else None)).fetchone()
            if dup:
                ids.append(dup[0])
                continue
            cur = c.execute("INSERT INTO data_quarantine (table_name, sid, row_key, rule, finding_id, reason, order_number, quarantined_at) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (table, sid, json.dumps(row_key) if row_key else None, rule, finding_id, reason, order_number, now()))
            ids.append(cur.lastrowid)
    return ids


def release(ids, by="fixed at the source", conn=None):
    from db import get_db
    from contextlib import nullcontext
    with (nullcontext(conn) if conn is not None else get_db()) as c:
        return c.executemany("UPDATE data_quarantine SET released_at=?, released_by=? WHERE id=? AND released_at IS NULL",
                             [(now(), by, int(i)) for i in ids]).rowcount


def open_rows(conn=None):
    """Every open quarantine row, as stored."""
    import db
    sql = "SELECT * FROM data_quarantine WHERE released_at IS NULL ORDER BY id"
    if conn is not None:
        return pd.read_sql_query(sql, conn).to_dict("records")
    return db.rows(sql)


def as_mask(rows):
    """{table: {sid: [row_key | None]}} from register rows."""
    out = {}
    for r in rows:
        out.setdefault(r["table_name"], {}).setdefault(r["sid"], []).append(json.loads(r["row_key"]) if r.get("row_key") else None)
    return out


# ─────────────────────────── the mask ───────────────────────────

_TABLES = re.compile(r"(?:FROM|JOIN)\s+\[?(\w+)\]?", re.I)


def tables_of(raw_key):
    """The legacy tables a pit.RAW_SQL frame reads."""
    import pit
    sql = pit.RAW_SQL.get(raw_key)
    if sql is None:
        return set()
    return set(_TABLES.findall(sql() if callable(sql) else sql))


def mask_frame(df, by_sid):
    """`df` without the rows `by_sid` ({sid: [row_key | None]}) names: a None key drops every row of
    the sid, a key dict drops the rows whose columns equal it (a column the frame lacks is ignored)."""
    if df is None or df.empty or "sid" not in df.columns or not by_sid:
        return df
    drop = pd.Series(False, index=df.index)
    for sid, keys in by_sid.items():
        hit = df["sid"] == sid
        if not hit.any():
            continue
        for key in keys:
            if not key:
                drop |= hit
                continue
            m = hit.copy()
            for col, val in key.items():
                if col in df.columns:
                    m &= df[col].astype(str) == str(val)
            drop |= m
    return df[~drop]


def current_mask():
    """What this process masks: ACTIVE when set, else the open register rows if config says apply them live."""
    if ACTIVE is not None:
        return ACTIVE
    if (getattr(config, "QUARANTINE", None) or {}).get("apply_live"):
        try:
            return as_mask(open_rows())
        except Exception:                                     # noqa: BLE001 — a DB without the table masks nothing
            return {}
    return {}


def mask_raw(raw):
    """The raw dict pit.features_at computes from, with the quarantined rows removed. Returns a
    new dict (frames untouched when nothing applies)."""
    mask = current_mask()
    if not mask:
        return raw
    out = dict(raw)
    for key, df in raw.items():
        by_sid = {}
        for table in tables_of(key):
            for sid, keys in mask.get(table, {}).items():
                by_sid.setdefault(sid, []).extend(keys)
        if by_sid:
            out[key] = mask_frame(df, by_sid)
    return out


# ─────────────────────────── the impact ───────────────────────────

def _rank_frame(scored):
    """[sid, cap_tier, rank, final_score] of the stocks that pass the pick gate, ranked within tier."""
    from scoring import screener
    ok = scored[screener._pick_eligible(scored)].copy()
    ok["rank"] = ok.groupby("cap_tier")["final_score"].rank(ascending=False, method="first").astype("Int64")
    return ok[["sid", "cap_tier", "rank", "final_score"]]


def rerank(mask):
    """Today's ranking with `mask` applied in memory: the screener's own load + score, no write."""
    global ACTIVE
    from scoring import screener
    ACTIVE = mask
    try:
        df, _prices = screener._load_signals(return_prices=True)
        return _rank_frame(screener.score_universe(df))
    finally:
        ACTIVE = None


def stored_ranking(pick_date=None):
    import db
    where = "pick_date = ?" if pick_date else "pick_date = (SELECT MAX(pick_date) FROM daily_picks)"
    return db.read_sql(f"SELECT sid, cap_tier, rank, final_score, pick_date FROM daily_picks WHERE {where}", [pick_date] if pick_date else None)


def diff(before, after, mask, top_n=TOP_N):
    """The pick diff: per tier, the top-N overlap (pit_replay's measure) and, for every quarantined
    stock, its rank before and after. `before` / `after`: [sid, cap_tier, rank, final_score]."""
    from tools.pit_replay import _classify, _diff_tier
    tiers = {}
    for tier in config.PICKABLE_TIERS:
        b = before[(before["cap_tier"] == tier) & (before["rank"] <= top_n)]
        a = after[(after["cap_tier"] == tier) & (after["rank"] <= top_n)]
        if b.empty and a.empty:
            continue
        tiers[tier] = _diff_tier(b, a)
    sids = sorted({s for by in mask.values() for s in by})
    bi, ai = before.set_index("sid"), after.set_index("sid")
    moves = []
    for s in sids:
        rb = int(bi.loc[s, "rank"]) if s in bi.index and pd.notna(bi.loc[s, "rank"]) else None
        ra = int(ai.loc[s, "rank"]) if s in ai.index and pd.notna(ai.loc[s, "rank"]) else None
        moves.append({"sid": s, "tier": (bi.loc[s, "cap_tier"] if s in bi.index else ai.loc[s, "cap_tier"] if s in ai.index else None),
                      "rank_before": rb, "rank_after": ra, "in_top": {"before": bool(rb and rb <= top_n), "after": bool(ra and ra <= top_n)}})
    changed = sum(1 for m in moves if m["rank_before"] != m["rank_after"])
    return {"verdict": _classify(tiers) if tiers else "PASS", "top_n": top_n, "tiers": tiers, "quarantined": len(sids),
            "moved": changed, "top_changes": sum(1 for m in moves if m["in_top"]["before"] != m["in_top"]["after"]),
            "moves": moves, "measured_at": now()}


def impact(mask=None, top_n=TOP_N, rerank_fn=None):
    """Measure a quarantine: mask the rows, re-rank, diff against the stored picks of the latest
    date. `mask` defaults to the open register rows. `rerank_fn` is for tests."""
    mask = as_mask(open_rows()) if mask is None else mask
    if not mask:
        return {"verdict": "PASS", "quarantined": 0, "moved": 0, "top_changes": 0, "tiers": {}, "moves": [], "top_n": top_n,
                "measured_at": now(), "note": "nothing quarantined"}
    before = stored_ranking()
    after = (rerank_fn or rerank)(mask)
    out = diff(before, after, mask, top_n)
    out["pick_date"] = str(before["pick_date"].iloc[0]) if not before.empty else None
    return out


def summary(imp):
    """One line for an order item or a memo."""
    if not imp.get("quarantined"):
        return "pick diff: nothing to mask"
    tiers = ", ".join(f"{t} top-{imp['top_n']} overlap {d['jaccard']:.0%}" for t, d in (imp.get("tiers") or {}).items())
    return (f"pick diff ({imp['verdict']}): {imp['quarantined']} stocks masked, {imp['moved']} changed rank, "
            f"{imp['top_changes']} entered or left a top-{imp['top_n']}; {tiers}")


# ─────────────────────────── findings → rows ───────────────────────────

def sids_from_sample(sample, known):
    """The stock ids a finding's sample names (`GROUP_CONCAT` fragments such as 'TEMB 2026-10-03; …'):
    every token that is a known sid, in order, once."""
    if not sample:
        return []
    out, seen = [], set()
    for tok in re.split(r"[\s,;:|()]+", str(sample)):
        if tok in known and tok not in seen:
            out.append(tok)
            seen.add(tok)
    return out


def main(argv=None):
    import db
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("table")
    a.add_argument("sids", help="comma-separated")
    a.add_argument("--rule")
    a.add_argument("--reason")
    a.add_argument("--order", type=int)
    sub.add_parser("list")
    i = sub.add_parser("impact")
    i.add_argument("--top-n", type=int, default=TOP_N)
    r = sub.add_parser("release")
    r.add_argument("ids", nargs="+", type=int)
    args = ap.parse_args(argv)
    if args.cmd == "add":
        print("quarantined:", add(args.table, args.sids.split(","), rule=args.rule, reason=args.reason, order_number=args.order))
    elif args.cmd == "list":
        rows = open_rows()
        print(pd.DataFrame(rows).to_string(index=False) if rows else "no open quarantine")
    elif args.cmd == "impact":
        out = impact(top_n=args.top_n)
        print(summary(out))
        for m in out["moves"]:
            print(f"  {m['sid']:8s} {m['tier'] or '?':6s} rank {m['rank_before']} → {m['rank_after']}")
    elif args.cmd == "release":
        print("released:", release(args.ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
