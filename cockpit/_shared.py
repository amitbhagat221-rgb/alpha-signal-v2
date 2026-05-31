"""
Alpha Signal Cockpit — shared helpers (cache decorators + JSON coercion).

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
# from disk (~ms) instead of recomputing (~5-17s). Background refresh kicks
# off the next time TTL expires. Use for the heaviest cockpit endpoints.
# 2026-05-25: added after /system cold-restart was 28-39s.
_PERSISTED_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / ".cockpit_cache"


def _persisted_cache(ttl_seconds, name=None):
    """Disk-backed sibling of _ttl_cache. Keyed by (args, kwargs) — each unique
    arg combo gets its own pickle file. Use sparingly for heavy functions where
    the arg space is small (e.g. news pool keyed by hours ∈ {24,72,168,720})."""
    import pickle as _pickle

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
            try:
                _PERSISTED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with _path_for(slot).open("wb") as f:
                    _pickle.dump((payload, mtime), f)
            except Exception:
                pass

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            force = kwargs.pop("_force", False)
            now = _time.time()
            slot = _key_to_slot(slot_base, args, kwargs)
            entry = memo.get(slot)
            if entry is None and not force:
                payload, mtime = _load(slot)
                if payload is not None:
                    entry = (payload, mtime)
                    memo[slot] = entry
            if not force and entry is not None and (now - entry[1]) < ttl_seconds:
                return entry[0]
            value = fn(*args, **kwargs)
            memo[slot] = (value, now)
            _save(slot, value, now)
            return value

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
