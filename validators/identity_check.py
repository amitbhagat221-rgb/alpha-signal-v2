"""
Identity Gate — Trust Pipeline Gate 1, Plan 0007 Phase 2.

Verifies that a source's response payload is actually about the entity we asked
for. Catches the BAJAJHLDNG-mc_slug class of bug — fetcher requests SID X,
source returns data for SID Y, fetcher writes Y's data under X without anyone
noticing.

ARCHITECTURE
    Producer side: every fetcher's pre-write path calls verify_identity(
    sid, response, source) and routes WRONG_ENTITY rows to <table>_quarantine
    instead of the live table. UHS Provenance dimension drops to 0 for the
    quarantined row.

    Offline auditor: tools/data_sanity.py:_mc_slug_name_mismatch_check (existing
    nightly audit) becomes the regression-gate of the live identity check
    here. If the live gate ever regresses, the nightly audit re-surfaces the
    drift.

WHAT EACH SOURCE'S VERIFY RULE CHECKS

    moneycontrol  — `_autosuggest()` already requires exact symbol match
                    since the BAJAJHLDNG fix (2026-05-25). This gate adds a
                    page-level check: the URL slug must contain the ticker
                    (case-insensitive) as a path segment.

    yfinance      — yfinance returns data only for the ticker queried (no
                    redirect / autosuggest pitfall). This gate is a cheap
                    sanity check: ticker query == ticker in response symbol.

    tickertape    — Tickertape uses internal sids ("tt_sid"). Response payload
                    carries the sid in the response root; verify_identity
                    asserts response['sid'] (or equivalent) == requested sid.

    screener.in   — The bank/stock page is keyed by ticker in the URL.
                    Response HTML's `<h1>` carries the company name.
                    Verifier asserts the H1 text normalises to a string that
                    contains the stock's expected name fragment (or canonical
                    name match via normalised compare).

    ETMoney       — Slug-based identity (`mf-regular-schemes-portfolio-details
                    -sitemap.xml` listing). Verifier asserts the response URL
                    path segment == the expected slug for the AMFI scheme code
                    we requested. Mismatch → wrong fund's holdings were fetched.

OUTPUTS
    verify_identity returns IdentityVerdict — a tiny named tuple with:
        status: 'PASS' | 'WRONG_ENTITY' | 'UNRESOLVED' | 'NO_RESPONSE'
        expected: what we asked for (name or sid)
        returned: what the source actually gave back
        reason: one-sentence diagnostic

    quarantine_row writes the rejected row + verdict to <table>_quarantine
    and trust_verdicts in one transaction. Returns True if written.

DOWNSTREAM
    UHS roll-up: rows with verdict_overall='QUARANTINED' contribute 0 to the
    factor's dim_provenance when the factor reads from the affected table.
    Phase 5's lineage-completeness gate will leverage this.
"""

import json
import re
from collections import namedtuple
from datetime import datetime
from typing import Optional


IdentityVerdict = namedtuple("IdentityVerdict", ["status", "expected", "returned", "reason"])


# Sources currently wired into the identity gate. Adding a new source means
# (a) adding a verifier function below + (b) listing it here. Anything not in
# this set is treated as UNRESOLVED (defaults to PASS for now; future tightening
# will make UNRESOLVED auto-quarantine for source classes we've audited).
SUPPORTED_SOURCES = {
    "moneycontrol", "yfinance", "tickertape", "screener_in", "etmoney"
}


def verify_identity(
    sid: str,
    response_payload,
    source: str,
    expected_name: Optional[str] = None,
    expected_url_segment: Optional[str] = None,
) -> IdentityVerdict:
    """Dispatch to the source-specific verifier. Returns IdentityVerdict.

    Caller is expected to:
    - branch on verdict.status
    - route to quarantine_row(...) if WRONG_ENTITY
    - write to live table if PASS

    response_payload shape varies per source:
        moneycontrol  — dict with 'url' or 'slug' key; or the response object
        yfinance      — yfinance.Ticker info dict (has 'symbol' key)
        tickertape    — JSON dict with 'sid' or 'symbol' key
        screener_in   — HTML string (BeautifulSoup parses the H1)
        etmoney       — dict with 'slug' or 'url' key
    """
    if source not in SUPPORTED_SOURCES:
        return IdentityVerdict("UNRESOLVED", sid, None,
                                f"source '{source}' not in SUPPORTED_SOURCES — pass-through")

    if response_payload is None:
        return IdentityVerdict("NO_RESPONSE", sid, None, "response was None")

    verifier = {
        "moneycontrol": _verify_moneycontrol,
        "yfinance":     _verify_yfinance,
        "tickertape":   _verify_tickertape,
        "screener_in":  _verify_screener_in,
        "etmoney":      _verify_etmoney,
    }[source]
    return verifier(sid, response_payload, expected_name=expected_name,
                    expected_url_segment=expected_url_segment)


# ─────────── Per-source verifiers ───────────

def _normalise_company_name(s: str) -> str:
    """Strip non-alphanumeric + lowercase. Same pattern as v1 mc_slug matcher."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _mc_slug_company(slug: str) -> str:
    """Company segment of a Moneycontrol slug URL.

    /india/stockpricequote/{industry}/{company}/{MC_CODE} → {company}.
    Mirrors tools/data_sanity.py:_mc_slug_name_mismatch_check._slug_co.
    """
    parts = (slug or "").strip("/").split("/")
    return parts[-2] if len(parts) >= 2 else ""


def _verify_moneycontrol(sid: str, payload, expected_name: Optional[str] = None,
                         expected_url_segment: Optional[str] = None) -> IdentityVerdict:
    """Moneycontrol identity: the slug's company segment must match the stock's
    COMPANY NAME — not the ticker.

    Moneycontrol slugs are company-name-derived (RELIANCE → 'relianceindustries'),
    so the NSE ticker is usually NOT in the slug at all. The previous ticker-
    substring check therefore failed BOTH ways:
      - false PASS  — short ticker accidentally embedded in a wrong company's
                      slug ('cera' in 'kajariaceramics' → Cera Sanitaryware
                      wrongly accepted as Kajaria Ceramics).
      - false QUARANTINE — correct mapping where ticker ≠ company slug
                      (CEATLTD vs 'ceat', BHARTIARTL vs 'bhartiairtel').

    This now mirrors the canonical accept logic in
    tools/data_sanity.py:_mc_slug_name_mismatch_check (its regression twin):
    accept if the normalised slug-company is a substring of the normalised
    company name (or vice versa) OR SequenceMatcher ratio >= 0.55. The ticker-
    substring shortcut was deliberately dropped there 2026-05-31 (it let
    STYL/MUT/APLL wrong-entity slugs through) — keep it dropped here too.

    `expected_name` carries the company name (stocks.name). `expected_url_segment`
    optionally carries the SID so MC_SLUG_OVERRIDES (hand-verified slugs whose
    company segment legitimately differs, e.g. India Power Corp → 'dpsc') can be
    allowlisted, matching the auditor.
    """
    from difflib import SequenceMatcher

    # If payload is a dict with `symbol` (the autosuggest record), require exact
    # match — discovery's upstream safety net (BAJAJHLDNG fix, 2026-05-25).
    if isinstance(payload, dict) and "symbol" in payload:
        returned = (payload.get("symbol") or "").strip().upper()
        if not returned:
            return IdentityVerdict("UNRESOLVED", sid, None, "payload.symbol empty")
        if expected_name and returned == expected_name.strip().upper():
            return IdentityVerdict("PASS", expected_name, returned, "symbol exact match")
        return IdentityVerdict("WRONG_ENTITY", expected_name or sid, returned,
                                f"autosuggest returned '{returned}' for query '{expected_name or sid}'")

    # Otherwise treat payload as the slug/URL we fetched from.
    url = payload if isinstance(payload, str) else (
        payload.get("url") if isinstance(payload, dict) else None
    )
    if not url:
        return IdentityVerdict("UNRESOLVED", sid, None, "no url in moneycontrol payload")

    # Allowlist hand-verified slugs whose company segment legitimately differs.
    override_sid = expected_url_segment or sid
    try:
        from sources.moneycontrol_recos import MC_SLUG_OVERRIDES
        if override_sid in {s for s, slug in MC_SLUG_OVERRIDES.items() if slug}:
            return IdentityVerdict("PASS", expected_name or sid, url,
                                    "MC_SLUG_OVERRIDES hand-verified slug")
    except Exception:
        pass

    if not expected_name:
        return IdentityVerdict("UNRESOLVED", sid, url,
                                "moneycontrol needs expected_name (stocks.name) to verify")

    slug_co = _normalise_company_name(_mc_slug_company(url))
    name_n = _normalise_company_name(expected_name)
    if not slug_co or not name_n:
        return IdentityVerdict("UNRESOLVED", expected_name, url,
                                "slug company segment or name normalises to empty")
    name_in = slug_co in name_n or name_n in slug_co
    ratio = SequenceMatcher(None, slug_co, name_n).ratio()
    if name_in or ratio >= 0.55:
        return IdentityVerdict("PASS", expected_name, url,
                                f"slug '{slug_co}' matches name (ratio={ratio:.2f})")
    return IdentityVerdict("WRONG_ENTITY", expected_name, url,
                            f"slug company '{slug_co}' does not match name "
                            f"'{expected_name}' (ratio={ratio:.2f})")


def _verify_yfinance(sid: str, payload, expected_name: Optional[str] = None,
                     expected_url_segment: Optional[str] = None) -> IdentityVerdict:
    """yfinance identity: info['symbol'] must equal the queried ticker."""
    if not isinstance(payload, dict):
        return IdentityVerdict("UNRESOLVED", sid, None, "yfinance payload not a dict")
    expected = (expected_name or sid).strip().upper()
    returned = (payload.get("symbol") or "").strip().upper()
    if not returned:
        return IdentityVerdict("UNRESOLVED", expected, None, "yfinance payload missing 'symbol'")
    # yfinance returns symbols with .NS / .BO suffix; strip exchange suffix.
    returned_base = returned.split(".")[0]
    if returned_base == expected or returned == expected:
        return IdentityVerdict("PASS", expected, returned, "symbol match")
    return IdentityVerdict("WRONG_ENTITY", expected, returned,
                            f"yfinance returned symbol '{returned}' for query '{expected}'")


def _verify_tickertape(sid: str, payload, expected_name: Optional[str] = None,
                       expected_url_segment: Optional[str] = None) -> IdentityVerdict:
    """Tickertape identity: response root must carry sid or symbol matching the request."""
    if not isinstance(payload, dict):
        return IdentityVerdict("UNRESOLVED", sid, None, "tickertape payload not a dict")
    # Tickertape responses vary — `tt_sid`, `sid`, `symbol` are all possible keys.
    returned = (
        payload.get("tt_sid")
        or payload.get("sid")
        or payload.get("symbol")
        or (payload.get("data") or {}).get("sid")
        or (payload.get("data") or {}).get("symbol")
    )
    if not returned:
        return IdentityVerdict("UNRESOLVED", sid, None,
                                "tickertape payload missing tt_sid / sid / symbol")
    if str(returned).upper() == sid.upper():
        return IdentityVerdict("PASS", sid, returned, "sid match")
    return IdentityVerdict("WRONG_ENTITY", sid, returned,
                            f"tickertape returned identifier '{returned}' for SID '{sid}'")


def _verify_screener_in(sid: str, payload, expected_name: Optional[str] = None,
                        expected_url_segment: Optional[str] = None) -> IdentityVerdict:
    """Screener.in identity: page `<h1>` must contain expected_name (normalised)."""
    if not isinstance(payload, str):
        return IdentityVerdict("UNRESOLVED", sid, None, "screener_in payload not html string")
    if not expected_name:
        return IdentityVerdict("UNRESOLVED", sid, None,
                                "screener_in needs expected_name (stocks.name) to verify")
    # Extract the H1 text. Avoid a full BS4 parse if possible — fast regex first.
    m = re.search(r"<h1[^>]*>(.*?)</h1>", payload, re.IGNORECASE | re.DOTALL)
    if not m:
        return IdentityVerdict("UNRESOLVED", expected_name, None, "no <h1> found in page")
    h1_text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
    h1_norm = _normalise_company_name(h1_text)
    exp_norm = _normalise_company_name(expected_name)
    if not exp_norm:
        return IdentityVerdict("UNRESOLVED", expected_name, h1_text,
                                "expected_name normalises to empty")
    if exp_norm in h1_norm or h1_norm in exp_norm:
        return IdentityVerdict("PASS", expected_name, h1_text, "h1 contains expected name")
    return IdentityVerdict("WRONG_ENTITY", expected_name, h1_text,
                            f"screener.in h1 '{h1_text}' does not match expected '{expected_name}'")


def _verify_etmoney(sid: str, payload, expected_name: Optional[str] = None,
                    expected_url_segment: Optional[str] = None) -> IdentityVerdict:
    """ETMoney identity: response url path segment must contain expected slug."""
    if isinstance(payload, dict):
        url = payload.get("url") or payload.get("slug") or ""
    else:
        url = str(payload) if payload else ""
    if not url:
        return IdentityVerdict("UNRESOLVED", sid, None, "no url/slug in etmoney payload")
    if not expected_url_segment:
        return IdentityVerdict("UNRESOLVED", sid, url,
                                "etmoney needs expected_url_segment to verify")
    if expected_url_segment.lower() in url.lower():
        return IdentityVerdict("PASS", expected_url_segment, url, "url segment match")
    return IdentityVerdict("WRONG_ENTITY", expected_url_segment, url,
                            f"etmoney url '{url}' does not contain '{expected_url_segment}'")


# ─────────── Quarantine + verdict persistence ───────────


def quarantine_row(
    source_table: str,
    row: dict,
    sid: str,
    datum_class: str,
    verdict: IdentityVerdict,
    snapshot_date: Optional[str] = None,
) -> bool:
    """Atomic write: append `row` to <source_table>_quarantine + insert a
    trust_verdicts row with gate_1_identity=0 (FAIL) and verdict_overall='QUARANTINED'.

    Returns True if both writes succeeded.
    """
    from db import get_db
    snapshot_date = snapshot_date or datetime.now().date().isoformat()
    mirror_table = f"{source_table}_quarantine"
    forensic = {
        "_q_failed_gate":     "gate_1_identity",
        "_q_reason":          verdict.reason,
        "_q_quarantined_at":  datetime.now().isoformat(timespec="seconds"),
    }
    payload = {**row, **forensic}
    cols = list(payload.keys())
    placeholders = ",".join("?" * len(cols))
    cols_sql = ",".join(f'"{c}"' for c in cols)
    insert_sql = f'INSERT INTO {mirror_table} ({cols_sql}) VALUES ({placeholders})'
    source_key = json.dumps({k: row.get(k) for k in _likely_pk_cols(source_table)
                              if k in row}, default=str)
    verdict_row = (
        sid, source_table, source_key, datum_class, snapshot_date,
        0,  # gate_1_identity = FAIL
        json.dumps({
            "gate_1_identity": {
                "status":   verdict.status,
                "expected": str(verdict.expected),
                "returned": str(verdict.returned),
                "reason":   verdict.reason,
            }
        }),
        "QUARANTINED",
    )
    try:
        with get_db() as conn:
            conn.execute(insert_sql, [payload[c] for c in cols])
            conn.execute(
                """
                INSERT OR REPLACE INTO trust_verdicts
                  (sid, source_table, source_key, datum_class, snapshot_date,
                   gate_1_identity, reasons_json, verdict_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                verdict_row,
            )
        return True
    except Exception as e:
        # Never let quarantine write failure crash the producer — log and return False
        # so the caller can fall back to "drop the row, don't write live".
        import sys
        print(f"  ⚠ quarantine_row failed for {source_table}/{sid}: {e}", file=sys.stderr)
        return False


def record_verdict(
    sid: str,
    source_table: str,
    source_key: str,
    datum_class: str,
    verdict: IdentityVerdict,
    snapshot_date: Optional[str] = None,
) -> None:
    """For PASS rows: persist a verdict row so downstream knows gate_1 was evaluated.

    Cheap. Reads at the UHS Provenance roll-up time become a single JOIN on
    trust_verdicts. Use whenever a writer calls verify_identity, even on PASS.
    """
    from db import get_db
    snapshot_date = snapshot_date or datetime.now().date().isoformat()
    try:
        with get_db() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trust_verdicts
                  (sid, source_table, source_key, datum_class, snapshot_date,
                   gate_1_identity, reasons_json, verdict_overall)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, source_table, source_key, datum_class, snapshot_date,
                 1 if verdict.status == "PASS" else (0 if verdict.status == "WRONG_ENTITY" else 2),
                 json.dumps({
                     "gate_1_identity": {
                         "status":   verdict.status,
                         "expected": str(verdict.expected),
                         "returned": str(verdict.returned),
                         "reason":   verdict.reason,
                     }
                 }),
                 "TRUSTED" if verdict.status == "PASS" else
                 ("QUARANTINED" if verdict.status == "WRONG_ENTITY" else "PENDING_REVIEW")),
            )
    except Exception as e:
        import sys
        print(f"  ⚠ record_verdict failed for {source_table}/{sid}: {e}", file=sys.stderr)


def _likely_pk_cols(source_table: str) -> list[str]:
    """Best-effort PK identification used to build source_key JSON.

    The table's PK is the deterministic anchor we use to look up the original
    row later (e.g. during forensic review of a quarantine). Hand-mapped per
    table; falls back to ['sid'] if unknown.
    """
    return {
        "broker_recommendations":      ["sid", "broker", "reco_date"],
        "forecast_history":            ["sid", "metric", "period"],
        "analyst_consensus":           ["sid"],
        "analyst_consensus_snapshots": ["sid", "snapshot_date", "source"],
        "consensus_signals":           ["sid", "snapshot_date"],
        "quarterly_income":            ["sid", "period", "end_date"],
        "annual_balance_sheet":        ["sid", "period", "end_date"],
        "annual_cash_flow":            ["sid", "period", "end_date"],
        "banking_metrics":             ["sid", "period_end", "period_type"],
        "mf_holdings":                 ["scheme_code", "as_of_date", "holding_rank"],
        "mf_sector_allocation":        ["scheme_code", "as_of_date", "sector"],
    }.get(source_table, ["sid"])
