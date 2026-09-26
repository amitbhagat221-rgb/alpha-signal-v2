"""
Per-signal eligibility registry — "who SHOULD have a score for this signal?"

Each entry maps a signal_id (matching SIGNAL_WEIGHTS keys in config.py) to a
SQL that returns the SIDs eligible to receive a score. A SID being INELIGIBLE
is NOT a defect — it's a deliberate exclusion from that signal's contribution
to the rank.

Consumed by:
  • tools/refresh_eligibility.py — nightly populates `universe_eligibility` table
  • scoring/screener.py — computes `eligible_coverage` distinct from `weight_coverage`
    (so a small-cap with no analyst attribution isn't penalised for the missing
    consensus_signal — that signal was never going to be available)
  • cockpit/api.py — surfaces per-signal eligible/covered in Health Center

Plan 0005 Phase A. See docs/plans/0005-data-confidence-to-95.md.
"""

# Each entry: signal_id (the config.SIGNAL_WEIGHTS key) →
# dict with `description` (human) and `eligible_sql` (returns DISTINCT sid).
# Declared per factor ("eligibility") in factors.py; this is the derived view.
from factors import SIGNAL_ELIGIBILITY  # noqa: E402


# Universe baseline — every sid we're tracking. Used to compute INELIGIBLE rows.
UNIVERSE_SQL = "SELECT sid FROM stocks WHERE ticker IS NOT NULL"


def all_signals():
    """List the signal_ids the registry knows about."""
    return list(SIGNAL_ELIGIBILITY.keys())
