"""
Alpha Signal v2 — the pipeline as a dataflow graph (the Node block; ADR 0052, plan 0015).

Every step in config.PIPELINE_STEPS declares what it `reads` and `writes`
(datasets = table names, or "file:<name>" for file hand-offs). From that alone
this module derives what used to be hand-kept:

  order          a topological sort — no step list position carries meaning
  critical path  the steps the email transitively needs (they run first)
  producers      which step feeds a dataset (freshness / heal / lineage / /flow)

Edges come in two kinds. By default a read is BLOCKING: the reader sees THIS
run's output, so the writer runs first. A read is LAGGED when the writer declares
`lagged_writes: [dataset]` ("readers get my write next run") or the reader
declares `lagged_reads: [dataset | "dataset@writer"]`: the reader sees the
PREVIOUS run's version, so it runs BEFORE the writer. Which version a read sees
is fixed by declaration, never by scheduling luck; the dataset's freshness check
covers staleness.

The 2026-09-27 incident (a 14-minute weekly fetch ahead of the screener) is
guarded by `slow_on_critical_path`: a step whose recent p90 runtime exceeds the
limit may not be a blocking ancestor of the email — make its write lagged.

Plain functions over the step dicts (ADR 0004). Runner-owned tables
(pipeline_log) are never edges.
"""

CADENCE_RANK = {"daily": 0, "weekly": 1, "monthly": 2, "quarterly": 3}
RUNNER_TABLES = {"pipeline_log", "sqlite_sequence", "sqlite_master"}
EMAIL = "email"


def writes(step):
    """Datasets a step writes: `writes` if declared, else its single `table`."""
    if "writes" in step:
        return list(step["writes"])
    return [step["table"]] if step.get("table") else []


def reads(step):
    return [t for t in step.get("reads", []) if t not in RUNNER_TABLES]


def lagged_from_order(steps):
    """Reads that, in `steps` list order, see the PREVIOUS run's version (writer
    listed after reader). Returns (lagged_writes, lagged_reads): a write whose every
    reader precedes the writer becomes writer-side `lagged_writes`; otherwise the
    reader gets `dataset@writer`. Used once to seed declarations so the derived
    order preserves every read's version."""
    pos = {s["name"]: i for i, s in enumerate(steps)}
    later, readers = {}, {}
    for w, r, d, kind in edges(steps):
        if kind != "blocking":
            continue
        readers.setdefault((w, d), set()).add(r)
        if pos[w] > pos[r]:
            later.setdefault((w, d), set()).add(r)
    lw, lr = {}, {}
    for (w, d), rs in later.items():
        if rs == readers[(w, d)]:
            lw.setdefault(w, set()).add(d)
        else:
            for r in rs:
                lr.setdefault(r, set()).add(f"{d}@{w}")
    return lw, lr


def edges(steps):
    """[(writer, reader, dataset, kind)] with kind 'blocking' | 'lagged'."""
    writers = {}
    for s in steps:
        for d in writes(s):
            writers.setdefault(d, []).append(s)
    out = []
    for r in steps:
        lagged_decl = set(r.get("lagged_reads", ()))
        for d in reads(r):
            for w in writers.get(d, []):
                if w["name"] == r["name"]:
                    continue
                lagged = (d in lagged_decl or f"{d}@{w['name']}" in lagged_decl
                          or d in w.get("lagged_writes", ()))
                out.append((w["name"], r["name"], d, "lagged" if lagged else "blocking"))
    return out


def constraints(steps):
    """{step: set of steps that must run before it} — blocking: writer→reader;
    lagged: reader→writer (the reader must see the previous version)."""
    before = {s["name"]: set() for s in steps}
    for w, r, _, kind in edges(steps):
        if kind == "blocking":
            before[r].add(w)
        else:
            before[w].add(r)
    return before


def ancestors(steps, target=EMAIL, needed_only=False):
    """Steps that must run before `target`.

    needed_only=False: every ordering constraint (blocking reads AND lagged reads
    that must happen before their writer) — the true critical path.
    needed_only=True: only blocking reads — the steps whose OUTPUT the target uses.
    The difference is the steps pinned ahead of the email solely so that some
    reader keeps seeing the previous run's data (Phase 1b candidates)."""
    if needed_only:
        parents = {}
        for w, r, _, kind in edges(steps):
            if kind == "blocking":
                parents.setdefault(r, set()).add(w)
    else:
        parents = constraints(steps)
    seen, stack = set(), [target]
    while stack:
        for p in parents.get(stack.pop(), ()):
            if p not in seen:
                seen.add(p)
                stack.append(p)
    return seen


def order(steps, target=EMAIL):
    """Topological order over blocking edges.

    Ties are broken by (1) the target's ancestors and the target itself first —
    the critical path to the email — then (2) the declared list position, so the
    derived order changes the hand order only where a dependency or the critical
    path demands it. Raises on a cycle.
    """
    names = [s["name"] for s in steps]
    pos = {n: i for i, n in enumerate(names)}
    crit = ancestors(steps, target) | {target}
    parents = constraints(steps)
    done, out = set(), []
    while len(out) < len(names):
        ready = [n for n in names if n not in done and parents[n] <= done]
        if not ready:
            left = sorted(set(names) - done)
            raise ValueError(f"dependency cycle among: {left}")
        nxt = min(ready, key=lambda n: (n not in crit, pos[n]))
        out.append(nxt)
        done.add(nxt)
    return out


def slow_on_critical_path(steps, p90_minutes, limit_minutes=5.0, target=EMAIL):
    """Steps on the email's critical path whose p90 runtime exceeds the limit."""
    crit = ancestors(steps, target)
    return sorted(n for n in crit if p90_minutes.get(n, 0.0) > limit_minutes)


def producers(steps, dataset):
    """Steps that write `dataset`, finest cadence first (ties: list order)."""
    ws = [s for s in steps if dataset in writes(s)]
    return sorted(ws, key=lambda s: CADENCE_RANK.get(s["frequency"], 9))


def read_versions(steps, sequence):
    """{(writer, reader, dataset): True if the reader sees THIS run's write} for a
    given execution sequence — the order-equivalence gate compares two of these."""
    pos = {n: i for i, n in enumerate(sequence)}
    return {(w, r, d): pos[w] < pos[r] for w, r, d, _ in edges(steps) if w in pos and r in pos}


def diff(steps, derived):
    """Steps whose relative position vs the email changes: (moved_before, moved_after)."""
    names = [s["name"] for s in steps]
    if EMAIL not in names:
        return [], []
    cur_before = set(names[:names.index(EMAIL)])
    new_before = set(derived[:derived.index(EMAIL)])
    return sorted(new_before - cur_before), sorted(cur_before - new_before)
