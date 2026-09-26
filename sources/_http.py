"""
Alpha Signal v2 — shared HTTP + harvest-loop helpers for sources/.

Plain functions (ADR 0004). Each replaces boilerplate that harvesters used to
copy by hand:

  polite_get(url, ...)          GET with a per-host minimum gap + retry/backoff
  warm_session(home_url, ...)   requests.Session cookie-warmed on NSE/BSE's home page
  sid_map(col)                  cached {stocks.<col>: sid} lookup
  run_harvester(items, ...)     fetch → count errors → flush every N → RAISE on 0

Rate policy (CLAUDE.md): ≥2s between calls to the same host. The gap is measured
from the END of the previous request to that host, so a slow response never
shortens it. Documented per-host exceptions live in config.API["host_min_gap"].
"""

import time
from urllib.parse import urlsplit

import requests

from config import API
from db import read_sql

_LAST_CALL = {}   # host → time.monotonic() when its previous request finished
_SID_MAPS = {}    # stocks column → {value: sid}

RETRY_STATUS = {429, 500, 502, 503, 504}


def _wait_turn(host, gap):
    wait = _LAST_CALL.get(host, float("-inf")) + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def _backoff(resp, gap, attempt):
    """Seconds to wait before retry `attempt + 1`: honour a numeric Retry-After
    on 429 (capped at 2 min), else exponential from the host gap (2s, 4s, 8s…)."""
    retry_after = resp.headers.get("Retry-After") if resp is not None else None
    if retry_after and retry_after.isdigit():
        return min(float(retry_after), 120.0)
    return max(gap, 2.0) * (2 ** attempt)


def polite_get(url, *, session=None, headers=None, params=None, timeout=15, retries=2, min_gap=None):
    """GET `url` politely. Returns the Response, or None on 404/410.

    - Waits until ≥ `min_gap` seconds (default: config.API per-host gap) have
      passed since the previous request to the same host ended.
    - Timeouts, connection errors, 429 and 5xx are retried `retries` times with
      backoff; after that the last error is raised.
    - Any other 4xx raises requests.HTTPError at once (no retry — a 403 from a
      WAF only gets worse when hammered).
    """
    host = urlsplit(url).netloc.lower()
    gap = min_gap if min_gap is not None else API["host_min_gap"].get(host, API["min_gap"])
    if session is None and headers is None:
        headers = {"User-Agent": API["user_agent"]}
    getter = session.get if session is not None else requests.get

    for attempt in range(retries + 1):
        _wait_turn(host, gap)
        resp = None
        try:
            resp = getter(url, headers=headers, params=params, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as e:
            err = e
        finally:
            _LAST_CALL[host] = time.monotonic()
        if resp is not None:
            if resp.status_code in (404, 410):
                return None
            if resp.status_code not in RETRY_STATUS:
                resp.raise_for_status()
                return resp
            err = requests.HTTPError(f"HTTP {resp.status_code} for {url}", response=resp)
        if attempt < retries:
            time.sleep(_backoff(resp, gap, attempt))
    raise err


def warm_session(home_url, headers=None):
    """requests.Session carrying `headers` (default: the API user agent), with its
    cookie jar warmed by one paced GET of `home_url` — NSE and BSE bot gates set
    their cookies there. A failed warm-up is logged, not raised: the API call that
    follows fails loudly on its own."""
    s = requests.Session()
    s.headers.update(headers or {"User-Agent": API["user_agent"]})
    try:
        polite_get(home_url, session=s, retries=0)
    except requests.RequestException as e:
        print(f"  cookie warm-up {home_url} failed: {type(e).__name__}: {e}")
    return s


def sid_map(col="ticker"):
    """Cached {stocks.<col>: sid} for rows where <col> is set.

    No case-folding: stocks.ticker is stored upper-case (verified 2026-09-26 —
    0 of 2,448 differ from UPPER(ticker)), and NSE symbols arrive upper-case.
    Cached per process; callers must not mutate the returned dict."""
    if col not in _SID_MAPS:
        df = read_sql(f"SELECT sid, [{col}] AS k FROM stocks WHERE [{col}] IS NOT NULL")
        _SID_MAPS[col] = dict(zip(df["k"], df["sid"]))
    return _SID_MAPS[col]


def run_harvester(items, fetch_fn, write_fn, *, flush_every=200, label, delay=0.0):
    """The per-item harvest loop.

    fetch_fn(item) → list of rows ([] / None = no data for this item; an
    exception = an error for this item, counted and logged, never fatal).
    write_fn(rows) → rows written (None → len(rows)); called with the buffer
    every `flush_every` items and at the end. Write errors propagate.
    `delay` sleeps between items — for clients that don't go through
    polite_get (yfinance, Bharat_sm_data), which paces itself.

    Returns (n_ok, n_err, n_written); n_ok counts items that yielded ≥1 row.
    RAISES RuntimeError when there were items but none yielded a row — a
    broken source must not report SUCCESS with 0 rows (CLAUDE.md).
    """
    items = list(items)
    total = len(items)
    buf = []
    n_ok = n_err = n_written = 0
    last_err = None
    for i, item in enumerate(items, 1):
        try:
            rows = fetch_fn(item)
        except Exception as e:
            n_err += 1
            last_err = f"{item!r}: {type(e).__name__}: {e}"
            if n_err <= 3:
                print(f"  {label}: {last_err}", flush=True)
            rows = None
        if rows:
            n_ok += 1
            buf.extend(rows)
        if buf and (i % flush_every == 0 or i == total):
            n = write_fn(buf)
            n_written += len(buf) if n is None else n
            buf = []
        if i % flush_every == 0:
            print(f"  [{i}/{total}] {label}: ok={n_ok} err={n_err} written={n_written}", flush=True)
        if delay and i < total:
            time.sleep(delay)

    print(f"  {label}: {total} items · {n_ok} with data · {n_err} errors · {n_written} rows written",
          flush=True)
    if total and n_ok == 0:
        raise RuntimeError(
            f"{label}: 0 of {total} items returned data ({n_err} errors"
            + (f"; last: {last_err}" if last_err else "") + ") — source broken or blocked?"
        )
    return n_ok, n_err, n_written
