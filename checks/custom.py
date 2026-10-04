"""
Custom checks (ADR 0052 Check block, ADR 0060): the few things a column range, a
coverage gate or a freshness limit cannot express.

Every check here must earn its place (ADR 0060):
  1. It can fail TODAY because the world changed — data arrived wrong, a factor
     input died, the ranking broke. A rule that can only break when code changes
     is a test (tests/, tools/regression_fixtures.py), not a daily check.
  2. It guards something the models read or the reader sees today.
  3. It has a drill in tests/test_check_drills.py that proves it fires.
  4. It looks at rows: a check whose scope is empty is reported, never passed.

Column ranges live once in checks/ranges.py; per-stock coverage gates in
tables.TABLES `coverage`; freshness limits in tables.TABLES. All run through the
same runner (checks.run).

A check is a dict: `code`, `table`, `column`, its meaning in plain words — `theme`
(which of the five questions in checks.THEMES), `message` (what it found), `why`
(why it matters), `fix` (what to do first) — and its rule, in one of two forms:
  1. `sql` returning one row with `n_bad` (plus optional `n_total`, `sample`).
  2. `fn` returning None or {n_bad, n_total, sample[, severity]}.
Severity: an explicit `severity` (or the one `fn` returns), else by % of rows
violating (`critical_pct`, default 10; `warn_pct`, default 1; below = INFO).
"""

from checks.ranges import PICKABLE_TIERS
from checks import CRITICAL, WARN
from checks import model
from validators.plausibility import pt_implausible_sql

# Every stored analyst target next to the latest close; {bad} is the rule being counted.
_TARGETS_SQL = """
    WITH latest_px AS (
        SELECT sid, close FROM stock_prices
        WHERE (sid, date) IN (SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)
    ),
    judged AS (
        SELECT ac.sid, ac.price_target AS pt, lp.close, ({bad}) AS bad
        FROM analyst_consensus ac JOIN latest_px lp ON ac.sid = lp.sid
        WHERE ac.has_analyst_data = 1 AND ac.price_target IS NOT NULL AND lp.close > 0
    )
    SELECT COALESCE(SUM(bad), 0) AS n_bad, COUNT(*) AS n_total,
           (SELECT sid || ': target ' || ROUND(pt, 1) || ' vs price ' || ROUND(close, 1)
            FROM judged WHERE bad ORDER BY pt / close DESC LIMIT 1) AS sample
    FROM judged
"""

CHECKS = [
    # ═══════════════════════════════════════════════════════════════════
    # The models: today's ranking
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "FACTOR_INPUT",
        "table": "pit_replay_snapshots",
        "column": "inputs_json",
        "theme": "picks",
        "message": "A wired factor's input collapsed in today's ranking",
        "why": "When a factor goes missing the ranking silently re-weights onto the factors that are left; "
               "the picks then come from a model nobody validated.",
        "fix": "The evidence names the tier and factor. Check the freshness and last run of that factor's source "
               "tables (factors.FACTORS[...]['source_tables']), fix the producer, rerun the screener.",
        "severity_text": f"CRITICAL when a broken input carries {model.HEAVY_WEIGHT:.0%}+ of a tier's weight, else WARN",
        "fn": model.factor_inputs,
    },
    {
        "code": "PICKS_RESHUFFLED",
        "table": "daily_picks",
        "column": "final_score",
        "theme": "picks",
        "message": "Today's ranking broke sharply from yesterday's",
        "why": "Scores drift a little each day (rank correlation is usually 0.95+). A sharp break without a model "
               "change behind it means an input changed under the ranking.",
        "fix": "If weights or factors changed yesterday this is expected. Otherwise look at FACTOR_INPUT and at "
               "'Did the data arrive?' for the input that moved.",
        "severity": WARN,
        "fn": model.ranking_stability,
    },
    {
        "code": "DAILY_PICKS_COVERAGE_LOW",
        "table": "daily_picks",
        "column": "—",
        "theme": "picks",
        "message": "A tier has far fewer ranked stocks than it has stocks",
        "why": "The screener dropped most of a tier (a mis-wired eligibility rule once removed every MID Financial).",
        "fix": "Compare today's daily_picks count per tier with yesterday's; the factors' eligibility rules (factors.FACTORS) "
               "and the pick gate (config.PICK_GATE) decide who is left out: find the factor that stopped covering the tier.",
        "severity": CRITICAL,
        # Tiers come from config (pickable ones); thin = under 80% of the tier's stocks ranked (a tier
        # with NO rows counts as thin). The bar used to be a flat 100, which a LARGE tier of ~103
        # stocks crosses the day seven of them miss the coverage gate.
        "sql": f"""
            SELECT {len(PICKABLE_TIERS)} - COALESCE(SUM(CASE WHEN p.c >= 0.8 * t.n THEN 1 ELSE 0 END), 0) AS n_bad,
                   {len(PICKABLE_TIERS)} AS n_total,
                   (SELECT GROUP_CONCAT(x.cap_tier || ' ' || x.c || ' of ' || y.n, '; ')
                    FROM (SELECT cap_tier, COUNT(*) AS c FROM daily_picks
                          WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks) GROUP BY cap_tier) x
                    JOIN (SELECT cap_tier, COUNT(*) AS n FROM stocks GROUP BY cap_tier) y USING (cap_tier)
                    WHERE x.c < 0.8 * y.n) AS sample
            FROM (SELECT cap_tier, COUNT(*) AS n FROM stocks GROUP BY cap_tier) t
            JOIN (SELECT cap_tier, COUNT(*) AS c FROM daily_picks
                  WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks) GROUP BY cap_tier) p USING (cap_tier)
            WHERE t.cap_tier IN ({", ".join("'" + x + "'" for x in PICKABLE_TIERS)})
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Prices — every price factor and the day's ranking read these rows
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "PRICE_DAY_COPIED",
        "table": "stock_prices",
        "column": "close",
        "theme": "correct",
        "message": "The newest price day is a copy of the session before it",
        "why": "On a market holiday NSE serves the previous session's file. Stored as a trading day, every price "
               "window counts it and the day's picks rank on it (44 such days were stored, 2020 to 2026).",
        "fix": "Delete that date from stock_prices and check the file-date guard in sources/nse.py "
               "(_fetch_date must refuse a file whose DATE1 is not the day asked for).",
        "critical_pct": 50,
        "warn_pct": 15,
        "sql": """
            WITH days AS (SELECT DISTINCT date FROM stock_prices ORDER BY date DESC LIMIT 2)
            SELECT COALESCE(SUM(a.close = b.close AND a.volume = b.volume), 0) AS n_bad, COUNT(*) AS n_total,
                   (SELECT MAX(date) FROM days) || ' repeats ' || (SELECT MIN(date) FROM days) AS sample
            FROM stock_prices a JOIN stock_prices b ON a.sid = b.sid
            WHERE a.date = (SELECT MAX(date) FROM days) AND b.date = (SELECT MIN(date) FROM days)
              AND (SELECT COUNT(*) FROM days) = 2
        """,
    },
    {
        "code": "PRICE_JUMP_UNEXPLAINED",
        "table": "stock_prices",
        "column": "close",
        "theme": "correct",
        "message": "A share price moved more than 40% in a day with no split, bonus or dividend on record",
        "why": "Circuit limits make such a move impossible in normal trading: it is a split, bonus or demerger the "
               "corporate-actions table missed. Momentum, volatility and the return label then read it as a crash or a spike.",
        "fix": "Look the stock up on the exchange's corporate-actions page; add the event to corporate_actions "
               "(or teach tools/compute_corporate_adjustments.py the wording it missed) and rerun that step.",
        "severity": WARN,
        "sql": """
            WITH recent AS (
                SELECT sid, date, close, LAG(close) OVER (PARTITION BY sid ORDER BY date) AS prev
                FROM stock_prices WHERE date >= (SELECT date(MAX(date), '-12 day') FROM stock_prices) AND close > 0
            ),
            judged AS (
                SELECT r.sid, r.date, r.close / r.prev AS move,
                       (r.close / r.prev < 0.6 OR r.close / r.prev > 1.67) AND NOT EXISTS (
                           SELECT 1 FROM corporate_adjustments ca WHERE ca.sid = r.sid
                             AND ca.ex_date BETWEEN date(r.date, '-10 day') AND date(r.date, '+10 day')) AS bad
                FROM recent r WHERE r.prev > 0
            )
            SELECT COALESCE(SUM(bad), 0) AS n_bad, COUNT(DISTINCT sid) AS n_total,
                   (SELECT sid || ' on ' || date || ': ×' || ROUND(move, 2) FROM judged WHERE bad LIMIT 1) AS sample
            FROM judged
        """,
    },

    # ═══════════════════════════════════════════════════════════════════
    # Analyst data — shown in the cockpit and the dossier, not a ranking input
    # (pt_upside was pulled from the model, ADR 0045)
    # ═══════════════════════════════════════════════════════════════════
    {
        "code": "ANALYST_TARGET_IMPLAUSIBLE",
        "table": "analyst_consensus",
        "column": "price_target",
        "theme": "correct",
        "message": "Analyst price targets that cannot be real: more than 3x, or under a third of, the share price",
        "why": "A broker call from before a split or a crash, or Yahoo garbage for a thinly covered small cap. "
               "The upside shown for that stock is wrong.",
        "fix": "Both writers refuse these (the Yahoo sweep and the broker aggregate share "
               "validators.plausibility.PT_CLOSE_RATIO), so a few rows mean a price moved since the last write: "
               "`python -m sources.moneycontrol_recos --aggregate-only` rebuilds. Many rows mean a writer lost its gate.",
        "critical_pct": 10,
        "warn_pct": 0.5,
        "sql": _TARGETS_SQL.format(bad=pt_implausible_sql("ac.price_target", "lp.close")),
    },
    {
        "code": "ANALYST_TARGET_IS_PRICE",
        "table": "analyst_consensus",
        "column": "price_target",
        "theme": "correct",
        "message": "Analyst price targets equal to the share price for a large share of stocks",
        "why": "A handful of targets sit on the price by chance. Many at once is the feed returning the last price "
               "in place of a target (the HALC bug, 2026-05-22): every upside figure then reads zero.",
        "fix": "Check which field sources/yfinance_analyst.py and the broker aggregate map to price_target.",
        "critical_pct": 25,
        "warn_pct": 5,
        "sql": _TARGETS_SQL.format(bad="ABS(ac.price_target - lp.close) < 0.005 * lp.close"),   # within half a percent
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
        "theme": "correct",
        "message": "A consensus signal exists for a stock that no analyst covers",
        "why": "Model projections are being treated as analyst consensus: the gate in signals/consensus.py has leaked.",
        "fix": "The SELECT in signals/consensus.py must require total_analysts or price_target.",
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

    # ═══════════════════════════════════════════════════════════════════
    # LLM-classified regulatory signals
    # ═══════════════════════════════════════════════════════════════════
    # 2026-05-23: Gillette dossier showed Consumer Staples regulatory items
    # because that part matched. But 1,638 regulatory_signals rows ("Financial
    # Services" + "IT") never joined any stock — the AI classifier and the
    # stocks universe were using different sector taxonomies and no one knew.
    {
        "code": "REGULATORY_SECTOR_TAXONOMY_MISMATCH",
        "table": "regulatory_signals",
        "column": "sector",
        "theme": "correct",
        "message": "Regulatory signals use sector names that no stock has",
        "why": "Those signals never join to a stock, so they silently drop out of dossiers and sector views.",
        "fix": "Map the classifier's sector names to stocks.sector in sources/regulatory_classifier.py.",
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
]
