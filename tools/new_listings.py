"""
Plan 0025 task 6.2 — new listings: does a simple score find the winners among stocks listed less than
12 months ago, the window where the live model sees them with missing momentum (scored 0.5)?
(READ-ONLY on the DB; writes data/lh/v2/newlist_*)

Why (Amit 2026-10-13): ATHERENERG was invisible to the live model for its first 12 months, and 13 % of
the 529 missed doublers in docs/studies/missed-winners-2019-2025.md were new listings.

PRE-REGISTRATION (written 2026-10-14 BEFORE any run of this tool; the plan 0025 task 6.2 spec, with
every gap the spec leaves filled by the most conservative house choice and marked "(filled in
2026-10-14 before any run)"). Nothing below may change after the first `run`; a bug found by a run is
fixed in code and logged here as a dated note, the bars stay.

Listing date
  Universe stocks: the first close > 0 in stock_prices, if after the data start 2010-01-04.
  It is NOT a new listing, the stock is dropped (filled in 2026-10-14 before any run; data checks
  found that about half the stocks whose stock_prices history starts after 2018 were already listed):
    G1  the first price row's source is yfinance.* (BSE-only names added in the 2026-04 universe
        expansion; their history starts at the fetch date, not at a listing);
    G2  the stock's first BSE corporate announcement (bse_announcements, which starts 2018-01) is more
        than 90 days before its first NSE close: a BSE-listed company that later added an NSE line
        (SPICEJET, CEINSYS), a BSE-SME migration, or a renamed symbol (RBA after BURGERKING);
    G3  its first close falls on a date shared by >= 20 universe stocks (a bulk universe add).
  NSE-Emerge SME listings have their SME history in stock_prices, so their listing date is the SME
  debut. Demerged companies (new securities) count as new listings.
  Delisted listings (spec: "delisted IPOs via stock_prices_unlisted"; rules filled in 2026-10-14
  before any run): a stock_prices_unlisted symbol whose first EQ/BE close is >= 2018-12-01 with no
  other series before it (an SME migrant), that is not a rights entitlement (-RE…), not an ETF / fund
  (symbol pattern ETF_RX), not a duplicate of a universe stock (same close within 0.5 % on >= 90 % of
  >= 10 common sessions), and that stopped trading >= 30 days before the last price date.
  Note 2026-10-14, after the `smoke` hygiene check (4 anchors, no outcome computed) and BEFORE the first
  `run`: most delisted candidates were renamed old companies (GATI→ACLGATI, DHANI, JSWISPL, TATASTLBSL,
  GENSOL's SME past), so G2 also applies to them: a BSE scrip whose bseindia URL slug equals the symbol
  with a first announcement > 90 days before the symbol's first close → dropped. ETF_RX gained GROW,
  SDL, ^AXIS, ^QUALITY$. A price-continuity rename test was tried and NOT adopted: on universe stocks it
  flagged 13 names, all genuine IPOs (chance matches). Prices
  split-neutralised as in tools/lh_price_history (one-day ratio < 0.70 or > 1.45 within 7 days);
  no sector (sector momentum missing = 0.5); Financials cannot be excluded (no sector).
Universe at each monthly anchor a of data/lh/labels.parquet: listed on or before a and a < listing
  date + 12 months; PIT tier SMALL or MID (labels cap_tier; delisted names: daily_snapshots_pit_unlisted
  cap_tier at a); 20-session median close x volume >= ₹1 crore over the sessions <= a (fewer sessions
  if younger); trusts (config.SCREEN trust_exclusion_patterns) and stocks.sector = Financials excluded,
  as tools/winner_hunter.py.
  The set is ONE set across SMALL + MID (spec: "within-set percentiles"; the set is too small to split
  by tier), costed and benchmarked as SMALL (filled in 2026-10-14 before any run).
Features at a (adjusted closes, signals._prices.apply_adjustments; only data dated <= a):
  F1  return since the first close after listing day 5: close(a) / close of the stock's 6th session − 1
      (missing until the 6th session has traded).
  F2  position vs the high since listing: close(a) / max close from the listing day to a.
  F3  latest-quarter revenue growth, year on year: quarters to 2024-12 from quarterly_results_nse,
      known from filed_at; quarters 2025+ from quarterly_income (Tickertape), known at period end + 60
      days (winner_hunter conventions). The year-ago comparator is the SAME source's quarter ending
      365 ± 15 days earlier (for a Tickertape 2025+ quarter this may be a 2024 Tickertape row, printed as
      the comparative in the current result), consolidated pair preferred, else standalone pair (filled
      in 2026-10-14 before any run). Pre-listing quarters are mostly absent, so F3 is expected to be
      mostly missing.
  F4  the sector's 6-month momentum: median 126-session return of every universe stock (any tier) in
      the stock's stocks.sector with >= 5 members with a value (else missing).
Score  newlist = mean of the within-set percentiles of F1..F4 at the anchor; a missing feature = 0.5.
       No fitted weight.
Labels universe stocks: data/lh/labels.parquet fwd_63 / fwd_126 / fwd_next_anchor (pit.forward_returns:
       entry = close of the first session after a; NULL if a guard fails). Delisted names: entry = the
       first session after a, exit h sessions later or the last traded close if it stops first (the
       tools/lh_price_history delisting convention).

Tests
 (a) rank IC: per anchor, Spearman(newlist, fwd_h) over the set with a label, anchors with >= 10
     labelled names; h = 63 and 126 sessions; t from non-overlapping subsamples (every 3rd / 6th anchor,
     averaged over the offsets). Reported with mean IC and anchors; reference mark t >= 2.0 at 126 (the
     plan 0025 task 2.1 bar). (a) informs, it does not enter the decision (the spec's decision reads (b)
     only) (filled in 2026-10-14 before any run).
 (b) book: tools.lh_book unchanged (measured costs, Indian tax, NIFTY SMALLCAP 250 with dividends,
     forensic red-flag sale). PRIMARY = monthly · top 10 by newlist · raw score · no tax deferral · a
     holding is kept until its listing turns 12 months old (it then has no score and is sold at the next
     monthly review) — implemented as an exit band k = 1000 (never binding); a holding that leaves the
     set for another reason (floor, tier) keeps a score of −1 until month 12 and is not sold, but cannot
     be bought. The hand-over to the normal tier rank after month 12 is OUT OF SCOPE (the position is
     simply sold).
     Starts: the first 12 anchors at which the set has >= 10 names, each run to the last anchor.
     Grid for DSR / PBO (first start): N 5 / 10 / 20 × exit (hold to month 12 | sell below rank 3N),
     6 variants (filled in 2026-10-14 before any run).
     Grade (ADR 0073), on PRIMARY:
       B  median t_nw across the 12 starts >= 1.5; DSR(N_eff of the grid) >= 0.90 or PBO (S = 8) <= 0.30;
          beats the index in >= 3 of the 5 calendar years 2021-25 (first start); >= 10 of 12 starts with
          excess CAGR > 0; worst 12-month excess (worst across the 12 starts) >= −15 %.
       A  B, and the median t after the haircut over the 6 variants >= 2.0, DSR >= 0.95, PBO <= 0.20.
       C  anything less.
     ADR 0073's ">= 20 names" book shape: the spec fixes top 10; the N 20 grid variant is reported but
     does not decide (filled in 2026-10-14 before any run).
Decision  PRIMARY grade A or B → PROPOSE (not implement) that the live model stops scoring missing
          momentum as 0.5 for stocks under 12 months and uses this score instead; else no change.
Diagnostics (decide nothing): IC of each feature alone; F3 / F1 coverage; the PRIMARY book from the first
  start against the NIFTY MIDCAP 150; ATHERENERG's rank in the set at each anchor of its first 12 months.

Usage:
  python -m tools.new_listings smoke    # hygiene on 4 anchors: set sizes, coverage, included delisted names (no outcomes)
  python -m tools.new_listings run      # the test
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import SCREEN  # noqa: E402
from signals._prices import apply_adjustments  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
RUN_DIR = V2 / "newlist_book"
DATA_START = "2010-01-04"
FLOOR = 1e7
QLAG = 60
BSE_LEAD_DAYS = 90
BULK_ADD = 20
TIERS = ("SMALL", "MID")
FEATS = ("F1", "F2", "F3", "F4")
METHOD = "newlist"
HOLD_K = 1000
CASE = "ATHER"
ETF_RX = re.compile(r"(?:ETF|BEES|GOLD|SILV|LIQ|NIFTY|^NIF|SENSEX|^NETF|^EBB|CASE$|ADD$|BETA$|AXIS$|^GROWW|^MO[A-Z]"
                    r"|^ICICI|^KOTAK|^HDFC|^SBI|^UTI|^ABSL|^IBMF|^IPRU|^RETF|^DSP|^AONE|^MAN(?:V30|XT50)|^NV20|^N100"
                    r"|^NEXT50|^BANK|^PSUB|^CPSE|IWIN|^SETF|^JUNIOR|^SDL|GILT|^BBNPP|^HNG|^NPBET|^EQUAL|^MID150"
                    r"|^SMALL|^MIDCAP|^MIDSMALL|^ALPHA|^MOMENTUM|^MON100|^LOWVOL|^QUAL30|^TOP10|^SELECTIPO"
                    r"|^EVINDIA|^MODEFENCE|^AFFORDABLE|^BFSI|^MAKEINDIA|^IT$|^PSUBANK|^ENERGY|^CHEMICAL"
                    r"|^DEFENCE|^VALUE|^METAL|^ELM250|^SML100|^EGOLD|^ESILVER|^ELIQUID|^CASHIETF|GROW|SDL|^AXIS|^QUALITY$)")
RE_RX = re.compile(r"-RE\d*$")
SLUG_RX = re.compile(r"/([^/]+)/\d+/?$")


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def nonoverlap_t(s, step):
    s = s.dropna().sort_index()
    ts = [x.mean() / (x.std() / np.sqrt(len(x))) for x in (s.iloc[o::step] for o in range(step))
          if len(x) >= 3 and x.std() > 0]
    return float(np.mean(ts)) if ts else np.nan


# ───────────────────────── listings and prices ─────────────────────────

def load(con):
    st = pd.read_sql("SELECT sid, ticker, name, sector FROM stocks", con)
    first = pd.read_sql("SELECT p.sid, p.date AS listed, p.source FROM stock_prices p JOIN "
                        "(SELECT sid, MIN(date) d FROM stock_prices WHERE close > 0 GROUP BY sid) m "
                        "ON m.sid = p.sid AND m.d = p.date", con).drop_duplicates("sid")
    bse = pd.read_sql("SELECT sid, MIN(substr(dt_tm, 1, 10)) AS bse_first FROM bse_announcements "
                      "WHERE sid IS NOT NULL AND dt_tm IS NOT NULL GROUP BY sid", con)
    px = pd.read_sql("SELECT sid, date, close, volume FROM stock_prices WHERE close > 0 AND date >= '2018-06-01'", con)
    adj = pd.read_sql("SELECT sid, ex_date, factor, inds FROM corporate_adjustments", con)
    un = pd.read_sql("SELECT symbol, series, date, close, volume FROM stock_prices_unlisted WHERE close > 0", con)
    pu = pd.read_sql("SELECT symbol, snapshot_date, cap_tier FROM daily_snapshots_pit_unlisted", con)
    sl = pd.read_sql("SELECT nsurl, MIN(substr(dt_tm, 1, 10)) AS bse_first FROM bse_announcements "
                     "WHERE nsurl IS NOT NULL AND dt_tm IS NOT NULL GROUP BY nsurl", con)
    sl["slug"] = sl["nsurl"].str.extract(SLUG_RX)[0].str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    slug_first = sl.dropna(subset=["slug"]).groupby("slug")["bse_first"].min()
    return st, first, bse, px, adj, un, pu, slug_first


def universe_listings(st, first, bse):
    f = first.merge(st, on="sid", how="left").merge(bse, on="sid", how="left")
    f = f[f["listed"] > DATA_START].copy()
    f["lead"] = (pd.to_datetime(f["listed"]) - pd.to_datetime(f["bse_first"])).dt.days
    shared = f.groupby("listed")["sid"].transform("size")
    f["drop"] = np.select([f["source"].str.startswith("yfinance"), f["lead"] > BSE_LEAD_DAYS, shared >= BULK_ADD],
                          ["G1 yfinance", "G2 BSE-listed earlier", "G3 bulk add"], "")
    return f


def delisted_listings(un, P_univ, last_date, bse_slug_first):
    """stock_prices_unlisted symbols that are new listings that later stopped trading (rules in the docstring)."""
    eq = un[un["series"].isin(["EQ", "BE"])]
    g = un.groupby("symbol")["date"].min().rename("any_first")
    e = eq.groupby("symbol")["date"].agg(["min", "max"]).rename(columns={"min": "listed", "max": "last"})
    c = e.join(g)
    c = c[(c["listed"] >= "2018-12-01") & (c["any_first"] == c["listed"])]
    c = c[c["last"] <= (pd.Timestamp(last_date) - pd.Timedelta(days=30)).date().isoformat()]
    c = c[~c.index.str.contains(RE_RX) & ~c.index.str.contains(ETF_RX)]
    bf = pd.Series(c.index.str.lower().str.replace(r"[^a-z0-9]", "", regex=True), index=c.index).map(bse_slug_first)
    lead = (pd.to_datetime(c["listed"]) - pd.to_datetime(bf)).dt.days
    c = c[~(lead > BSE_LEAD_DAYS)]
    keep, dup = [], []
    raw = eq[eq["symbol"].isin(c.index)].pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    for sym in c.index:
        s = raw[sym].dropna()
        U = P_univ.reindex(s.index)
        both = U.notna()
        n = both.sum()
        same = (np.abs(U.div(s, axis=0) - 1) < 0.005).sum()
        if ((n >= 10) & (same >= 0.9 * n)).any():
            dup.append(sym)
        else:
            keep.append(sym)
    return c.loc[keep].reset_index().rename(columns={"symbol": "sym"}), dup


def unlisted_prices(un, syms):
    u = un[un["symbol"].isin(syms) & un["series"].isin(["EQ", "BE"])].copy()
    u["id"] = "U:" + u["symbol"]
    u = u.sort_values(["id", "date"]).drop_duplicates(["id", "date"], keep="last")
    g = u.groupby("id")
    r = u["close"] / g["close"].shift(1)
    gap = (pd.to_datetime(u["date"]) - pd.to_datetime(g["date"].shift(1))).dt.days
    jump = ((r < 0.70) | (r > 1.45)) & (gap <= 7)
    fac = pd.Series(np.where(jump, r, 1.0), index=u.index)
    u["adj_close"] = u["close"] * fac.groupby(u["id"]).transform(lambda s: s[::-1].cumprod()[::-1].shift(-1).fillna(1.0))
    return u


# ───────────────────────── quarterly revenue growth ─────────────────────────

def quarterly(con):
    nse = pd.read_sql("SELECT sid, period_end, basis, filed_at, revenue FROM quarterly_results_nse "
                      "WHERE period_end <= '2024-12-31'", con)
    nse["known"] = pd.to_datetime(nse["filed_at"].str[:10], errors="coerce")
    nse["src"] = "nse"
    tt = pd.read_sql("SELECT sid, end_date AS period_end, reporting, revenue FROM quarterly_income "
                     "WHERE end_date >= '2024-01-01'", con)
    tt["basis"] = np.where(tt["reporting"] == "consolidated", "consolidated", "standalone")
    tt["known"] = pd.to_datetime(tt["period_end"]) + pd.Timedelta(days=QLAG)
    tt["src"] = "tt"
    cols = ["sid", "period_end", "basis", "known", "revenue", "src"]
    q = pd.concat([nse[cols], tt[cols]], ignore_index=True).dropna(subset=["known", "revenue"])
    q["pe"] = pd.to_datetime(q["period_end"])
    return q


def rev_growth_at(q, anchor, sids):
    k = q[(q["known"] <= pd.Timestamp(anchor)) & q["sid"].isin(sids)]
    if k.empty:
        return pd.Series(dtype=float)
    k = k.sort_values("known").drop_duplicates(["sid", "period_end", "basis", "src"], keep="last")
    cur = k[(k["src"] == "nse") | (k["period_end"] >= "2025-01-01")]
    latest = cur.groupby("sid")["pe"].max()
    cur = cur[cur["pe"] == cur["sid"].map(latest)]
    m = cur.merge(k, on=["sid", "src", "basis"], suffixes=("", "_4"))
    lag = (m["pe"] - m["pe_4"]).dt.days
    m = m[(lag - 365).abs() <= 15]
    m = m[m["revenue_4"] > 0]
    m["g"] = m["revenue"] / m["revenue_4"] - 1
    m["pref"] = (m["basis"] != "consolidated").astype(int)
    m = m.sort_values(["sid", "pref"]).drop_duplicates("sid")
    return m.set_index("sid")["g"]


# ───────────────────────── panel ─────────────────────────

def build(anchors_limit=None, verbose=True):
    con = ro()
    st, first, bse, px, adj, un, pu, slug_first = load(con)
    q = quarterly(con)
    con.close()
    lab = pd.read_parquet(LH / "labels.parquet")
    anchors = sorted(lab["snapshot_date"].unique())
    if anchors_limit:
        anchors = [anchors[i] for i in anchors_limit]

    ul = universe_listings(st, first, bse)
    px = apply_adjustments(px, adj, date.max)
    P = px.pivot_table(index="date", columns="sid", values="adj_close").sort_index()
    RAW = px.pivot_table(index="date", columns="sid", values="close").reindex(P.index)
    TV = (px.assign(tv=px["close"] * px["volume"]).pivot_table(index="date", columns="sid", values="tv")
          .reindex(P.index))
    del px
    cal = P.index.to_numpy()
    dl, dups = delisted_listings(un, RAW, cal[-1], slug_first)
    up = unlisted_prices(un, dl["sym"].tolist())
    del un
    UP = up.pivot_table(index="date", columns="id", values="adj_close").reindex(cal)
    UTV = up.assign(tv=up["close"] * up["volume"]).pivot_table(index="date", columns="id", values="tv").reindex(cal)
    URAW = up.pivot_table(index="date", columns="id", values="close").reindex(cal)

    new_u = ul[ul["drop"] == ""].set_index("sid")["listed"]
    new_d = pd.Series(dl["listed"].values, index="U:" + dl["sym"])
    listed = pd.concat([new_u, new_d])
    pats = SCREEN.get("trust_exclusion_patterns", [])
    bad = set(st.loc[st["sector"].eq("Financials") |
                     st["name"].str.contains("|".join(pats), case=False, regex=True, na=False), "sid"])
    sector = st.set_index("sid")["sector"]
    tier_lab = lab.set_index(["snapshot_date", "sid"])["cap_tier"]
    pu = pu.assign(id="U:" + pu["symbol"]).sort_values("snapshot_date")
    if verbose:
        print(f"listing guards (stocks whose first close is after {DATA_START}):\n{ul['drop'].replace('', 'kept').value_counts().to_string()}")
        print(f"delisted listings kept: {len(dl)} {sorted(dl['sym'])}; dropped as duplicates of universe stocks: {dups}")

    PALL = pd.concat([P, UP], axis=1)
    TVALL = pd.concat([TV, UTV], axis=1)
    Pf = P.ffill(limit=5)
    rows = []
    for a in anchors:
        k = int(np.searchsorted(cal, a, side="right"))
        young = listed[(listed <= a) & (pd.to_datetime(listed) + pd.DateOffset(months=12) > pd.Timestamp(a))]
        if young.empty or k < 127:
            continue
        ids = list(young.index)
        w = PALL.iloc[:k][ids]
        n_sess = w.notna().sum()
        last = w.ffill().iloc[-1]
        base = w.apply(lambda s: s.dropna().iloc[5] if s.notna().sum() >= 6 else np.nan)
        f = pd.DataFrame({"listed": young, "sessions": n_sess, "F1": last / base - 1, "F2": last / w.max(),
                          "adtv": TVALL.iloc[max(0, k - 20):k][ids].median()})
        mom = Pf.iloc[k - 1] / Pf.iloc[k - 1 - 126] - 1
        sm = pd.DataFrame({"m": mom, "sec": sector.reindex(mom.index)}).dropna().groupby("sec")["m"].agg(["median", "count"])
        sec_mom = sm["median"].where(sm["count"] >= 5)
        f["F4"] = sector.reindex(f.index).map(sec_mom).values
        f["F3"] = rev_growth_at(q, a, set(f.index)).reindex(f.index).values
        tl = pd.Series({s: tier_lab.get((a, s)) for s in f.index if not s.startswith("U:")}, dtype=object)
        pt = pu[(pu["snapshot_date"] <= a) & pu["id"].isin(f.index)].groupby("id")["cap_tier"].last()
        f["cap_tier"] = pd.concat([tl, pt]).reindex(f.index).values
        f["excluded"] = f.index.isin(bad)
        f["in_set"] = f["cap_tier"].isin(TIERS) & (f["adtv"].fillna(0) >= FLOOR) & ~f["excluded"] & (f["sessions"] > 0)
        rows.append(f.rename_axis("sid").reset_index().assign(snapshot_date=a))
    d = pd.concat(rows, ignore_index=True)
    s = d[d["in_set"]].copy()
    g = s.groupby("snapshot_date")
    for c in FEATS:
        s[f"p_{c}"] = g[c].rank(pct=True)
    s["score"] = s[[f"p_{c}" for c in FEATS]].fillna(0.5).mean(axis=1)
    s["rank"] = s.groupby("snapshot_date")["score"].rank(ascending=False, method="first")
    s["set_size"] = s.groupby("snapshot_date")["sid"].transform("size")
    d = d.merge(s[["sid", "snapshot_date", "score", "rank", "set_size"] + [f"p_{c}" for c in FEATS]],
                on=["sid", "snapshot_date"], how="left")
    labels = unlisted_labels(d, lab, cal, URAW, anchors)
    d = d.merge(labels, on=["sid", "snapshot_date"], how="left")
    return d, labels, cal, URAW, UTV


def unlisted_labels(d, lab, cal, URAW, anchors):
    """fwd_63 / fwd_126 / fwd_next_anchor: labels.parquet for universe stocks; delisting convention for U: names."""
    L = lab[["sid", "snapshot_date", "fwd_63", "fwd_126", "fwd_next_anchor"]]
    ids = sorted(set(d.loc[d["sid"].str.startswith("U:"), "sid"]))
    out = []
    all_anchors = sorted(lab["snapshot_date"].unique())
    for i, a in enumerate(all_anchors):
        if not ids:
            break
        k = int(np.searchsorted(cal, a, side="right"))
        if k >= len(cal):
            continue
        nxt = int(np.searchsorted(cal, all_anchors[i + 1], side="right")) if i + 1 < len(all_anchors) else None
        for sid in ids:
            s = URAW[sid].to_numpy(float)
            if not np.isfinite(s[k]):
                continue
            r = dict(sid=sid, snapshot_date=a)
            for h, col in ((63, "fwd_63"), (126, "fwd_126")):
                e = k + h
                if e < len(cal):
                    seg = s[k + 1:e + 1]
                    v = seg[np.isfinite(seg)]
                    r[col] = (v[-1] if len(v) else s[k]) / s[k] - 1
            if nxt is not None and nxt < len(cal):
                seg = s[k + 1:nxt + 1]
                v = seg[np.isfinite(seg)]
                r["fwd_next_anchor"] = (v[-1] / s[k] - 1) if len(v) else np.nan
            out.append(r)
    U = pd.DataFrame(out, columns=["sid", "snapshot_date", "fwd_63", "fwd_126", "fwd_next_anchor"])
    keep = set(d["sid"])
    return pd.concat([L[L["sid"].isin(keep)], U], ignore_index=True)


# ───────────────────────── tests ─────────────────────────

def ic_test(d):
    s = d[d["in_set"]]
    res, per = {}, []
    for h, step in ((63, 3), (126, 6)):
        col = f"fwd_{h}"
        for name in ("score",) + tuple(f"p_{c}" for c in FEATS):
            ics = {}
            for a, g in s.dropna(subset=[col]).groupby("snapshot_date"):
                if len(g) >= 10 and g[name].nunique() > 1:
                    ics[a] = g[name].corr(g[col], method="spearman")
            x = pd.Series(ics, dtype=float)
            r = dict(h=h, signal=name, anchors=len(x), mean_ic=round(float(x.mean()), 4) if len(x) else None,
                     t_nonoverlap=round(nonoverlap_t(x, step), 2) if len(x) else None,
                     share_positive=round(float((x > 0).mean()), 3) if len(x) else None)
            per.append(r)
            if name == "score":
                res[h] = r
    return res, pd.DataFrame(per)


def grid():
    return [dict(method=METHOD, reb="M", N=N, k=k, score="raw", min_hold=0, defer=False, block="newlist")
            for N in (5, 10, 20) for k in (HOLD_K, 3)]


PRIMARY = dict(method=METHOD, reb="M", N=10, k=HOLD_K, score="raw", min_hold=0, defer=False, block="newlist")


def book_scores(d):
    """In-set rows carry the score; a name bought earlier keeps −1 until month 12 (held, never bought)."""
    d = d.sort_values("snapshot_date")
    seen = d["in_set"].astype(int).groupby(d["sid"]).cummax().astype(bool)
    sc = d[seen][["sid", "snapshot_date", "score", "in_set"]].copy()
    sc["score"] = sc["score"].where(sc["in_set"], -1.0)
    sc["cap_tier"] = "SMALL"
    sc["method"] = METHOD
    sc["pct_rank"] = sc.groupby("snapshot_date")["score"].rank(pct=True)
    sc["oos"] = True
    return sc


def books(d, labels, cal, URAW, UTV):
    import tools.lh_book as B
    from tools.lh_luck import n_effective, pbo, sharpe

    sc = book_scores(d)
    n_set = d[d["in_set"]].groupby("snapshot_date").size()
    all_anchors = sorted(pd.read_parquet(LH / "labels.parquet", columns=["snapshot_date"])["snapshot_date"].unique())
    starts = [a for a in all_anchors if n_set.get(a, 0) >= 10][:12]
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier", "fwd_next_anchor"])
    ul = labels[labels["sid"].str.startswith("U:")][["sid", "snapshot_date", "fwd_next_anchor"]].assign(cap_tier="UNL")
    pd.concat([lab, ul], ignore_index=True).to_parquet(RUN_DIR / "labels.parquet", index=False)
    in_set = {a: set(g["sid"]) for a, g in d[d["in_set"]].groupby("snapshot_date")}
    u_ids = [c for c in URAW.columns]
    rows, first = [], {}
    for stt in starts:
        w = sc[sc["snapshot_date"] >= stt]
        missing = sorted(set(a for a in all_anchors if a >= stt) - set(w["snapshot_date"]))
        assert not missing, f"anchors with no scored name would break the return chain: {missing}"
        w.drop(columns=["in_set"]).to_parquet(RUN_DIR / "oos_scores.parquet", index=False)
        B.LH = RUN_DIR
        D = B.Data()
        for i, a in enumerate(D.anchors):          # buy only from the set; delisted names' liquidity and price
            o = D.rank[(METHOD, "raw")][i]["order"]
            o["SMALL"] = [s for s in o["SMALL"] if s in in_set.get(a, set())]
            if u_ids:
                k = int(np.searchsorted(cal, a, side="right"))
                tv = UTV.iloc[max(0, k - 20):k][u_ids].median().dropna()
                pr = URAW.iloc[:k][u_ids].ffill().iloc[-1].dropna()
                D.adtv[i].update(tv.to_dict())
                D.price[i].update(pr.to_dict())
        benches = {"SMALL": B.benchmark(D, "SMALL")}
        if stt == starts[0]:
            benches["MID"] = B.benchmark(D, "MID")
        for v in (grid() if stt == starts[0] else [PRIMARY]):
            r, m = B.simulate(D, "SMALL", v, benches["SMALL"])
            name = B.vname(v)
            rows.append(dict(start=stt, bench="NIFTY SMALLCAP 250", variant=name, primary=v == PRIMARY,
                             **{kk: r[kk] for kk in ("excess_cagr", "t_nw", "worst_12m_excess", "cagr_after_tax",
                                                     "bench_cagr_after_tax", "turnover_pa", "median_hold_closed_m",
                                                     "avg_cash_share", "costs_bps_pa", "no_signal_exits", "positions",
                                                     "n_months", "max_drawdown")}))
            if stt == starts[0]:
                a_, b_ = m["atlv"].to_numpy(float), m["bench"].to_numpy(float)
                x = pd.Series(a_[1:] / a_[:-1] - b_[1:] / b_[:-1], index=m["entry"].iloc[1:].values)
                first[name] = dict(x=x, rb=pd.Series(a_[1:] / a_[:-1], index=x.index),
                                   rx=pd.Series(b_[1:] / b_[:-1], index=x.index))
                if v == PRIMARY:
                    r2, _ = B.simulate(D, "SMALL", v, benches["MID"])
                    rows.append(dict(start=stt, bench="NIFTY MIDCAP 150 (diagnostic)", variant=name, primary=False,
                                     **{kk: r2[kk] for kk in ("excess_cagr", "t_nw", "worst_12m_excess",
                                                              "cagr_after_tax", "bench_cagr_after_tax")}))
    res = pd.DataFrame(rows)
    res.to_csv(V2 / "newlist_books.csv", index=False)

    pname = B.vname(PRIMARY)
    X = pd.DataFrame({n: first[n]["x"] for n in first})
    srs = X.apply(sharpe)
    ne, _, _ = n_effective(X)
    dsr, _, _ = B.deflated_sharpe(X[pname], srs.values, max(ne, 2))
    p = pbo(X)
    prim = res[res["primary"]]
    rb, rx = first[pname]["rb"], first[pname]["rx"]
    yrs = pd.Index(pd.to_datetime(rb.index).year)
    cal_x = {int(y): round(float(rb[yrs == y].prod() / rx[yrs == y].prod() - 1), 4) for y in sorted(set(yrs))}
    years_beating = sum(cal_x.get(y, -1) > 0 for y in range(2021, 2026))
    t_med = float(prim["t_nw"].median())
    t_h = B.haircut_t(t_med, int(prim["n_months"].iloc[0]), len(grid()))
    beat = int((prim["excess_cagr"] > 0).sum())
    g = dict(starts=list(starts), median_excess=round(float(prim["excess_cagr"].median()), 4),
             min_excess=round(float(prim["excess_cagr"].min()), 4), median_t=round(t_med, 3),
             t_haircut=round(t_h, 3) if t_h is not None else None, starts_beating=f"{beat}/{len(prim)}",
             worst12=float(prim["worst_12m_excess"].min()), dsr=round(dsr, 3), n_eff=round(ne, 2), pbo=p["pbo"],
             calendar_excess_first_start=cal_x, years_beating_2021_25=years_beating,
             grid_first_start={n: round(float(res[(res["start"] == starts[0]) & (res["variant"] == n) &
                                                  (res["bench"] == "NIFTY SMALLCAP 250")]["excess_cagr"].iloc[0]), 4)
                               for n in first})
    Bg = (t_med >= 1.5 and (dsr >= 0.90 or p["pbo"] <= 0.30) and years_beating >= 3 and beat >= 10
          and g["worst12"] >= -0.15)
    Ag = Bg and (t_h or 0) >= 2.0 and dsr >= 0.95 and p["pbo"] <= 0.20
    g["grade"] = "A" if Ag else ("B" if Bg else "C")
    return res, g


def cases(d):
    c = d[(d["sid"] == CASE)][["snapshot_date", "listed", "cap_tier", "adtv", "in_set", "rank", "set_size", "score",
                               "F1", "F2", "F3", "F4"]]
    return c


# ───────────────────────── entry points ─────────────────────────

def hygiene(d):
    s = d[d["in_set"]]
    n = s.groupby("snapshot_date").size()
    print(f"set size per anchor: min {n.min()} median {n.median():.0f} max {n.max()} ({len(n)} anchors)")
    print("by year: ", s.groupby(s["snapshot_date"].str[:4]).size().div(
        s.groupby(s["snapshot_date"].str[:4])["snapshot_date"].nunique()).round(1).to_dict())
    print("tier mix:", s["cap_tier"].value_counts().to_dict(), " delisted names in set:",
          sorted(set(s.loc[s["sid"].str.startswith("U:"), "sid"])))
    print("feature coverage in set:", {c: round(float(s[c].notna().mean()), 3) for c in FEATS})
    print("F3 coverage by year:", s.groupby(s["snapshot_date"].str[:4])["F3"].apply(lambda x: round(x.notna().mean(), 3)).to_dict())
    print("young names failing only the floor / tier:",
          int((~d["in_set"] & d["cap_tier"].isin(TIERS) & ~d["excluded"]).sum()), "/",
          int((~d["in_set"] & ~d["cap_tier"].isin(TIERS)).sum()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["smoke", "run"])
    cmd = ap.parse_args().cmd
    pd.set_option("display.width", 240)
    if cmd == "smoke":
        d, *_ = build(anchors_limit=[0, 20, 50, 70])
        hygiene(d)
        print(d[d["in_set"]].sort_values(["snapshot_date", "rank"]).groupby("snapshot_date").head(5)
              [["snapshot_date", "sid", "listed", "cap_tier", "rank", "set_size", "score"] + list(FEATS)].to_string(index=False))
        return
    d, labels, cal, URAW, UTV = build()
    hygiene(d)
    d.to_parquet(V2 / "newlist_panel.parquet", index=False)
    ic, ic_all = ic_test(d)
    ic_all.to_csv(V2 / "newlist_ic.csv", index=False)
    print("\nIC (score and each feature alone):\n", ic_all.to_string(index=False))
    res, grade = books(d, labels, cal, URAW, UTV)
    print("\nBOOKS:\n", res.round(4).to_string(index=False))
    print("\nGRADE:", json.dumps(grade, indent=1, default=str))
    cs = cases(d)
    print(f"\nCASE {CASE}:\n", cs.round(3).to_string(index=False))
    s = d[d["in_set"]]
    verdict = ("PROPOSE (not implemented): the live model stops scoring missing momentum as 0.5 for stocks under "
               "12 months and uses the newlist score" if grade["grade"] in ("A", "B") else "no change")
    out = dict(anchors=int(s["snapshot_date"].nunique()), avg_set_size=round(float(s.groupby("snapshot_date").size().mean()), 1),
               names=int(s["sid"].nunique()), IC=ic, book=grade, verdict=verdict,
               case=cs.assign(rank=cs["rank"]).to_dict("records"))
    (V2 / "newlist_result.json").write_text(json.dumps(out, indent=1, default=str))
    print("\nVERDICT:", verdict)


if __name__ == "__main__":
    main()
