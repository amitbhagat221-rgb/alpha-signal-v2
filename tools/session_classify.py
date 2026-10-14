"""
Alpha Signal v2 — classify regulatory/news backlogs WITHOUT the Anthropic API.

The LLM work is done out-of-process (Claude Code subagents today, a Routine +
MCP claim/submit later) on the Claude subscription. This module is the
deterministic half: export claimable chunks, then validate results and write
them through the classifiers' OWN save paths — same row shapes, same dedup,
same guardrails as the API pipeline.

  python -m tools.session_classify export-reg   DIR [--days 60] [--chunk 200]
  python -m tools.session_classify export-news  DIR [--days 7]  [--chunk 200]
  python -m tools.session_classify export-calib DIR [--n 40]
  python -m tools.session_classify score-calib  DIR
  python -m tools.session_classify ingest-reg   DIR
  python -m tools.session_classify ingest-news  DIR
  python -m tools.session_classify rollback-reg DIR
  python -m tools.session_classify export-conflicts DIR [--days 60] [--since ISO]
  python -m tools.session_classify apply-reconcile  DIR
  python -m tools.session_classify rollback-reconcile DIR

Chunks: DIR/chunk_NNN.in.jsonl → worker writes DIR/chunk_NNN.out.jsonl (one
JSON object per input line, keyed by "id"). Missing/invalid ids stay claimable.

Regulatory status mapping: is_regulatory=false → 'haiku_rejected' (the terminal
reject state _dedup_lookup + health.py already understand); true →
'classified' (+ signals). Duplicate title_hash rows copy the representative's
verdict via _reuse_classification_existing. Every touched event is logged to
DIR/manifest.tsv (event_id, prev_status) so rollback-reg can undo it.

Reconciliation: syndicated copies of one story get near-identical (not
identical) headlines, so title_hash dedup misses them and independent workers
can code the same story×sector with opposite directions — which cancel inside
signals/regulatory's per-sector average. export-conflicts clusters headlines
(token Jaccard ≥ 0.5 within 3 days) and emits only clusters where a sector has
both +1 and -1; a worker returns one direction per cluster×sector (or null =
genuinely different stories, leave as-is); apply-reconcile rewrites
regulatory_signals.direction for that cluster×sector, logging old values to
DIR/reconcile_manifest.tsv.
"""
import argparse
import collections
import datetime as dt
import json
import random
import re
import sys
from pathlib import Path

from db import read_sql, get_db, log_llm_usage
from sources import regulatory_classifier as rc
from sources import news_classifier as nc

SESSION_MODEL = "claude-sonnet-5"  # the subagent model; ledger label only

VALID_SECTORS = {
    "Communication Services", "Consumer Discretionary", "Consumer Staples", "Energy",
    "Financials", "Health Care", "Industrials", "Information Technology", "Materials",
    "Real Estate", "Utilities",
}
STAGES = {"discussion", "draft", "notification", "implementation", "enforcement"}
MAGNITUDES = {"minor", "moderate", "major"}
HORIZONS = {"immediate", "3mo", "6mo", "12mo"}
CONFIDENCES = {"high", "medium", "low"}
CLAIMABLE = ("pending", "haiku_passed_sonnet_failed")


def _write_chunks(out_dir, items, chunk):
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for i in range(0, len(items), chunk):
        path = out_dir / f"chunk_{i // chunk:03d}.in.jsonl"
        with path.open("w") as f:
            for it in items[i:i + chunk]:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        n += 1
    return n


def _read_results(out_dir):
    """{id: result} across every chunk_*.out.jsonl; bad lines are counted, not fatal."""
    res, bad = {}, 0
    for p in sorted(out_dir.glob("chunk_*.out.jsonl")):
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                res[str(obj["id"])] = obj
            except (json.JSONDecodeError, KeyError, TypeError):
                bad += 1
    return res, bad


# ── Regulatory ──

def _reg_item(ev):
    return {"id": ev["event_id"], "title": str(ev["title"])[:300],
            "summary": str(ev["summary"] or "")[:1000],
            "source": ev["source"], "published_at": ev["published_at"]}


def export_reg(out_dir, days, chunk):
    rows = read_sql(
        f"SELECT event_id, title, summary, source, published_at, classifier_status "
        f"FROM regulatory_events WHERE classifier_status IN {CLAIMABLE} "
        f"AND title IS NOT NULL AND length(title) > 10 "
        f"AND date(published_at) >= date('now', ?) ORDER BY published_at DESC",
        params=[f"-{days} days"],
    )
    groups, reps = {}, []
    for _, ev in rows.iterrows():
        th = rc._title_hash(ev["title"])
        if th in groups:
            groups[th]["dups"].append(ev["event_id"])
            continue
        groups[th] = {"rep": ev["event_id"], "dups": []}
        reps.append(_reg_item(ev))
    (out_dir).mkdir(parents=True, exist_ok=True)
    (out_dir / "groups.json").write_text(json.dumps(groups))
    n = _write_chunks(out_dir, reps, chunk)
    print(f"export-reg: {len(rows)} claimable rows (last {days}d) → {len(reps)} unique "
          f"headlines in {n} chunks of ≤{chunk} → {out_dir}")


def validate_reg(obj):
    """Result object → (is_regulatory, classification dict) or raise ValueError."""
    if not isinstance(obj.get("is_regulatory"), bool):
        raise ValueError("is_regulatory must be true/false")
    if not obj["is_regulatory"]:
        return False, None
    stage = obj.get("stage")
    if stage is not None and stage not in STAGES:
        raise ValueError(f"bad stage {stage!r}")
    sectors = []
    for s in obj.get("sectors_affected") or []:
        if (s.get("sector") not in VALID_SECTORS or s.get("direction") not in (1, -1)
                or s.get("magnitude") not in MAGNITUDES
                or s.get("time_horizon") not in HORIZONS
                or s.get("confidence") not in CONFIDENCES):
            raise ValueError(f"bad sector entry {s!r}")
        sectors.append({**s, "reasoning": str(s.get("reasoning") or "")[:300]})
    if len({s["sector"] for s in sectors}) != len(sectors):
        raise ValueError("duplicate sector")
    return True, {"stage": stage, "ministry": obj.get("ministry"), "sectors_affected": sectors}


def _status(event_id):
    r = read_sql("SELECT classifier_status FROM regulatory_events WHERE event_id = ?",
                 params=[event_id])
    return None if r.empty else r.iloc[0]["classifier_status"]


def ingest_reg(out_dir):
    groups = json.loads((out_dir / "groups.json").read_text())
    by_rep = {g["rep"]: (th, g["dups"]) for th, g in groups.items()}
    results, bad_lines = _read_results(out_dir)
    manifest = (out_dir / "manifest.tsv").open("a")
    stats = {"classified": 0, "rejected": 0, "signals": 0, "dups": 0,
             "invalid": 0, "skipped": 0, "unknown_id": 0}
    invalid_log = []
    for rep, obj in results.items():
        if rep not in by_rep:
            stats["unknown_id"] += 1
            continue
        th, dups = by_rep[rep]
        prev = _status(rep)
        if prev not in CLAIMABLE:  # already done (re-ingest or pipeline got there first)
            stats["skipped"] += 1
            continue
        try:
            is_reg, cls = validate_reg(obj)
        except ValueError as e:
            stats["invalid"] += 1
            invalid_log.append(f"{rep}\t{e}")
            continue
        manifest.write(f"{rep}\t{prev}\n")
        if is_reg:
            stats["signals"] += rc._save_signals_for_event(rep, cls)
            rc._mark_classified(rep, cls.get("ministry"))
            with get_db() as conn:
                conn.execute("UPDATE regulatory_events SET title_hash = ? WHERE event_id = ?",
                             (th, rep))
            status = "classified"
            stats["classified"] += 1
        else:
            rc._bulk_mark([(rep, th)], "haiku_rejected")
            status = "haiku_rejected"
            stats["rejected"] += 1
        for d in dups:
            dprev = _status(d)
            if dprev in CLAIMABLE:
                manifest.write(f"{d}\t{dprev}\n")
                stats["signals"] += rc._reuse_classification_existing(d, th, status, rep)
                stats["dups"] += 1
    manifest.close()
    if invalid_log:
        (out_dir / "invalid.tsv").write_text("\n".join(invalid_log) + "\n")
    n = stats["classified"] + stats["rejected"]
    if n:
        log_llm_usage("classify_regulatory_deep", SESSION_MODEL,
                      {"input_tokens": 0, "output_tokens": 0}, mode="session", n_calls=n)
    print(f"ingest-reg: {stats} · unparseable lines={bad_lines}")
    return stats


def rollback_reg(out_dir):
    rows = [l.split("\t") for l in (out_dir / "manifest.tsv").read_text().splitlines() if l]
    with get_db() as conn:
        for eid, prev in rows:
            conn.execute("DELETE FROM regulatory_signals WHERE event_id = ?", (eid,))
            conn.execute("UPDATE regulatory_events SET classifier_status = ? WHERE event_id = ?",
                         (prev, eid))
    print(f"rollback-reg: restored {len(rows)} events")


# ── Calibration (vs prior API-Sonnet/Haiku verdicts) ──

def export_calib(out_dir, n):
    pos = read_sql(
        "SELECT e.event_id, e.title, e.summary, e.source, e.published_at FROM regulatory_events e "
        "WHERE e.classifier_status = 'classified' AND e.classifier_processed_at < '2026-08-25' "
        "AND EXISTS (SELECT 1 FROM regulatory_signals s WHERE s.event_id = e.event_id) "
        "AND date(e.published_at) >= '2026-06-01' ORDER BY random() LIMIT ?", params=[n])
    neg = read_sql(
        "SELECT event_id, title, summary, source, published_at FROM regulatory_events "
        "WHERE classifier_status = 'haiku_rejected' AND classifier_processed_at < '2026-08-25' "
        "AND date(published_at) >= '2026-06-01' ORDER BY random() LIMIT ?", params=[n])
    items = [_reg_item(ev) for _, ev in pos.iterrows()] + [_reg_item(ev) for _, ev in neg.iterrows()]
    random.Random(7).shuffle(items)
    _write_chunks(out_dir, items, len(items))
    print(f"export-calib: {len(pos)} prior-classified + {len(neg)} prior-rejected → {out_dir}")


def score_calib(out_dir):
    results, bad = _read_results(out_dir)
    ids = list(results)
    ph = ",".join("?" * len(ids))
    truth = read_sql(f"SELECT event_id, classifier_status FROM regulatory_events "
                     f"WHERE event_id IN ({ph})", params=ids).set_index("event_id")["classifier_status"]
    sig = read_sql(f"SELECT event_id, sector, direction FROM regulatory_signals "
                   f"WHERE event_id IN ({ph})", params=ids)
    agree = n = invalid = dir_ok = dir_n = pos_recall = pos_n = neg_ok = neg_n = 0
    for eid, obj in results.items():
        try:
            is_reg, cls = validate_reg(obj)
        except ValueError:
            invalid += 1
            continue
        was_reg = truth.get(eid) == "classified"
        n += 1
        agree += is_reg == was_reg
        if was_reg:
            pos_n += 1
            pos_recall += is_reg
        else:
            neg_n += 1
            neg_ok += not is_reg
        if was_reg and is_reg:
            prior = dict(sig[sig.event_id == eid][["sector", "direction"]].values)
            for s in cls["sectors_affected"]:
                if s["sector"] in prior:
                    dir_n += 1
                    dir_ok += int(prior[s["sector"]]) == s["direction"]
    print(f"calib: n={n} parse-invalid={invalid} bad-lines={bad}")
    print(f"  is_regulatory agreement {agree}/{n} = {agree / max(n, 1):.1%}  "
          f"(vs Sonnet-classified recall {pos_recall}/{pos_n}, vs Haiku-rejected agree {neg_ok}/{neg_n})")
    print(f"  direction agreement on shared sectors {dir_ok}/{dir_n} = {dir_ok / max(dir_n, 1):.1%}")


# ── Reconciliation (cross-worker direction splits on the same story) ──

_STOP = set("the a an of to in on for and or with by at as is are be from after over into its it "
            "this that new india indian says said will may could amid govt government".split())


def _title_tokens(title):
    title = re.sub(r"\s+-\s+[^-]+$", "", str(title or "")).lower()  # drop " - Outlet" suffix
    return frozenset(w for w in re.findall(r"[a-z0-9]+", title) if w not in _STOP and len(w) > 2)


def _story_clusters(events, jaccard=0.5, window_days=3):
    """events: {event_id: (tokens, date)} → list of event_id lists (size ≥ 2)."""
    parent = {e: e for e in events}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_day = collections.defaultdict(list)
    for e, (_, d) in events.items():
        by_day[d].append(e)
    for e, (te, d) in events.items():
        if len(te) < 3:
            continue
        for k in range(window_days + 1):
            for o in by_day.get(d + dt.timedelta(days=k), []):
                if k == 0 and o <= e:
                    continue
                to = events[o][0]
                if len(to) >= 3 and len(te & to) / len(te | to) >= jaccard:
                    parent[find(e)] = find(o)
    groups = collections.defaultdict(list)
    for e in events:
        groups[find(e)].append(e)
    return [g for g in groups.values() if len(g) > 1]


def export_conflicts(out_dir, days, since):
    sig = read_sql(
        "SELECT e.event_id, e.title, date(e.published_at) AS d, s.sector, s.direction, s.ai_reasoning "
        "FROM regulatory_events e JOIN regulatory_signals s ON s.event_id = e.event_id "
        "WHERE e.classifier_status = 'classified' AND date(e.published_at) >= date('now', ?) "
        "AND e.classifier_processed_at >= ?",
        params=[f"-{days} days", since])
    events, rows = {}, collections.defaultdict(list)
    for r in sig.itertuples(index=False):
        events[r.event_id] = (_title_tokens(r.title), dt.date.fromisoformat(r.d))
        rows[r.event_id].append(r)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    with (out_dir / "conflicts.in.jsonl").open("w") as f:
        for g in _story_clusters(events):
            by_sector = collections.defaultdict(list)
            for e in g:
                for r in rows[e]:
                    by_sector[r.sector].append(r)
            for sector, rs in by_sector.items():
                if len({int(r.direction) for r in rs}) < 2:
                    continue
                seen, examples = set(), []
                for r in rs:
                    if r.title not in seen and len(examples) < 10:
                        seen.add(r.title)
                        examples.append({"title": str(r.title)[:200], "direction": int(r.direction),
                                         "reasoning": str(r.ai_reasoning or "")[:200]})
                f.write(json.dumps({
                    "id": f"c{n:03d}", "sector": sector,
                    "event_ids": sorted({r.event_id for r in rs}),
                    "n_pos": sum(int(r.direction) == 1 for r in rs),
                    "n_neg": sum(int(r.direction) == -1 for r in rs),
                    "examples": examples}, ensure_ascii=False) + "\n")
                n += 1
    print(f"export-conflicts: {len(events)} classified events since {since} → "
          f"{n} cluster×sector direction conflicts → {out_dir / 'conflicts.in.jsonl'}")


def apply_reconcile(out_dir):
    conflicts = {json.loads(l)["id"]: json.loads(l)
                 for l in (out_dir / "conflicts.in.jsonl").read_text().splitlines() if l.strip()}
    verdicts = {}
    for l in (out_dir / "conflicts.out.jsonl").read_text().splitlines():
        if l.strip():
            v = json.loads(l)
            verdicts[v["id"]] = v
    changed = kept = bad = 0
    with (out_dir / "reconcile_manifest.tsv").open("a") as man, get_db() as conn:
        for cid, c in conflicts.items():
            v = verdicts.get(cid)
            if v is None or v.get("direction") not in (1, -1, None):
                bad += 1
                continue
            if v["direction"] is None:
                kept += 1
                continue
            for eid in c["event_ids"]:
                old = conn.execute("SELECT direction FROM regulatory_signals WHERE event_id = ? AND sector = ?",
                                   (eid, c["sector"])).fetchone()
                if old and int(old[0]) != v["direction"]:
                    man.write(f"{eid}\t{c['sector']}\t{old[0]}\n")
                    conn.execute("UPDATE regulatory_signals SET direction = ? WHERE event_id = ? AND sector = ?",
                                 (v["direction"], eid, c["sector"]))
                    changed += 1
    print(f"apply-reconcile: {changed} signal rows re-pointed, {kept} conflicts left as distinct stories, "
          f"{bad} missing/invalid verdicts")


def rollback_reconcile(out_dir):
    rows = [l.split("\t") for l in (out_dir / "reconcile_manifest.tsv").read_text().splitlines() if l]
    with get_db() as conn:
        for eid, sector, old in rows:
            conn.execute("UPDATE regulatory_signals SET direction = ? WHERE event_id = ? AND sector = ?",
                         (int(old), eid, sector))
    print(f"rollback-reconcile: restored {len(rows)} signal rows")


# ── News ──

def export_news(out_dir, days, chunk):
    rows = read_sql(
        "SELECT na.article_id, na.title, na.summary, na.source FROM news_articles na "
        "LEFT JOIN news_enriched ne ON ne.article_id = na.article_id "
        "WHERE na.published_at >= date('now', ?) "
        "AND (ne.article_id IS NULL OR ne.classifier_status IN ('pending', 'failed')) "
        "ORDER BY na.published_at DESC", params=[f"-{days} days"])
    items = [{"id": str(r.article_id), "title": (r.title or "").replace("\n", " ")[:300],
              "source": r.source or "", "summary": (r.summary or "").replace("\n", " ")[:1500]}
             for r in rows.itertuples(index=False)]
    n = _write_chunks(out_dir, items, chunk)
    print(f"export-news: {len(items)} articles (last {days}d) in {n} chunks → {out_dir}")


def ingest_news(out_dir):
    results, bad = _read_results(out_dir)
    done = skipped = 0
    for aid, obj in results.items():
        src = read_sql(
            "SELECT na.title, na.summary, ne.classifier_status FROM news_articles na "
            "LEFT JOIN news_enriched ne ON ne.article_id = na.article_id "
            "WHERE na.article_id = ?", params=[aid])
        if src.empty or src.iloc[0]["classifier_status"] == "done":
            skipped += 1
            continue
        title, summary = src.iloc[0]["title"], src.iloc[0]["summary"]
        out = nc.normalize(obj, title, summary)
        with get_db() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO news_enriched
                   (article_id, topics, primary_topic, one_liner, why_it_matters,
                    key_numbers, what_to_watch, confidence, sentiment, keywords,
                    classifier_status, classified_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (aid, out["topics"], out["primary_topic"], out["one_liner"],
                 out["why_it_matters"], out["key_numbers"], out["what_to_watch"],
                 out["confidence"], out["sentiment"], out["keywords"], out["classifier_status"]),
            )
        done += 1
    if done:
        log_llm_usage("classify_news", SESSION_MODEL,
                      {"input_tokens": 0, "output_tokens": 0}, mode="session", n_calls=done)
    print(f"ingest-news: {done} enriched, {skipped} skipped, unparseable lines={bad}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["export-reg", "export-news", "export-calib", "score-calib",
                                   "ingest-reg", "ingest-news", "rollback-reg",
                                   "export-conflicts", "apply-reconcile", "rollback-reconcile"])
    p.add_argument("dir", type=Path)
    p.add_argument("--days", type=int)
    p.add_argument("--chunk", type=int, default=200)
    p.add_argument("--n", type=int, default=40)
    p.add_argument("--since", default="0000", help="export-conflicts: only events classified at/after this ISO time")
    a = p.parse_args()
    if a.cmd == "export-reg":
        export_reg(a.dir, a.days or 60, a.chunk)
    elif a.cmd == "export-news":
        export_news(a.dir, a.days or 7, a.chunk)
    elif a.cmd == "export-calib":
        export_calib(a.dir, a.n)
    elif a.cmd == "score-calib":
        score_calib(a.dir)
    elif a.cmd == "ingest-reg":
        ingest_reg(a.dir)
    elif a.cmd == "ingest-news":
        ingest_news(a.dir)
    elif a.cmd == "rollback-reg":
        rollback_reg(a.dir)
    elif a.cmd == "export-conflicts":
        export_conflicts(a.dir, a.days or 60, a.since)
    elif a.cmd == "apply-reconcile":
        apply_reconcile(a.dir)
    elif a.cmd == "rollback-reconcile":
        rollback_reconcile(a.dir)


if __name__ == "__main__":
    sys.exit(main())
