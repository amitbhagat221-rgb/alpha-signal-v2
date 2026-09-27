"""
Alpha Signal v2 — the Host door + shared harvest-loop helpers for sources/.

Every external call goes through here, paced per host as declared in
hosts.HOSTS (ADR 0052 invariant 5 "Politeness"). Plain functions (ADR 0004):

  polite_get(url, ...)          GET: host gap + headers + retry/backoff, 404 → None
  polite_request(method, url)   any verb; check=False hands back the raw Response
                                for modules that read redirects/status themselves
  pace(host)                    context manager for library clients that do their own
                                HTTP (yfinance, nselib, feedparser, kiteconnect, …)
  time_budget(host)             "is this run's budget spent?" (moneycontrol: 90 min)
  warm_session(home_url, ...)   requests.Session cookie-warmed on NSE/BSE's home page
  sid_map(col)                  cached {stocks.<col>: sid} lookup
  run_harvester(items, ...)     fetch → count errors → flush every N → RAISE on 0

Gap rule: ≥ the host's gap (+ jitter) between calls to the same host, measured
from the END of the previous call, so a slow response never shortens it. All of
a host's netlocs share one gap; an undeclared netloc is paced on its own.
"""

import contextlib
import random
import time
from urllib.parse import urlsplit

import requests

try:                                   # browser-TLS client for hosts whose WAF fingerprints
    from curl_cffi import requests as _cffi     # python-requests (hosts.HOSTS "impersonate")
    _NET_ERRORS = (requests.ConnectionError, requests.Timeout,
                   _cffi.exceptions.ConnectionError, _cffi.exceptions.Timeout)
    _REQ_ERRORS = (requests.RequestException, _cffi.exceptions.RequestException)
except ImportError:                    # pragma: no cover — curl_cffi ships with yfinance
    _cffi = None
    _NET_ERRORS = (requests.ConnectionError, requests.Timeout)
    _REQ_ERRORS = (requests.RequestException,)

from db import read_sql
from hosts import DEFAULT, HOSTS

_LAST_CALL = {}   # host key → time.monotonic() when its previous call finished
_SID_MAPS = {}    # stocks column → {value: sid}
_NETLOC_HOST = {n: name for name, h in HOSTS.items() for n in h.get("netlocs", ())}
HOST_BUDGET = object()   # time_budget(): "use the host's declared budget_min"

RETRY_STATUS = {429, 500, 502, 503, 504}


def host(url_or_name):
    """(key, entry) for a HOSTS name, a URL or a bare netloc. `entry` is the HOSTS
    entry over DEFAULT; an undeclared netloc keys its own gap with DEFAULT
    politeness. A bare name that isn't declared (a typo) raises KeyError."""
    if url_or_name in HOSTS:
        key = url_or_name
    elif "://" in url_or_name or "." in url_or_name:
        netloc = (urlsplit(url_or_name).netloc or url_or_name).lower()
        key = _NETLOC_HOST.get(netloc, netloc)
    else:
        raise KeyError(f"host {url_or_name!r} is not declared in hosts.HOSTS")
    return key, {**DEFAULT, **HOSTS.get(key, {})}


def _gap(entry):
    jitter = entry["jitter"]
    return entry["gap"] + (random.uniform(0, jitter) if jitter else 0.0)


def _wait_turn(key, gap):
    wait = _LAST_CALL.get(key, float("-inf")) + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)


@contextlib.contextmanager
def pace(url_or_name):
    """Run the body as one call to the host: wait out its gap first, and stamp
    the end of the body as the host's last call. For library clients:
        with pace("yahoo"):
            data = yf.download(...)"""
    key, entry = host(url_or_name)
    _wait_turn(key, _gap(entry))
    try:
        yield
    finally:
        _LAST_CALL[key] = time.monotonic()


def time_budget(url_or_name, minutes=HOST_BUDGET):
    """→ zero-arg fn that turns True once `minutes` (default: the host's
    budget_min) have passed since this call. None / 0 minutes = no budget."""
    if minutes is HOST_BUDGET:
        minutes = host(url_or_name)[1]["budget_min"]
    deadline = time.monotonic() + minutes * 60 if minutes else None
    return lambda: deadline is not None and time.monotonic() > deadline


def _backoff(resp, gap, attempt):
    """Seconds to wait before retry `attempt + 1`: honour a numeric Retry-After
    on 429 (capped at 2 min), else exponential from the host gap (2s, 4s, 8s…)."""
    retry_after = resp.headers.get("Retry-After") if resp is not None else None
    if retry_after and retry_after.isdigit():
        return min(float(retry_after), 120.0)
    return max(gap, 2.0) * (2 ** attempt)


def polite_request(method, url, *, session=None, headers=None, params=None, timeout=15,
                   retries=None, min_gap=None, check=True, **kwargs):
    """`method` `url` through the host door. Returns the Response (None on 404/410
    when `check`).

    - Waits until ≥ the host's gap (`min_gap` overrides) has passed since the
      previous call to the same host ended.
    - Headers: the host's, unless the caller passes `headers` or a `session`
      (a session carries its own; per-call `headers` merge over it, as in requests).
    - Timeouts and connection errors are retried `retries` times (default: the
      host's) with backoff; after that the last error is raised.
    - check=True: 429/5xx are retried too; any other 4xx raises requests.HTTPError
      at once (no retry — a 403 from a WAF only gets worse when hammered).
    - check=False: the Response comes back whatever its status — for modules that
      read redirects / status codes themselves. `kwargs` (data, allow_redirects…)
      pass through to requests.
    """
    key, entry = host(url)
    base_gap = min_gap if min_gap is not None else entry["gap"]
    if retries is None:
        retries = entry["retries"]
    if session is None and headers is None:
        headers = entry["headers"]
    call = getattr(session if session is not None else requests, method.lower())

    for attempt in range(retries + 1):
        _wait_turn(key, base_gap if min_gap is not None else _gap(entry))
        resp = None
        try:
            resp = call(url, headers=headers, params=params, timeout=timeout, **kwargs)
        except _NET_ERRORS as e:
            err = e
        finally:
            _LAST_CALL[key] = time.monotonic()
        if resp is not None:
            if not check:
                return resp
            if resp.status_code in (404, 410):
                return None
            if resp.status_code not in RETRY_STATUS:
                resp.raise_for_status()
                return resp
            err = requests.HTTPError(f"HTTP {resp.status_code} for {url}", response=resp)
        if attempt < retries:
            time.sleep(_backoff(resp, base_gap, attempt))
    raise err


def polite_get(url, **kwargs):
    """GET `url` politely — polite_request("GET", url, **kwargs)."""
    return polite_request("GET", url, **kwargs)


def warm_session(home_url, headers=None):
    """A session carrying `headers` (default: the home host's), with its
    cookie jar warmed by one paced GET of `home_url` — NSE and BSE bot gates set
    their cookies there. A failed warm-up is logged, not raised: the API call that
    follows fails loudly on its own."""
    entry = host(home_url)[1]
    headers = dict(headers or entry["headers"])
    if entry.get("impersonate") and _cffi is not None:
        # The browser fingerprint must stay consistent: let curl_cffi send its own UA.
        headers.pop("User-Agent", None)
        s = _cffi.Session(impersonate=entry["impersonate"])
    else:
        s = requests.Session()
    s.headers.update(headers)
    try:
        polite_get(home_url, session=s, retries=0)
    except _REQ_ERRORS as e:
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


def run_harvester(items, fetch_fn, write_fn, *, flush_every=200, label, host=None):
    """The per-item harvest loop.

    fetch_fn(item) → list of rows ([] / None = no data for this item; an
    exception = an error for this item, counted and logged, never fatal).
    write_fn(rows) → rows written (None → len(rows)); called with the buffer
    every `flush_every` items and at the end. Write errors propagate.
    `host` paces each fetch_fn call as one call to that host — for library
    clients (yfinance, Bharat_sm_data); polite_get callers are paced already.

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
            with (pace(host) if host else contextlib.nullcontext()):
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

    print(f"  {label}: {total} items · {n_ok} with data · {n_err} errors · {n_written} rows written",
          flush=True)
    if total and n_ok == 0:
        raise RuntimeError(
            f"{label}: 0 of {total} items returned data ({n_err} errors"
            + (f"; last: {last_err}" if last_err else "") + ") — source broken or blocked?"
        )
    return n_ok, n_err, n_written
