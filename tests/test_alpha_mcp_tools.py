"""
alpha_mcp tool contract on a real DB copy (plan 0016 phase 1 gate): every research
tool and the fast ops tools return JSON under the size cap, carry `as_of`, and keep
their top-level keys. Needs a copy: ALPHA_MCP_TEST_DB=/path/to/copy.db (e.g.
`sqlite3 "file:data/alpha_signal.db?mode=ro" ".backup /tmp/x/copy.db"`); skipped
otherwise. Refuses the live DB. Runs in a subprocess (install_readonly is global).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COPY = os.environ.get("ALPHA_MCP_TEST_DB")
LIVE = (ROOT / "data" / "alpha_signal.db").resolve()

pytestmark = pytest.mark.skipif(not COPY or not Path(COPY).exists(),
                                reason="set ALPHA_MCP_TEST_DB to a DB copy")

CALLS = {  # tool: (python call, top-level keys that must be present)
    "picks": ("R.picks(tier='LARGE', top=5)", {"as_of", "gated", "per_tier", "picks"}),
    "pick_dates": ("R.pick_dates(3)", {"as_of", "items"}),
    "pick_breakdown": ("R.pick_breakdown(R.picks(tier='LARGE', top=1)['picks']['LARGE'][0]['sid'])",
                       {"as_of", "sid", "tier", "rank", "base_score", "contributions", "reproduces_stored_score"}),
    "stock": ("R.stock('RELIANCE')", {"as_of", "sid", "ticker", "cap_tier"}),
    "search_stocks": ("R.search_stocks('tata')", {"as_of", "items"}),
    "stock_financials": ("R.stock_financials('RELI')", {"as_of", "sid", "kind", "quarters"}),
    "stock_ownership": ("R.stock_ownership('RELI')", {"as_of", "shareholding", "insider_by_month", "bulk_deals"}),
    "stock_news": ("R.stock_news('RELI')", {"as_of", "items"}),
    "stock_analyst": ("R.stock_analyst('RELI')", {"as_of", "consensus", "forecast_trend"}),
    "stock_lineage": ("R.stock_lineage('RELI')", {"as_of", "factors_in_registry"}),
    "price_series": ("R.price_series('RELI', 10)", {"as_of", "items"}),
    "factors": ("R.factors_list()", {"as_of", "total", "items"}),
    "factor": ("R.factor('book_to_price')", {"as_of", "id", "status", "evidence", "horizon_gate"}),
    "model_weights": ("R.model_weights()", {"as_of", "weights", "signal_ids"}),
    "ic_evidence": ("R.ic_evidence()", {"as_of", "items", "total"}),
    "regime": ("R.regime()", {"as_of", "regime"}),
    "changes": ("R.changes()", {"as_of", "items"}),
    "book": ("R.book()", {"as_of"}),
    "risk": ("R.risk(['RELI', 'TCS'])", {"as_of", "sids"}),
    "sectors": ("R.sectors()", {"as_of", "items"}),
    "sector": ("R.sector('Materials')", {"as_of", "brief", "regulatory", "macro_contributors"}),
    "macro": ("R.macro()", {"as_of", "items"}),
    "news": ("R.news()", {"as_of", "items"}),
    "regulatory": ("R.regulatory()", {"as_of", "items"}),
    "mf_search": ("R.mf_search('index')", {"as_of", "items"}),
    "sql": ("R.sql('SELECT COUNT(*) AS n FROM stocks')", {"as_of", "rows"}),
    "schema": ("R.schema('stocks')", {"as_of", "columns"}),
    "pipeline_status": ("O.pipeline_status()", {"as_of", "items"}),
    "llm_usage": ("O.llm_usage()", {"as_of", "items"}),
    "queue_status": ("O.queue_status()", {"as_of", "kinds"}),
}


def test_every_tool_on_the_copy():
    assert Path(COPY).resolve() != LIVE, "ALPHA_MCP_TEST_DB must be a copy, not the live DB"
    script = "import json\nfrom alpha_mcp import research as R, ops as O\nout = {}\n" + "".join(
        f"try:\n    out[{k!r}] = {c}\nexcept Exception as e:\n    out[{k!r}] = {{'__error__': repr(e)}}\n"
        for k, (c, _) in CALLS.items()) + "print('@@' + json.dumps(out))\n"
    r = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=900,
                       env={**os.environ, "ALPHA_DB": COPY, "ALPHA_RUNLOG_DB": COPY})
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads(r.stdout.split("@@", 1)[1])
    from alpha_mcp._core import MAX_CHARS
    for name, (_, keys) in CALLS.items():
        res = out[name]
        assert "__error__" not in res, (name, res)
        assert keys <= set(res), (name, keys - set(res))
        assert len(json.dumps(res, separators=(",", ":"))) <= MAX_CHARS + 500, name
    assert out["pick_breakdown"]["reproduces_stored_score"] is True
