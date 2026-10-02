"""
The pipeline's LLM steps (plan 0016 phase 3). config.PIPELINE_STEPS points
classify_news, classify_regulatory, news_brief, dossier and compute_sector_dossiers
here; each keeps its name, reads, writes and post-check.

config.LLM_WORK["executor"]:
  "queue" (default) — queue the kind's items in llm_tasks, then run the local worker
           (ops/llm_worker_local.sh: claude -p on the Claude subscription) on that kind
           until it drains or the step's deadline passes. Every result is validated and
           written by alpha-work.submit through the producer's own save path.
  "api"   — the old Anthropic API path (paid credits; kept as a fallback, decision D3).

Silent-failure rule: a step whose kind had items but produced nothing raises, exactly
as the API paths did, so the run, the post-check and the health email see it.
"""
import datetime as dt
import os
import subprocess
import time

from alpha_mcp._core import ROOT

WORKER = ROOT / "ops" / "llm_worker_local.sh"


def _executor():
    import config
    return config.LLM_WORK["executor"]


def _deadline(step):
    import config
    return config.LLM_WORK["deadline_min"][step]


def run_kind(kinds, deadline_min, max_batches=40):
    """Enqueue `kinds`, then run the local worker on them until nothing is claimable,
    the deadline passes, or two worker runs in a row make no progress.
    Returns {"queued", "claimable_before", "claimable_after", "runs"}."""
    from alpha_mcp import tasks
    queued = sum(tasks.enqueue(k)["queued"] for k in kinds)
    before = left = tasks.claimable_count(kinds)
    end = time.monotonic() + deadline_min * 60
    runs = stalls = 0
    while left and stalls < 2:
        remaining = int(end - time.monotonic())
        if remaining < 60:
            break
        env = {**os.environ, "LLM_WORKER_KINDS": ",".join(kinds), "LLM_WORKER_TIMEOUT": f"{remaining}s"}
        subprocess.run([str(WORKER), str(max_batches)], env=env, check=False)
        runs += 1
        now = tasks.claimable_count(kinds)
        stalls = stalls + 1 if now >= left else 0
        left = now
    out = {"queued": queued, "claimable_before": before, "claimable_after": left, "runs": runs}
    print(f"[llm queue] {','.join(kinds)}: {out}")
    return out


def _require_progress(kind, r):
    """Items existed but none was done this run → raise (CLAUDE.md: no silent failures)."""
    if r["claimable_before"] and r["claimable_after"] >= r["claimable_before"]:
        raise RuntimeError(f"{kind}: {r['claimable_before']} items claimable, none done "
                           f"({r['runs']} worker runs) — see output/llm_worker.log")


# ═══════════════════════════ steps ═══════════════════════════

def classify_news():
    if _executor() == "api":
        from sources import news_classifier
        return news_classifier.compute()
    r = run_kind(["news_enrich"], _deadline("classify_news"))
    _require_progress("news_enrich", r)
    return r["claimable_before"] - r["claimable_after"]


def classify_regulatory():
    if _executor() == "api":
        from sources import regulatory_classifier
        return regulatory_classifier.compute()
    r = run_kind(["regulatory"], _deadline("classify_regulatory"))
    _require_progress("regulatory", r)
    return r["claimable_before"] - r["claimable_after"]


def news_brief():
    if _executor() == "api":
        from sources import news_brief as nb
        return nb.compute()
    import db
    day = dt.date.today().isoformat()
    r = run_kind(["news_brief"], _deadline("news_brief"))
    have = db.scalar("SELECT 1 FROM news_briefs WHERE brief_date = ?", [day])
    if not have and r["queued"] + r["claimable_before"] == 0:
        print(f"No enriched articles for {day} — skipping brief")
        return 0
    if not have:
        raise RuntimeError(f"news_brief: no brief written for {day} — see output/llm_worker.log")
    return 1


def compute_sector_dossiers():
    if _executor() == "api":
        from output import sector_dossier
        return sector_dossier.compute()
    import db
    r = run_kind(["sector_dossier"], _deadline("compute_sector_dossiers"))
    snap = db.scalar("SELECT MAX(snapshot_date) FROM sector_briefs")
    n_valid = db.scalar("SELECT COUNT(*) FROM sector_dossiers WHERE snapshot_date = ? AND valid = 1",
                        [snap], default=0)
    if snap and not n_valid:
        raise RuntimeError(f"compute_sector_dossiers: 0 valid sector dossiers for {snap} "
                           f"({r}) — see output/llm_worker.log")
    return n_valid


def dossier():
    """Queue today's published picks, wait up to the deadline (D4: the email waits at most
    this long), then complete today's file: a pick the worker didn't reach gets a
    `thesis pending` placeholder, which the email shows as pending."""
    if _executor() == "api":
        from output import dossier as od
        return od.compute()
    import views
    from alpha_mcp import tasks
    from output.dossier import is_publishable
    day = dt.date.today().isoformat()
    run_kind(["dossier"], _deadline("dossier"))
    picks = views.published_picks("book")
    counts = {}

    def fill(data):
        good = [d for d in data if is_publishable(d)]
        have = {d.get("sid") for d in good}
        pending = [{"sid": p["sid"], "ticker": p["ticker"], "status": "thesis pending"}
                   for _, p in picks.iterrows() if p["sid"] not in have]
        counts["thesis"], counts["pending"] = len(good), len(pending)
        return good + pending, None
    tasks._locked_json_update(tasks._dossier_path(day), fill)
    print(f"dossier: {counts['thesis']} validated theses, {counts['pending']} pending of {len(picks)} picks")
    if len(picks) and counts["thesis"] == 0:
        raise RuntimeError(f"dossier: 0 of {len(picks)} theses written by the deadline — see output/llm_worker.log")
    return counts["thesis"]
