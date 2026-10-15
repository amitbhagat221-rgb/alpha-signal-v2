"""
Alpha Signal v2 — whether a fund takes new money, from Kuvera, for funds Groww has no page for
(fallback route of the mf_holdings feed, 2026-10-14).

Groww's fund page is the primary source (sources.mf_holdings_groww). ~100 investable funds have no
Groww page (groww_slug = '') — mostly overseas FoFs and offshore funds, the very funds that close
at the RBI overseas-investment limit — so without this they show no status at all.

Kuvera's public scheme JSON carries `lump_available` / `sip_available` ('Y'/'N') but is keyed by
Kuvera's own code; `mf.captnemo.in/kuvera/{ISIN}` (open-source ISIN → Kuvera redirect) resolves it.
Identity is exact: a response is written only when its ISIN is the one asked for. Kuvera gives no
reason, so closed_reason stays NULL. A suspension is the fund's, so one plan's answer is written on
every plan of the fund, as the Groww route does. Agreement with Groww on funds both cover: 14 of 15
(2026-10-14; the one difference was a SIP flag).

Usage:
    python -m sources.mf_subscription_kuvera --limit 3     # smoke test
    python -m sources.mf_subscription_kuvera               # every due fund (= the daily route)
"""

import argparse

import pandas as pd

import runlog
from db import get_db, read_sql
from sources import _http
from sources.mf_holdings_groww import FUND_ROWS_SQL, NO_PAGE, RECHECK_DAYS

LOOKUP = "https://mf.captnemo.in/kuvera/{isin}"
UNKNOWN = {"lumpsum_open": None, "sip_open": None, "closed_reason": None}


def due_funds(recheck_days: int = RECHECK_DAYS) -> pd.DataFrame:
    """One row per fund Groww has no page for, not checked within `recheck_days`: amc, scheme_name,
    codes, isins (Direct-Growth first — the plan Kuvera always lists)."""
    rows = read_sql(f"""
        SELECT f.scheme_code, f.amc, f.scheme_name, f.isin_growth, sm.plan_type, sm.option_type,
               sm.subscription_checked_at
        FROM ({FUND_ROWS_SQL}) f JOIN mf_scheme_master sm USING (scheme_code)
        WHERE f.groww_slug = ?""", (NO_PAGE,))
    if recheck_days > 0:
        cutoff = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=recheck_days)).strftime("%Y-%m-%d %H:%M:%S")
        stale = rows.groupby(["amc", "scheme_name"])["subscription_checked_at"].transform(
            lambda s: s.isna().any() or s.min() < cutoff)
        rows = rows[stale]
    out = []
    for (amc, name), g in rows.groupby(["amc", "scheme_name"], sort=False):
        g = g.assign(_pref=(g["plan_type"] != "DIRECT").astype(int) + (g["option_type"] != "GROWTH").astype(int))
        isins = [i for i in g.sort_values("_pref")["isin_growth"] if isinstance(i, str) and i.startswith("IN")]
        out.append({"amc": amc, "scheme_name": name, "codes": sorted(g["scheme_code"].astype(str)),
                    "isins": list(dict.fromkeys(isins))})
    return pd.DataFrame(out, columns=["amc", "scheme_name", "codes", "isins"])


def parse(payload, isin: str) -> dict | None:
    """{lumpsum_open, sip_open, closed_reason} from Kuvera's scheme JSON, or None when it is not
    the scheme for `isin` (empty list, another ISIN). Raises ValueError on shape drift."""
    if not isinstance(payload, list):
        raise ValueError(f"Kuvera scheme JSON is {type(payload).__name__}, not a list")
    rows = [d for d in payload if (d.get("ISIN") or d.get("isin")) == isin]
    if not rows:
        return None
    d = rows[0]
    if "lump_available" not in d or "sip_available" not in d:
        raise ValueError("no lump_available / sip_available in Kuvera scheme JSON")
    flag = lambda v: None if v is None else int(str(v).upper() == "Y")
    return {"lumpsum_open": flag(d["lump_available"]), "sip_open": flag(d["sip_available"]), "closed_reason": None}


def _write_status(codes: list[str], status: dict) -> None:
    with get_db() as conn:
        conn.executemany("UPDATE mf_scheme_master SET lumpsum_open = ?, sip_open = ?, closed_reason = ?, "
                         "subscription_checked_at = datetime('now') WHERE scheme_code = ?",
                         [(status["lumpsum_open"], status["sip_open"], status["closed_reason"], c) for c in codes])


def compute(limit: int | None = None, recheck_days: int = RECHECK_DAYS, max_minutes=_http.HOST_BUDGET) -> int:
    """Look up every due fund; returns funds written. Raises when lookups were made and all failed."""
    if max_minutes is _http.HOST_BUDGET:
        max_minutes = _http.host("kuvera")[1]["budget_min"]
    todo = due_funds(recheck_days)
    if limit:
        todo = todo.head(limit)
    print(f"Kuvera: {len(todo)} funds without a Groww page due")
    over_budget = _http.time_budget("kuvera", max_minutes)
    n_ok = n_missing = n_err = 0
    for f in todo.itertuples(index=False):
        if over_budget():
            print("  budget reached — rest continue next run", flush=True)
            break
        status, failed = None, False
        for isin in f.isins[:2]:   # a second plan's ISIN when Kuvera lacks the first
            try:
                r = _http.polite_request("GET", LOOKUP.format(isin=isin), check=False, timeout=30)
                if getattr(r, "status_code", None) == 200:
                    status = parse(r.json(), isin)
                elif getattr(r, "status_code", None) not in (None, 404):
                    raise RuntimeError(f"HTTP {r.status_code}")
            except Exception as e:
                n_err += 1
                failed = True
                runlog.item_error("kuvera scheme", isin, e)
                break
            if status:
                break
        if status:
            _write_status(f.codes, status)
            n_ok += 1
        elif not failed:   # not on Kuvera: unknown, due again in recheck_days (an error keeps the last answer)
            _write_status(f.codes, UNKNOWN)
            n_missing += 1
    print(f"Kuvera done: {n_ok} written · {n_missing} not on Kuvera · {n_err} errors")
    if n_err and not (n_ok or n_missing):
        raise RuntimeError(f"every Kuvera lookup failed ({n_err})")
    return n_ok


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, help="Cap funds looked up (smoke test)")
    p.add_argument("--recheck-days", type=int, default=RECHECK_DAYS, help="Skip funds checked within N days")
    a = p.parse_args()
    compute(limit=a.limit, recheck_days=a.recheck_days)
