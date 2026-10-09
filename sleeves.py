"""
Alpha Signal v2 — Sleeves: the investor-playbook rules as portfolios.

A sleeve is one playbook turned into a rule that answers, for any date t, "which
stocks does this playbook hold?" using only what was known at t. The cockpit page
(cockpit/playbooks.py) and the backtest (tools/playbook_backtest.py) call the SAME
functions, so what is shown is what is tested.

    SLEEVES[key] = {label, who, rule (plain words), since (first date the inputs
                    exist), members(ctx, t) -> set of sids, caveat}

`ctx` is the loaded data (load_context): the stored point-in-time factor panel
(daily_snapshots_pit), insider trades, annual statements, resignations, pledge.
Members are always restricted to pickable tiers as of t (never MICRO) and, for
statement rules, to non-financial companies.

The thresholds were set on 2026-10-04 BEFORE any return was looked at. Do not tune
them against the backtest: with ~5 years of survivors-only history every extra try
is a multiple-testing cost (ADR 0043).
"""

import re
from datetime import date, timedelta

import pandas as pd

from config import PICKABLE_TIERS
from pit import INSIDER_DISCLOSURE_DAYS
from db import read_sql

# ── breakouts (O'Neil / Minervini) ──
BREAKOUT_DELIVERY_Z = 1.0       # delivery anomaly, standard deviations above the stock's own norm
BREAKOUT_POSITION = 0.85        # where the price sits in its 52-week range (1 = at the high)

# ── deep value (Graham) ──
DEEP_BOOK_TO_PRICE = 1.0        # price at or below book value
DEEP_EARNINGS_YIELD = 0.08      # earnings / price
DEEP_MAX_DEBT_TO_EQUITY = 0.5
DEEP_MIN_PRICE_TO_BOOK = 0.2    # below this (or a P/E under DEEP_MIN_PE) the inputs are more likely wrong than the stock cheap
DEEP_MIN_PE = 2

# ── insider buying ──
INSIDER_DAYS = 90
INSIDER_CATEGORIES = ("Promoters", "Promoter Group", "Director", "Key Managerial Personnel")
INSIDER_MIN_CR = 1.0            # net purchases, Rs crore
INSIDER_MIN_BUYERS = 2
INSIDER_LAG_DAYS = INSIDER_DISCLOSURE_DAYS   # trade → public (pit; was 3 = the median, half not yet public)

# ── quality (the compounder rule on the years of statements we hold) ──
ROCE_BAR = 15                   # %
SALES_CAGR_BAR = 10             # % a year
QUALITY_YEARS = 5               # backtest version: 5 fiscal years (the page uses 10, which has no history to test)
QUALITY_MIN_HITS = 4
STATEMENT_LAG_DAYS = 75         # an annual statement is public about 75 days after the year ends

# ── red flags that have history (the avoid list as a veto) ──
RESIGNATION_DAYS = 180
RESIGNATIONS = ("Resignation of Statutory Auditors", "Resignation of Chief Financial Officer (CFO)",
                "Resignation of Chief Executive Officer (CEO)", "Resignation of Managing Director")
DISTRESS_Z = 1.81               # Altman Z below this = distress zone
PLEDGE_PCT = 25
SHAREHOLDING_LAG_DAYS = 21

# ── cloning (Pabrai): follow what proven investors just bought ──
CLONE_FRESH_DAYS = 120          # the filing showing the purchase must be this recent
CLONE_MIN_RISE = 0.05           # percentage points; below this a change is rounding
CLONE_MIN_STOCKS = 5            # "active investor" in the broad version: named above 1% in this many companies
INDIVIDUAL_SECTION = "ShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh"
# Investors worth following, matched on name tokens across every non-promoter section of
# the filing (individuals, FPIs, AIFs, bodies corporate). Each pattern is a set of words
# that must all appear in the filed name. Only names present in our filings are listed.
# NOTE: this list was chosen in 2026 knowing who did well — a backtest on it has hindsight
# in the choice of investors. `cloning_broad` is the version without that problem.
FOLLOWED = {
    "Mukul Agrawal": [("MUKUL", "MAHAVIR", "AGRAWAL")],
    "Ashish Kacholia": [("ASHISH", "KACHOLIA")],
    "Rekha Jhunjhunwala & family": [("REKHA", "JHUNJHUNWALA"), ("RAKESH", "JHUNJHUNWALA")],
    "Anil Kumar Goel & Seema Goel": [("ANIL", "KUMAR", "GOEL"), ("SEEMA", "GOEL")],
    "Nalanda (Pulak Prasad)": [("NALANDA", "INDIA")],
    "Abakkus (Sunil Singhania)": [("ABAKKUS",)],
    "Akash Bhanshali": [("AKASH", "BHANSHALI")],
    "Vijay Kedia": [("VIJAY", "KEDIA"), ("KEDIA", "SECURITIES")],
    "Madhusudan Kela & family": [("MADHUSUDAN", "KELA")],
    "Radhakishan Damani": [("RADHAKISHAN", "DAMANI"), ("BRIGHT", "STAR", "INVESTMENTS"), ("DERIVE", "TRADING")],
    "Nemish Shah": [("NEMISH", "SHAH")],
    "Dolly Khanna": [("DOLLY", "KHANNA")],
    "Ramesh Damani": [("RAMESH", "DAMANI")],
    "Porinju Veliyath": [("PORINJU", "VELIYATH")],
}

MIN_NAMES = 5                   # a sleeve with fewer names that month is not held


def _iso(d):
    return d.isoformat() if hasattr(d, "isoformat") else str(d)[:10]


def _back(t, days):
    return (pd.Timestamp(_iso(t)) - timedelta(days=days)).date().isoformat()


# ═══════════════════════════ the rules (pure: frame in, mask / set out) ═══════════════════════════

def breakout_mask(df):
    """Rows of a factor frame that meet the breakout rule."""
    return ((df["announcement_car"] > 0) & (df["delivery_anomaly_z"] >= BREAKOUT_DELIVERY_Z)
            & (df["position_52w"] >= BREAKOUT_POSITION) & (df["mom_6m"] > 0))


def deep_value_mask(df):
    """Rows that meet the deep-value rule and have plausible ratios."""
    cheap = ((df["book_to_price"] >= DEEP_BOOK_TO_PRICE) & (df["earnings_yield"] >= DEEP_EARNINGS_YIELD)
             & (df["debt_to_equity"].fillna(0) <= DEEP_MAX_DEBT_TO_EQUITY))
    return cheap & deep_value_sane(df)


def deep_value_sane(df):
    return (df["book_to_price"] <= 1 / DEEP_MIN_PRICE_TO_BOOK) & (df["earnings_yield"] <= 1 / DEEP_MIN_PE)


def insider_net_buyers(trades):
    """Per stock, from trades [sid, person, side, value_lakhs, trade_date] inside the window:
    [sid, buyers, n_buys, bought_cr, sold_cr, net_cr, last_buy, top_buyer, cluster] for
    stocks where insiders were net buyers of INSIDER_MIN_CR or INSIDER_MIN_BUYERS bought."""
    cols = ["sid", "buyers", "n_buys", "bought_cr", "sold_cr", "net_cr", "last_buy", "top_buyer", "cluster"]
    if trades.empty:
        return pd.DataFrame(columns=cols)
    t = trades.assign(cr=trades["value_lakhs"] / 100.0)
    rows = []
    for sid, g in t.groupby("sid"):
        buys, sells = g[g["side"] == "Buy"], g[g["side"] == "Sell"]
        net, buyers = buys["cr"].sum() - sells["cr"].sum(), buys["person"].nunique()
        if buys.empty or net <= 0 or not (net >= INSIDER_MIN_CR or buyers >= INSIDER_MIN_BUYERS):
            continue
        top = buys.groupby("person")["cr"].sum().sort_values(ascending=False)
        rows.append((sid, int(buyers), len(buys), round(buys["cr"].sum(), 2), round(sells["cr"].sum(), 2), round(net, 2),
                     buys["trade_date"].max(), " ".join(str(top.index[0]).split()), buyers >= INSIDER_MIN_BUYERS))
    return pd.DataFrame(rows, columns=cols)


def quality_stats(years, n_years, min_hits):
    """One stock's annual rows (oldest first; columns Profit before tax, Interest, Equity Share
    Capital, Reserves, Borrowings, Sales, Net profit) → {hits, roce_median, roce_latest,
    sales_cagr, debt_to_equity} when the last `n_years` pass the quality rule, else None.
    Return on capital = (profit before tax + interest) / (equity + reserves + borrowings)."""
    g = years.tail(n_years)
    if len(g) < n_years:
        return None
    capital = g["Equity Share Capital"].fillna(0) + g["Reserves"].fillna(0) + g["Borrowings"].fillna(0)
    roce = (g["Profit before tax"] + g["Interest"].fillna(0)) / capital.where(capital > 0) * 100
    hits = int((roce >= ROCE_BAR).sum())
    s0, s1 = g["Sales"].iloc[0], g["Sales"].iloc[-1]
    if hits < min_hits or (g["Net profit"] <= 0).any() or not (s0 and s0 > 0 and s1 and s1 > 0):
        return None
    cagr = ((s1 / s0) ** (1 / (len(g) - 1)) - 1) * 100
    if cagr < SALES_CAGR_BAR:
        return None
    equity = g["Equity Share Capital"].iloc[-1] + g["Reserves"].iloc[-1]
    return {"hits": hits, "roce_median": round(float(roce.median()), 1), "roce_latest": round(float(roce.iloc[-1]), 1),
            "sales_cagr": round(cagr, 1),
            "debt_to_equity": round(float(g["Borrowings"].fillna(0).iloc[-1] / equity), 2) if equity and equity > 0 else None}


def norm_name(name):
    """A filed holder name, upper-cased with punctuation and extra spaces removed."""
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", str(name).upper())).strip()


def followed_investor(name):
    """The FOLLOWED investor a filed name belongs to, or None."""
    tokens = set(norm_name(name).split())
    for who, patterns in FOLLOWED.items():
        if any(set(p) <= tokens for p in patterns):
            return who
    return None


def holder_changes(holders, t):
    """From named-holder rows [sid, end_date, filed_at, investor, pct] public at t: one row per
    (sid, investor) in each stock's LATEST filing — [sid, investor, pct, before, change, filed_at]
    with change ∈ new / up / down / same, or 'unknown' when the stock has no earlier filing.
    Uses the latest revision of each quarter that was public at t."""
    cols = ["sid", "investor", "pct", "before", "change", "filed_at"]
    h = holders[holders["filed_at"] <= _iso(t) + "T23:59:59"]
    if h.empty:
        return pd.DataFrame(columns=cols)
    filings = h.groupby(["sid", "end_date"], as_index=False)["filed_at"].max()
    filings["rank"] = filings.groupby("sid")["end_date"].rank(ascending=False, method="first")
    two = filings[filings["rank"] <= 2]
    h = h.merge(two, on=["sid", "end_date", "filed_at"])
    h = h[h["investor"].notna()]
    pct = h.groupby(["sid", "investor", "rank"])["pct"].sum().unstack("rank")
    for r in (1.0, 2.0):
        if r not in pct.columns:
            pct[r] = float("nan")
    now = pct[pct[1.0].notna()].reset_index().rename(columns={1.0: "pct", 2.0: "before"})
    has_prev = set(two.loc[two["rank"] == 2, "sid"])
    latest = two[two["rank"] == 1].set_index("sid")["filed_at"]

    def change(r):
        if r["sid"] not in has_prev:
            return "unknown"
        if pd.isna(r["before"]):
            return "new"
        d = r["pct"] - r["before"]
        return "up" if d > CLONE_MIN_RISE else "down" if d < -CLONE_MIN_RISE else "same"
    now["change"] = now.apply(change, axis=1) if len(now) else []
    now["filed_at"] = now["sid"].map(latest)
    return now[cols]


def _fresh_buys(changes, t):
    fresh = changes[(changes["change"].isin(["new", "up"])) & (changes["filed_at"] >= _back(t, CLONE_FRESH_DAYS))]
    return set(fresh["sid"])


# ═══════════════════════════ context: everything the rules read ═══════════════════════════

PANEL_COLS = ("cap_tier", "announcement_car", "delivery_anomaly_z", "position_52w", "mom_6m", "book_to_price",
              "earnings_yield", "debt_to_equity", "z_score")
STATEMENT_ITEMS = ("Profit before tax", "Interest", "Equity Share Capital", "Reserves", "Borrowings", "Sales", "Net profit")


def annual_statements():
    """{sid: annual rows oldest first} from the Screener export, the trailing-12-month column dropped."""
    raw = read_sql(f"SELECT sid, period_end, line_item, value FROM fundamentals_screener WHERE period_type = 'annual' "
                   f"AND line_item IN ({','.join('?' * len(STATEMENT_ITEMS))})", params=list(STATEMENT_ITEMS))
    wide = raw.pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first").reset_index()
    for c in STATEMENT_ITEMS:
        if c not in wide.columns:
            wide[c] = float("nan")
    wide["month"] = wide["period_end"].str[5:7]
    out = {}
    for sid, g in wide.groupby("sid"):
        out[sid] = g[g["month"] == g["month"].mode().iloc[0]].sort_values("period_end").reset_index(drop=True)
    return out


def load_context(since=None):
    """Load once, reuse for every date."""
    where = f"WHERE snapshot_date >= '{_iso(since)}'" if since else ""
    panel = read_sql(f"SELECT sid, snapshot_date, {', '.join(PANEL_COLS)} FROM daily_snapshots_pit {where}")
    ph = ",".join("?" * len(INSIDER_CATEGORIES))
    trades = read_sql(f"SELECT sid, person, transaction_type AS side, value_lakhs, trade_date FROM insider_trades "
                      f"WHERE person_category IN ({ph}) AND transaction_type IN ('Buy', 'Sell') AND value_lakhs > 0",
                      params=list(INSIDER_CATEGORIES))
    resign = read_sql(f"SELECT sid, substr(dt_tm, 1, 10) AS d FROM bse_announcements WHERE sid IS NOT NULL "
                      f"AND subcategory IN ({','.join('?' * len(RESIGNATIONS))})", params=list(RESIGNATIONS))
    pledge = read_sql("SELECT sid, end_date, pledge_pct FROM shareholding WHERE pledge_pct IS NOT NULL")
    stocks = read_sql("SELECT sid, sector FROM stocks")
    holders = read_sql("SELECT sid, end_date, filed_at, holder_name, holder_category, pct FROM shareholding_holders "
                       "WHERE promoter_type IS NULL")
    names = pd.Series(holders["holder_name"].unique())
    holders["followed"] = holders["holder_name"].map(dict(zip(names, names.map(followed_investor))))
    holders["person"] = holders["holder_name"].map(dict(zip(names, names.map(norm_name))))
    holders.loc[~holders["holder_category"].str.endswith(INDIVIDUAL_SECTION), "person"] = None
    return {"holders": holders, "panel": {d: g.set_index("sid") for d, g in panel.groupby("snapshot_date")},
            "dates": sorted(panel["snapshot_date"].unique()), "trades": trades, "resign": resign, "pledge": pledge,
            "annual": annual_statements(), "financials": set(stocks.loc[stocks["sector"] == "Financials", "sid"])}


def frame_at(ctx, t):
    """The stored factor frame of the latest snapshot on or before t (None before the panel starts)."""
    t = _iso(t)
    prior = [d for d in ctx["dates"] if d <= t]
    return ctx["panel"][prior[-1]] if prior else None


def _pickable(ctx, t, sids):
    f = frame_at(ctx, t)
    if f is None:
        return set()
    ok = set(f.index[f["cap_tier"].isin(PICKABLE_TIERS)])
    return set(sids) & ok


# ═══════════════════════════ members at a date ═══════════════════════════

def breakout_members(ctx, t):
    f = frame_at(ctx, t)
    return set() if f is None else _pickable(ctx, t, f.index[breakout_mask(f)])


def deep_value_members(ctx, t):
    f = frame_at(ctx, t)
    return set() if f is None else _pickable(ctx, t, set(f.index[deep_value_mask(f)]) - ctx["financials"])


def insider_members(ctx, t):
    tr = ctx["trades"]
    window = tr[(tr["trade_date"] > _back(t, INSIDER_DAYS)) & (tr["trade_date"] <= _back(t, INSIDER_LAG_DAYS))]
    return _pickable(ctx, t, insider_net_buyers(window)["sid"])


def quality_members(ctx, t, n_years=QUALITY_YEARS, min_hits=QUALITY_MIN_HITS):
    known = _back(t, STATEMENT_LAG_DAYS)
    out = set()
    for sid, years in ctx["annual"].items():
        if sid in ctx["financials"]:
            continue
        if quality_stats(years[years["period_end"] <= known], n_years, min_hits):
            out.add(sid)
    return _pickable(ctx, t, out)


def red_flags(ctx, t):
    """{sid: set of flags} from the checks that have history: a key resignation in the last
    RESIGNATION_DAYS, a balance sheet in the distress zone, promoter pledge ≥ PLEDGE_PCT
    in the latest shareholding public at t."""
    flags = {}
    r = ctx["resign"]
    for sid in r.loc[(r["d"] > _back(t, RESIGNATION_DAYS)) & (r["d"] <= _iso(t)), "sid"].unique():
        flags.setdefault(sid, set()).add("resignation")
    f = frame_at(ctx, t)
    if f is not None:
        for sid in f.index[(f["z_score"] < DISTRESS_Z)]:
            if sid not in ctx["financials"]:
                flags.setdefault(sid, set()).add("distress")
    p = ctx["pledge"]
    p = p[p["end_date"] <= _back(t, SHAREHOLDING_LAG_DAYS)]
    if not p.empty:
        latest = p.sort_values("end_date").groupby("sid").tail(1)
        for sid in latest.loc[latest["pledge_pct"] >= PLEDGE_PCT, "sid"]:
            flags.setdefault(sid, set()).add("pledge")
    return flags


def flagged_members(ctx, t):
    return _pickable(ctx, t, red_flags(ctx, t))


def cloning_members(ctx, t):
    """Stocks where a FOLLOWED investor newly appears above 1% or raised the stake in the
    stock's latest filing, filed within CLONE_FRESH_DAYS."""
    # the whole frame goes in: "new" needs the stock's earlier filing, whoever was named in it
    ch = holder_changes(ctx["holders"].rename(columns={"followed": "investor"}), t)
    return _pickable(ctx, t, _fresh_buys(ch, t))


def cloning_broad_members(ctx, t):
    """The same event for ANY individual who, at t, is named above 1% in CLONE_MIN_STOCKS or
    more companies — the investors are chosen by the data of the day, not by today's fame."""
    ch = holder_changes(ctx["holders"].rename(columns={"person": "investor"}), t)
    if ch.empty:
        return set()
    active = ch.groupby("investor")["sid"].nunique()
    ch = ch[ch["investor"].isin(active[active >= CLONE_MIN_STOCKS].index)]
    return _pickable(ctx, t, _fresh_buys(ch, t))


SLEEVES = {
    "cloning": {
        "label": "Cloning (followed investors)", "who": "Pabrai", "since": "2016-10-01", "members": cloning_members,
        "rule": f"a followed investor newly appears above 1% or adds, in a filing from the last {CLONE_FRESH_DAYS} days",
        "caveat": "The followed list was chosen today, knowing who did well, so its history is flattered; filings before 2026 are still loading."},
    "cloning_broad": {
        "label": "Cloning (any active individual)", "who": "Pabrai", "since": "2016-10-01", "members": cloning_broad_members,
        "rule": f"any individual named above 1% in {CLONE_MIN_STOCKS}+ companies newly appears or adds, in a filing from the last {CLONE_FRESH_DAYS} days",
        "caveat": "The fair version of cloning: investors are picked by the data of the day. Filings before 2026 are still loading."},
    "breakouts": {
        "label": "Breakouts", "who": "O'Neil, Minervini", "since": "2020-01-01", "members": breakout_members,
        "rule": "results well received, delivery far above the stock's norm, price in the top of its 52-week range, rising over 6 months",
        "caveat": "Inputs are stored monthly before 2024, so entries can be up to a month late."},
    "insiders": {
        "label": "Insider buying", "who": "Event-driven", "since": "2024-04-01", "members": insider_members,
        "rule": f"promoters, directors or key managers were net buyers over {INSIDER_DAYS} days",
        "caveat": "Insider trades are held from 2024 only: under three years, one market phase."},
    "quality": {
        "label": f"Quality ({QUALITY_YEARS}-year rule)", "who": "Buffett, Munger", "since": "2021-07-01", "members": quality_members,
        "rule": f"return on capital ≥ {ROCE_BAR}% in {QUALITY_MIN_HITS} of the last {QUALITY_YEARS} years, no loss year, sales growing ≥ {SALES_CAGR_BAR}% a year",
        "caveat": "A 5-year stand-in for the page's 10-year rule (we hold 10–11 years of statements, so the 10-year rule has no history). "
                  "Statements are as restated today, and no price condition is applied."},
    "deep_value": {
        "label": "Deep value", "who": "Graham", "since": "2024-01-01", "members": deep_value_members,
        "rule": "price at or below book, earnings at least 8% of price, little debt, non-financial",
        "caveat": "Earnings yield is stored from 2024 only."},
}
VETO = {"label": "Red-flag veto", "since": "2020-01-01", "members": flagged_members,
        "rule": "key resignation in 180 days, distress-zone balance sheet, or promoter pledge ≥ 25% (pledge from 2024)"}


def members_today(ctx=None):
    """{sleeve: sorted sids} as of today — what the forward record stores each morning."""
    ctx = ctx or load_context(since=(date.today() - timedelta(days=40)).isoformat())
    today = date.today().isoformat()
    out = {k: sorted(s["members"](ctx, today)) for k, s in SLEEVES.items()}
    out["flagged"] = sorted(flagged_members(ctx, today))
    return out
