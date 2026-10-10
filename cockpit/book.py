"""
Alpha Signal Cockpit - page data for /book (the sized book, its risk, its track record).

"The book" is the HRP-sized book in `portfolio_weights`, rebuilt each morning and
banded (a held name stays until it drifts past the band). Reads named view functions
and cockpit.api; the one query here asks when a held name last sat in the top picks.

  get_book()          the holdings + the one expected-return figure + the band line
  get_risk()          concentration and style, a plain one-line summary on top
  get_track_record()  realised outcomes, weekday pick dates only, a verdict per tier
  tier_verdicts()     the verdict rule (pure, tested); /model Health reads it too
"""

from datetime import date, timedelta

import pandas as pd

import config
import db
import views
from cockpit import api
from cockpit._shared import _ttl_cache

# Every row in pick_outcomes was picked before this model change (3-4 Oct 2026).
MODEL_CHANGE_FIRST, MODEL_CHANGE = date(2026, 10, 3), date(2026, 10, 4)
# Verdict rule: the top-10 basket against the whole ranked tier it was drawn from.
OUTCOME_MIN_DATES = 20       # fewer pick days than this = too early to say (row muted)
VERDICT_BAR_PP = 1.0         # within +-1.0 percentage point of the tier = no difference

STYLE_LABELS = {"Value": "cheap stocks", "Quality": "financially strong stocks",
                "Growth": "analyst growth outlook", "Momentum": "recent price strength",
                "Accruals": "earnings backed by cash", "Ownership": "promoter buying",
                "Flow": "institutional buying"}


def _num(v, kind=float):
    return None if v is None or pd.isna(v) else kind(v)


def _top_n(tier):
    return config.TIERS[tier]["picks"]


def band_line():
    """The rebalancing rule in one sentence, from config (never hand-typed numbers)."""
    rb = config.PORTFOLIO["hrp"]["rebalance"]
    return (f"A name is bought when it reaches the top {_top_n(views.pickable_tiers()[0])} of its tier and sold only "
            f"after {rb.get('debounce_days', 1)} days below rank {rb['rank_exit']}. That is why some names below "
            f"today's top picks are still held. Weights change only on a buy or sell, or when one drifts "
            f"{rb['drift_pp']:g} percentage points from target.")


def _history(sids, pick_date):
    """{sid: {ranked_today, in_top_today, last_top, dates}} over the last 60 days of daily_picks.
    'In the top picks' = within-tier rank at most that tier's pick count, and published."""
    if not sids:
        return {}
    ph = ",".join("?" * len(sids))
    df = db.read_sql(
        f"SELECT sid, pick_date, rank, cap_tier, integrity_status FROM daily_picks "
        f"WHERE sid IN ({ph}) AND pick_date >= date(?, '-60 days') AND pick_date <= ? ORDER BY pick_date",
        params=list(sids) + [pick_date, pick_date])
    out = {}
    for sid, g in df.groupby("sid"):
        top = g[(g["rank"] <= g["cap_tier"].map(_top_n)) & (g["integrity_status"] != "FAIL")]
        last = top["pick_date"].max() if len(top) else None
        out[sid] = {"ranked_today": bool((g["pick_date"] == pick_date).any()), "in_top_today": last == pick_date,
                    "last_top": last, "dates": sorted(g["pick_date"].unique())}
    return out


def left_flag(info, pick_date):
    """Words for a held name that is not in today's top picks (None when it is)."""
    if info is None or not info["ranked_today"]:
        return "not ranked today"
    if info["in_top_today"]:
        return None
    last = info["last_top"]
    if last is None:
        return "not in the top picks for 60 days"
    later = [d for d in info["dates"] if d > last]
    d = date.fromisoformat(later[0] if later else last)
    return f"left top picks {d.day} {d:%b}"


@_ttl_cache(60)
def get_book():
    """The held book, or None before the first build."""
    sb = api.get_sized_book()
    if not sb:
        return None
    pick_date = api.latest_pick_date()
    rows = pd.DataFrame(sb["rows"])
    ranked = views.picks(pick_date, gated=False)
    ranked = ranked.set_index("sid")[["rank", "final_score"]]
    hist = _history(rows["sid"].tolist(), pick_date)
    exit_rank = config.PORTFOLIO["hrp"]["rebalance"]["rank_exit"]
    out = []
    for r in rows.to_dict("records"):
        t = ranked.loc[r["sid"]] if r["sid"] in ranked.index else None
        out.append({
            "sid": r["sid"], "ticker": r["ticker"] or r["sid"], "name": r["name"], "cap_tier": r["cap_tier"],
            "sector": r["sector"], "weight_pct": round(r["weight"] * 100, 1),
            "risk_pct": round((r["marginal_risk_contrib"] or 0) * 100, 0),
            "score": None if t is None else int(round(t["final_score"] * 100)),
            "rank": None if t is None else int(t["rank"]),
            "pt_upside_pct": _num(r.get("pt_upside_median_pct")), "n_analysts": _num(r.get("n_analysts"), int),
            "left_top": left_flag(hist.get(r["sid"]), pick_date),
        })
        out[-1]["below_exit"] = out[-1]["rank"] is None or out[-1]["rank"] > exit_rank
    out.sort(key=lambda x: -x["weight_pct"])
    return {
        "asof": sb["asof_date"], "pick_date": pick_date, "rows": out, "n": len(out),
        "n_left": sum(1 for r in out if r["left_top"]), "n_below_exit": sum(r["below_exit"] for r in out),
        "exit_rank": exit_rank,
        "tier_pct": sb["tier_weights"], "top_n": {t: _top_n(t) for t in views.pickable_tiers()},
        "expected_return_pct": sb["expected_return_1y"], "er_basis": sb.get("er_basis"),
        "er_names": sb["er_coverage_n"], "er_weight_pct": sb["er_coverage_weight_pct"],
        "band": band_line(),
    }


def risk_summary(sectors, hhi, strong, max_stock, cap_stock, cap_sector):
    """The plain one-line summary above the Risk details."""
    word = "Concentrated" if hhi > 2500 else ("Moderately concentrated" if hhi > 1500 else "Well spread")
    top_sector, top_w = sectors[0]
    lean = (" It leans " + " and ".join(f"{'toward' if t['z'] >= 0 else 'away from'} {t['label']}" for t in strong[:2]) + "."
            if strong else " No strong style lean.")
    return (f"{word}: {len(sectors)} sectors, the largest is {top_sector} at {top_w:.0f}% of the book "
            f"(limit {cap_sector:.0f}%). The biggest stock is {max_stock:.1f}% (limit {cap_stock:.0f}%).{lean}")


@_ttl_cache(60)
def get_risk():
    """Concentration and style of the held book, plain summary first."""
    book = get_book()
    sb = api.get_sized_book()
    if not book or not sb:
        return None
    rd = api.get_risk_decomposition([r["sid"] for r in book["rows"]]) or {}
    by_sector = {}
    for r in book["rows"]:
        by_sector[r["sector"]] = by_sector.get(r["sector"], 0) + r["weight_pct"]
    sectors = sorted(by_sector.items(), key=lambda kv: -kv[1])
    total = sum(by_sector.values()) or 1
    hhi = int(round(sum((w * 100 / total) ** 2 for w in by_sector.values())))
    tilts = [{**t, "label": STYLE_LABELS.get(t["group"], t["group"].lower())} for t in rd.get("tilts", [])]
    strong = sorted((t for t in tilts if t["magnitude"] == "strong"), key=lambda t: -abs(t["z"]))
    return {
        "asof": book["asof"], "sectors": sectors, "hhi": hhi, "tilts": tilts, "n_picks": rd.get("n_picks"),
        "summary": risk_summary(sectors, hhi, strong, sb["max_stock_pct"], sb["cap_stock_pct"], sb["cap_sector_pct"]),
        "effective_n": sb["effective_n"], "n": sb["n_names"],
        "max_stock_pct": sb["max_stock_pct"], "cap_stock_pct": sb["cap_stock_pct"],
        "max_sector_pct": sb["max_sector_pct"], "cap_sector_pct": sb["cap_sector_pct"],
        "tier_pct": sb["tier_weights"],
    }


# ── track record ────────────────────────────────────────────────────────────────────

def _cell(summary, tier, window, scope):
    for r in summary["by_window_tier"]:
        if r["cap_tier"] == tier and r["window_days"] == window and r["scope"] == scope:
            return r
    return None


def tier_verdict(tier, top, whole, top_short=None, whole_short=None, top_n=10):
    """One tier's verdict from the realised outcomes: did the top-N basket beat the whole
    ranked tier it was drawn from, at the longest window with data (`top` / `whole` are
    the summary cells of that window; `*_short` the 20-day cells, which must not disagree)?

    -> {tier, verdict: beat | lagged | mixed | early | none, spread_pp, window, n_dates, text}"""
    if not top or not whole or top.get("avg_fwd") is None or whole.get("avg_fwd") is None:
        return {"tier": tier, "verdict": "none", "spread_pp": None, "window": None, "n_dates": 0,
                "text": f"{tier}: no matured outcomes yet."}
    w, n = top["window_days"], top["n_dates"]
    spread = round(top["avg_fwd"] - whole["avg_fwd"], 1)
    if n < OUTCOME_MIN_DATES:
        return {"tier": tier, "verdict": "early", "spread_pp": spread, "window": w, "n_dates": n,
                "text": f"{tier}: too early, only {n} pick days at {w} trading days."}
    short = None
    if top_short and whole_short and top_short.get("avg_fwd") is not None and whole_short.get("avg_fwd") is not None:
        short = top_short["avg_fwd"] - whole_short["avg_fwd"]
    if spread >= VERDICT_BAR_PP and (short is None or short >= 0):
        verdict, what = "beat", f"beat the tier by {spread:.1f} percentage points"
    elif spread <= -VERDICT_BAR_PP and (short is None or short <= 0):
        verdict, what = "lagged", f"lagged the tier by {abs(spread):.1f} percentage points"
    else:
        verdict = "mixed"
        what = (f"was {spread:+.1f} percentage points from the tier at {w} trading days but "
                f"{short:+.1f} at 20 trading days" if short is not None else f"was {spread:+.1f} percentage points from the tier")
    return {"tier": tier, "verdict": verdict, "spread_pp": spread, "window": w, "n_dates": n,
            "text": f"{tier}: top {top_n} {what}" + ("" if verdict == "mixed" else f" at {w} trading days")
                    + f" ({n} pick days, overlapping)."}


def tier_verdicts(summary):
    """[tier_verdict per pickable tier] from api.get_pick_outcomes_summary()."""
    top_n, w = summary["top_n"], summary["headline_window"]
    scope = f"top_{top_n}"
    return [tier_verdict(t, _cell(summary, t, w, scope), _cell(summary, t, w, "all"),
                         _cell(summary, t, 20, scope), _cell(summary, t, 20, "all"), top_n)
            for t in views.pickable_tiers()]


def first_read_date():
    """When the first 20-trading-day outcome on the current model exists (28 calendar days on)."""
    return MODEL_CHANGE + timedelta(days=round(20 * 7 / 5))


def get_track_record(top_n=10):
    s = api.get_pick_outcomes_summary(top_n=top_n)
    return {
        "summary": s, "top_n": top_n, "verdicts": tier_verdicts(s),
        "last_pick_date": max((r["pick_date"] for r in s["time_series"]), default=None),
        "min_dates": OUTCOME_MIN_DATES, "first_read": first_read_date(),
        "model_change_text": f"{MODEL_CHANGE_FIRST.day}-{MODEL_CHANGE.day} {MODEL_CHANGE:%b}",
        "bench_stale": (s["bench_staleness_days"] or 0) > 7,
    }
