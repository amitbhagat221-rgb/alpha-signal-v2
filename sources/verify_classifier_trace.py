"""
Verify the classifier audit-trail (classifier_status column on regulatory_events) works.

This test does NOT call the Anthropic API. It mocks the Haiku/Sonnet calls and
checks that classifier_status is updated correctly through every code path:

  1. Haiku says NO  → classifier_status = 'haiku_rejected'
  2. Haiku says YES + Sonnet succeeds → classifier_status = 'classified'
  3. Haiku says YES + Sonnet fails    → classifier_status = 'haiku_passed_sonnet_failed'
  4. Haiku raises an exception        → classifier_status unchanged (retry-safe)

Run: python -m sources.verify_classifier_trace
"""

import sys
from datetime import datetime
from unittest.mock import patch, MagicMock

import pandas as pd

from db import get_db, read_sql, insert_df


TEST_EVENT_IDS = [
    "verify_test_haiku_no",
    "verify_test_full_classified",
    "verify_test_sonnet_fail",
    "verify_test_haiku_error",
]


def _cleanup():
    """Remove any test rows from prior verification runs."""
    with get_db() as conn:
        for eid in TEST_EVENT_IDS:
            conn.execute("DELETE FROM regulatory_signals WHERE event_id = ?", (eid,))
            conn.execute("DELETE FROM regulatory_events WHERE event_id = ?", (eid,))


def _seed_test_events():
    """Insert 4 test events with classifier_status='pending'."""
    rows = [
        {
            "event_id": eid,
            "title": f"Verify trace test event {i+1}",
            "summary": "synthetic test event for classifier trace verification",
            "source": "verify_test",
            "source_url": None,
            "published_at": "2026-04-11T00:00:00",
            "ministry": None,
            "classifier_status": "pending",
            "classifier_processed_at": None,
        }
        for i, eid in enumerate(TEST_EVENT_IDS)
    ]
    insert_df(pd.DataFrame(rows), "regulatory_events")


def _get_status(event_id):
    df = read_sql(
        "SELECT classifier_status, classifier_processed_at FROM regulatory_events WHERE event_id = ?",
        params=[event_id],
    )
    if df.empty:
        return None, None
    return df.iloc[0]["classifier_status"], df.iloc[0]["classifier_processed_at"]


def _make_mock_client(mode):
    """Build a fake Anthropic client whose responses simulate one classifier scenario."""
    client = MagicMock()

    def messages_create(model, max_tokens, messages):
        prompt_text = messages[0]["content"]
        is_haiku = max_tokens <= 10  # PREFILTER uses max_tokens=5

        resp = MagicMock()
        resp.content = [MagicMock()]

        if is_haiku:
            if mode == "haiku_no":
                resp.content[0].text = "NO"
            elif mode == "haiku_error":
                raise RuntimeError("simulated Haiku API error")
            else:
                resp.content[0].text = "YES"
        else:  # Sonnet
            if mode == "sonnet_fail":
                resp.content[0].text = "this is not valid JSON {{{"
            elif mode == "full_classified":
                resp.content[0].text = (
                    '{"is_regulatory": true, "stage": "notification", '
                    '"ministry": "RBI", '
                    '"sectors_affected": [{"sector": "Financial Services", '
                    '"direction": 1, "magnitude": "minor", '
                    '"time_horizon": "3mo", "confidence": "low", '
                    '"reasoning": "synthetic test signal"}]}'
                )

        return resp

    client.messages.create = messages_create
    return client


def run_verification():
    print("=" * 60)
    print("Classifier trace verification (no API calls)")
    print("=" * 60)

    _cleanup()
    _seed_test_events()

    initial = read_sql(
        "SELECT event_id, classifier_status FROM regulatory_events WHERE event_id LIKE 'verify_test_%' ORDER BY event_id"
    )
    print("\n[Setup] All test events seeded as 'pending':")
    print(initial.to_string(index=False))

    from sources import regulatory_classifier as rc

    # Each scenario: which test event_id we run, what mock client we use, expected final state
    scenarios = [
        ("verify_test_haiku_no", "haiku_no", "haiku_rejected"),
        ("verify_test_full_classified", "full_classified", "classified"),
        ("verify_test_sonnet_fail", "sonnet_fail", "haiku_passed_sonnet_failed"),
        ("verify_test_haiku_error", "haiku_error", "pending"),  # error → unchanged
    ]

    print("\n[Test] Running each scenario through classify_events():")
    results = []
    for event_id, mode, expected in scenarios:
        # Patch _get_client AND time.sleep so test runs instantly
        with patch.object(rc, "_get_client", return_value=_make_mock_client(mode)), \
             patch.object(rc.time, "sleep", lambda *a, **k: None):
            # Build a single-event DataFrame to make read_sql return only this event
            with patch.object(rc, "read_sql") as mock_read_sql:
                mock_read_sql.return_value = pd.DataFrame([{
                    "event_id": event_id,
                    "title": "test event",
                    "summary": "test summary",
                    "source": "verify_test",
                    "published_at": "2026-04-11T00:00:00",
                }])
                try:
                    rc.classify_events(limit=1)
                except Exception as e:
                    if mode != "haiku_error":
                        print(f"  UNEXPECTED EXCEPTION in {mode}: {e}")

        actual_status, processed_at = _get_status(event_id)
        ok = actual_status == expected
        status_icon = "OK" if ok else "FAIL"
        print(f"  [{status_icon}] {mode:25s} → expected={expected:30s} actual={actual_status}")
        results.append((mode, expected, actual_status, ok))

    # Cleanup
    _cleanup()

    # Summary
    n_pass = sum(1 for *_, ok in results if ok)
    n_total = len(results)
    print(f"\n[Result] {n_pass}/{n_total} scenarios passed")
    if n_pass != n_total:
        print("\nFAILED scenarios:")
        for mode, expected, actual, ok in results:
            if not ok:
                print(f"  {mode}: expected '{expected}' but got '{actual}'")
        sys.exit(1)
    print("All trace updates working correctly.")


if __name__ == "__main__":
    run_verification()
