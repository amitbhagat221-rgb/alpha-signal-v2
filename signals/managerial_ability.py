"""
Alpha Signal v2 — Managerial Ability (Demerjian-Lev-McVay 2012)

Reads:  fundamentals_screener (annual rows), annual_cash_flow, stocks
Writes: managerial_ability_scores

The peer-reviewed standard for measuring management quality as a single
firm-level number (Demerjian, Lev & McVay, *Management Science* 2012). Two
stages:

  Stage 1 — DEA efficiency frontier.
    Input-oriented, Variable-Returns-to-Scale (VRS) Data Envelopment Analysis
    run WITHIN each sector (financials excluded). One output produced from the
    resources management controls:
      output = operating profit (EBITDA = Sales − COGS − Employee Cost − Other Exp)
      inputs = { COGS, Employee Cost, Net Block (PP&E), Intangible Assets }
    θ ∈ (0,1] = how close the firm sits to the best-practice frontier of its
    sector peers. θ=1 ⇒ on the frontier. VRS (not CRS) so a small firm isn't
    penalised purely for sub-scale — scale is handled in stage 2.

    Output is PROFIT, not Sales (a deliberate departure from textbook DLM): a
    Sales-output frontier rewards revenue-per-input and is therefore fooled by
    fabricated / zero-margin revenue — it graded the Rajesh Exports fraud A+
    (the exact REXP blind spot we already have an exclusion rule for) and
    flattered lumpy-revenue real-estate developers. A profit output can't be
    reached on fabricated sales (≈0 margin → ≈0 output) or by loss-makers
    (floored out), so MA measures profit-generating, not revenue-generating,
    efficiency — the right notion for management quality. Loss / ≤0-EBITDA
    firms are floored to a tiny output ⇒ they sit far from the frontier ⇒ low MA.

  Stage 2 — strip the firm, keep the manager.
    Right-censored Tobit (efficiency is censored at the θ=1 frontier) of θ on
    firm characteristics the manager doesn't control — size, market share,
    free-cash-flow status. The RESIDUAL (θ minus what the firm's
    characteristics predict) is the manager-attributable efficiency = the
    Managerial Ability score.

We surface it as a 0-100 percentile WITHIN cap_tier (so it slots into the same
ranking frame as every other factor) plus an A+/A/B/C/D grade.

Why this and not the existing management_scores scorecard? That scorecard
re-aggregates factors already weighted elsewhere (roic/pledge/f_score …) — a
transparent display lens, but colinear with the model. MA is a genuinely
ORTHOGONAL signal: frontier-relative operating efficiency, net of size/share.

DEA is solved in-house with scipy.optimize.linprog (HiGHS) — no new dependency
(keeps the v1-shared venv untouched). Tobit MLE via scipy.optimize.minimize.

Inputs we can't source for the Indian feed (vs canonical DLM): net operating
leases, separated R&D. Employee Cost stands in for the SG&A/labour input;
Intangible Assets covers goodwill + other intangibles. Controls we omit (no
clean source): firm age, business-segment count, foreign-ops indicator.

Financial Services excluded — frontier/asset semantics differ for banks; they
route through the financial sub-model per CLAUDE.md.

Usage:
    python -m signals.managerial_ability
    python -m signals.managerial_ability --dry-run
    python -m signals.managerial_ability --show 20      # print top/bottom N
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import linprog, minimize
from scipy.stats import norm

from config import SCREEN
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

# fundamentals_screener line items
SALES_ITEM = "Sales"
COGS_ITEMS = ["Raw Material Cost", "Change in Inventory", "Power and Fuel", "Other Mfr. Exp"]
EMP_ITEM = "Employee Cost"
OTHER_EXP_ITEM = "Other Expenses"
NI_ITEM = "Net profit"
PPE_ITEM = "Net Block"
INTANG_ITEM = "Intangible Assets"
ASSETS_ITEM = "Total"
ALL_ITEMS = [SALES_ITEM, EMP_ITEM, OTHER_EXP_ITEM, NI_ITEM,
             PPE_ITEM, INTANG_ITEM, ASSETS_ITEM] + COGS_ITEMS

# DEA input columns (the resources converted into Sales)
INPUT_COLS = ["cogs", "employee_cost", "net_block", "intangibles"]

SMOOTH_YEARS = 3
MIN_YEARS = 2
MIN_SALES_CR = 50.0
MIN_ASSETS_CR = 50.0
MIN_PEERS = 8           # absolute floor for any frontier group
MIN_INDUSTRY_PEERS = 15  # DEA with 4 inputs+1 output needs ~3×(m+s)=15 DMUs to
                         # discriminate; industries below this fall back to their
                         # GICS sector. Industry-level keeps capital-heavy
                         # businesses (cement, steel) from being judged against
                         # asset-light names in the same sector (the JK Cement problem).
INPUT_FLOOR = 1e-3      # ₹0.001 cr — DEA needs strictly-positive inputs
CENSOR_TOL = 1e-6       # θ ≥ 1−tol treated as on-frontier (right-censored)

# percentile → grade bands (mirrors management_scores' distribution shape)
GRADE_BANDS = [(90, "A+"), (75, "A"), (50, "B"), (25, "C"), (0, "D")]


# ─────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────
def _load_data():
    placeholders = ",".join("?" for _ in FINANCIAL_SECTORS)
    # Exclude InvITs/REITs/business-trusts — pass-through vehicles, not operating
    # companies: huge rental/toll "Sales" against negligible operating inputs put
    # them spuriously on the efficiency frontier. DEA-on-Sales is meaningless for
    # them; they're financial-like and out of scope for a management-quality lens.
    stocks = read_sql(
        f"SELECT sid, sector, cap_tier, industry FROM stocks "
        f"WHERE sector NOT IN ({placeholders}) "
        f"AND name NOT LIKE '%InvIT%' AND name NOT LIKE '%REIT%' "
        f"AND name NOT LIKE '%Trust%'",   # InvITs/REITs/business-trusts (pass-throughs)
        params=list(FINANCIAL_SECTORS),
    )
    sids = set(stocks["sid"])

    fund = read_sql(
        "SELECT sid, period_end, line_item, value FROM fundamentals_screener "
        f"WHERE period_type='annual' AND line_item IN ({','.join('?' for _ in ALL_ITEMS)})",
        params=ALL_ITEMS,
    )
    fund = fund[fund["sid"].isin(sids)].copy()

    cf = read_sql(
        "SELECT sid, end_date AS period_end, free_cash_flow FROM annual_cash_flow"
    )
    cf = cf[cf["sid"].isin(sids)].copy()
    return stocks, fund, cf


def _smoothed_frame(stocks, fund, cf):
    """One row per sid: 3y-median inputs/output + latest period_end + fcf status."""
    if fund.empty:
        return pd.DataFrame()
    wide = fund.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()

    for it in ALL_ITEMS:
        if it not in wide.columns:
            wide[it] = np.nan
    # COGS optional components → 0; output/assets required
    wide[COGS_ITEMS] = wide[COGS_ITEMS].fillna(0.0)
    wide["cogs"] = wide[COGS_ITEMS].sum(axis=1)
    wide["sales"] = wide[SALES_ITEM]
    wide["employee_cost"] = wide[EMP_ITEM].fillna(0.0)
    wide["other_expenses"] = wide[OTHER_EXP_ITEM].fillna(0.0)
    wide["net_block"] = wide[PPE_ITEM]
    wide["intangibles"] = wide[INTANG_ITEM].fillna(0.0)
    wide["total_assets"] = wide[ASSETS_ITEM]
    wide["net_income"] = wide[NI_ITEM]
    # operating profit (EBITDA) = the DEA output — robust to fabricated revenue
    wide["op_profit"] = (wide["sales"] - wide["cogs"]
                         - wide["employee_cost"] - wide["other_expenses"])

    wide = wide.dropna(subset=["sales", "net_block", "total_assets"])
    wide = wide.sort_values(["sid", "period_end"])

    # 3y median per sid (≥2 of last 3 annual periods)
    last_n = wide.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        period_end=("period_end", "max"),
        sales=("sales", "median"),
        cogs=("cogs", "median"),
        employee_cost=("employee_cost", "median"),
        op_profit=("op_profit", "median"),
        net_income=("net_income", "median"),
        net_block=("net_block", "median"),
        intangibles=("intangibles", "median"),
        total_assets=("total_assets", "median"),
        years_used=("sales", "count"),
    )
    agg = agg[agg["years_used"] >= MIN_YEARS]

    # FCF status (median over recent years)
    fcf_pos = {}
    if not cf.empty:
        cf2 = cf.sort_values(["sid", "period_end"])
        cf_last = cf2.groupby("sid", as_index=False).tail(SMOOTH_YEARS)
        med = cf_last.groupby("sid")["free_cash_flow"].median()
        fcf_pos = {s: int(v > 0) for s, v in med.items() if pd.notna(v)}
    agg["fcf_positive"] = agg["sid"].map(fcf_pos).fillna(0).astype(int)

    agg = agg.merge(stocks, on="sid", how="left")

    # Drop fabricated / implausible-revenue names (REXP-class) — the SAME
    # validated hard exclusion that keeps them out of daily_picks. No efficiency
    # frontier can catch coherent steady-state fabrication (REXP's asset-light,
    # positive-profit statements sit ON the frontier by construction, just as
    # they fooled Beneish/Altman/Piotroski), so we apply the gate rather than
    # expect DEA to. See revenue_plausibility / the REXP drive-by.
    from signals.revenue_plausibility import flag_revenue_implausible
    impl = agg.apply(
        lambda r: flag_revenue_implausible(
            r["sales"], r["net_income"], r["total_assets"], r["sector"])[0],
        axis=1,
    )
    if impl.any():
        print(f"  revenue-implausible excluded: {int(impl.sum())} "
              f"({', '.join(agg.loc[impl, 'sid'].head(5).tolist())})")
    agg = agg[~impl].copy()

    # economic-size + operating-input floors
    agg = agg[(agg["sales"] >= MIN_SALES_CR)
              & (agg["total_assets"] >= MIN_ASSETS_CR)
              & (agg["net_block"] > 0)
              & ((agg["cogs"] + agg["employee_cost"]) > 0)].copy()
    return agg.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — DEA (input-oriented, VRS)
# ─────────────────────────────────────────────────────────────────────────────
def _dea_vrs_input(X, y):
    """Input-oriented VRS efficiency θ for every DMU in one peer group.

    X: (n, m) inputs (>0). y: (n,) single output (>0). Returns θ ∈ (0,1], n-vec.
    Per DMU o:  min θ  s.t.  Σ λ_j X_ij ≤ θ X_io ∀i ;  Σ λ_j y_j ≥ y_o ;
                Σ λ_j = 1 (VRS) ;  λ ≥ 0.
    Variables z = [θ, λ_0..λ_{n-1}].
    """
    n, m = X.shape
    theta = np.full(n, np.nan)
    c = np.concatenate([[1.0], np.zeros(n)])          # minimise θ
    A_eq = np.concatenate([[0.0], np.ones(n)]).reshape(1, -1)   # VRS: Σλ = 1
    b_eq = np.array([1.0])
    bounds = [(0.0, None)] * (n + 1)                  # θ≥0, λ≥0

    for o in range(n):
        # input rows: Σ_j λ_j X_ji − θ X_oi ≤ 0
        A_in = np.column_stack([-X[o, :], X.T])        # (m, n+1)
        # output row: −Σ_j λ_j y_j ≤ −y_o
        A_out = np.concatenate([[0.0], -y]).reshape(1, -1)
        A_ub = np.vstack([A_in, A_out])
        b_ub = np.concatenate([np.zeros(m), [-y[o]]])
        res = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                      bounds=bounds, method="highs")
        if res.success and res.x is not None:
            theta[o] = min(1.0, max(1e-6, float(res.x[0])))
    return theta


def _run_dea_by_group(df):
    """Add a `dea_efficiency` column, computed within each frontier group
    (industry where it has ≥MIN_INDUSTRY_PEERS, else the GICS sector)."""
    eff = pd.Series(np.nan, index=df.index)
    n_peers = pd.Series(np.nan, index=df.index)
    for group, grp in df.groupby("frontier_group"):
        if len(grp) < MIN_PEERS:
            continue
        X = np.clip(grp[INPUT_COLS].to_numpy(dtype=float), INPUT_FLOOR, None)
        # output = operating profit; loss / ≤0-EBITDA firms floored → far from
        # frontier (can't fabricate profit the way Sales can be fabricated)
        y = np.clip(grp["op_profit"].to_numpy(dtype=float), INPUT_FLOOR, None)
        n_loss = int((grp["op_profit"] <= 0).sum())
        theta = _dea_vrs_input(X, y)
        eff.loc[grp.index] = theta
        n_peers.loc[grp.index] = len(grp)
        print(f"  DEA {str(group)[:28]:28s} n={len(grp):4d}  on-frontier={int(np.nansum(theta >= 1 - CENSOR_TOL)):3d}  "
              f"loss/floored={n_loss:3d}  median θ={np.nanmedian(theta):.3f}")
    df = df.copy()
    df["dea_efficiency"] = eff
    df["n_peers"] = n_peers
    return df.dropna(subset=["dea_efficiency"])


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — right-censored Tobit; residual = managerial ability
# ─────────────────────────────────────────────────────────────────────────────
def _tobit_residual(theta, Xc):
    """θ right-censored at 1, regressed on controls Xc (incl. intercept).

    Returns ma = θ − Xc·β̂ (manager-attributable efficiency). Falls back to the
    OLS residual if the MLE fails to converge.
    """
    n, k = Xc.shape
    censored = theta >= 1 - CENSOR_TOL
    # OLS warm-start (and fallback)
    beta_ols, *_ = np.linalg.lstsq(Xc, theta, rcond=None)
    resid_ols = theta - Xc @ beta_ols
    sigma0 = max(resid_ols.std(ddof=k), 1e-3)

    def neg_ll(params):
        beta = params[:k]
        sigma = np.exp(params[k])
        mu = Xc @ beta
        ll = 0.0
        unc = ~censored
        if unc.any():
            z = (theta[unc] - mu[unc]) / sigma
            ll += np.sum(norm.logpdf(z) - np.log(sigma))
        if censored.any():
            zc = (1.0 - mu[censored]) / sigma
            ll += np.sum(norm.logsf(zc))   # P(latent ≥ 1)
        return -ll

    x0 = np.concatenate([beta_ols, [np.log(sigma0)]])
    try:
        res = minimize(neg_ll, x0, method="L-BFGS-B")
        beta = res.x[:k] if res.success else beta_ols
    except Exception:
        beta = beta_ols
    return theta - Xc @ beta


def _stage2(df):
    df = df.copy()
    # controls: intercept, standardised ln(assets) [size], fcf status, +
    # FRONTIER-GROUP fixed effects. The DEA runs within each frontier group, so
    # groups carry different θ-LEVELS (some have most firms on the frontier);
    # without group FE that level leaks into the residual and a firm looks
    # "able" just for sitting in a loose-frontier group. Group dummies remove it.
    #
    # We standardise ln(assets) and DROP raw market-share: share = sales/group-
    # sales is collinear with size and explodes for a group-dominant firm,
    # which made the linear control extrapolate a predicted efficiency far above
    # the θ=1 cap and dump frontier mega-caps (e.g. GAIL) at the bottom. Size
    # alone, standardised, keeps the scale control without the pathology.
    ln_assets = np.log(df["total_assets"].to_numpy(dtype=float))
    ln_assets_z = (ln_assets - ln_assets.mean()) / (ln_assets.std() or 1.0)
    grp_dummies = pd.get_dummies(df["frontier_group"], drop_first=True, dtype=float)
    Xc = np.column_stack([
        np.ones(len(df)),
        ln_assets_z,
        df["fcf_positive"].to_numpy(dtype=float),
        grp_dummies.to_numpy(dtype=float),
    ])
    df["ma_residual"] = _tobit_residual(df["dea_efficiency"].to_numpy(dtype=float), Xc)
    return df


def _grade(pct):
    for thr, g in GRADE_BANDS:
        if pct >= thr:
            return g
    return "D"


def _percentile_within_tier(df):
    df = df.copy()
    df["ma_score"] = (
        df.groupby("cap_tier")["ma_residual"].rank(pct=True) * 100
    ).round(1)
    df["grade"] = df["ma_score"].apply(_grade)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────
def _compute():
    stocks, fund, cf = _load_data()
    frame = _smoothed_frame(stocks, fund, cf)
    if frame.empty:
        return pd.DataFrame()
    # Frontier group = INDUSTRY where it has enough peers to discriminate, else
    # the broad GICS sector (keeps capital-heavy industries like cement/steel
    # from being judged against asset-light names in the same sector).
    ind_counts = frame["industry"].value_counts()
    big = set(ind_counts[ind_counts >= MIN_INDUSTRY_PEERS].index)
    frame["frontier_group"] = [ind if ind in big else sec
                               for ind, sec in zip(frame["industry"], frame["sector"])]
    n_ind = int(frame["frontier_group"].isin(big).sum())
    print(f"  frontier: {len(big)} industry groups (≥{MIN_INDUSTRY_PEERS}) + sector fallback "
          f"→ {n_ind}/{len(frame)} names ({n_ind/len(frame)*100:.0f}%) industry-judged")
    frame = _run_dea_by_group(frame)
    if frame.empty:
        return pd.DataFrame()
    frame = _stage2(frame)
    frame = _percentile_within_tier(frame)
    return frame


def compute(dry_run=False, show=0):
    df = _compute()
    if df.empty:
        print("Managerial Ability: 0 stocks scored — fundamentals_screener thin "
              "or no sector reached the peer floor.")
        return 0

    df["snapshot_date"] = date.today().isoformat()
    out_cols = ["sid", "snapshot_date", "cap_tier", "sector", "frontier_group",
                "period_end", "dea_efficiency", "ma_residual", "ma_score", "grade",
                "sales", "cogs", "employee_cost", "net_block", "intangibles",
                "total_assets", "n_peers"]
    out = df[out_cols].copy()
    out["n_peers"] = out["n_peers"].astype(int)

    n = len(out)
    gd = out["grade"].value_counts().to_dict()
    print(f"\nManagerial Ability: {n} stocks scored | "
          f"grades A+{gd.get('A+',0)}/A{gd.get('A',0)}/B{gd.get('B',0)}/"
          f"C{gd.get('C',0)}/D{gd.get('D',0)}")

    if show:
        names = read_sql("SELECT sid, name FROM stocks").set_index("sid")["name"].to_dict()
        ranked = df.sort_values("ma_score", ascending=False)
        def _line(r):
            return (f"    {names.get(r['sid'], r['sid'])[:30]:30s} "
                    f"[{r['cap_tier'][:1]}/{str(r['frontier_group'])[:14]:14s}] "
                    f"θ={r['dea_efficiency']:.2f} ma={r['ma_residual']:+.3f} "
                    f"score={r['ma_score']:.0f} {r['grade']}")
        print(f"\n  TOP {show} (highest managerial ability):")
        for _, r in ranked.head(show).iterrows():
            print(_line(r))
        print(f"\n  BOTTOM {show} (lowest):")
        for _, r in ranked.tail(show).iloc[::-1].iterrows():
            print(_line(r))

    if dry_run:
        print("\nDry run — not saving.")
        return n
    rows = upsert_df(out, "managerial_ability_scores")
    print(f"\nSaved {rows} rows to managerial_ability_scores")
    return rows


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--show", type=int, default=0, help="print top/bottom N by score")
    args = p.parse_args()
    compute(dry_run=args.dry_run, show=args.show)
