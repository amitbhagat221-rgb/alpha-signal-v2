"""The Zerodha rules catalogue (docs/reference/zerodha-kite-constraints.md) and the code that enforces it stay in step."""
import re
from pathlib import Path

import options_live as ol
from sources import kite_pull as kp

DOC = Path(__file__).resolve().parents[1] / "docs" / "reference" / "zerodha-kite-constraints.md"


def test_the_catalogue_names_every_control_the_code_has():
    text = DOC.read_text()
    for needle in ("SAFE_LOGIN_IST", "login_info", "profile()", "preflight", "cached_only=True", "variety=\"amo\"",
                   "ALERT_CALL_URL", "15:45", "08:30", "400/min", "5,000/day", "25 modifications"):
        assert needle in text, needle


def test_the_code_matches_the_catalogue():
    assert kp.SAFE_LOGIN_IST == "08:30"
    assert ol.OPTIONS_LIVE["reprice_every_s"] >= 20            # ≤ 25 modifications per order over a 5-minute window
    assert "Kite holds MORE short" in ol.preflight.__doc__ or "MORE short" in ol.preflight.__doc__
    src = Path(ol.__file__).read_text()
    assert 'order_type="LIMIT"' in src or "'LIMIT'" in src or '"LIMIT"' in src   # never a market order
    assert "MARKET" not in re.findall(r'order_type=\s*"(\w+)"', src)
