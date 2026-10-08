"""Ratchets for the ADR 0052 invariants that nothing enforced (architecture review F10).

Each test freezes today's known violations in an allowlist and fails on
  * a NEW violation (a file not on the list), and
  * a FIXED one still listed — delete it from the allowlist, so the list only shrinks.
Scans tracked Python files only (git ls-files), with the AST — comments don't count.
"""
import ast
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_TOP = {"_archive", "tests", "notebooks"}


def _tracked():
    out = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout.split()
    for rel in out:
        if rel.split("/")[0] in SKIP_TOP or not (ROOT / rel).exists():
            continue
        yield rel, ast.parse((ROOT / rel).read_text())


def _check(found, allowed, rule):
    new, fixed = sorted(set(found) - allowed), sorted(allowed - set(found))
    assert not new, f"{rule}: new violation(s) {new} — fix them, don't extend the allowlist"
    assert not fixed, f"{rule}: {fixed} no longer violate — remove them from the allowlist"


# ── Invariant 1: a Feature sees data only through as-of frames — signals/ must not import db ──
SIGNALS_IMPORTING_DB = {
    "signals/_annual.py", "signals/_prices.py", "signals/accruals.py", "signals/announcement_car.py",
    "signals/asset_growth.py", "signals/book_to_price.py", "signals/consensus.py",
    "signals/earnings_yield.py", "signals/eps_revision.py",
    "signals/financial_signal.py", "signals/fno_iv_factors.py", "signals/fno_oi_factors.py",
    "signals/forensic.py", "signals/governance_events.py", "signals/industry_id.py",
    "signals/insider_signal.py", "signals/macro.py", "signals/macro_betas.py",
    "signals/management_quality.py", "signals/managerial_ability.py", "signals/mf_metrics.py",
    "signals/microstructure.py", "signals/multibagger.py", "signals/nlp_factors.py",
    "signals/nlp_scores.py", "signals/pead.py", "signals/piotroski.py", "signals/promoter.py",
    "signals/regulatory.py", "signals/residual_momentum.py", "signals/revenue_plausibility.py",
    "signals/sector_breadth.py", "signals/sector_briefs.py", "signals/sector_forces.py",
    "signals/sector_momentum.py", "signals/sector_policy.py", "signals/sector_tilt.py",
    "signals/sentiment.py", "signals/smart_money.py",
    "signals/value_composite.py",
}


def _imports_db(tree):
    return any((isinstance(n, ast.Import) and any(a.name == "db" for a in n.names))
               or (isinstance(n, ast.ImportFrom) and n.module == "db") for n in ast.walk(tree))


def test_inv1_signals_do_not_import_db():
    found = [f for f, t in _tracked() if f.startswith("signals/") and _imports_db(t)]
    _check(found, SIGNALS_IMPORTING_DB, "invariant 1 (signals/ imports db)")


# ── Invariant 3: writers don't pick an INSERT mode; OR REPLACE NULLs co-owned columns (CLAUDE.md) ──
INSERT_OR_REPLACE = {
    "db.py",                       # upsert_df fallback for PK-less tables
    "output/sector_dossier.py",    # sector_dossiers — moves to the plan 0016 task queue
    "scoring/regime.py",
    "signals/management_quality.py", "signals/nlp_scores.py", "signals/sector_briefs.py",
    "signals/sector_forces.py",
    "sources/fno_iv.py", "sources/fno_pull.py", "sources/kite_pull.py", "sources/mf_holdings.py",
    "sources/mf_holdings_scrape.py", "sources/news_brief.py", "sources/news_classifier.py",
    "sources/regulatory_classifier.py", "sources/scrip_master.py",
    "tools/build_historical_universe.py", "tools/pit_replay.py",
}


def _or_replace(tree):
    return any(isinstance(n, ast.Constant) and isinstance(n.value, str)
               and "INSERT OR REPLACE" in n.value.upper() for n in ast.walk(tree))


def test_inv3_no_new_insert_or_replace():
    found = [f for f, t in _tracked() if _or_replace(t)]
    _check(found, INSERT_OR_REPLACE, "invariant 3 (INSERT OR REPLACE)")


# ── Invariant 5: every external call goes through the host door (sources/_http) ──
RAW_HTTP = {
    "sources/kite_pull.py",             # dead module (no table in schema.sql)
    "sources/screener_pull.py",         # login POST via its own session helper
    "tools/build_historical_universe.py",
    "tools/health_report.py",           # ntfy push
}
_HTTP_CALLS = {("requests", "get"), ("requests", "post"), ("requests", "request"),
               ("requests", "Session"), ("urllib.request", "urlopen"), ("request", "urlopen"),
               ("httpx", "get"), ("httpx", "post"), ("httpx", "Client")}


def _raw_http(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            v = n.func.value
            base = (v.id if isinstance(v, ast.Name) else
                    f"{v.value.id}.{v.attr}" if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name)
                    else None)
            if (base, n.func.attr) in _HTTP_CALLS:
                return True
    return False


def test_inv5_http_only_through_the_host_door():
    found = [f for f, t in _tracked() if f != "sources/_http.py" and _raw_http(t)]
    _check(found, RAW_HTTP, "invariant 5 (raw HTTP outside sources/_http)")
