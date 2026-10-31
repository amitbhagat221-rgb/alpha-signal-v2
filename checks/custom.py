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

# Every stored analyst target next to the latest close; {bad} is the rule being counted.
_TARGETS_SQL = """
    WITH latest_px AS (
        SELECT a.sid AS sid, (SELECT close FROM stock_prices WHERE sid = a.sid ORDER BY date DESC LIMIT 1) AS close
        FROM (SELECT DISTINCT sid FROM analyst_consensus) a
    ),
    judged AS (
        SELECT ac.sid, ac.price_target AS pt, lp.close, COALESCE({bad}, 0) AS bad
        FROM analyst_consensus ac JOIN latest_px lp ON ac.sid = lp.sid
        WHERE ac.has_analyst_data = 1 AND ac.price_target IS NOT NULL AND lp.close > 0
    )
    SELECT COALESCE(SUM(bad), 0) AS n_bad, COUNT(*) AS n_total,
           (SELECT sid || ': target ' || ROUND(pt, 1) || ' vs price ' || ROUND(close, 1)
            FROM judged WHERE bad ORDER BY pt / close DESC LIMIT 1) AS sample
    FROM judged
"""

# An index option within a week of expiry may sit at most this share of the index above its
# intrinsic value (OPTION_PRICE_IMPOSSIBLE).
OPTION_TIME_VALUE_MAX = 0.30

def _implausible_targets():
    """ANALYST_TARGET_IMPLAUSIBLE on the targets a reader is shown: rebased across a later split,
    consolidation or demerger (views.target_basis) before the PT_CLOSE_RATIO test, so a call Yahoo
    never rebased (IFIB after its 2026-10-13 consolidation) is judged on today's share basis."""
    import views
    from validators.plausibility import pt_implausible, pt_outside_range
    rows = views.native_rows("SELECT sid, price_target, price_target_low, price_target_high FROM analyst_consensus "
                             "WHERE has_analyst_data = 1 AND price_target IS NOT NULL")
    sids = [r["sid"] for r in rows]
    close, basis = views.latest_close(sids), views.target_basis(sids)
    bad, n = [], 0
    for r in rows:
        px = (close.get(r["sid"]) or (None,))[0]
        if not px or px <= 0:
            continue
        n += 1
        pt = r["price_target"] * basis.get(r["sid"], {}).get("factor", 1.0)
        if pt_implausible(pt, px) or pt_outside_range(r["price_target"], r["price_target_low"], r["price_target_high"]):
            bad.append((pt / px, f"{r['sid']}: target {pt:.1f} vs price {px:.1f}"))
    return {"n_bad": len(bad), "n_total": n, "sample": max(bad)[1] if bad else None}


def _options_live():
    import options_live           # lazy: the check catalog must not import the Kite stack
    return options_live.health_check()


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
            WITH window_px AS MATERIALIZED (     -- the 12 days first (date index); LAG over the table walked all 5M rows
                SELECT sid, date, close FROM stock_prices
                WHERE date >= (SELECT date(MAX(date), '-12 day') FROM stock_prices) AND close > 0
            ),
            recent AS (
                SELECT sid, date, close, LAG(close) OVER (PARTITION BY sid ORDER BY date) AS prev FROM window_px
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

    {
        "code": "OPTION_PRICE_IMPOSSIBLE",
        "table": "fno_bhav",
        "column": "close",
        "theme": "correct",
        "message": "Index option prices that cannot be real: in the last week before expiry, more than "
                   f"{OPTION_TIME_VALUE_MAX:.0%} of the index above the option's value at expiry",
        "why": "A week from expiry an index option is worth its intrinsic value plus a little time value (a few % of "
               "the index in a crash). A price far above that is the index level or a shifted column: BSE's expiry-day "
               "file puts the index settlement in the close column, and 43,361 SENSEX/BANKEX rows stored a 69000 call "
               "'closing' at 72026 (fixed 2026-10-21). The options paper book, the IV surface and the premium backtest "
               "read these prices.",
        "fix": "Look at the sample row's raw file; fix the producer (sources/bse_fo.py for SENSEX/BANKEX, "
               "sources/fno_pull.py for NSE) and rewrite the rows with targeted UPDATEs.",
        "severity": WARN,
        # Last 14 days of the chain (date index). Settle on expiry day is the index settlement by
        # convention (NSE and BSE), so settle is judged only before expiry. Bound 30%: NSE's history
        # tops out at 22% (stale closes of untraded strikes), the BSE bug sat at ~100%.
        "sql": f"""
            WITH chain AS (
                SELECT symbol, trade_date, expiry_date, strike, option_type, close, settle, underlying_price AS s,
                       MAX(CASE WHEN option_type = 'CE' THEN underlying_price - strike
                                ELSE strike - underlying_price END, 0) AS intrinsic
                FROM fno_bhav
                WHERE trade_date >= (SELECT date(MAX(trade_date), '-14 day') FROM fno_bhav)
                  AND instrument_type = 'IDO' AND underlying_price > 0 AND trade_date >= date(expiry_date, '-7 day')
            ),
            judged AS (
                SELECT *, (close - intrinsic > {OPTION_TIME_VALUE_MAX} * s
                           OR (trade_date < expiry_date AND settle - intrinsic > {OPTION_TIME_VALUE_MAX} * s)) AS bad
                FROM chain
            )
            SELECT COALESCE(SUM(bad), 0) AS n_bad, COUNT(*) AS n_total,
                   (SELECT symbol || ' ' || strike || ' ' || option_type || ' expiring ' || expiry_date || ' on '
                           || trade_date || ': close ' || close || ', settle ' || settle || ', index ' || s
                    FROM judged WHERE bad LIMIT 1) AS sample
            FROM judged
        """,
    },

    {
        "code": "OPTIONS_LIVE",
        "table": "option_live_settings",
        "column": "value",
        "theme": "ran",
        "message": "The live option book (plan 0029): Kite positions differ from the ledger, or a live step failed",
        "why": "The job sells option strangles through Kite. A position the ledger does not know is unmanaged risk "
               "(the buy-back and Close-all only act on what the ledger holds); a failed entry, buy-back or settle "
               "is a missed trade, a NIFTY leg left into expiry or a skipped SENSEX entry.",
        "fix": "Open /options on the ops cockpit: the Live panel shows the last step results and the mismatch. "
               "A mismatch already stopped entries: fix the position in Kite (or the ledger), then "
               "`run.sh options_live reconcile` and Resume. A failed step: read its run in Flow; "
               "a missing Kite login is the usual cause.",
        "severity_text": "CRITICAL on a broker ≠ ledger mismatch, or on a failed step in approve / auto mode; WARN in shadow",
        "may_be_empty": True,     # nothing to judge before the first shadow run
        "fn": _options_live,
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
        "message": "Analyst price targets that cannot be real: more than 3x, or under a third of, the share price, or an average outside its own low-high range",
        "why": "A broker call from before a crash, or Yahoo garbage for a thinly covered small cap; or an "
               "average written by one source next to a range from another (178 rows, 2026-10). A call from "
               "before a split, consolidation or demerger is judged rebased (views.target_basis), not flagged. "
               "The cockpit already hides these; the weekly Yahoo sweep nulls them.",
        "fix": "Both writers refuse these (the Yahoo sweep and the broker aggregate share "
               "validators.plausibility.PT_CLOSE_RATIO), so a few rows mean a price moved since the last write: "
               "`python -m sources.moneycontrol_recos --aggregate-only` rebuilds. Many rows mean a writer lost its gate. "
               "A rebase gone wrong: check corporate_adjustments for the stock.",
        "critical_pct": 10,
        "warn_pct": 0.5,
        "fn": _implausible_targets,
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
