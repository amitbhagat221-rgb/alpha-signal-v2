"""
Alpha Signal v2 — Canary runner (plan 0018 §4 Gates 1-2, §6 rung 2).

Runs each feed's canary (sources/canaries.py: ONE live item), judges what came back
and records a verdict per feed in `feed_checks`:

  Gate 1 transport   HTTP status, HTML-where-data-expected (bot/login page), empty body
  Gate 2 content     row floor, required fields, feed-specific checks, and the SHAPE
                     FINGERPRINT (sorted field names) vs the accepted baseline —
                     removed fields = FAIL (an API changed under us), added-only = WARN

Every failure is tagged with its symptom class (feeds.SYMPTOM_CLASSES A-H) — the
first thing a human or the DQ agent needs. Raw responses land in data/raw/<canary>/
(last good + every failure, 30 days, 2 GB cap — plan 0018 D3) for diagnosis,
fixtures and replay. A canary never writes a data table.

Usage (run.sh canary holds the harvest lock — never alongside a harvester):
    python -m tools.canary --due              # T1 daily + T2 on Sundays (the cron)
    python -m tools.canary --feed nse_bhavcopy [--feed …]
    python -m tools.canary --tier T1 | --all
    python -m tools.canary --accept screener  # accept the current shape as the new baseline
    python -m tools.canary --list

Exit code: 0 when the runner itself worked (feed failures are verdicts, not crashes);
1 when every canary ERRORed (our bug, or the network is down).
"""

import argparse
import gzip
import hashlib
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import feeds  # noqa: E402
import runlog  # noqa: E402

RAW_ROOT = PROJECT_ROOT / "data" / "raw"
RETENTION_DAYS = 30
CAP_BYTES = 2 * 1024 ** 3
EXT = {"json": "json", "csv": "csv", "html": "html", "xml": "xml", "text": "txt", "frame": "csv"}
DATA_EXPECT = ("json", "csv", "xml", "text")


# ─────────────────────────────── Pure judging (tested offline) ───────────────────────────────

def fields_of(sample):
    """Field names the fingerprint reads: explicit `fields`, a frame's columns, the
    union of keys over the first 50 records, or a dict's keys."""
    if sample.get("fields") is not None:
        return sorted({str(f) for f in sample["fields"]})
    rec = sample.get("records")
    if isinstance(rec, pd.DataFrame):
        return sorted({str(c) for c in rec.columns})
    if isinstance(rec, dict):
        return sorted({str(k) for k in rec})
    if isinstance(rec, list):
        keys = set()
        for r in rec[:50]:
            if isinstance(r, dict):
                keys |= {str(k) for k in r}
        return sorted(keys)
    return []


def n_rows(sample):
    rec = sample.get("records")
    if rec is None:
        return 0
    if isinstance(rec, dict):
        return 1 if rec else 0
    return len(rec)


def fingerprint(fields):
    return hashlib.sha1("\n".join(sorted(set(fields))).encode()).hexdigest()[:12] if fields else None


def _looks_html(raw):
    head = (raw or b"")[:600].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<head" in head[:300]


def gate_transport(sample):
    """(status, symptom, detail) — None status = passed."""
    http, raw, expect = sample.get("http"), sample.get("raw") or b"", sample.get("expect")
    if http is not None and http != 200:
        sym = {401: "C", 403: "A", 404: "B", 410: "B", 429: "G"}.get(http, "E" if http >= 500 else "A")
        return "FAIL", sym, f"HTTP {http}"
    if expect in DATA_EXPECT and _looks_html(raw):
        low = raw[:4000].lower()
        sym = "C" if (b"login" in low or b"sign in" in low) else "A"
        return "FAIL", sym, f"HTML page where {expect} was expected ({len(raw)} bytes)"
    return None, None, "ok"


def gate_content(sample, baseline_fields):
    """[(gate, status, symptom, detail)] for Gate 2 — status ∈ PASS/WARN/FAIL."""
    out = []
    rows, floor = n_rows(sample), sample.get("min_rows", 1)
    if rows == 0:
        out.append(("rows", "FAIL", "B", "0 rows — 200-but-empty (moved / deprecated endpoint?)"))
    elif rows < floor:
        out.append(("rows", "FAIL", "E", f"{rows} rows < floor {floor}"))
    else:
        out.append(("rows", "PASS", None, f"{rows} rows (floor {floor})"))
    fields = fields_of(sample)
    missing = [f for f in sample.get("required") or [] if f not in fields]
    if rows and missing:
        out.append(("required", "FAIL", "D", f"missing required fields: {missing}"))
    elif sample.get("required"):
        out.append(("required", "PASS", None, f"{len(sample['required'])} required fields present"))
    for chk in sample.get("checks") or []:          # (name, ok, detail[, symptom[, severity]])
        name, ok, detail = chk[:3]
        sym = chk[3] if len(chk) > 3 else ("C" if name == "logged_in" else "F")
        sev = chk[4] if len(chk) > 4 else "FAIL"     # WARN: e.g. a dead FALLBACK route
        out.append((f"check:{name}", "PASS" if ok else sev, None if ok else sym, detail))
    if rows and baseline_fields is not None and fields:
        added = sorted(set(fields) - set(baseline_fields))
        removed = sorted(set(baseline_fields) - set(fields))
        if removed:
            out.append(("shape", "FAIL", "D", f"fields removed {removed[:12]}" + (f"; added {added[:12]}" if added else "")))
        elif added:
            out.append(("shape", "WARN", "D", f"fields added {added[:12]} (additive — accept if intended)"))
        else:
            out.append(("shape", "PASS", None, "matches baseline"))
    return out


def judge(sample, baseline_fields):
    """One verdict: status (worst gate), symptom (first failing gate's), gate list."""
    t_status, t_sym, t_detail = gate_transport(sample)
    gates = [("transport", t_status or "PASS", t_sym, t_detail)]
    if t_status is None:
        gates += gate_content(sample, baseline_fields)
    rank = {"PASS": 0, "WARN": 1, "FAIL": 2}
    worst = max(gates, key=lambda g: rank[g[1]])
    status = worst[1]
    symptom = next((g[2] for g in gates if g[1] == status and g[2]), None) if status != "PASS" else None
    fields = fields_of(sample)
    return {"status": status, "symptom": symptom, "gates": gates, "fields": fields,
            "fingerprint": fingerprint(fields), "n_rows": n_rows(sample),
            "bytes": len(sample.get("raw") or b"")}


classify_exception = runlog.classify_exception    # one copy, shared with the run log


# ─────────────────────────────── Baselines + raw landing zone ───────────────────────────────

def _dir(key, root=None):
    d = (root or RAW_ROOT) / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_baseline(key, root=None):
    p = _dir(key, root) / "baseline.json"
    return json.loads(p.read_text()) if p.exists() else None


def save_baseline(key, fields, note, root=None):
    b = {"fields": sorted(fields), "fingerprint": fingerprint(fields),
         "accepted_at": datetime.now().isoformat(timespec="seconds"), "note": note}
    (_dir(key, root) / "baseline.json").write_text(json.dumps(b, indent=1))
    return b


def land_raw(key, sample, ok, root=None, now=None):
    """Last good overwrites last_good.<ext>.gz; every failure keeps its own file."""
    raw = sample.get("raw") or b""
    if not raw:
        return None
    if sample.get("raw_head"):
        raw = raw[:256 * 1024]
    ext = EXT.get(sample.get("expect"), "bin")
    stamp = (now or datetime.now()).strftime("%Y%m%dT%H%M%S")
    p = _dir(key, root) / (f"last_good.{ext}.gz" if ok else f"fail_{stamp}.{ext}.gz")
    p.write_bytes(gzip.compress(raw))
    return p


def prune(root=None, retention_days=RETENTION_DAYS, cap_bytes=CAP_BYTES, now=None):
    """Delete failure files older than retention, then the oldest failures until the
    zone fits the cap. last_good.* and baseline.json are never deleted."""
    root = root or RAW_ROOT
    if not root.exists():
        return []
    now = now or time.time()
    fails = sorted((p for p in root.glob("*/fail_*") if p.is_file()), key=lambda p: p.stat().st_mtime)
    removed = []
    for p in fails:
        if now - p.stat().st_mtime > retention_days * 86400:
            p.unlink()
            removed.append(p)
    fails = [p for p in fails if p.exists()]
    total = sum(p.stat().st_size for p in root.glob("*/*") if p.is_file())
    while fails and total > cap_bytes:
        p = fails.pop(0)
        total -= p.stat().st_size
        p.unlink()
        removed.append(p)
    return removed


# ─────────────────────────────── Selection + run ───────────────────────────────

def canary_feeds():
    """{canary_key: [feed, …]} for live feeds that declare a canary."""
    out = {}
    for name, f in feeds.FEEDS.items():
        if f["status"] in feeds.LIVE and f.get("canary"):
            out.setdefault(f["canary"], []).append(name)
    return out


def select(due=False, tier=None, names=None, all_=False, today=None):
    today = today or date.today()
    keys = []
    for key, fs in canary_feeds().items():
        tiers = {feeds.tier(f) for f in fs}
        if names:
            ok = key in names or any(f in names for f in fs)
        elif all_:
            ok = True
        elif tier:
            ok = tier in tiers
        elif due:
            ok = "T1" in tiers or ("T2" in tiers and today.weekday() == 6)
        else:
            ok = False
        if ok:
            keys.append(key)
    return keys


def run_one(key, accept=False, root=None):
    from sources.canaries import CANARIES
    t0 = time.time()
    baseline = load_baseline(key, root)
    try:
        sample = CANARIES[key]()
    except Exception as e:                                 # noqa: BLE001 — classified, never swallowed
        status, sym = classify_exception(e)
        return {"key": key, "status": status, "symptom": sym, "gates": [("call", status, sym, f"{type(e).__name__}: {str(e)[:300]}")],
                "fingerprint": None, "baseline": (baseline or {}).get("fingerprint"), "n_rows": 0, "bytes": 0,
                "http": None, "url": None, "duration": round(time.time() - t0, 1)}
    v = judge(sample, None if (accept or baseline is None) else baseline["fields"])
    transport_ok = v["gates"][0][1] == "PASS"
    if transport_ok and v["n_rows"] and v["fields"] and (accept or baseline is None) and v["status"] != "FAIL":
        baseline = save_baseline(key, v["fields"], "accepted by --accept" if accept else "first run")
        v["gates"].append(("shape", "PASS", None, "baseline " + ("accepted" if accept else "set (first run)")))
    land_raw(key, sample, v["status"] == "PASS", root)
    v.update(key=key, baseline=(baseline or {}).get("fingerprint"), http=sample.get("http"),
             url=sample.get("url"), duration=round(time.time() - t0, 1))
    return v


def record(results, dry_run=False):
    """One feed_checks row per (feed sharing the canary)."""
    fmap = canary_feeds()
    rows = []
    for r in results:
        for feed in fmap.get(r["key"], []):
            rows.append({"run_date": date.today().isoformat(), "feed": feed, "check_kind": "canary",
                         "route": (feeds.FEEDS[feed].get("routes") or [{}])[0].get("id"),
                         "status": r["status"], "symptom": r["symptom"], "http_status": r.get("http"),
                         "n_rows": r["n_rows"], "bytes": r["bytes"], "fingerprint": r["fingerprint"],
                         "baseline": r["baseline"], "duration_sec": r["duration"],
                         "detail": json.dumps({"canary": r["key"], "url": r.get("url"),
                                               "gates": [list(g) for g in r["gates"]]}, default=str),
                         "checked_at": datetime.now().isoformat(timespec="seconds")})
    if rows and not dry_run:
        from db import insert_df
        insert_df(pd.DataFrame(rows), "feed_checks")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Run feed canaries (plan 0018)")
    ap.add_argument("--due", action="store_true", help="T1 daily + T2 on Sundays (cron)")
    ap.add_argument("--tier", choices=["T1", "T2"])
    ap.add_argument("--feed", action="append", help="feed or canary key (repeatable)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--accept", metavar="KEY", help="accept the current shape of a canary as its baseline")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="probe but do not write feed_checks")
    a = ap.parse_args(argv)

    if a.list:
        for key, fs in sorted(canary_feeds().items()):
            b = load_baseline(key)
            print(f"{key:26} {','.join(sorted({feeds.tier(f) for f in fs})):6} {', '.join(fs):48} "
                  f"baseline={(b or {}).get('fingerprint')}")
        return 0

    keys = [a.accept] if a.accept else select(a.due, a.tier, set(a.feed or []), a.all)
    if not keys:
        print("no canaries selected")
        return 0
    print(f"=== canary {datetime.now():%Y-%m-%d %H:%M:%S} — {len(keys)} canaries")
    runlog.start("canary", module="tools.canary", adopt_env=True)
    results = []
    fmap = canary_feeds()
    for key in keys:
        r = run_one(key, accept=bool(a.accept))
        results.append(r)
        if r["status"] != "PASS":                       # one queryable event per non-PASS canary
            for feed in fmap.get(key, []):
                runlog._ctx["feed"] = feed
                runlog._emit("canary", "WARN" if r["status"] == "WARN" else "ERROR", host=None, url=r.get("url"),
                             http_status=r.get("http"), symptom=r["symptom"], item=key, rows=r["n_rows"],
                             error_type=r["status"], location=f"sources/canaries.py:{key}",
                             message="; ".join(f"{g[0]}: {g[3]}" for g in r["gates"] if g[1] != "PASS")[:600],
                             detail={"gates": r["gates"], "fingerprint": r["fingerprint"], "baseline": r["baseline"]})
            runlog._ctx["feed"] = None
        sym = f" [{r['symptom']}]" if r["symptom"] else ""
        bad = [g for g in r["gates"] if g[1] != "PASS"]
        print(f"  {r['status']:5}{sym:5} {key:26} rows={r['n_rows']:<7} {r['duration']:>5}s  "
              + ("; ".join(f"{g[0]}: {g[3]}" for g in bad)[:220] if bad else "ok"), flush=True)
    record(results, dry_run=a.dry_run)
    removed = prune()
    runlog.prune()
    counts = pd.Series([r["status"] for r in results]).value_counts().to_dict()
    print(f"=== {counts}" + (f"; pruned {len(removed)} raw files" if removed else ""))
    all_error = counts.get("ERROR", 0) == len(results)
    runlog.end("FAILED" if all_error else "SUCCESS", rows=len(results),
               error=None if not counts.get("FAIL") else f"{counts.get('FAIL')} canaries failed")
    return 1 if all_error else 0


if __name__ == "__main__":
    sys.exit(main())
