"""The picks email marks a tier with no out-of-sample skill the way the cockpit does."""
import views
from output import email_sender


def test_unproven_tier_header_carries_the_marker_and_reason():
    assert email_sender._unproven_note(None) == ""
    html = email_sender._unproven_note(views.NO_OOS_SKILL["LARGE"])
    assert views.UNPROVEN_WORD in html and "out-of-sample skill" in html


def test_email_lists_unproven_tiers_last():
    order = views.display_tiers()
    bad = set(views.unproven_tiers())
    assert [t for t in order if t in bad] == order[len(order) - len(bad):]
