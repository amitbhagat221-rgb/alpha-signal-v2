"""formatting.py — must match the template/email formatting it replaced."""
import math

from formatting import DASH, crore, inr, inr_short, pct, signed, tone


def test_signed_matches_percent_format():
    for x in (1.234, -0.4, 0, 12, -3.05):
        for d in (0, 1, 2):
            assert signed(x, d) == ("%+." + str(d) + "f") % x


def test_pct_inr_crore():
    assert pct(12.345) == "12.3%"
    assert pct(3.0, 0, signed=True) == "+3%"
    assert pct(0.123, 1, scale=100) == "12.3%"
    assert inr(11155.4) == "₹11,155"          # grouped by default
    assert inr(11155.4, group=False) == "₹11155"
    assert inr(1234567, group=True) == "₹1,234,567"
    assert inr(277.104, 2) == "₹277.10"
    assert inr(1234567.5, 1) == "₹1,234,567.5"
    assert crore(250000) == "₹2.5L Cr"
    assert crore(12345.6) == "₹12,346 Cr"
    assert crore(-23) == "-₹23 Cr" and crore(-250000) == "-₹2.5L Cr" and crore(-0.2) == "₹0 Cr"   # a loss


def test_inr_short_indian_units():
    assert inr_short(950) == "₹950" and inr_short(0) == "₹0" and inr_short(-0.4) == "₹0"
    assert inr_short(50_000) == "₹50 K" and inr_short(-2057) == "-₹2.06 K"
    assert inr_short(172_308) == "₹1.72 L" and inr_short(200_000) == "₹2 L"
    assert inr_short(12_500_000) == "₹1.25 Cr"


def test_missing_values_dash():
    for f in (signed, pct, inr, inr_short, crore):
        assert f(None) == DASH and f(float("nan")) == DASH and f("x") == DASH


def test_tone():
    assert tone(2) == "score-green" and tone(-1) == "score-red" and tone(0) == ""
    assert tone(0, zero="score-red") == "score-red"
    assert tone(None) == "" and tone(math.nan) == ""
    assert tone(-5, "#0f0", "#f00", "#888") == "#f00"


def test_count_groups_and_drops_the_decimal():
    from formatting import count
    assert count(3254.0) == "3,254" and count(0) == "0" and count(None) == "—"
