"""Do the top-ranked picks actually beat the bottom-ranked ones?

The one test that decides whether the model can pick stocks. For each cap tier
and each pick date we split that day's ranked universe into deciles, then ask:
did the best-ranked decile out-return the worst-ranked decile?

The catch: overlapping windows lie. If we score 20-day forward returns from
pick dates one day apart, those windows share 19 of 20 days — they are NOT
independent observations. So we also collapse to non-overlapping dates (spaced
at least one window apart) and report the honest sample size. A spread that
looks great on 24 overlapping dates but rests on 2 independent windows has not
been proven.

Run:  python -m tools.validate_rank_skill
      python -m tools.validate_rank_skill --window 5
"""
import argparse
import math
import sqlite3
from datetime import date

DB = "data/alpha_signal.db"
MIN_PERIODS = 6          # don't call anything "proven" on fewer independent windows than this


def _decile_means(rows):
    """rows = [(rank, fwd_return), ...] for one tier+date. Return (top10%, bottom10%) mean fwd return."""
    rows = [(r, f) for r, f in rows if f is not None]
    if len(rows) < 20:                       # too few to cut a clean decile
        return None
    rows.sort(key=lambda x: x[0])            # rank 1 = best, ascending
    n = len(rows)
    cut = max(1, n // 10)
    top = [f for _, f in rows[:cut]]         # best-ranked decile
    bottom = [f for _, f in rows[-cut:]]     # worst-ranked decile
    return sum(top) / len(top), sum(bottom) / len(bottom)


def _pick_non_overlapping(dates, window_days):
    """Greedily keep dates at least `window_days` apart so windows don't overlap."""
    gap = max(window_days * 7 // 5, window_days)   # trading days -> rough calendar days
    kept, last = [], None
    for d in sorted(dates):
        dd = date.fromisoformat(d)
        if last is None or (dd - last).days >= gap:
            kept.append(d)
            last = dd
    return kept


def _summary(spreads):
    """Mean spread + a rough 95% confidence band (t-ish, normal approx)."""
    n = len(spreads)
    mean = sum(spreads) / n
    if n < 2:
        return mean, None, None, n
    sd = math.sqrt(sum((s - mean) ** 2 for s in spreads) / (n - 1))
    se = sd / math.sqrt(n)
    return mean, mean - 1.96 * se, mean + 1.96 * se, n


def run(window_days):
    db = sqlite3.connect(DB)
    c = db.cursor()
    tiers = [r[0] for r in c.execute(
        "SELECT DISTINCT cap_tier FROM pick_outcomes WHERE window_days=? ORDER BY cap_tier",
        (window_days,))]

    print(f"\n=== DO TOP PICKS BEAT BOTTOM PICKS?  ({window_days}-day forward returns) ===\n")
    print("Spread = avg return of best-ranked decile MINUS worst-ranked decile.")
    print("Positive = the ranking works.  Around zero = the ranking is noise.\n")

    for tier in tiers:
        dates = [r[0] for r in c.execute(
            "SELECT DISTINCT pick_date FROM pick_outcomes WHERE window_days=? AND cap_tier=? ORDER BY pick_date",
            (window_days, tier))]

        # spread on every date (overlapping) and on the independent subset
        per_date = {}
        for d in dates:
            rows = c.execute(
                "SELECT rank_at_pick, fwd_return_pct FROM pick_outcomes "
                "WHERE window_days=? AND cap_tier=? AND pick_date=?",
                (window_days, tier, d)).fetchall()
            dm = _decile_means(rows)
            if dm:
                per_date[d] = dm[0] - dm[1]

        if not per_date:
            print(f"{tier:6} — not enough data\n")
            continue

        indep = [d for d in _pick_non_overlapping(list(per_date), window_days) if d in per_date]
        all_spreads = list(per_date.values())
        indep_spreads = [per_date[d] for d in indep]

        m_all, _, _, n_all = _summary(all_spreads)
        m_ind, lo, hi, n_ind = _summary(indep_spreads)

        print(f"{tier}")
        print(f"  overlapping view : avg spread {m_all:+.2f}pp  over {n_all} dates (NOT independent)")
        if n_ind >= 2:
            band = f"  95% range [{lo:+.2f}, {hi:+.2f}]"
            if n_ind < MIN_PERIODS:
                proven = f"NOT enough data (need ~{MIN_PERIODS} independent periods, have {n_ind})"
            elif lo > 0:
                proven = "PROVEN"
            else:
                proven = "NOT proven (range includes 0 or negative)"
            print(f"  independent view : avg spread {m_ind:+.2f}pp  over {n_ind} real periods{band}  -> {proven}")
        else:
            print(f"  independent view : {m_ind:+.2f}pp on only {n_ind} independent period "
                  f"-> CANNOT be proven yet (need more time)")
        print(f"    independent dates used: {', '.join(indep)}\n")

    print("VERDICT GATE: invest in a tier only once its independent-view spread is")
    print("clearly positive (95% range above 0) on at least ~6 independent periods.\n")
    db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=20, help="forward-return horizon in days")
    run(ap.parse_args().window)
