"""
Alpha Signal Cockpit — shared helpers for both apps (trading :3000, ops :3001):
cache decorators, JSON coercion, Jinja template setup and the startup prewarm.

Lives below both cockpit/api.py and cockpit_ops/api.py so neither has to import
the other just to reuse the caches. Previously these decorators lived in
cockpit/api.py and cockpit_ops did `from cockpit.api import _ttl_cache,
_persisted_cache` — which forced the 2,900-LOC api module to load. Importing
from here keeps the dependency one-directional.
"""

import functools
import time as _time
from pathlib import Path

import pandas as pd


# In-process TTL cache for read-only functions.
# Pages call these on every render, but the underlying SQLite tables only
# change when the daily cron pipeline runs — so a 60s TTL is invisible to
# users and shaves 1-2 seconds off /system, /command, /model, /actions, /portfolio.
# Args are tuple-keyed; pass `_force=True` to bypass.
def _ttl_cache(ttl_seconds, max_entries=512):
    def decorator(fn):
        cache: dict = {}

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            force = kwargs.pop("_force", False)
            key = (args, tuple(sorted(kwargs.items())))
            now = _time.time()
            entry = cache.get(key)
            if not force and entry is not None and (now - entry[1]) < ttl_seconds:
                return entry[0]
            value = fn(*args, **kwargs)
            cache[key] = (value, now)
            # Bound memory: evict oldest entries if over max_entries.
            if len(cache) > max_entries:
                oldest = sorted(cache.items(), key=lambda kv: kv[1][1])[: len(cache) - max_entries]
                for k, _ in oldest:
                    cache.pop(k, None)
            return value

        wrapper.cache_clear = lambda: cache.clear()
        return wrapper

    return decorator


# Persistent TTL cache — same as _ttl_cache but also pickles to disk so a
# systemd restart doesn't reset the cache. First call after restart loads
# from disk (~ms) instead of recomputing (~5-17s). Use for the heaviest
# cockpit endpoints.
# 2026-05-25: added after /system cold-restart was 28-39s.
# 2026-09-26: stale-while-revalidate. Past the TTL the stale value is returned
# at once and ONE daemon thread per key recomputes it; before this an expired
# /system recomputed inline (40-68s on the live DB). Only a true cold start
# (no memo, no pickle) or `_force=True` computes inline — and concurrent cold
# callers of the same key share one compute via the per-key lock.
# COCKPIT_CACHE_DIR overrides the location so test instances (worktrees, ad-hoc
# uvicorn on another port) never write pickles into prod's cache.
import os as _os
_PERSISTED_CACHE_DIR = Path(
    _os.environ.get("COCKPIT_CACHE_DIR")
    or Path(__file__).resolve().parent.parent / "data" / ".cockpit_cache"
)


def _persisted_cache(ttl_seconds, name=None, max_entries=128):
    """Disk-backed sibling of _ttl_cache. Keyed by (args, kwargs) — each unique
    arg combo gets its own pickle file. Use sparingly for heavy functions where
    the arg space is small (e.g. news pool keyed by hours ∈ {24,72,168,720}).
    `max_entries` bounds the in-process memo (oldest evicted first)."""
    import pickle as _pickle
    import threading
    import traceback

    def _key_to_slot(slot_base, args, kwargs):
        if not args and not kwargs:
            return slot_base
        parts = [slot_base]
        if args:
            parts.append("_".join(str(a) for a in args))
        if kwargs:
            parts.append("_".join(f"{k}={v}" for k, v in sorted(kwargs.items())))
        return "__".join(parts)

    def decorator(fn):
        slot_base = name or f"{fn.__module__}.{fn.__name__}"
        memo: dict = {}  # key -> (value, mtime)
        locks: dict = {}  # key -> Lock held while that key computes
        locks_guard = threading.Lock()

        def _lock_for(slot):
            with locks_guard:
                return locks.setdefault(slot, threading.Lock())

        def _path_for(slot):
            return _PERSISTED_CACHE_DIR / f"{slot}.pkl"

        def _load(slot):
            p = _path_for(slot)
            if not p.exists():
                return None, 0
            try:
                with p.open("rb") as f:
                    payload, mtime = _pickle.load(f)
                return payload, mtime
            except Exception:
                return None, 0

        def _save(slot, payload, mtime):
            # Write-then-rename so a reader (another worker / the other app)
            # never unpickles a half-written file.
            try:
                _PERSISTED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                tmp = _path_for(slot).with_suffix(f".tmp{threading.get_ident()}")
                with tmp.open("wb") as f:
                    _pickle.dump((payload, mtime), f)
                tmp.replace(_path_for(slot))
            except Exception:
                pass

        def _store(slot, value, mtime):
            memo[slot] = (value, mtime)
            if len(memo) > max_entries:
                for k, _ in sorted(memo.items(), key=lambda kv: kv[1][1])[: len(memo) - max_entries]:
                    memo.pop(k, None)
            _save(slot, value, mtime)

        def _compute(slot, args, kwargs):
            now = _time.time()
            value = fn(*args, **kwargs)
            _store(slot, value, now)
            return value

        def _refresh_in_background(slot, args, kwargs):
            lock = _lock_for(slot)
            if not lock.acquire(blocking=False):
                return  # a refresh for this key is already running

            def _run():
                try:
                    _compute(slot, args, kwargs)
                except Exception:
                    print(f"  [persisted-cache] background refresh of {slot} failed:")
                    traceback.print_exc()
                finally:
                    lock.release()

            threading.Thread(target=_run, daemon=True, name=f"swr:{slot}").start()

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            force = kwargs.pop("_force", False)
            slot = _key_to_slot(slot_base, args, kwargs)
            if force:
                with _lock_for(slot):
                    return _compute(slot, args, kwargs)
            entry = memo.get(slot)
            if entry is None:
                payload, mtime = _load(slot)
                if payload is not None:
                    entry = (payload, mtime)
                    memo[slot] = entry
            if entry is not None:
                if (_time.time() - entry[1]) >= ttl_seconds:
                    _refresh_in_background(slot, args, kwargs)
                return entry[0]
            # Cold: nothing cached anywhere — compute inline, once per key.
            with _lock_for(slot):
                entry = memo.get(slot)
                if entry is not None:
                    return entry[0]  # a concurrent caller just computed it
                return _compute(slot, args, kwargs)

        wrapper.cache_clear = lambda: memo.clear()
        return wrapper

    return decorator


def safe_json_records(data):
    """Convert a DataFrame (or an existing list of record dicts) into JSON-safe
    dicts. Single source of truth for cockpit payload coercion — previously
    re-implemented three different ways (run_sql_query, get_data_freshness,
    get_top_picks._records).

    Coercion rules (order matters — NaN/None checked before the numeric branch
    because numpy NaN is a float and would otherwise pass through):
      - None                       → None
      - float NaN / Inf            → None  (json.dumps emits invalid `NaN`/`Infinity` otherwise)
      - int / float / str / bool   → kept as-is
      - pandas NA                  → None
      - anything else (Timestamp, Decimal, numpy scalar) → str(v)
    """
    import math

    records = data.to_dict("records") if hasattr(data, "to_dict") else data
    out = []
    for record in records:
        clean = {}
        for k, v in record.items():
            if v is None:
                clean[k] = None
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                clean[k] = None
            elif isinstance(v, (int, float, str, bool)):
                clean[k] = v
            else:
                try:
                    if pd.isna(v):
                        clean[k] = None
                        continue
                except (TypeError, ValueError):
                    pass
                clean[k] = str(v)
        out.append(clean)
    return out


# ═══════════════════════════════════════════════════
# App scaffolding shared by cockpit/app.py and cockpit_ops/app.py
# ═══════════════════════════════════════════════════

COCKPIT_DIR = Path(__file__).resolve().parent
COCKPIT_TEMPLATES = COCKPIT_DIR / "templates"
COCKPIT_STATIC = COCKPIT_DIR / "static"  # both apps mount this as /static

from jinja2 import Undefined


class SilentUndefined(Undefined):
    """Jinja undefined that renders as empty / falsy / None-equal instead of
    raising, so templates don't blow up on a missing attribute."""
    def __str__(self): return ""
    def __bool__(self): return False
    def __iter__(self): return iter([])
    def __eq__(self, other): return other is None
    def __ne__(self, other): return other is not None
    def __ge__(self, other): return False
    def __le__(self, other): return False
    def __gt__(self, other): return False
    def __lt__(self, other): return False
    def __float__(self): return 0.0
    def __int__(self): return 0


# Cache-busting for static assets — appends ?v=<mtime> so browser caches
# invalidate automatically whenever a static file is edited.
def asset_version(filename: str) -> str:
    try:
        return str(int((COCKPIT_STATIC / filename).stat().st_mtime))
    except OSError:
        return "0"


def make_templates(dirs):
    """Jinja2Templates searching `dirs` in order, then cockpit/templates — so
    base.html, _components.html and _icons.html exist once and the ops app
    (which passes its own templates dir first) shares them. Registers
    SilentUndefined and the asset_version global."""
    from fastapi.templating import Jinja2Templates
    from jinja2 import ChoiceLoader, FileSystemLoader

    search = [Path(d) for d in dirs]
    if COCKPIT_TEMPLATES not in search:
        search.append(COCKPIT_TEMPLATES)
    templates = Jinja2Templates(directory=search[0])
    templates.env.loader = ChoiceLoader([FileSystemLoader(d) for d in search])
    templates.env.undefined = SilentUndefined
    templates.env.globals["asset_version"] = asset_version
    return templates


def prewarm(warmers, label="cache-warm", max_workers=4):
    """Background-warm expensive caches in PARALLEL so wall-clock matches the
    slowest single warmer rather than the sum. `warmers` is [(name, fn), ...].
    Returns immediately; results are printed as each warmer finishes.
    2026-05-25: parallel after /system's sequential cold path was 39s.
    SQLite is single-writer so unbounded parallelism doesn't help and can
    starve user requests; 4 workers is the sweet spot for our mix."""
    import threading
    import concurrent.futures as cf

    def _warm_one(name, fn):
        t = _time.time()
        try:
            fn()
            return name, _time.time() - t, None
        except Exception as e:
            return name, _time.time() - t, str(e)

    def _warm():
        t0 = _time.time()
        with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = [ex.submit(_warm_one, n, f) for n, f in warmers]
            for fut in cf.as_completed(futures):
                name, dt, err = fut.result()
                if err:
                    print(f"  [{label}] {name}: FAILED — {err}")
                else:
                    print(f"  [{label}] {name}: {dt:.1f}s")
        print(f"  [{label}] total wall-clock: {_time.time()-t0:.1f}s")

    threading.Thread(target=_warm, daemon=True).start()
