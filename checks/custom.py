"""
Custom semantic checks (plan 0015 Phase 4) — the ones a column range can't express:
cross-table consistency, distribution collapse, feed-dark, taxonomy drift. They
catch the class of bug freshness misses: producers ran cleanly, wrote rows, but
the rows are semantically wrong (analyst PT == close, rank duplicates, …).

Column ranges / enums are NOT here — they live once in checks/ranges.py and every
range verdict is derived from it. Per-stock coverage checks are derived from
tables.TABLES `coverage`. Both run through the same runner (checks.run).

Adding a check: append a dict to CHECKS. Two forms —
  1. SQL form: `sql` returning one row with `n_bad` (plus optional `n_total`,
     `sample`). The runner computes the percentage and the severity.
  2. Function form: `fn` returning None or {n_bad, n_total, sample, ...}.
Severity: an explicit `severity`, else by % of rows violating
(`critical_pct`, default 10; `warn_pct`, default 1; below = INFO).
"""

from checks.ranges import PICKABLE_TIERS
from checks import CRITICAL, INFO, WARN
from db import read_sql

CHECKS = [
    # ═══════════════════════════════════════════════════════════════════
    # Data-feed integrity — wrong source, mislabeled column
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "PT_EQUALS_PRICE",
        "table": "analyst_consensus",
        "column": "price_target",
        "message": "analyst PT equals current close (feed misread — see HANDOFF 2026-05-22)",
        "critical_pct": 25,
        "warn_pct": 5,
        "sql": """
            WITH latest_px AS (
                SELECT sid, close FROM stock_prices
                WHERE (sid, date) IN (SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)
            )
            SELECT
                SUM(CASE WHEN ABS(ac.price_target - lp.close) < 1.0 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT ac2.sid || ': PT=' || ROUND(ac2.price_target,1) || ' / close=' || ROUND(lp2.close,1)
                 FROM analyst_consensus ac2 JOIN latest_px lp2 ON ac2.sid = lp2.sid
                 WHERE ABS(ac2.price_target - lp2.close) < 1.0 AND ac2.has_analyst_data=1 LIMIT 1) AS sample
            FROM analyst_consensus ac
            JOIN latest_px lp ON ac.sid = lp.sid
            WHERE ac.has_analyst_data = 1 AND ac.price_target IS NOT NULL
        """,
    },
    {
        "code": "PT_RATIO_IMPLAUSIBLE",
        "table": "analyst_consensus",
        "column": "price_target",
        "message": "analyst PT implies >3x or <0.33x the close (Yahoo garbage for thin-coverage small-caps — SPRE ₹3960 vs ₹110)",
        "critical_pct": 3,
        "warn_pct": 0.5,
        "sql": """
            WITH latest_px AS (
                SELECT sid, close FROM stock_prices
                WHERE (sid, date) IN (SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)
            )
            SELECT
                SUM(CASE WHEN ac.price_target > 3.0 * lp.close OR ac.price_target < 0.33 * lp.close THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT ac2.sid || ': PT=' || ROUND(ac2.price_target,1) || ' / close=' || ROUND(lp2.close,1)
                 FROM analyst_consensus ac2 JOIN latest_px lp2 ON ac2.sid = lp2.sid
                 WHERE (ac2.price_target > 3.0 * lp2.close OR ac2.price_target < 0.33 * lp2.close)
                   AND ac2.has_analyst_data = 1 AND ac2.price_target IS NOT NULL
                 ORDER BY ac2.price_target / lp2.close DESC LIMIT 1) AS sample
            FROM analyst_consensus ac
            JOIN latest_px lp ON ac.sid = lp.sid
            WHERE ac.has_analyst_data = 1 AND ac.price_target IS NOT NULL AND lp.close > 0
        """,
    },
    {
        "code": "FORECAST_HISTORY_IS_PRICE_HISTORY",
        "table": "forecast_history",
        "column": "value (metric=price)",
        "message": "forecast_history.value (metric=price) matches stock_prices.close — not a real PT history",
        "critical_pct": 50,
        "warn_pct": 10,
        # SQL history (read before editing — two prior versions both had blind spots):
        #   v1 (original): JOINed fh ⋈ sp on (sid, date) but only ever the latest
        #      row — missed the pattern entirely.
        #   v2 (2026-05-23 "strengthening"): compared each stock's LATEST fh.value
        #      vs LATEST sp.close. NEW blind spot — the contaminant is "fh.value on
        #      date D equals the close ON date D", not "equals TODAY's close". Any
        #      stock that moved since its year-end snapshot no longer matches, so it
        #      caught only ~35 coincidentally-flat names (audit 2026-05-31).
        #   v3 (this, 2026-05-31): the contamination signature is value≈close ON THE
        #      SAME DATE. JOIN every metric=price row to its same-date stock_prices
        #      close and count matches within ₹1. A real year-end PT differs from
        #      that day's close (sell-side optimism / time value); a lastPrice
        #      contaminant equals it. The write-time defense is
        #      sources/tickertape_analyst._extract_forecast_rows (90-day filter) +
        #      FORECAST_HISTORY_NON_YEAREND_PRICE; this is the nightly backstop.
        "sql": """
            SELECT
                SUM(CASE WHEN ABS(fh.value - sp.close) < 1.0 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT fh2.sid || ': fh.value=' || fh2.value || ' = sp.close=' || sp2.close || ' @ ' || fh2.date
                 FROM forecast_history fh2 JOIN stock_prices sp2
                   ON fh2.sid=sp2.sid AND fh2.date=sp2.date
                 WHERE fh2.metric='price' AND ABS(fh2.value - sp2.close) < 1.0 LIMIT 1) AS sample
            FROM forecast_history fh
            JOIN stock_prices sp ON fh.sid = sp.sid AND fh.date = sp.date
            WHERE fh.metric='price'
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Schema correctness — PT data shape
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "FORECAST_HISTORY_NON_YEAREND_PRICE",
        "table": "forecast_history",
        "column": "date (metric=price)",
        "message": "forecast_history.price has non-year-end entries (Tickertape stores PT only at year-end)",
        "critical_pct": 5,
        "warn_pct": 1,
        "sql": """
            SELECT
                SUM(CASE WHEN substr(date, 6, 2) NOT IN ('12') AND date >= '2022-01-01' THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT sid || '@' || date FROM forecast_history
                 WHERE metric='price' AND substr(date,6,2) NOT IN ('12') AND date >= '2022-01-01' LIMIT 1) AS sample
            FROM forecast_history WHERE metric='price'
        """,
    },
    {
        "code": "ACS_SNAPSHOTS_MISSING_RECENT_MONTH",
        "table": "analyst_consensus_snapshots",
        "column": "snapshot_date",
        "message": "Current month has no analyst_consensus_snapshots rows — monthly cron may not have fired",
        "severity": WARN,
        "sql": """
            SELECT
                CASE WHEN (SELECT COUNT(*) FROM analyst_consensus_snapshots
                           WHERE snapshot_date >= strftime('%Y-%m-01', 'now', '-1 month')) < 100
                     THEN 1 ELSE 0 END AS n_bad,
                1 AS n_total
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Distribution sanity — column should have spread / non-degenerate
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "PT_UPSIDE_DEGENERATE",
        "table": "consensus_signals",
        "column": "pt_upside",
        # 1% absolute threshold (consensus_signals uses % units, so 1% = real-world 0.01)
        "message": "pt_upside is near-zero for >80% of universe (PT data dead)",
        "critical_pct": 80,
        "warn_pct": 50,
        "sql": """
            WITH latest AS (
                SELECT * FROM consensus_signals
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM consensus_signals)
            )
            SELECT
                SUM(CASE WHEN ABS(pt_upside) < 1.0 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total
            FROM latest WHERE pt_upside IS NOT NULL
        """,
    },
    {
        "code": "FINAL_SCORE_NO_SPREAD",
        "table": "daily_picks",
        "column": "final_score",
        "message": "final_score std < 0.05 — ranker has degenerated",
        "severity": CRITICAL,
        "sql": """
            SELECT
                CASE WHEN (SELECT 1 FROM (
                    SELECT AVG((final_score - mean) * (final_score - mean)) AS var FROM (
                        SELECT final_score, (SELECT AVG(final_score) FROM daily_picks WHERE pick_date=(SELECT MAX(pick_date) FROM daily_picks)) AS mean
                        FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                    )
                ) WHERE var < 0.0025) THEN 1 ELSE 0 END AS n_bad,
                1 AS n_total
        """,
    },
    {
        "code": "PIOTROSKI_NO_SPREAD",
        "table": "daily_snapshots",
        "column": "piotroski_f",
        "message": "piotroski_f distribution collapsed (≥80% on single integer)",
        "severity": CRITICAL,
        "sql": """
            WITH latest AS (
                SELECT piotroski_f FROM daily_snapshots
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots)
                  AND piotroski_f IS NOT NULL
            ),
            modes AS (
                SELECT piotroski_f, COUNT(*) AS n FROM latest GROUP BY piotroski_f ORDER BY n DESC LIMIT 1
            )
            SELECT
                CASE WHEN (SELECT 100.0 * (SELECT n FROM modes) / (SELECT COUNT(*) FROM latest)) >= 80 THEN 1 ELSE 0 END AS n_bad,
                1 AS n_total
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Coverage / cardinality — table should have rows / dates as expected
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "DAILY_PICKS_COVERAGE_LOW",
        "table": "daily_picks",
        "column": "—",
        "message": "Latest daily_picks has <100 rows per tier — screener output thin",
        "severity": CRITICAL,
        # Tiers come from config (pickable ones); a tier with NO rows counts as thin.
        "sql": f"""
            SELECT {len(PICKABLE_TIERS)} - COALESCE(SUM(CASE WHEN c >= 100 THEN 1 ELSE 0 END), 0) AS n_bad,
                   {len(PICKABLE_TIERS)} AS n_total
            FROM (
                SELECT cap_tier, COUNT(*) AS c
                FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                GROUP BY cap_tier
            )
        """,
    },
    {
        "code": "DAILY_PICKS_ORPHAN_SID",
        "table": "daily_picks",
        "column": "sid",
        "message": "daily_picks references a sid not in stocks table",
        "critical_pct": 0.1,
        "sql": """SELECT
                    SUM(CASE WHEN s.sid IS NULL THEN 1 ELSE 0 END) AS n_bad,
                    COUNT(*) AS n_total,
                    (SELECT dp2.sid FROM daily_picks dp2 LEFT JOIN stocks s2 ON dp2.sid=s2.sid
                     WHERE s2.sid IS NULL AND dp2.pick_date=(SELECT MAX(pick_date) FROM daily_picks) LIMIT 1) AS sample
                  FROM daily_picks dp LEFT JOIN stocks s ON dp.sid = s.sid
                  WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)""",
    },
    {
        "code": "DAILY_PICKS_RANK_DUPLICATE",
        "table": "daily_picks",
        "column": "rank",
        "message": "Duplicate (pick_date, cap_tier, rank) — rank not unique within tier",
        "critical_pct": 0.05,
        "warn_pct": 0.01,
        "sql": """
            SELECT
                COALESCE((SELECT SUM(n-1) FROM (
                    SELECT cap_tier, rank, COUNT(*) AS n
                    FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                    GROUP BY cap_tier, rank HAVING COUNT(*) > 1
                )), 0) AS n_bad,
                (SELECT COUNT(*) FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)) AS n_total,
                (SELECT cap_tier || ' rank ' || rank || ' shared by ' || COUNT(*) || ' stocks'
                 FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                 GROUP BY cap_tier, rank HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC LIMIT 1) AS sample
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Null / completeness — critical columns shouldn't be all-null
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "DAILY_SNAPSHOTS_ALL_NULL_PIOTROSKI",
        "table": "daily_snapshots",
        "column": "piotroski_f",
        "message": "piotroski_f null rate elevated for today's snapshots",
        "critical_pct": 80,
        "warn_pct": 50,
        "sql": """
            WITH latest AS (
                SELECT piotroski_f FROM daily_snapshots
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots)
            )
            SELECT SUM(CASE WHEN piotroski_f IS NULL THEN 1 ELSE 0 END) AS n_bad,
                   COUNT(*) AS n_total
            FROM latest
        """,
    },
    {
        "code": "PIOTROSKI_F_SUM_MISMATCH",
        "table": "piotroski_scores",
        "column": "f_score",
        "message": "f_score doesn't equal sum of 9 component flags",
        "critical_pct": 5,
        "sql": """
            SELECT
                SUM(CASE WHEN f_score != (
                    COALESCE(roa_positive,0)+COALESCE(cfo_positive,0)+COALESCE(roa_improving,0)+
                    COALESCE(accruals_quality,0)+COALESCE(leverage_down,0)+COALESCE(liquidity_up,0)+
                    COALESCE(no_dilution,0)+COALESCE(gross_margin_up,0)+COALESCE(asset_turnover_up,0)
                ) THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total
            FROM piotroski_scores
            WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM piotroski_scores)
              AND f_score IS NOT NULL
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Cross-table consistency
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "ANALYST_CONSENSUS_NEGATIVE_EPS_GROWTH_BUT_BUY",
        "table": "analyst_consensus",
        "column": "—",
        "message": "Sanity: many stocks with negative EPS growth flagged 100% buy (possible logic flip)",
        "severity": INFO,
        "sql": """
            SELECT
                SUM(CASE WHEN eps_growth_pct < -20 AND buy_pct = 100 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total
            FROM analyst_consensus WHERE has_analyst_data = 1
        """,
    },
    {
        "code": "DAILY_SNAPSHOTS_DATE_DRIFT",
        "table": "daily_snapshots",
        "column": "snapshot_date",
        "message": "daily_snapshots latest date doesn't match daily_picks latest date",
        "severity": WARN,
        "sql": """
            SELECT
                CASE WHEN (SELECT MAX(snapshot_date) FROM daily_snapshots) != (SELECT MAX(pick_date) FROM daily_picks)
                     THEN 1 ELSE 0 END AS n_bad,
                1 AS n_total,
                (SELECT MAX(snapshot_date) FROM daily_snapshots) || ' vs ' || (SELECT MAX(pick_date) FROM daily_picks) AS sample
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # LLM dossier — schema + validation
    # ═══════════════════════════════════════════════════════════════════
    # (Existing dossier validation already runs at write-time and the health
    # report already reports DOSSIER_HALLUCINATION. We don't double-count it.)

    # ═══════════════════════════════════════════════════════════════════
    # Output-quality — pick is only as good as the data behind it
    # ═══════════════════════════════════════════════════════════════════
    # 2026-05-23: ANO ranked #1 SMALL with zero price rows and only 2 of 7
    # signals (one a default 50.0). Freshness watchdog said FRESH because
    # stock_prices.MAX(date) was current — the per-stock coverage hole was
    # invisible. The checks below catch that class of bug at the output layer.
    {
        "code": "DAILY_PICK_NO_PRICES",
        "table": "daily_picks",
        "column": "sid",
        "message": "Top-ranked stock has zero rows in stock_prices",
        "severity": CRITICAL,
        "sql": """
            WITH latest AS (
                SELECT sid, cap_tier, rank FROM daily_picks
                WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                  AND rank <= 20
            )
            SELECT
                SUM(CASE WHEN sp.cnt IS NULL OR sp.cnt = 0 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT l.cap_tier || ' rank ' || l.rank || ': ' || l.sid
                 FROM latest l LEFT JOIN (
                    SELECT sid, COUNT(*) AS cnt FROM stock_prices WHERE close > 0 GROUP BY sid
                 ) sp2 ON l.sid = sp2.sid
                 WHERE sp2.cnt IS NULL OR sp2.cnt = 0 LIMIT 1) AS sample
            FROM latest l
            LEFT JOIN (
                SELECT sid, COUNT(*) AS cnt FROM stock_prices WHERE close > 0 GROUP BY sid
            ) sp ON l.sid = sp.sid
        """,
    },
    {
        "code": "DAILY_PICK_THIN_SIGNAL_COVERAGE",
        "table": "daily_picks",
        "column": "—",
        "message": "Top picks scored on <4 of 8 signals (rank inflated by missing-data normalization)",
        "critical_pct": 25,
        "warn_pct": 10,
        "sql": """
            WITH latest_picks AS (
                SELECT sid, cap_tier, rank FROM daily_picks
                WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                  AND rank <= 50
            ),
            signal_counts AS (
                SELECT
                    lp.sid, lp.cap_tier, lp.rank,
                    (CASE WHEN ps.f_score IS NOT NULL THEN 1 ELSE 0 END +
                     CASE WHEN ac.accruals_signal IS NOT NULL THEN 1 ELSE 0 END +
                     CASE WHEN cs.consensus_signal IS NOT NULL THEN 1 ELSE 0 END +
                     CASE WHEN pr.promoter_signal IS NOT NULL THEN 1 ELSE 0 END +
                     CASE WHEN sm.smart_money_score IS NOT NULL THEN 1 ELSE 0 END +
                     CASE WHEN sp.cnt > 100 THEN 1 ELSE 0 END +    /* momentum + earnings_yield + b/p */
                     CASE WHEN sp.cnt > 100 THEN 1 ELSE 0 END +
                     CASE WHEN sp.cnt > 100 AND abs.total_equity IS NOT NULL THEN 1 ELSE 0 END) AS n_signals
                FROM latest_picks lp
                LEFT JOIN (SELECT sid, f_score FROM piotroski_scores WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM piotroski_scores)) ps ON lp.sid = ps.sid
                LEFT JOIN (SELECT sid, accruals_signal FROM accruals_scores WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM accruals_scores)) ac ON lp.sid = ac.sid
                LEFT JOIN (SELECT sid, consensus_signal FROM consensus_signals WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM consensus_signals)) cs ON lp.sid = cs.sid
                LEFT JOIN (SELECT sid, promoter_signal FROM promoter_signals WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM promoter_signals)) pr ON lp.sid = pr.sid
                LEFT JOIN (SELECT sid, smart_money_score FROM smart_money_scores WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM smart_money_scores)) sm ON lp.sid = sm.sid
                LEFT JOIN (SELECT sid, COUNT(*) AS cnt FROM stock_prices WHERE close > 0 GROUP BY sid) sp ON lp.sid = sp.sid
                LEFT JOIN (SELECT sid, MAX(total_equity) AS total_equity FROM annual_balance_sheet GROUP BY sid) abs ON lp.sid = abs.sid
            )
            SELECT
                SUM(CASE WHEN n_signals < 4 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT cap_tier || ' rank ' || rank || ': ' || sid || ' (' || n_signals || '/8 signals)'
                 FROM signal_counts WHERE n_signals < 4 ORDER BY rank LIMIT 1) AS sample
            FROM signal_counts
        """,
    },
    {
        "code": "SCORE_TABLE_DEFAULT_PROLIFERATION",
        "table": "smart_money_scores",
        "column": "smart_money_score",
        "message": "smart_money_score = 50.0 for >30% of universe (default-value leak from missing inputs)",
        "critical_pct": 30,
        "warn_pct": 15,
        # The 2026-05-23 bug: _minmax_by_tier seeded all stocks at 50.0, so
        # stocks with no bulk-deals AND no delivery data came out at exactly
        # 50.0 instead of NaN. Hardcoded threshold of exactly 50.0 catches the
        # default-substitution pattern; legitimate near-50 scores from real
        # min-max output won't land on the exact value.
        "sql": """
            WITH latest AS (
                SELECT smart_money_score FROM smart_money_scores
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM smart_money_scores)
            )
            SELECT
                SUM(CASE WHEN smart_money_score = 50.0 THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total
            FROM latest
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Sector taxonomy — regulatory_signals.sector must align with stocks.sector
    # ═══════════════════════════════════════════════════════════════════
    # 2026-05-23: Gillette dossier showed Consumer Staples regulatory items
    # because that part matched. But 1,638 regulatory_signals rows ("Financial
    # Services" + "IT") never joined any stock — the AI classifier and the
    # stocks universe were using different sector taxonomies and no one knew.
    {
        "code": "REGULATORY_SECTOR_TAXONOMY_MISMATCH",
        "table": "regulatory_signals",
        "column": "sector",
        "message": "regulatory_signals.sector values don't exist in stocks.sector (taxonomy drift)",
        "critical_pct": 20,
        "warn_pct": 5,
        "sql": """
            SELECT
                (SELECT COUNT(*) FROM regulatory_signals
                 WHERE sector NOT IN (SELECT DISTINCT sector FROM stocks)) AS n_bad,
                (SELECT COUNT(*) FROM regulatory_signals) AS n_total,
                (SELECT sector || ' (' || COUNT(*) || ' rows orphaned)' FROM regulatory_signals
                 WHERE sector NOT IN (SELECT DISTINCT sector FROM stocks)
                 GROUP BY sector ORDER BY COUNT(*) DESC LIMIT 1) AS sample
        """,
    },
    # 2026-05-23: regulatory_events stopped flowing 2026-04-10 but stayed
    # "FRESH" because its threshold was monthly (50d). Gillette dossier showed
    # 43-day-old items as "most recent." Watchdog override now 14d.
    {
        "code": "REGULATORY_FEED_DARK",
        "table": "regulatory_events",
        "column": "published_at",
        "message": "No classified regulatory events in last 7 days — harvester or classifier silent",
        "severity": WARN,
        "sql": """
            SELECT
                CASE WHEN (SELECT COUNT(*) FROM regulatory_events
                           WHERE classifier_status = 'classified'
                             AND julianday('now') - julianday(published_at) <= 7) = 0
                     THEN 1 ELSE 0 END AS n_bad,
                1 AS n_total,
                (SELECT MAX(published_at) FROM regulatory_events WHERE classifier_status='classified') AS sample
        """,
    },
    # 2026-05-24 audit: 273 stocks have |eps_growth_pct| > 200% — arithmetic
    # artifacts from near-zero base EPS (turnarounds). consensus.py clips
    # internally before computing the signal, so screener rank is safe, but
    # the raw value is fed verbatim to the dossier LLM prompt. VSKI ranked
    # #1 SMALL today with eps_growth=2941%. Clip happens in output/dossier.py;
    # this check fires when extreme values reach the top-100 of any tier
    # (where they would be eligible for dossier generation if we extended it).
    {
        "code": "EXTREME_GROWTH_PCT_IN_TOP_PICKS",
        "table": "analyst_consensus",
        "column": "eps_growth_pct",
        "message": "Top-100 picks have |eps_growth_pct| or |revenue_growth_pct| > 300% (likely div-by-near-zero artifacts)",
        "critical_pct": 20,
        "warn_pct": 5,
        "sql": """
            WITH top_picks AS (
                SELECT sid FROM daily_picks
                WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
                  AND rank <= 100
            )
            SELECT
                SUM(CASE WHEN ABS(ac.eps_growth_pct) > 300 OR ABS(ac.revenue_growth_pct) > 300
                         THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT sid || ' (eps=' || ROUND(eps_growth_pct, 0) || '%)' FROM analyst_consensus
                 WHERE sid IN (SELECT sid FROM top_picks)
                   AND (ABS(eps_growth_pct) > 300 OR ABS(revenue_growth_pct) > 300)
                 ORDER BY ABS(eps_growth_pct) DESC LIMIT 1) AS sample
            FROM analyst_consensus ac
            WHERE ac.sid IN (SELECT sid FROM top_picks)
        """,
    },
    # 2026-05-24 fixed at consumer: signals/consensus.py now requires
    # (total_analysts IS NOT NULL OR price_target IS NOT NULL) in its SELECT —
    # Tickertape-only forecast rows (forward_eps without analyst attribution)
    # are model projections, not analyst consensus, and never fire consensus_signal.
    # This check now verifies the gate is holding: zero consensus_signals rows
    # should have a source analyst_consensus row missing both attribution fields.
    {
        "code": "CONSENSUS_SIGNAL_WITHOUT_ANALYST_ATTRIBUTION",
        "table": "consensus_signals",
        "column": "consensus_signal",
        "message": "consensus_signal fired for a stock whose analyst_consensus row has NULL total_analysts AND NULL price_target",
        "critical_pct": 1,   # ANY leak is a bug — gate failure
        "warn_pct": 0,
        "sql": """
            SELECT
                SUM(CASE WHEN ac.total_analysts IS NULL AND ac.price_target IS NULL
                         THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT cs2.sid FROM consensus_signals cs2
                 JOIN analyst_consensus ac2 ON ac2.sid = cs2.sid
                 WHERE cs2.consensus_signal IS NOT NULL
                   AND ac2.total_analysts IS NULL
                   AND ac2.price_target IS NULL LIMIT 1) AS sample
            FROM consensus_signals cs
            JOIN analyst_consensus ac ON ac.sid = cs.sid
            WHERE cs.consensus_signal IS NOT NULL
              AND cs.snapshot_date = (SELECT MAX(snapshot_date) FROM consensus_signals)
        """,
    },
    # Companion observation check: how much of the universe lacks analyst
    # attribution entirely. INFO severity — this is yfinance coverage gap,
    # not a leak. Watch for sudden jumps which indicate yfinance breakage.
    {
        "code": "ANALYST_ATTRIBUTION_COVERAGE",
        "table": "analyst_consensus",
        "column": "total_analysts",
        "message": "Stocks with NO analyst attribution (total_analysts AND price_target both NULL) — yfinance coverage gap, not a leak",
        "severity": INFO,
        "sql": """
            SELECT
                SUM(CASE WHEN total_analysts IS NULL AND price_target IS NULL THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT sid FROM analyst_consensus
                 WHERE total_analysts IS NULL AND price_target IS NULL LIMIT 1) AS sample
            FROM analyst_consensus
        """,
    },
    # Plan 0005 Phase F: cross-source price-target reconciliation.
    # Compare yfinance consensus PT vs the *consensus of broker PTs* (mean of
    # last-90d broker calls per stock). Single-broker PT vs yfinance consensus
    # is apples-to-oranges and trips false positives — broker calls are by
    # construction higher-variance than consensus. We only fire CRITICAL when
    # the two CONSENSUSES diverge meaningfully (>30%), and only after we have
    # ≥10 broker recos for the stock (so the broker mean is meaningful).
    # 2026-05-25: scope tightened after first run flagged 57/213 stocks @ 15%
    # threshold — most disagreements were stale single-broker calls, not real
    # source divergence.
    {
        "code": "CROSS_SOURCE_PT_MISMATCH",
        "table": "analyst_consensus",
        "column": "price_target",
        "message": "yfinance consensus PT and broker-mean PT differ by >30% (consensus-of-consensuses divergence, ≥10 broker recos)",
        "critical_pct": 25,
        "warn_pct": 10,
        "sql": """
            WITH broker_mean AS (
                SELECT sid,
                       AVG(target_price) AS broker_pt,
                       COUNT(*) AS n_recos
                FROM broker_recommendations
                WHERE target_price IS NOT NULL AND target_price > 0
                  AND reco_date >= date('now', '-90 days')
                GROUP BY sid
                HAVING COUNT(*) >= 10
            )
            SELECT
                SUM(CASE WHEN ABS(ac.price_target - bm.broker_pt) / ac.price_target > 0.30
                         THEN 1 ELSE 0 END) AS n_bad,
                COUNT(*) AS n_total,
                (SELECT ac2.sid || ': yf=' || ROUND(ac2.price_target,1) || ' vs broker_mean=' || ROUND(bm2.broker_pt,1) || ' (n=' || bm2.n_recos || ')'
                 FROM analyst_consensus ac2
                 JOIN broker_mean bm2 ON bm2.sid = ac2.sid
                 WHERE ac2.price_target IS NOT NULL AND ac2.price_target > 0
                   AND ABS(ac2.price_target - bm2.broker_pt) / ac2.price_target > 0.30
                 ORDER BY ABS(ac2.price_target - bm2.broker_pt) / ac2.price_target DESC LIMIT 1) AS sample
            FROM analyst_consensus ac
            JOIN broker_mean bm ON bm.sid = ac.sid
            WHERE ac.price_target IS NOT NULL AND ac.price_target > 0
        """,
    },
    # Plan 0005 Phase C item 5: catch a harvester silently shrinking the
    # universe overnight. Compares each signal's eligible_n today vs prior
    # snapshot in universe_eligibility; fires if any signal dropped ≥5%
    # (WARN) or ≥10% (CRITICAL). Returns 0 when there's no prior snapshot
    # (the cron hasn't run twice yet — false-positive-free by design).
    {
        "code": "ELIGIBILITY_REGRESSION",
        "table": "universe_eligibility",
        "column": "eligible",
        "message": "Signal eligible count dropped overnight — source may have regressed",
        "critical_pct": 10,
        "warn_pct": 5,
        "sql": """
            WITH per_date AS (
                SELECT signal, snapshot_date, SUM(eligible) AS n_elig
                FROM universe_eligibility GROUP BY signal, snapshot_date
            ),
            ranked AS (
                SELECT signal, snapshot_date, n_elig,
                       ROW_NUMBER() OVER (PARTITION BY signal ORDER BY snapshot_date DESC) AS rn
                FROM per_date
            ),
            paired AS (
                SELECT t.signal,
                       t.n_elig AS today_n,
                       y.n_elig AS prior_n,
                       100.0 * (y.n_elig - t.n_elig) / y.n_elig AS pct_drop
                FROM ranked t
                JOIN ranked y ON y.signal = t.signal AND y.rn = 2
                WHERE t.rn = 1 AND y.n_elig > 0
            )
            SELECT
                COALESCE(MAX(pct_drop), 0) AS n_bad,
                100 AS n_total,
                (SELECT signal || ': ' || prior_n || ' → ' || today_n || ' (' || ROUND(pct_drop,1) || '% drop)'
                 FROM paired ORDER BY pct_drop DESC LIMIT 1) AS sample
            FROM paired WHERE pct_drop >= 5
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # MoneyControl slug integrity — discovery mis-mapped 21% of stocks
    # (2026-05-25). The autosuggest endpoint returned the wrong company
    # for non-exact ticker matches (IOC → ITC, ABB → Hitachi Energy,
    # BAJAJ-AUTO → Bajaj Finance, etc.). Slug fix landed; this check
    # gates future regressions.
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "LINEAGE_REGISTRY_DRIFT",
        "table": "lineage.FACTOR_LINEAGE",
        "column": "(registry coverage)",
        "message": "BACKTEST_SIGNALS contains factor(s) with no FACTOR_LINEAGE entry — "
                   "any new factor MUST be added to lineage.py before ranking",
        "critical_pct": 0.01,   # any missing factor is CRITICAL
        "warn_pct": 0,
        "fn": lambda: _lineage_registry_drift_check(),
    },
    {
        "code": "MC_SLUG_NAME_MISMATCH",
        "table": "stocks",
        "column": "mc_slug",
        "message": "stocks.mc_slug points to a Moneycontrol URL whose company segment "
                   "does not match stocks.name (was autosuggest's wrong-result bug)",
        "critical_pct": 2,
        "warn_pct": 0.5,
        "fn": lambda: _mc_slug_name_mismatch_check(),
    },
    # ═══════════════════════════════════════════════════════════════════
    # Plan 0007 Phase 6 — External Anchor drift sentinel.
    # Offline auditor of the live Gate 7 (tools/anchor_audit.py).
    # If the live gate ever regresses, this nightly check resurfaces it.
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "EXTERNAL_ANCHOR_DRIFT",
        "table": "trust_verdicts",
        "column": "gate_7_anchor",
        "message": "yfinance close drifted from NSE bhavcopy anchor by >0.5% (Plan 0007 Gate 7)",
        "critical_pct": 5,
        "warn_pct": 1,
        "sql": """
            SELECT
              SUM(CASE WHEN gate_7_anchor = 0 THEN 1 ELSE 0 END) AS n_bad,
              COUNT(*) AS n_total,
              (SELECT sid || ': ' || json_extract(reasons_json, '$.gate_7_anchor.drift_pct') || '%'
               FROM trust_verdicts
               WHERE gate_7_anchor = 0
                 AND snapshot_date >= date('now', '-7 days')
               ORDER BY snapshot_date DESC LIMIT 1) AS sample
            FROM trust_verdicts
            WHERE gate_7_anchor IS NOT NULL
              AND snapshot_date >= date('now', '-7 days')
        """,
    },
]


def _lineage_registry_drift_check():
    """Flag canonical factors missing from lineage.FACTOR_LINEAGE.

    Enforces: every BACKTEST_SIGNALS entry MUST have a corresponding
    FACTOR_LINEAGE entry. Adding a new factor without lineage = CRITICAL.
    See ADR 0027 + plan 0005 Phase F.
    """
    try:
        from lineage import FACTOR_LINEAGE, missing_factors, orphan_factors
        from db import BACKTEST_SIGNALS
    except Exception as exc:
        return {"n_bad": 1, "n_total": 1, "sample": f"import failed: {exc}"}

    missing = missing_factors()
    orphan = orphan_factors()
    total = len(BACKTEST_SIGNALS)
    n_bad = len(missing)
    sample = None
    if missing:
        sample = f"missing lineage entry: {missing[0]}" + (
            f" (+{len(missing)-1} more)" if len(missing) > 1 else "")
    elif orphan:
        sample = f"orphan registry entry (in lineage but not in BACKTEST_SIGNALS): {orphan[0]}"
    return {"n_bad": n_bad, "n_total": total, "sample": sample}


def _mc_slug_name_mismatch_check():
    """Flag stocks.mc_slug values whose company segment doesn't match stocks.name.

    Match logic mirrors the audit that purged 497 contaminated slugs on
    2026-05-25: accept if normalised slug-company is a substring of the
    normalised stock name (or vice versa), OR if SequenceMatcher ratio
    >= 0.55, OR if the ticker is a substring of the slug. Mismatch otherwise.
    """
    import re as _re
    from difflib import SequenceMatcher as _SM

    # Hand-verified slugs whose company segment legitimately doesn't match the
    # stock name (renamed entity, InvIT short-name, etc.). Single source of
    # truth lives next to slug discovery. e.g. India Power Corp → 'dpsc',
    # Cube Highways Trust → 'cubeinvit'. See MC_SLUG_OVERRIDES.
    try:
        from sources.moneycontrol_recos import MC_SLUG_OVERRIDES
        _verified = {sid for sid, slug in MC_SLUG_OVERRIDES.items() if slug}
    except Exception:
        _verified = set()

    rows = read_sql("SELECT sid, name, ticker, mc_slug FROM stocks WHERE mc_slug IS NOT NULL")
    if rows.empty:
        return {"n_bad": 0, "n_total": 0, "sample": None}

    def _norm(s):
        return _re.sub(r"[^a-z0-9]", "", (s or "").lower())

    def _slug_co(slug):
        parts = (slug or "").strip("/").split("/")
        return parts[-2] if len(parts) >= 2 else ""

    bad_sample = None
    bad_list = []
    n_bad = 0
    for sid, name, ticker, slug in rows.itertuples(index=False):
        if sid in _verified:
            continue
        sc_n = _norm(_slug_co(slug)); name_n = _norm(name); ticker_n = _norm(ticker)
        ratio = _SM(None, sc_n, name_n).ratio()
        # ticker_in dropped entirely 2026-05-31 after a 2nd sweep caught 6
        # more wrong-entity slugs that startswith(ticker) still passed:
        #   STYL → "stylamindustries" (Stylam, not Seshaasai)
        #   MUT  → "muthootfinance"   (Muthoot Finance, not Muthoot Microfin)
        #   APLL → "apollohospitals"  (Apollo Hospitals, not Apollo Micro)
        # The name-based check (substring or SequenceMatcher ratio ≥ 0.55) is
        # enough — every legitimate slug has the stock's name embedded in the
        # slug-company segment (RELIANCE→relianceindustries is name_in=True).
        # Ticker shortcuts can ONLY introduce false negatives, never true
        # positives that the name check would miss.
        name_in = sc_n in name_n or name_n in sc_n
        if not (name_in or ratio >= 0.55):
            n_bad += 1
            bad_list.append((sid, name, _slug_co(slug)))
            if bad_sample is None:
                bad_sample = f"{sid}: name='{name[:30]}' → slug='{_slug_co(slug)}'"

    return {"n_bad": n_bad, "n_total": len(rows), "sample": bad_sample,
            "bad_list": bad_list}


