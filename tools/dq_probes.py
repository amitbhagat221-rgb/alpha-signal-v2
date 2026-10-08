"""
Alpha Signal v2 — Weekly data-quality probes (plan 0020; the evidence half of the
dq-auditor seat, plan 0019).

The October 2026 factor audit found its data faults five ways, none of which a
freshness, range or volume check performs. This job runs those five mechanically
on the tables the factors read, every week:

  second source     every statement column factors read against the Screener line
                    item that must hold the same quantity (tools.reconcile.FUND_FIELDS)
  column meaning    every OTHER statement column: which Screener item does it agree
                    with most? ("depreciation" agreed with 'Dividend Amount")
  impossible        values that cannot be real (operating expenses outside 20-150% of
                    revenue, equity above assets, a share count moving 5x in a year)
  days and jumps    a price day copied from the session before; a 40% move with no
                    corporate action on record; rows dated in the future
  proof vs ranking  each wired weight against the evidence on the column it ranks
                    (tools.factor_audit), and an independent recompute of the
                    factors that have a simple definition, against the frozen inputs
  rotation          one input table a week, profiled column by column

A finding is a plain claim plus the SQL that shows it (`query`, returning n_bad and
n_total), so anyone — the auditor seat, the server that checks its memo, Amit — can
re-run it. Nothing here writes to the database.

`drill()` proves the probes still work: it copies a recent slice of the tables into a
scratch database, plants known faults there one at a time (a column holding another
column's values, a copied price day, a share count times 1,000 …) and checks each is
found. A probe that cannot catch its planted fault is itself a finding.

Usage:
    python -m tools.dq_probes                # findings, as a table
    python -m tools.dq_probes --json
    python -m tools.dq_probes --drill        # plant faults in a scratch copy, prove they are caught
"""
import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db
from tools.reconcile import FUND_FIELDS, FUND_TOL

DISAGREE_MAX = 0.20          # a mapped column may disagree with Screener for up to this share of stocks
MEANING_MIN = 0.50           # an unmapped column "agrees with" an item from this share up
STATEMENT_TABLES = {"quarterly_income": "quarterly", "annual_balance_sheet": "annual", "annual_cash_flow": "annual"}
NOT_VALUES = {"sid", "period", "end_date", "reporting", "fetched_at"}
CONSOLIDATED = ("AND (t.reporting = 'consolidated' OR t.sid NOT IN "
                "(SELECT sid FROM quarterly_income WHERE reporting = 'consolidated'))")

# Unmapped columns whose best-agreeing Screener item is the one the name promises: a
# confirmation, not a finding. Anything else the probe matches is put to the reader.
NAME_FITS = {
    ("quarterly_income", "tax_and_minority"): {"Tax"},
    ("annual_balance_sheet", "total_assets"): {"Total"},
    ("annual_balance_sheet", "total_debt"): {"Borrowings"},
    ("annual_balance_sheet", "long_term_debt"): {"Long term Borrowings"},
    ("annual_balance_sheet", "cash_and_equivalents"): {"Cash & Bank", "Cash Equivalents"},
    ("annual_balance_sheet", "receivables"): {"Receivables", "Trade receivables"},
    ("annual_cash_flow", "net_change_in_cash"): {"Net Cash Flow"},
}

# What a second look already settled: reported every week as known, never as news.
KNOWN = {
    ("impossible", "annual_balance_sheet.shares_outstanding"):
        "about 36 vendor rows jump on the year; book-to-price and tiers take the share count from "
        "signals._fundamentals.shares_and_book, which rejects them (ADR 0062)",
    ("column_meaning", "annual_cash_flow.dividends_paid"):
        "cash paid in the year vs Screener's dividend declared for it: a timing difference; no factor reads it",
    ("second_source", "quarterly_income.revenue"):
        "Tickertape's revenue includes other income, Screener's Sales does not (Reliance: about 2% apart); "
        "about a fifth of stocks sit just outside the 5% tolerance",
}


def reader(path=None):
    """q(sql, params) → DataFrame on a read-only connection to `path` (default: the live DB)."""
    uri = f"file:{path or db.DB_PATH}?mode=ro"

    def q(sql, params=()):
        with sqlite3.connect(uri, uri=True) as conn:
            return pd.read_sql_query(sql, conn, params=params)
    return q


# ─────────────────────────── SQL the findings carry ───────────────────────────

def agree_sql(table, column, period_type, items, scale=1.0, count="disagree"):
    """One Tickertape column vs the sum of Screener `items` on the latest period both hold:
    n_bad = stocks that disagree (or, count='agree', agree) within FUND_TOL; n_total = compared."""
    basis = CONSOLIDATED if table == "quarterly_income" else ""
    names = ", ".join("'" + i.replace("'", "''") + "'" for i in items)
    op = ">" if count == "disagree" else "<="
    return f"""WITH tt AS (SELECT t.sid, t.end_date AS pe, t.{column} AS ours FROM {table} t
                 WHERE t.{column} IS NOT NULL AND t.{column} != 0 {basis}),
     sc AS (SELECT sid, period_end AS pe, SUM(value) * {scale} AS theirs, COUNT(*) AS k FROM fundamentals_screener
            WHERE period_type = '{period_type}' AND line_item IN ({names}) AND value IS NOT NULL GROUP BY sid, period_end),
     m AS (SELECT tt.sid, ours, theirs, ROW_NUMBER() OVER (PARTITION BY tt.sid ORDER BY tt.pe DESC) AS rn
           FROM tt JOIN sc ON sc.sid = tt.sid AND sc.pe = tt.pe WHERE sc.k >= {min(2, len(items))} AND theirs != 0)
SELECT COALESCE(SUM(ABS(ABS(ours) / ABS(theirs) - 1) {op} {FUND_TOL}), 0) AS n_bad, COUNT(*) AS n_total FROM m WHERE rn = 1"""


_LATEST_QUARTER = f"""WITH q AS (SELECT t.*, ROW_NUMBER() OVER (PARTITION BY t.sid ORDER BY t.end_date DESC) AS rn
           FROM quarterly_income t JOIN stocks s ON s.sid = t.sid
           WHERE s.sector != 'Financials' AND t.revenue > 0 {CONSOLIDATED})
SELECT COALESCE(SUM({{bad}}), 0) AS n_bad, COUNT(*) AS n_total FROM q WHERE rn = 1 AND {{col}} IS NOT NULL"""
_LATEST_BALANCE = """WITH b AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY sid ORDER BY end_date DESC) AS rn
           FROM annual_balance_sheet WHERE total_assets > 0)
SELECT COALESCE(SUM({bad}), 0) AS n_bad, COUNT(*) AS n_total FROM b WHERE rn = 1 AND {col} IS NOT NULL"""
_SCREENER_SHARE = """WITH f AS (SELECT fs.sid, fs.period_end, MAX(CASE WHEN line_item = 'Sales' THEN value END) AS sales,
                  MAX(CASE WHEN line_item = '{item}' THEN value END) AS x
           FROM fundamentals_screener fs JOIN stocks s ON s.sid = fs.sid
           WHERE fs.period_type = 'annual' AND s.sector != 'Financials' AND fs.line_item IN ('Sales', '{item}')
           GROUP BY fs.sid, fs.period_end),
     l AS (SELECT *, ROW_NUMBER() OVER (PARTITION BY sid ORDER BY period_end DESC) AS rn FROM f WHERE sales > 0 AND x IS NOT NULL)
SELECT COALESCE(SUM(x > 0.5 * sales), 0) AS n_bad, COUNT(*) AS n_total FROM l WHERE rn = 1"""

# (probe, subject, what a hit means, SQL → n_bad / n_total[/ sample], share allowed, factors it feeds)
RULES = [
    ("impossible", "quarterly_income.operating_expenses",
     "operating expenses are outside 20% to 150% of revenue",
     _LATEST_QUARTER.format(bad="operating_expenses > 1.5 * revenue OR operating_expenses < 0.2 * revenue", col="operating_expenses"),
     0.10, ["piotroski"]),
    ("impossible", "quarterly_income.ebitda",
     "stored EBITDA is not revenue minus operating expenses",
     _LATEST_QUARTER.format(bad="ABS(ebitda - (revenue - operating_expenses)) > 0.01 * revenue", col="ebitda"), 0.01, []),
    ("impossible", "quarterly_income.pbt", "profit before tax is larger than revenue",
     _LATEST_QUARTER.format(bad="pbt > revenue", col="pbt"), 0.03, ["piotroski", "accruals"]),
    ("impossible", "quarterly_income.net_income", "net profit is larger than revenue",
     _LATEST_QUARTER.format(bad="net_income > revenue", col="net_income"), 0.03, ["piotroski", "accruals"]),
    ("impossible", "annual_balance_sheet.total_equity", "equity is larger than total assets",
     _LATEST_BALANCE.format(bad="total_equity > total_assets", col="total_equity"), 0.01, ["book_to_price"]),
    ("impossible", "annual_balance_sheet.current_assets", "current assets are larger than total assets",
     _LATEST_BALANCE.format(bad="current_assets > 1.001 * total_assets", col="current_assets"), 0.01, ["piotroski", "accruals"]),
    ("impossible", "annual_balance_sheet.cash_and_equivalents", "cash is larger than total assets",
     _LATEST_BALANCE.format(bad="cash_and_equivalents > 1.001 * total_assets", col="cash_and_equivalents"), 0.01, ["accruals"]),
    ("impossible", "annual_balance_sheet.shares_outstanding",
     "the share count moved more than 5x on the year",
     """WITH b AS (SELECT sid, shares_outstanding AS s, LAG(shares_outstanding) OVER (PARTITION BY sid ORDER BY end_date) AS p,
                  ROW_NUMBER() OVER (PARTITION BY sid ORDER BY end_date DESC) AS rn
           FROM annual_balance_sheet WHERE shares_outstanding > 0)
SELECT COALESCE(SUM(s / p > 5 OR s / p < 0.2), 0) AS n_bad, COUNT(*) AS n_total FROM b WHERE rn = 1 AND p > 0""",
     0.0, ["book_to_price"]),
    ("impossible", "fundamentals_screener.Interest", "interest is more than half of sales (non-financial)",
     _SCREENER_SHARE.format(item="Interest"), 0.05, ["forensic penalty"]),
    ("impossible", "fundamentals_screener.Depreciation", "depreciation is more than half of sales (non-financial)",
     _SCREENER_SHARE.format(item="Depreciation"), 0.05, ["accruals", "forensic penalty"]),
    ("dates", "stock_prices.date", "a recent price day is a copy of the session before it",
     """WITH d AS (SELECT sid, date, close, volume, LAG(close) OVER (PARTITION BY sid ORDER BY date) AS pc,
                  LAG(volume) OVER (PARTITION BY sid ORDER BY date) AS pv
           FROM stock_prices WHERE date >= date((SELECT MAX(date) FROM stock_prices), '-60 day')),
     g AS (SELECT date, AVG(close = pc AND volume = pv) AS same FROM d WHERE pc IS NOT NULL GROUP BY date)
SELECT COALESCE(SUM(same > 0.5), 0) AS n_bad, COUNT(*) AS n_total, (SELECT GROUP_CONCAT(date) FROM g WHERE same > 0.5) AS sample FROM g""",
     0.0, ["every price factor"]),
    ("dates", "stock_prices.close", "a price moved more than 40% in a day with no split, bonus or dividend on record",
     """WITH r AS (SELECT sid, date, close, LAG(close) OVER (PARTITION BY sid ORDER BY date) AS prev
           FROM stock_prices WHERE date >= date((SELECT MAX(date) FROM stock_prices), '-60 day') AND close > 0),
     j AS (SELECT r.sid, r.date, (r.close / r.prev < 0.6 OR r.close / r.prev > 1.67) AND NOT EXISTS (
                      SELECT 1 FROM corporate_adjustments ca WHERE ca.sid = r.sid
                        AND ca.ex_date BETWEEN date(r.date, '-10 day') AND date(r.date, '+10 day')) AS bad
           FROM r WHERE r.prev > 0)
SELECT COALESCE(SUM(bad), 0) AS n_bad, COUNT(DISTINCT sid) AS n_total, (SELECT GROUP_CONCAT(sid || ' ' || date) FROM j WHERE bad) AS sample FROM j""",
     0.0, ["momentum", "the return label"]),
    ("dates", "quarterly_income.end_date", "statement rows are dated in the future",
     "SELECT COALESCE(SUM(end_date > date('now')), 0) AS n_bad, COUNT(*) AS n_total FROM quarterly_income", 0.0, []),
    ("dates", "stock_prices.delivery_pct", "the newest price day has no delivery figure for many stocks",
     """SELECT COALESCE(SUM(delivery_pct IS NULL), 0) AS n_bad, COUNT(*) AS n_total FROM stock_prices
WHERE date = (SELECT MAX(date) FROM stock_prices) AND source = 'bhavcopy'""", 0.30, ["delivery_anomaly_z"]),
    # found by the dq-auditor, 2026-10-04: a crore column holding rupees, valuation columns never filled
    ("impossible", "stocks.market_cap_cr", "a market cap above ₹30 lakh crore (rupees stored in a crore column)",
     "SELECT COALESCE(SUM(market_cap_cr > 3000000), 0) AS n_bad, COUNT(market_cap_cr) AS n_total FROM stocks", 0.0,
     ["the tiers", "every market-cap display"]),
    ("impossible", "stocks.pe_ratio", "P/E, P/B and ROE are all empty for the stock",
     "SELECT COALESCE(SUM(pe_ratio IS NULL AND pb_ratio IS NULL AND roe IS NULL), 0) AS n_bad, COUNT(*) AS n_total FROM stocks",
     0.25, ["the pick email", "the stock page", "the MCP stock tool"]),
    # 2026-10-08: 721 calls fetched since June sat unscored; forward_looking_intensity read last quarter's call
    ("dates", "nlp_scores.doc_date", "a fetched earnings call older than 14 days has no language score",
     """SELECT COALESCE(SUM(n.sid IS NULL), 0) AS n_bad, COUNT(*) AS n_total FROM transcripts t
LEFT JOIN nlp_scores n ON n.sid = t.sid AND n.doc_type = t.doc_type AND n.doc_date = t.doc_date
WHERE t.raw_text IS NOT NULL AND LENGTH(t.raw_text) > 2000 AND t.fetched_at < date('now', '-14 day')""", 0.02,
     ["forward_looking_intensity"]),
]


def _finding(probe, subject, claim, n_bad, n_total, query=None, sample=None, touches=(), verify="query"):
    n_bad, n_total = int(n_bad or 0), int(n_total or 0)
    return {"probe": probe, "subject": subject, "claim": claim, "n_bad": n_bad, "n_total": n_total,
            "share": round(n_bad / n_total, 3) if n_total else None, "sample": (str(sample)[:300] if sample else None),
            "query": query, "verify": verify if query else "sample", "touches": list(touches),
            "known": KNOWN.get((probe, subject))}


# ─────────────────────────── the probes ───────────────────────────

def second_source(q):
    """Mapped statement columns that disagree with Screener for too many stocks."""
    out = []
    for table, column, period_type, items, scale in FUND_FIELDS:
        sql = agree_sql(table, column, period_type, items, scale)
        r = q(sql).iloc[0]
        if r["n_total"] and r["n_bad"] / r["n_total"] > DISAGREE_MAX:
            out.append(_finding("second_source", f"{table}.{column}",
                                f"disagrees with Screener {' + '.join(items)} for more than a fifth of stocks",
                                r["n_bad"], r["n_total"], sql, touches=["every statement factor reading it"]))
    return out


def column_meaning(q, tables=None):
    """Statement columns with no declared second source: the Screener item each agrees
    with most. The reader judges whether the name fits."""
    mapped = {(t, c) for t, c, *_ in FUND_FIELDS}
    out = []
    for table, period_type in STATEMENT_TABLES.items():
        if tables and table not in tables:
            continue
        cols = [c for c in q(f"PRAGMA table_info({table})")["name"] if c not in NOT_VALUES and (table, c) not in mapped]
        if not cols:
            continue
        basis = CONSOLIDATED if table == "quarterly_income" else ""
        tt = q(f"SELECT t.sid, t.end_date AS pe, {', '.join('t.' + c for c in cols)} FROM {table} t WHERE 1 = 1 {basis}")
        sc = q("SELECT sid, period_end AS pe, line_item, value FROM fundamentals_screener WHERE period_type = ? "
               "AND value IS NOT NULL AND value != 0", (period_type,))
        wide = sc.pivot_table(index=["sid", "pe"], columns="line_item", values="value", aggfunc="first")
        m = tt.merge(wide, left_on=["sid", "pe"], right_index=True).sort_values("pe").groupby("sid").tail(1)
        for c in cols:
            ours = pd.to_numeric(m[c], errors="coerce").abs()
            best, share, n = None, 0.0, 0
            for item in wide.columns:
                both = ours.notna() & (ours != 0) & m[item].notna()
                if both.sum() < 50:
                    continue
                s = float(((ours[both] / m.loc[both, item].abs() - 1).abs() <= FUND_TOL).mean())
                if s > share:
                    best, share, n = item, s, int(both.sum())
            fits = NAME_FITS.get((table, c))
            if fits and best not in fits:      # it used to hold what its name says; now it does not
                item = sorted(fits)[0]
                sql = agree_sql(table, c, period_type, (item,))
                r = q(sql).iloc[0]
                out.append(_finding("column_meaning", f"{table}.{c}",
                                    f"no longer agrees with Screener '{item}', the item its name promises",
                                    r["n_bad"], r["n_total"], sql))
            elif best and share >= MEANING_MIN and not fits:
                sql = agree_sql(table, c, period_type, (best,), count="agree")
                out.append(_finding("column_meaning", f"{table}.{c}",
                                    f"holds the same values as Screener '{best}' for most stocks: does the column's name say that?",
                                    round(share * n), n, sql))
    return out


def rules(q, only=None):
    out = []
    for probe, subject, claim, sql, max_share, touches in RULES:
        if only and subject not in only:
            continue
        r = q(sql).iloc[0]
        n_bad, n_total = int(r["n_bad"] or 0), int(r["n_total"] or 0)
        if n_bad and (not n_total or n_bad / n_total > max_share):
            out.append(_finding(probe, subject, claim, n_bad, n_total, sql, r.get("sample"), touches))
    return out


def proof_vs_ranking():
    """Each wired weight against its evidence and its coverage (tools.factor_audit)."""
    import factors
    from tools.factor_audit import audit
    words = {"WRONG_SIGN": "the weight's sign is opposite to the evidence",
             "BELOW_BAR": "the evidence is below the bar for a weight",
             "THIN_EVIDENCE": "the evidence rests on fewer than 20 dates",
             "NO_EVIDENCE": "there is no evidence row for this tier",
             "DEAD": "no stock in the tier has a value", "COVERAGE_DROP": "coverage fell sharply against a year ago",
             "BELOW_ELIGIBLE": "many stocks that should have a value do not",
             "STALE_INPUT": "an input table is older than its allowance"}
    out = []
    for row in audit()["rows"]:
        if not row["weight"]:
            continue
        col = factors.FACTORS[row["factor"]].get("replay_col") or factors.pit_column(row["factor"])
        if col != factors.pit_column(row["factor"]):
            out.append(_finding("proof_vs_ranking", f"{row['factor']} {row['tier']}",
                                "the weight ranks a different column from the one its evidence was measured on",
                                1, 1, sample=f"ranked {col}, evidence on {factors.pit_column(row['factor'])}",
                                touches=[row["factor"]]))
        for flag in row["flags"]:
            flag = flag.split(":")[0]
            if flag not in words:
                continue
            sql = None
            if flag in ("WRONG_SIGN", "BELOW_BAR", "THIN_EVIDENCE"):
                bad = {"WRONG_SIGN": f"t_stat * {row['weight']} < 0", "BELOW_BAR": "ABS(t_stat) < 1.5",
                       "THIN_EVIDENCE": "n_periods < 20"}[flag]
                sql = (f"SELECT ({bad}) AS n_bad, 1 AS n_total FROM pit_ic_by_tier_v2 WHERE signal = '{row['factor']}' "
                       f"AND cap_tier = '{row['tier']}' AND source LIKE 'v2_recompute%' ORDER BY n_periods DESC LIMIT 1")
            out.append(_finding("proof_vs_ranking", f"{row['factor']} {row['tier']}", words[flag], 1, 1, sql,
                                sample=f"weight {row['weight']:+.2f}, coverage {row.get('coverage')}",
                                touches=[row["factor"]]))
    return out


def recompute(q, sample=40, seed=None):
    """Three wired factors with a one-line definition, recomputed from raw rows for a
    random sample and compared with what the screener froze on the latest pick date."""
    import factors
    snap = q("SELECT sid, cap_tier, inputs_json FROM pit_replay_snapshots WHERE snapshot_date = "
             "(SELECT MAX(snapshot_date) FROM pit_replay_snapshots)")
    if snap.empty:
        return []
    frozen = pd.DataFrame([json.loads(j) for j in snap["inputs_json"]], index=snap["sid"])
    day = q("SELECT MAX(snapshot_date) AS d FROM pit_replay_snapshots").iloc[0]["d"]
    pick = frozen.sample(min(sample, len(frozen)), random_state=seed if seed is not None else int(date.today().strftime("%Y%m%d"))).index
    ph = ", ".join("?" * len(pick))
    mine = {}
    px = q(f"SELECT sid, date, delivery_pct FROM stock_prices WHERE sid IN ({ph}) AND close > 0 AND date <= ? ORDER BY sid, date",
           (*pick, day))
    z = {}
    for sid, g in px.groupby("sid"):
        d = g["delivery_pct"].tail(90).dropna()
        if len(d) >= 30 and d.iloc[:-1].std() > 0:
            z[sid] = (d.iloc[-1] - d.iloc[:-1].mean()) / d.iloc[:-1].std()
    mine["delivery_anomaly_z"] = (pd.Series(z), 0.01)
    sh = q(f"SELECT sid, end_date, pledge_pct FROM shareholding WHERE sid IN ({ph}) AND date(end_date, '+21 day') <= ? "
           "ORDER BY sid, end_date", (*pick, day)).groupby("sid").tail(1).set_index("sid")
    mine["pledge_quality"] = (1 - sh["pledge_pct"] / 100, 0.001)
    out = []
    for key, (values, tol) in mine.items():
        col = factors.SCREENER_COLS.get(key, key)
        if col not in frozen.columns:
            continue
        both = pd.DataFrame({"mine": values, "ranked": pd.to_numeric(frozen.loc[pick, col], errors="coerce")}).dropna()
        off = both[(both["mine"] - both["ranked"]).abs() > tol]
        if len(both) >= 10 and len(off) / len(both) > 0.10:
            out.append(_finding("recompute", key, "an independent recompute from raw rows differs from the ranked value",
                                len(off), len(both), touches=[key],
                                sample="; ".join(f"{s}: {r.mine:.3f} vs {r.ranked:.3f}" for s, r in off.head(4).iterrows())))
    return out


def rotation(q, week=None):
    """One factor-input table a week: a column whose share of empty values in the newest
    period jumped, or whose values in the newest period are all the same."""
    import factors
    import tables as registry
    names = sorted({t for ts in factors.INPUT_TABLES.values() for t in ts
                    if (registry.TABLES.get(t) or {}).get("date_col") and t != "stock_prices_unlisted"})
    week = date.today().isocalendar()[1] if week is None else week
    table = names[week % len(names)]
    col = registry.TABLES[table]["date_col"]
    periods = q(f"SELECT DISTINCT {col} AS d FROM {table} WHERE {col} <= date('now') ORDER BY 1 DESC LIMIT 5")["d"].tolist()
    if len(periods) < 3:
        return table, []
    df = q(f"SELECT * FROM {table} WHERE {col} IN ({', '.join('?' * len(periods))})", tuple(periods))
    out = []
    now, before = df[df[col] == periods[0]], df[df[col] != periods[0]]
    for c in df.columns:
        if c in NOT_VALUES or c == col:
            continue
        empty_now = now[c].isna().mean()
        empty_before = before.groupby(col)[c].apply(lambda s: s.isna().mean()).median()
        if empty_now - empty_before > 0.20 and len(now) >= 20:
            sql = (f"SELECT COALESCE(SUM({c} IS NULL), 0) AS n_bad, COUNT(*) AS n_total FROM {table} WHERE {col} = '{periods[0]}'")
            out.append(_finding("rotation", f"{table}.{c}",
                                "far more values are empty in the newest period than in the periods before it",
                                int(now[c].isna().sum()), len(now), sql, sample=f"newest period {periods[0]}"))
        elif now[c].nunique() == 1 and before[c].nunique() > 3 and len(now) >= 20:
            sql = (f"SELECT (COUNT(DISTINCT {c}) = 1) * COUNT(*) AS n_bad, COUNT(*) AS n_total FROM {table} WHERE {col} = '{periods[0]}'")
            out.append(_finding("rotation", f"{table}.{c}", "every row of the newest period carries the same value",
                                len(now), len(now), sql, sample=f"newest period {periods[0]}"))
    return table, out


def run(seed=None):
    """Every probe on the live database → {as_of, findings: [...], scanned: {...}}. A probe
    that cannot run is reported in `scanned`, never dropped."""
    q = reader()
    findings, scanned = [], {}
    for name, fn in (("second_source", lambda: second_source(q)), ("column_meaning", lambda: column_meaning(q)),
                     ("impossible + dates", lambda: rules(q)), ("proof_vs_ranking", proof_vs_ranking),
                     ("recompute", lambda: recompute(q, seed=seed))):
        try:
            got = fn()
            findings += got
            scanned[name] = f"{len(got)} finding(s)"
        except Exception as e:                              # noqa: BLE001
            scanned[name] = f"could not run: {type(e).__name__}: {e}"[:200]
    try:
        table, got = rotation(q)
        findings += got
        scanned["rotation"] = f"{table}: {len(got)} finding(s)"
    except Exception as e:                                  # noqa: BLE001
        scanned["rotation"] = f"could not run: {type(e).__name__}: {e}"[:200]
    scanned["second_source"] += f" over {len(FUND_FIELDS)} mapped columns"
    scanned["impossible + dates"] += f" over {len(RULES)} rules"
    for i, f in enumerate(findings, 1):
        f["id"] = f"F{i}"
    return {"as_of": date.today().isoformat(), "findings": findings, "scanned": scanned}


def check(query):
    """Re-run a finding's SQL on the live DB, read-only → (n_bad, n_total) or raises ValueError."""
    df, err = db.safe_read_sql(query, max_rows=5)
    if err or df is None or df.empty or "n_bad" not in df.columns:
        raise ValueError(err or "the query must return a row with a column named n_bad")
    r = df.iloc[0]
    return int(r["n_bad"] or 0), int(r["n_total"] or 0) if "n_total" in df.columns else 0


# ─────────────────────────── the drill: planted faults ───────────────────────────

_SLICE = {
    "stocks": "SELECT * FROM live.stocks",
    "corporate_adjustments": "SELECT * FROM live.corporate_adjustments",
    "quarterly_income": "SELECT * FROM live.quarterly_income WHERE end_date >= date('now', '-400 day')",
    "annual_balance_sheet": "SELECT * FROM live.annual_balance_sheet WHERE end_date >= date('now', '-1200 day')",
    "annual_cash_flow": "SELECT * FROM live.annual_cash_flow WHERE end_date >= date('now', '-800 day')",
    "fundamentals_screener": "SELECT * FROM live.fundamentals_screener WHERE period_end >= date('now', '-800 day')",
    "stock_prices": "SELECT * FROM live.stock_prices WHERE date >= date((SELECT MAX(date) FROM live.stock_prices), '-25 day')",
}

# (name, what is planted, SQL that plants it, probe that must notice, subject it must name)
PLANTS = [
    ("column holds another column", "operating expenses overwritten with profit before tax",
     "UPDATE quarterly_income SET operating_expenses = pbt",
     lambda q: second_source(q) + rules(q), "quarterly_income.operating_expenses"),
    ("cash flow column mis-mapped", "operating cash flow overwritten with dividends paid",
     "UPDATE annual_cash_flow SET operating_cash_flow = dividends_paid",
     second_source, "annual_cash_flow.operating_cash_flow"),
    ("unmapped column changes meaning", "total assets overwritten with total equity",
     "UPDATE annual_balance_sheet SET total_assets = total_equity",
     lambda q: column_meaning(q, tables={"annual_balance_sheet"}) + rules(q), "annual_balance_sheet.total_assets"),
    ("copied price day", "the newest price day duplicated as the next day",
     "INSERT INTO stock_prices SELECT sid, date(date, '+1 day'), open, high, low, close, prev_close, volume, traded_value, "
     "num_trades, delivered_qty, delivery_pct, source FROM stock_prices WHERE date = (SELECT MAX(date) FROM stock_prices)",
     rules, "stock_prices.date"),
    ("unrecorded split", "one stock's newest close cut to a fifth",
     "UPDATE stock_prices SET close = close / 5 WHERE date = (SELECT MAX(date) FROM stock_prices) AND sid = "
     "(SELECT sid FROM stock_prices WHERE date = (SELECT MAX(date) FROM stock_prices) AND sid NOT IN "
     "(SELECT sid FROM corporate_adjustments WHERE ex_date >= date('now', '-90 day')) ORDER BY sid LIMIT 1)",
     rules, "stock_prices.close"),
    ("unit slip", "the share count of every stock's newest year multiplied by 1,000",
     "UPDATE annual_balance_sheet SET shares_outstanding = shares_outstanding * 1000 WHERE (sid, end_date) IN "
     "(SELECT sid, MAX(end_date) FROM annual_balance_sheet GROUP BY sid)",
     lambda q: second_source(q) + rules(q), "annual_balance_sheet.shares_outstanding"),
    ("inflated profit", "net profit multiplied by 100 for every stock",
     "UPDATE quarterly_income SET net_income = net_income * 100",
     lambda q: second_source(q) + rules(q), "quarterly_income.net_income"),
]


def _scratch(path):
    conn = sqlite3.connect(f"file:{path}?mode=rwc", uri=True)      # uri: the live DB attaches read-only
    conn.execute(f"ATTACH DATABASE 'file:{db.DB_PATH}?mode=ro' AS live")
    for table, sql in _SLICE.items():         # always `main.`: an unqualified name would resolve to the live table
        conn.execute(f"CREATE TABLE main.{table} AS {sql}")
    conn.commit()
    conn.execute("DETACH DATABASE live")
    return conn


def drill():
    """Plant each fault in a fresh scratch copy and run the probe that must notice it: the
    subject must be flagged afterwards, with more bad rows than before the plant.
    → {planted, caught, missed: [...], results: [...]}. The live database is only read."""
    import shutil
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        clean = str(Path(tmp) / "clean.db")
        _scratch(clean).close()
        for name, what, plant, probe, subject in PLANTS:
            path = str(Path(tmp) / "scratch.db")
            shutil.copy(clean, path)
            q = reader(path)
            before = {f["subject"]: f["n_bad"] for f in probe(q)}
            with sqlite3.connect(path) as conn:
                conn.execute(plant)
            after = {f["subject"]: f["n_bad"] for f in probe(q)}
            results.append({"plant": name, "planted": what, "must_flag": subject,
                            "caught": after.get(subject, 0) > before.get(subject, 0)})
            Path(path).unlink()
    return {"planted": len(results), "caught": sum(r["caught"] for r in results),
            "missed": [r["plant"] for r in results if not r["caught"]], "results": results}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--drill", action="store_true")
    a = ap.parse_args()
    if a.drill:
        d = drill()
        if a.json:
            print(json.dumps(d))
        else:
            for r in d["results"]:
                print(f"  {'caught' if r['caught'] else 'MISSED':8s} {r['plant']}: {r['planted']}")
            print(f"\n{d['caught']} of {d['planted']} planted faults caught")
        sys.exit(1 if d["missed"] else 0)
    out = run()
    if a.json:
        print(json.dumps(out, default=str))
        return
    for f in out["findings"]:
        tag = " (known)" if f["known"] else ""
        print(f"  {f['id']:4s} {f['probe']:17s} {f['subject']:44s} {f['n_bad']:>6,} of {f['n_total']:>6,}  {f['claim']}{tag}")
    print("\nscanned: " + "; ".join(f"{k}: {v}" for k, v in out["scanned"].items()))


if __name__ == "__main__":
    main()
