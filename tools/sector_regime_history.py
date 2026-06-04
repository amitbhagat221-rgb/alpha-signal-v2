"""
Alpha Signal v2 — Sector × Regime History Study (the creative / hypothesis lab)

The user's brief: "find from a few regimes what sectors boomed, then think why
they could have, and TEST it on other regimes."

Method:
  1. Pull ~15yr of NSE sector index history (yfinance) + macro regime markers
     (Nifty50, Brent, Copper, US-10Y) and a hardcoded RBI repo-rate path.
     Cached to parquet so re-runs don't re-hit yfinance.
  2. Narrative leaderboard: for a handful of NAMED historical regimes, rank
     sector total returns → which boomed, which lagged.
  3. Turn the narrative into MECHANICAL, cross-regime hypotheses and test them
     across ALL months 2011-2026 (not just the window that inspired them):
       H1 rate-sensitives (Realty/Auto/Bank/PSUBank) beat Nifty when RBI is
          CUTTING, lag when HIKING.
       H2 commodity sectors (Metal/Energy) beat Nifty when Brent+Copper rising.
       H3 defensives/exporters (FMCG/Pharma/IT) beat Nifty in risk-OFF months
          (Nifty 3m return < 0).
     Report mean monthly EXCESS return + t per (regime-label × sector basket),
     and the hit consistency across the named regimes.

Caveat: the RBI repo path is hand-encoded to major turning points — exact bps
are approximate but the FALLING/RISING/FLAT direction of each cycle is correct,
which is all the regime labels use. 2025 cuts flagged as provisional.

Usage:
    python -m tools.sector_regime_history            # uses cache if present
    python -m tools.sector_regime_history --refresh  # force re-pull
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path("/tmp/sector_regime_cache.parquet")

SECTOR_TICKERS = {
    "IT": "^CNXIT", "Auto": "^CNXAUTO", "Bank": "^NSEBANK", "Pharma": "^CNXPHARMA",
    "Realty": "^CNXREALTY", "Metal": "^CNXMETAL", "FMCG": "^CNXFMCG",
    "Energy": "^CNXENERGY", "Infra": "^CNXINFRA", "PSUBank": "^CNXPSUBANK",
    "Media": "^CNXMEDIA",
}
MACRO_TICKERS = {"Nifty": "^NSEI", "Brent": "BZ=F", "Copper": "HG=F",
                 "US10Y": "^TNX", "USDINR": "INR=X"}

EXPORTERS = ["IT", "Pharma"]            # INR-weakness beneficiaries

# RBI repo rate path (effective date → rate %). Major turning points; direction
# is what matters for regime labels. 2025 cuts provisional (knowledge-cutoff).
REPO_PATH = [
    ("2010-03-19", 5.00), ("2010-11-02", 6.25), ("2011-01-25", 6.50),
    ("2011-05-03", 7.25), ("2011-10-25", 8.50), ("2012-04-17", 8.00),
    ("2013-05-03", 7.25), ("2013-09-20", 7.50), ("2014-01-28", 8.00),
    ("2015-01-15", 7.75), ("2015-06-02", 7.25), ("2015-09-29", 6.75),
    ("2016-04-05", 6.50), ("2016-10-04", 6.25), ("2017-08-02", 6.00),
    ("2018-06-06", 6.25), ("2018-08-01", 6.50), ("2019-02-07", 6.25),
    ("2019-06-06", 5.75), ("2019-10-04", 5.15), ("2020-03-27", 4.40),
    ("2020-05-22", 4.00), ("2022-05-04", 4.40), ("2022-08-05", 5.40),
    ("2022-12-07", 6.25), ("2023-02-08", 6.50), ("2025-02-07", 6.25),
    ("2025-06-06", 5.50),
]

# Curated narrative regimes (windows) for the leaderboard.
NAMED_REGIMES = [
    ("2014 Modi capex rally",      "2014-01-01", "2015-03-01", "rates peak→cut, risk-on"),
    ("2015-16 commodity bust",     "2015-04-01", "2016-02-29", "commodities crash, risk-off"),
    ("2016-18 liquidity rally",    "2016-03-01", "2018-01-31", "rates low, risk-on"),
    ("2018-19 NBFC/credit crisis", "2018-09-01", "2019-08-31", "credit freeze, small-cap bust"),
    ("2020 COVID crash",           "2020-02-01", "2020-03-31", "risk-off extreme"),
    ("2020-21 everything rally",   "2020-04-01", "2021-10-31", "repo 4%, liquidity flood"),
    ("2022 rate-hike correction",  "2021-11-01", "2022-06-30", "global hikes, Ukraine spike"),
    ("2022-24 capex/PSU boom",     "2022-07-01", "2024-09-30", "capex+PSU rerating, risk-on"),
    ("2024-25 rotation/correction","2024-10-01", "2025-12-31", "froth unwind"),
]

RATE_SENSITIVE = ["Realty", "Auto", "Bank", "PSUBank"]
COMMODITY = ["Metal", "Energy"]
DEFENSIVE = ["FMCG", "Pharma", "IT"]


def _pull():
    import yfinance as yf
    frames = {}
    for name, tkr in {**SECTOR_TICKERS, **MACRO_TICKERS}.items():
        df = yf.download(tkr, start="2007-01-01", progress=False, auto_adjust=True)
        if df is None or len(df) == 0:
            print(f"  ⚠ {name} ({tkr}) empty")
            continue
        s = df["Close"]
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        frames[name] = s
        print(f"  {name:8s} {len(s):>5d} rows {s.index.min().date()}..{s.index.max().date()}")
    out = pd.DataFrame(frames)
    out.to_parquet(CACHE)
    return out


def _load(refresh=False):
    if CACHE.exists() and not refresh:
        return pd.read_parquet(CACHE)
    print("Pulling sector indices + macro markers from yfinance...")
    return _pull()


def _repo_series(index):
    """Step-function repo rate on a daily index, + 6-month direction label."""
    rp = pd.Series({pd.Timestamp(d): r for d, r in REPO_PATH}).sort_index()
    repo = rp.reindex(index.union(rp.index)).ffill().reindex(index)
    chg6 = repo - repo.shift(126)   # ~6 months of trading days
    direction = pd.Series(np.where(chg6 > 0.1, "HIKING",
                          np.where(chg6 < -0.1, "CUTTING", "FLAT")), index=index)
    return repo, direction


def _month_end(df):
    return df.resample("ME").last()


def run(refresh=False):
    px = _load(refresh)
    px.index = pd.to_datetime(px.index)
    sectors = [c for c in SECTOR_TICKERS if c in px.columns]

    # ── monthly returns ──
    me = _month_end(px)
    mret = me.pct_change()
    nifty_m = mret["Nifty"]
    excess = mret[sectors].sub(nifty_m, axis=0)     # sector return − Nifty (sector-relative)

    # ── regime labels on month-end ──
    repo, rate_dir = _repo_series(px.index)
    rate_dir_m = rate_dir.resample("ME").last()
    brent_m, copper_m = me["Brent"], me["Copper"]
    comm_dir = ((brent_m.pct_change(6) > 0) & (copper_m.pct_change(6) > 0))   # both rising 6m
    risk_off = nifty_m.rolling(3).sum() < 0                                   # trailing 3m Nifty < 0

    # ───────── 1. NARRATIVE LEADERBOARD ─────────
    print("\n" + "=" * 80)
    print("WHICH SECTORS BOOMED PER REGIME  (total return over window; ▲ = beat Nifty)")
    print("=" * 80)
    for name, start, end, why in NAMED_REGIMES:
        w = px.loc[start:end, sectors + ["Nifty"]].dropna(how="all")
        if len(w) < 5:
            continue
        tot = (w.iloc[-1] / w.iloc[0] - 1.0) * 100
        nif = tot["Nifty"]
        rank = tot[sectors].sort_values(ascending=False)
        lead = ", ".join(f"{s} {rank[s]:+.0f}%" for s in rank.index[:3])
        lag = ", ".join(f"{s} {rank[s]:+.0f}%" for s in rank.index[-2:])
        print(f"\n● {name}  ({start[:7]}→{end[:7]})  [{why}]   Nifty {nif:+.0f}%")
        print(f"    BOOMED:  {lead}")
        print(f"    lagged:  {lag}")

    # ───────── 2. CROSS-REGIME MECHANICAL TESTS ─────────
    def basket_excess(basket, mask):
        """Mean monthly sector-relative return of a basket over masked months + t."""
        sub = excess[basket].mean(axis=1)[mask].dropna()
        if len(sub) < 6:
            return np.nan, np.nan, len(sub)
        se = sub.std(ddof=1) / np.sqrt(len(sub))
        return sub.mean() * 100, (sub.mean() / se if se else np.nan), len(sub)

    print("\n" + "=" * 80)
    print("DOES THE 'WHY' GENERALISE?  mean monthly EXCESS return (sector−Nifty) by regime")
    print("=" * 80)

    print("\nH1 — rate-sensitives (Realty/Auto/Bank/PSUBank) vs RBI rate cycle:")
    for lbl in ["CUTTING", "FLAT", "HIKING"]:
        m, t, n = basket_excess(RATE_SENSITIVE, rate_dir_m == lbl)
        print(f"    repo {lbl:8s}: {m:+.2f}%/mo (t {t:+.1f}, n{n})")

    print("\nH2 — commodity sectors (Metal/Energy) vs Brent+Copper 6m trend:")
    for lbl, mask in [("RISING", comm_dir), ("falling/mixed", ~comm_dir)]:
        m, t, n = basket_excess(COMMODITY, mask)
        print(f"    commodities {lbl:13s}: {m:+.2f}%/mo (t {t:+.1f}, n{n})")

    print("\nH3 — defensives/exporters (FMCG/Pharma/IT) in risk-off vs risk-on months:")
    for lbl, mask in [("risk-OFF (Nifty 3m<0)", risk_off), ("risk-on", ~risk_off)]:
        m, t, n = basket_excess(DEFENSIVE, mask)
        print(f"    {lbl:22s}: {m:+.2f}%/mo (t {t:+.1f}, n{n})")

    # full sector × rate-regime heat table (the diagnostic)
    print("\n" + "=" * 80)
    print("SECTOR × RATE-REGIME heat (mean monthly excess return, %):")
    print("=" * 80)
    print(f"{'sector':8s} | {'CUTTING':>9s} {'FLAT':>9s} {'HIKING':>9s}")
    for s in sectors:
        row = []
        for lbl in ["CUTTING", "FLAT", "HIKING"]:
            sub = excess[s][rate_dir_m == lbl].dropna()
            row.append(f"{sub.mean()*100:+.2f}" if len(sub) else "  n/a")
        print(f"{s:8s} | " + " ".join(f"{x:>9s}" for x in row))

    # ───────── 3. MOMENTUM HORIZON-DECAY (the multibagger answer) ─────────
    # Does sector momentum survive to the 2-4yr multibagger horizon, or die/reverse?
    # Cross-sectional Spearman rho(trailing m-mo sector return, forward k-mo return),
    # pooled over all months on the 11 sector INDICES (2011+, no survivorship).
    print("\n" + "=" * 80)
    print("MOMENTUM HORIZON-DECAY  (sector indices 2011+):  does sector momentum")
    print("survive to the multibagger 2-4yr horizon?  rho(trailing mom, forward ret)")
    print("=" * 80)
    sret = mret[sectors]          # monthly sector returns (absolute; rho is rank-based)
    months_idx = list(sret.index)

    def _cum(ix0, ix1):           # compounded return over [ix0+1 .. ix1]
        w = sret.iloc[ix0 + 1: ix1 + 1]
        return (1 + w).prod() - 1 if len(w) else None

    def _decay(mlb, fwds):
        out = {}
        for k in fwds:
            rhos = []
            for ti in range(len(months_idx)):
                if ti - mlb < 0 or ti + k >= len(months_idx):
                    continue
                sig = (1 + sret.iloc[ti - mlb + 1: ti + 1]).prod() - 1
                fwd = (1 + sret.iloc[ti + 1: ti + 1 + k]).prod() - 1
                df = pd.concat([sig, fwd], axis=1).dropna()
                if len(df) >= 5:
                    rhos.append(df.iloc[:, 0].rank().corr(df.iloc[:, 1].rank()))
            r = np.array([x for x in rhos if not np.isnan(x)])
            se = r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 2 else np.nan
            out[k] = (r.mean(), r.mean() / se if se else np.nan, (r > 0).mean(), len(r))
        return out

    fwds = [1, 3, 6, 12, 24, 36]
    print(f"{'trail':>6s} | " + " | ".join(f"fwd{k:>2d}m" for k in fwds))
    print("-" * 72)
    for mlb in [6, 12]:
        d = _decay(mlb, fwds)
        cells = " | ".join(f"{d[k][0]:+.2f}" + ("*" if abs(d[k][1]) >= 2 else " ") for k in fwds)
        print(f"{mlb:>4d}m  | " + cells)
    print("(* = |t|>=2 pooled.  rho>0 = momentum persists; rho<=0 = decayed/reversed.)")
    d = _decay(12, fwds)
    print("  detail (trail 12m):  " + "  ".join(
        f"fwd{k}m rho{d[k][0]:+.2f}(t{d[k][1]:+.1f},{d[k][2]*100:.0f}%+)" for k in fwds))

    # ───────── 4. SPECIFIC MACRO→SECTOR LINKS (depth-permitting) ─────────
    print("\n" + "=" * 80)
    print("SPECIFIC MACRO LINKS (cross-regime, 2011+):  mean monthly EXCESS return")
    print("=" * 80)

    # H4 — INR weakness → exporters (IT/Pharma). signal = trailing 3m USDINR change.
    inr_up = me["USDINR"].pct_change(3) > 0          # rupee depreciating (USDINR rising)
    print("\nH4 — exporters (IT/Pharma) vs rupee direction (trailing 3m USDINR):")
    for lbl, mask in [("INR weakening", inr_up), ("INR strengthening", ~inr_up)]:
        m, t, n = basket_excess(EXPORTERS, mask)
        print(f"    {lbl:18s}: {m:+.2f}%/mo (t {t:+.1f}, n{n})")

    # H5 — rising US10Y → rate-sensitives lag vs defensives (rotation).
    if "US10Y" in me.columns:
        y_up = me["US10Y"].diff(3) > 0
        print("\nH5 — rate-sensitives vs defensives when US10Y rising (trailing 3m):")
        for lbl, mask in [("US10Y rising", y_up), ("US10Y falling", ~y_up)]:
            mr, tr, nr = basket_excess(RATE_SENSITIVE, mask)
            md, td, nd = basket_excess(DEFENSIVE, mask)
            print(f"    {lbl:14s}: rate-sens {mr:+.2f}%/mo(t{tr:+.1f}) | "
                  f"defensive {md:+.2f}%/mo(t{td:+.1f})  [n{nr}]")

    print("\nExcess = sector monthly return − Nifty (sector-relative). "
          f"Window: {mret.index.min().date()}..{mret.index.max().date()}.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--refresh", action="store_true", help="force re-pull from yfinance")
    args = p.parse_args()
    run(refresh=args.refresh)
