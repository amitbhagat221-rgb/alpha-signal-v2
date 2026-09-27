"""
Alpha Signal v2 — named read-models (the View block, ADR 0052 / plan 0015).

A surface (email, dossier, cockpit page) asks for a concept by name here instead
of writing its own SQL, so every surface shows the same thing. Plan 0015 Phase 5
moves the cockpit onto this module; Phase 0 starts it with the picks the email and
the dossier generator must agree on.
"""
from db import read_sql

# The published pick set: today's ranked universe minus integrity FAILs and the
# UHS AVOID band (< 60; plan 0007 Phase 5). NULL uhs_score = rows pre-dating UHS.
_PUBLISHED_PICKS_SQL = """
    SELECT
      dp.sid, dp.final_score, dp.rank, dp.cap_tier, dp.sector,
      dp.uhs_score, dp.uhs_label, dp.uhs_worst_dim,
      s.ticker, s.name, s.pe_ratio, s.pb_ratio, s.roe, s.market_cap_cr,
      ds.close_price, ds.piotroski_f, ds.earnings_yield, ds.delivery_pct,
      ds.consensus_signal, ds.promoter_qoq, ds.cf_accruals, ds.smart_money,
      ds.mom_6m, ds.mom_12m, ds.sentiment_7d
    FROM daily_picks dp
    JOIN stocks s ON dp.sid = s.sid
    LEFT JOIN daily_snapshots ds ON dp.sid = ds.sid
          AND ds.snapshot_date = dp.pick_date
    WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
      AND (dp.integrity_status IS NULL OR dp.integrity_status != 'FAIL')
      AND (dp.uhs_score IS NULL OR dp.uhs_score >= 60)
    ORDER BY dp.cap_tier, dp.rank
"""


def published_picks(per_tier=None):
    """Latest pick date's published picks, ordered by tier then rank.

    per_tier: None = all; "book" = config.PORTFOLIO["picks_per_tier"] (the 5/5/5
    set the email shows and the dossier generator narrates); or an int per tier.
    """
    picks = read_sql(_PUBLISHED_PICKS_SQL)
    if per_tier is None or picks.empty:
        return picks
    if per_tier == "book":
        from config import PORTFOLIO
        n = PORTFOLIO["picks_per_tier"]
        keep = picks.groupby("cap_tier", sort=False).cumcount() < picks["cap_tier"].map(n).fillna(0)
        return picks[keep]
    return picks.groupby("cap_tier", sort=False).head(per_tier)
