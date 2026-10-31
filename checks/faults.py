"""
The daily data-fault check (plan 0032, ADR 0085): the weekly data-quality probes whose
hits reach today's ranking, run every morning.

tools/dq_probes.RULES are the dq-auditor's weekly evidence. A rule whose `touches` names
a wired factor or the tiers (dq_probes.pick_rules) cannot wait for Sunday: a vendor share
count 10x out sets a stock's tier today, a stale annual feeds every balance-sheet factor
today. This check runs those rules and fails when any fires, naming the worst one. The
seat still judges each finding on Sunday; this is the alarm, not the verdict.
"""
from checks import WARN


def _daily():
    from tools import dq_probes
    return dq_probes.daily()


CHECKS = [
    {
        "code": "DATA_FAULT_IN_PICK_INPUTS",
        "table": "fundamentals_screener",
        "column": "—",
        "theme": "correct",
        "message": "A data-quality rule the ranking depends on is firing",
        "why": "These are the faults the forensic research found by reading filings (plan 0027): a share count "
               "10x out, annuals that stopped, a one-off booked as sales, a tax write-back as profit. Each one "
               "reaches a wired factor or a tier the same morning it appears.",
        "fix": "`python -m tools.dq_probes` lists the rule, the stocks and the query. The dq-auditor's Sunday memo "
               "judges it and drafts the fix order; a WARN that stands for two weeks is a 'fix at the source' job "
               "for the data-engineer (docs/plans/0027-forensic-data-audit.md).",
        "severity": WARN,
        "fn": _daily,
    },
]
