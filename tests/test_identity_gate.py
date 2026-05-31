"""
Identity Gate poison tests — Plan 0007 Phase 2.

Run: python -m tests.test_identity_gate
or:  pytest tests/test_identity_gate.py

Verifies the Trust Pipeline Gate 1 (Identity) catches every documented
historic-bug pattern that should have been blocked at fetch time but wasn't.

THE BAJAJHLDNG CASE
    2026-05-25: 21% of moneycontrol slug mappings pointed at the wrong
    company. `BAJAJHLDNG` → Bajaj Finance URL → 1,115 contaminated rows
    in broker_recommendations. Passed every freshness, range, schema,
    null check; surfaced only by user spot-check after 20+ days.

    This test deliberately feeds the gate a wrong-entity response and
    asserts the row routes to broker_recommendations_quarantine instead
    of the live table. If this test ever passes, the gate is broken.
"""
from validators.identity_check import (
    verify_identity, _verify_moneycontrol, _verify_yfinance,
    _verify_tickertape, _verify_screener_in, _verify_etmoney,
)


# ─────────── Moneycontrol identity verifier ───────────

def test_moneycontrol_autosuggest_pass_on_exact_symbol_match():
    """The autosuggest fix (commit 0d8d8bd) is verified by gate 1."""
    payload = {"symbol": "BAJAJHLDNG", "url": "/india/stockpricequote/financials/bajajholdings/BHC02"}
    v = verify_identity("BAJHL", payload, source="moneycontrol",
                        expected_name="BAJAJHLDNG")
    assert v.status == "PASS", f"expected PASS, got {v.status}: {v.reason}"


def test_moneycontrol_autosuggest_quarantines_wrong_symbol():
    """THE BAJAJHLDNG CASE — autosuggest returned the wrong company's slug."""
    payload = {
        "symbol": "BAJFINANCE",   # The contaminating value — wrong company
        "url": "/india/stockpricequote/finance-investments/bajajfinance/BAF",
    }
    v = verify_identity("BAJHL", payload, source="moneycontrol",
                        expected_name="BAJAJHLDNG")
    assert v.status == "WRONG_ENTITY", (
        f"BAJAJHLDNG-class bug should be WRONG_ENTITY but got {v.status}"
    )
    assert "BAJFINANCE" in v.returned
    assert "BAJAJHLDNG" in str(v.expected)


def test_moneycontrol_url_segment_pass():
    """When payload is a URL string, the gate matches the slug's company segment
    against the COMPANY NAME (slugs are name-derived, not ticker-derived)."""
    url = "/india/stockpricequote/finance-investments/relianceindustries/REI"
    v = verify_identity("RELI", url, source="moneycontrol",
                        expected_name="Reliance Industries Ltd")
    assert v.status == "PASS", v.reason


def test_moneycontrol_url_segment_quarantine():
    """URL pointing at a DIFFERENT company must quarantine."""
    url = "/india/stockpricequote/refineries/indianoilcorporation/IOC"
    v = verify_identity("ITC", url, source="moneycontrol",
                        expected_name="ITC Ltd")
    assert v.status == "WRONG_ENTITY", (
        f"ITC name vs indianoilcorporation slug must quarantine; got {v.status}: {v.reason}"
    )


def test_moneycontrol_no_false_pass_on_embedded_ticker():
    """Regression (audit 2026-05-31): the old ticker-substring check FALSE-PASSED
    when a short ticker was embedded in a wrong company's slug — 'cera' lives
    inside 'kajariacera-mics'. Name-based matching must reject it."""
    url = "/india/stockpricequote/sanitaryware/kajariaceramics/KC11"
    v = verify_identity("CERA", url, source="moneycontrol",
                        expected_name="Cera Sanitaryware Ltd")
    assert v.status == "WRONG_ENTITY", (
        f"Cera Sanitaryware ≠ Kajaria Ceramics must quarantine; got {v.status}: {v.reason}"
    )


def test_moneycontrol_no_false_quarantine_when_ticker_unlike_slug():
    """Regression (audit 2026-05-31): the old check FALSE-QUARANTINED correct
    mappings where the NSE ticker differs from the company slug
    (CEATLTD→'ceat', BHARTIARTL→'bhartiairtel'). Name-based matching passes them."""
    for ticker, name, url in [
        ("CEATLTD",   "CEAT Ltd",          "/india/stockpricequote/tyres/ceat/C07"),
        ("BHARTIARTL","Bharti Airtel Ltd", "/india/stockpricequote/telecommunications-service/bhartiairtel/BA08"),
    ]:
        v = verify_identity(ticker, url, source="moneycontrol", expected_name=name)
        assert v.status == "PASS", f"{ticker} should PASS; got {v.status}: {v.reason}"


def test_moneycontrol_override_allowlist_passes_legit_mismatch():
    """MC_SLUG_OVERRIDES pins hand-verified slugs whose company segment
    legitimately differs from the name (India Power Corp → 'dpsc'). Passing the
    SID via expected_url_segment must allowlist it."""
    url = "/india/stockpricequote/power-generationdistribution/dpsc/DPS"
    v = verify_identity("DPSC", url, source="moneycontrol",
                        expected_name="India Power Corporation Ltd",
                        expected_url_segment="DPSC")
    assert v.status == "PASS", f"override should PASS; got {v.status}: {v.reason}"


# ─────────── yfinance identity verifier ───────────

def test_yfinance_symbol_match_passes():
    """yfinance returns info['symbol']; must equal queried ticker."""
    payload = {"symbol": "RELIANCE.NS", "targetMeanPrice": 1450.0}
    v = verify_identity("RELI", payload, source="yfinance",
                        expected_name="RELIANCE")
    assert v.status == "PASS", v.reason


def test_yfinance_symbol_mismatch_quarantines():
    """yfinance returning a different symbol for our query → WRONG_ENTITY."""
    payload = {"symbol": "RELIANCEPP.NS", "targetMeanPrice": 12.5}
    v = verify_identity("RELI", payload, source="yfinance",
                        expected_name="RELIANCE")
    assert v.status == "WRONG_ENTITY", v.reason


def test_yfinance_missing_symbol_is_unresolved():
    """No symbol in payload → UNRESOLVED, not WRONG_ENTITY."""
    payload = {"targetMeanPrice": 1450.0}
    v = verify_identity("RELI", payload, source="yfinance",
                        expected_name="RELIANCE")
    assert v.status == "UNRESOLVED"


# ─────────── Tickertape identity verifier ───────────

def test_tickertape_sid_match_passes():
    payload = {"tt_sid": "RELI", "data": {"sid": "RELI", "name": "Reliance Industries"}}
    v = verify_identity("RELI", payload, source="tickertape")
    assert v.status == "PASS"


def test_tickertape_sid_mismatch_quarantines():
    payload = {"tt_sid": "INFY", "data": {"name": "Infosys"}}
    v = verify_identity("RELI", payload, source="tickertape")
    assert v.status == "WRONG_ENTITY"


def test_tickertape_payload_data_nested_lookup():
    """Some Tickertape APIs return sid inside a nested 'data' key."""
    payload = {"data": {"sid": "RELI"}}
    v = verify_identity("RELI", payload, source="tickertape")
    assert v.status == "PASS"


# ─────────── Screener.in identity verifier ───────────

def test_screener_in_h1_match_passes():
    html = "<html><body><h1>HDFC Bank Ltd.</h1><p>...</p></body></html>"
    v = verify_identity("HDBK", html, source="screener_in",
                        expected_name="HDFC Bank Ltd")
    assert v.status == "PASS"


def test_screener_in_h1_mismatch_quarantines():
    """The classic banking_metrics redirect risk."""
    html = "<html><body><h1>Bajaj Finance Limited</h1></body></html>"
    v = verify_identity("BAJHL", html, source="screener_in",
                        expected_name="Bajaj Holdings")
    assert v.status == "WRONG_ENTITY"


def test_screener_in_no_h1_is_unresolved():
    html = "<html><body><p>Lorem ipsum</p></body></html>"
    v = verify_identity("RELI", html, source="screener_in",
                        expected_name="Reliance")
    assert v.status == "UNRESOLVED"


# ─────────── ETMoney identity verifier ───────────

def test_etmoney_url_segment_passes():
    payload = {"url": "https://www.etmoney.com/mutual-funds/sbi-multi-cap-fund/12345"}
    v = verify_identity("122639", payload, source="etmoney",
                        expected_url_segment="sbi-multi-cap-fund")
    assert v.status == "PASS"


def test_etmoney_url_segment_mismatch_quarantines():
    """If ETMoney sent us a different fund's page than the slug we expected."""
    payload = {"url": "https://www.etmoney.com/mutual-funds/some-other-fund/99999"}
    v = verify_identity("122639", payload, source="etmoney",
                        expected_url_segment="sbi-multi-cap-fund")
    assert v.status == "WRONG_ENTITY"


# ─────────── Quarantine + verdict persistence integration ───────────

def test_quarantine_row_writes_to_mirror_and_verdict():
    """Integration: feeding a poisoned payload through the full producer path
    writes to broker_recommendations_quarantine + trust_verdicts but NOT
    broker_recommendations.

    Uses the real DB (single-user dev environment); cleans up the test rows.
    """
    from db import get_db
    from validators.identity_check import quarantine_row, IdentityVerdict

    test_sid = "_TEST_IDENTITY_GATE_BAJHL"
    test_broker = "_TEST_BROKER"
    test_reco_date = "1999-01-01"   # far past so won't collide with real data

    # Cleanup from prior runs
    with get_db() as conn:
        conn.execute("DELETE FROM broker_recommendations_quarantine WHERE sid=?", (test_sid,))
        conn.execute("DELETE FROM trust_verdicts WHERE sid=?", (test_sid,))

    poison_row = {
        "sid": test_sid, "broker": test_broker, "reco_date": test_reco_date,
        "reco_type": "BUY", "reco_price": 100.0, "target_price": 999.0,
        "report_url": "https://wrong-company.com/foo",
        "fetched_at": "1999-01-01 00:00:00",
    }
    verdict = IdentityVerdict(
        "WRONG_ENTITY", "BAJAJHLDNG", "BAJFINANCE",
        "autosuggest returned BAJFINANCE for query BAJAJHLDNG",
    )

    ok = quarantine_row(
        source_table="broker_recommendations",
        row=poison_row, sid=test_sid, datum_class="broker_target_price",
        verdict=verdict,
    )
    assert ok, "quarantine_row returned False"

    with get_db() as conn:
        q = conn.execute(
            "SELECT * FROM broker_recommendations_quarantine WHERE sid=?", (test_sid,)
        ).fetchone()
        assert q is not None, "row didn't land in broker_recommendations_quarantine"

        live = conn.execute(
            "SELECT * FROM broker_recommendations WHERE sid=?", (test_sid,)
        ).fetchone()
        assert live is None, "POISON row leaked into live broker_recommendations table!"

        verdict_row = conn.execute(
            "SELECT gate_1_identity, verdict_overall FROM trust_verdicts WHERE sid=?", (test_sid,)
        ).fetchone()
        assert verdict_row is not None, "no trust_verdicts row written"
        assert verdict_row[0] == 0, f"gate_1_identity should be 0 (FAIL), got {verdict_row[0]}"
        assert verdict_row[1] == "QUARANTINED", f"verdict_overall should be QUARANTINED, got {verdict_row[1]}"

        # Cleanup
        conn.execute("DELETE FROM broker_recommendations_quarantine WHERE sid=?", (test_sid,))
        conn.execute("DELETE FROM trust_verdicts WHERE sid=?", (test_sid,))


if __name__ == "__main__":
    import inspect
    import sys

    tests = [(name, fn) for name, fn in globals().items()
              if name.startswith("test_") and inspect.isfunction(fn)]
    failures = []
    for name, fn in tests:
        try:
            fn()
            print(f"  ✓ {name}")
        except AssertionError as e:
            print(f"  ✗ {name}: {e}")
            failures.append(name)
        except Exception as e:
            print(f"  ✗ {name}: {type(e).__name__}: {e}")
            failures.append(name)
    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    if failures:
        sys.exit(1)
