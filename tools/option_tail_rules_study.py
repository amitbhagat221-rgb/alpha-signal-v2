"""Alpha Signal v2: T-1 tail rules and heavyweight results for the strangle. READ-ONLY.
Rules fixed in docs/studies/option-tail-rules-preregistration-2026-11.md. Run: python -m tools.option_tail_rules_study
"""
from __future__ import annotations

import math
import random
from statistics import NormalDist

import numpy as np
import pandas as pd

import option_book as ob
from db import read_sql
from signals._fundamentals import SHARE_ITEMS, market_caps
from sources.fno_iv import _implied_forward, _invert_iv

LOTS, BUDGET, WING, TAIL_K = 20, 200_000, 0.0085, 1.65 * 1.25
RULES = ("exit z<1", "exit z<1.5", "exit tail>2L", "wing z<1", "wing z<1.5")
N = NormalDist()


def chain(u, t, e):
    df = read_sql("SELECT option_type o, strike k, settle s, volume v FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                  "AND trade_date = ? AND expiry_date = ?", params=[u, t, e])
    df["k"] = df.k.astype(float)
    return df


def sides(df):
    return df[(df.o == "CE") & (df.s > 0)].set_index("k").s, df[(df.o == "PE") & (df.s > 0)].set_index("k").s


def forward(df, t, e):
    ce, pe = sides(df)
    if ce.empty or pe.empty:
        return None
    F, _ = _implied_forward(ce, pe, ob.years(t, e))
    return F


def strikes(df, t, e, width):
    """Short strikes at T-2 → (F, σ, kc, kp). width None = the 0.05-delta picker; else N sigma on the ATM implied vol."""
    d = ob.slice_deltas(df.rename(columns={"o": "option_type", "k": "strike", "s": "settle", "v": "volume"}), t, e)
    if not d:
        return None
    F, deltas = d
    ce, pe = sides(df)
    both = set(ce.index) & set(pe.index)
    if not both:
        return None
    k0 = min(both, key=lambda k: abs(k - F))
    T = ob.years(t, e)
    iv = np.nanmean([_invert_iv(float(ce[k0]), F, k0, T, "C"), _invert_iv(float(pe[k0]), F, k0, T, "P")])
    if not np.isfinite(iv) or iv <= 0:
        return None
    m = iv * math.sqrt(T)
    if width is None:
        k = ob.nearest(deltas, 0.05)
    else:
        k = {cp: min((K for _, K in deltas[cp]), key=lambda K: abs(K - F * math.exp(s * width * m))) for cp, s in (("C", 1), ("P", -1))}
    return F, m, k["C"], k["P"]


def settle_of(u, e):
    s = read_sql("SELECT MAX(underlying_price) s FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' AND trade_date = ?", params=[u, e]).s.iloc[0]
    return None if s is None or pd.isna(s) else float(s)


def one(u, e, width, S=None, hol=None):
    t2, t1 = ob.entry_day(e, hol, 2), ob.entry_day(e, hol, 1)
    c2, c1 = chain(u, t2, e), chain(u, t1, e)
    if c2.empty or c1.empty:
        return None
    S = S if S is not None else settle_of(u, e)
    st = strikes(c2, t2, e, width) if S else None
    F1 = forward(c1, t1, e) if st else None
    if not st or not F1:
        return None
    F2, m2, kc, kp = st
    ce2, pe2 = sides(c2)
    ce1, pe1 = sides(c1)
    if kc not in ce2.index or kp not in pe2.index or kc not in ce1.index or kp not in pe1.index:
        return None
    both = set(ce1.index) & set(pe1.index)
    if not both:
        return None
    k0 = min(both, key=lambda k: abs(k - F1))
    sg = float(ce1[k0] + pe1[k0]) / (0.8 * F1)
    if sg <= 0:
        return None
    lot = ob.lot_size(u, t2, e)
    units = lot * LOTS
    cost = sum(ob.leg_cost(float(p), "sell", lot, ob.SLIP, t2) for p in (ce2[kc], pe2[kp]))
    credit = float(ce2[kc] + pe2[kp]) - cost
    zc, zp = math.log(kc / F1) / sg, math.log(F1 / kp) / sg
    near = "C" if zc <= zp else "P"
    K, z, px, sgn = (kc, zc, ce1, 1) if near == "C" else (kp, zp, pe1, -1)
    pay = ob.intrinsic(near, K, S)
    other = ob.intrinsic("P" if near == "C" else "C", kp if near == "C" else kc, S)
    leg = float(px[K])
    hold = credit - pay - other
    exit_ = credit - leg - ob.leg_cost(leg, "buy", lot, ob.SLIP, t1) - other
    out = [k for k in px.index if sgn * (k - K) > 0]
    if out:
        wk = min(out, key=lambda k: abs(abs(k - K) - WING * F1))
        wc = float(px[wk])
        wing = hold - wc - ob.leg_cost(wc, "buy", lot, ob.SLIP, t1) + max(sgn * (S - wk), 0)
    else:
        wing = exit_
    tail = max(sgn * (F1 * math.exp(sgn * TAIL_K * sg) - K), 0) * units
    return dict(u=u, e=e, t2=t2, t1=t1, lot=lot, units=units, kc=kc, kp=kp, F2=F2, m2=m2, F1=F1, sg=sg, z=z, tail=tail, S=S,
                itm=pay > 0, breach=pay + other > 0, hold=hold * units, exit=exit_ * units, wing=wing * units, credit=credit * units,
                move=abs(math.log(S / F2)) / m2, move1=abs(math.log(S / F1)) / sg)


def book(u, width, hol):
    ex = read_sql("SELECT DISTINCT expiry_date e FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' AND expiry_date >= '2019-01-01' "
                  "AND expiry_date <= (SELECT MAX(trade_date) FROM fno_bhav WHERE symbol = ?) ORDER BY 1", params=[u, u]).e   # as pre-registered; older rows exist
    rows = [one(u, e, width, hol=hol) for e in ex]
    return pd.DataFrame([r for r in rows if r])


def applied(h, rule):
    if rule == "hold":
        return h.hold.to_numpy(), np.zeros(len(h), bool)
    act, cond = rule.split(" ")
    fire = (h["tail"] > BUDGET) if cond.startswith("tail") else h.z < float(cond[2:])
    return np.where(fire, h[act], h.hold), fire.to_numpy()


def line(h, rule):
    p, f = applied(h, rule)
    yrs = max((pd.Timestamp(h.e.max()) - pd.Timestamp(h.e.min())).days / 365.25, 0.5)
    return dict(rule=rule, n=len(h), fired=int(f.sum()), ok=float((~h.itm[f]).mean()) if f.any() else None, yearly=p.sum() / yrs, mean=p.mean(),
                p5=np.percentile(p, 5), worst=p.min(), over2L=int((p < -BUDGET).sum()))


def show(h, label):
    t = pd.DataFrame([line(h, r) for r in ("hold",) + RULES]).set_index("rule")
    with pd.option_context("display.width", 200, "display.float_format", lambda v: f"{v:,.2f}" if abs(v) <= 1 else f"{v:,.0f}"):
        print(f"\n--- {label}\n{t.to_string()}")
    return t


def bar(t):
    hw, hy = t.loc["hold", "worst"], t.loc["hold", "yearly"]
    res = {}
    for r in RULES:
        w, y = t.loc[r, "worst"], t.loc[r, "yearly"]
        worst_ok = (w >= 0.5 * hw) if hw <= -50_000 else (w >= hw)
        res[r] = bool(worst_ok and y >= 0.7 * hy)
    return res


def part_a(width, hol):
    name = "2.5 sigma" if width else "0.05 delta"
    n, s = book("NIFTY", width, hol), book("SENSEX", width, hol)
    print(f"\n========== PART A, {name} ==========")
    sel = n[n.e < "2024-01-01"]
    ts, tu, tx = show(sel, "NIFTY selection, before 2024"), show(n[n.e >= "2024-01-01"], "NIFTY unseen, 2024 on"), show(s, "SENSEX unseen")
    cut = [r for r in RULES if ts.loc[r, "worst"] >= 0.5 * ts.loc["hold", "worst"]]
    pick = max(cut, key=lambda r: ts.loc[r, "yearly"]) if cut else None
    bu, bx = bar(tu), bar(tx)
    print(f"selection pick: {pick}\npass NIFTY unseen: {bu}\npass SENSEX unseen: {bx}\nPASS BOTH: {[r for r in RULES if bu[r] and bx[r]]}; pick passes: {bool(pick and bu[pick] and bx[pick])}")
    for lab, h in (("NIFTY", n), ("SENSEX", s)):
        print(f"\ncalibration {lab}: nearer strike, z bucket: n, finished ITM, normal says")
        for a, b in ((-9, .5), (.5, 1), (1, 1.5), (1.5, 2), (2, 3), (3, 99)):
            x = h[(h.z >= a) & (h.z < b)]
            if len(x):
                print(f"  {a:>4} to {b:<3} n={len(x):3d}  {x.itm.mean():6.1%}  {np.mean([1 - N.cdf(v) for v in x.z]):6.1%}")
        print(f"  T-1 to settle in σ: over 1.65 {np.mean(h.move1 > 1.65):.1%} (normal 9.9%), over 2.5 {np.mean(h.move1 > 2.5):.1%} (normal 1.2%), over 3 {np.mean(h.move1 > 3):.1%} (normal 0.3%)")
        print(f"  breach, either side: {h.breach.mean():.1%} of {len(h)} weeks")
    r = one("NIFTY", "2026-11-03", width, S=23810.85, hol=hol)
    if r:
        print(f"\n2026-11-03, reported close 23,810.85, UNVERIFIED, in no pass test: strikes {r['kp']:.0f}/{r['kc']:.0f}, F1 {r['F1']:,.0f}, sigma {r['sg']*100:.2f}%, z {r['z']:.2f}, "
              f"tail Rs {r['tail']:,.0f}, move {r['move1']:.2f} sigma, hold {r['hold']:,.0f}, exit {r['exit']:,.0f}, wing {r['wing']:,.0f}")
    return n, s


def caps(as_of, sids, bs, fund, adj):
    q = ",".join("?" * len(sids))
    close = read_sql(f"SELECT p.sid, p.close AS close_price FROM stock_prices p JOIN (SELECT sid, MAX(date) d FROM stock_prices WHERE sid IN ({q}) "
                     f"AND date <= ? AND close > 0 GROUP BY sid) l ON l.sid = p.sid AND l.d = p.date", params=[*sids, as_of])
    return market_caps(bs[bs.end_date <= as_of], fund[fund.period_end <= as_of], adj, close, as_of).sort_values("mcap_cr", ascending=False)


def reaction_dates(hol):
    """{sid: sorted reaction sessions} from BSE Result filings (timestamped) and earnings_calendar (treated as after hours)."""
    bse = read_sql("SELECT sid, dt_tm FROM bse_announcements WHERE sid IS NOT NULL AND category = 'Result' AND subcategory LIKE '%Result%'")
    cal = read_sql("SELECT sid, date FROM earnings_calendar WHERE sid IS NOT NULL AND purpose LIKE '%Financial Result%'")
    from datetime import date, timedelta

    def nxt(d):
        d += timedelta(days=1)
        while not ob.is_session(d, hol):
            d += timedelta(days=1)
        return d
    out = {}
    for sid, ts in zip(bse.sid, bse.dt_tm):
        t = pd.Timestamp(ts)
        d = t.date()
        d = d if ob.is_session(d, hol) and t.strftime("%H:%M") < "15:30" else nxt(d)
        out.setdefault(sid, set()).add(d.isoformat())
    for sid, ds in zip(cal.sid, cal.date):
        out.setdefault(sid, set()).add(nxt(date.fromisoformat(ds)).isoformat())
    return out


def perm(a, b, n=10_000, seed=7):
    """One-sided: mean(a) > mean(b)."""
    if len(a) == 0 or len(b) == 0:
        return None
    rng, pool, obs, hits = random.Random(seed), list(a) + list(b), np.mean(a) - np.mean(b), 0
    for _ in range(n):
        rng.shuffle(pool)
        hits += (np.mean(pool[:len(a)]) - np.mean(pool[len(a):])) >= obs
    return (hits + 1) / (n + 1)


def part_b(n, s, hol):
    print("\n========== PART B, 2.5 sigma ==========")
    sids = read_sql("SELECT sid FROM stocks WHERE market_cap_cr > 0 ORDER BY market_cap_cr DESC LIMIT 80").sid.tolist()
    q = ",".join("?" * len(sids))
    bs = read_sql(f"SELECT sid, end_date, shares_outstanding, total_equity FROM annual_balance_sheet WHERE sid IN ({q})", params=sids)
    fund = read_sql(f"SELECT sid, period_end, line_item, value FROM fundamentals_screener WHERE period_type = 'annual' AND sid IN ({q}) "
                    f"AND line_item IN ({','.join('?' * len(SHARE_ITEMS))})", params=[*sids, *SHARE_ITEMS])
    adj = read_sql(f"SELECT sid, ex_date, factor, inds FROM corporate_adjustments WHERE sid IN ({q})", params=sids)
    react, memo = reaction_dates(hol), {}

    def ranks(t):
        key = t[:7]
        if key not in memo:
            memo[key] = caps(t, sids, bs, fund, adj).sid.tolist()
        return memo[key]

    def flags(h, a, b):
        return np.array([any(r.t2 < d <= r.e for sid in ranks(r.t2)[a:b] for d in react.get(sid, ())) for r in h.itertuples()])

    tests = {}
    for lab, h in (("NIFTY before 2024", n[n.e < "2024-01-01"]), ("NIFTY 2024 on", n[n.e >= "2024-01-01"]), ("SENSEX", s),
                   ("unseen combined", pd.concat([n[n.e >= "2024-01-01"], s]))):
        print(f"\n--- {lab}, n={len(h)}")
        for name, a, b in (("top 10", 0, 10), ("top 5", 0, 5), ("placebo 11-20", 10, 20)):
            f = flags(h, a, b)
            x, y = h[f], h[~f]
            p = perm(x.move.tolist(), y.move.tolist())
            tests[(lab, name)] = (x.move.mean() - y.move.mean() if len(x) and len(y) else None, p)
            if len(x) and len(y):
                print(f"  {name:14s} flagged {len(x):3d} / {len(h)}  move in sigma {x.move.mean():.2f} vs {y.move.mean():.2f}  p {p:.3f}  breach {x.breach.mean():5.1%} vs {y.breach.mean():5.1%}  "
                      f"mean Rs {x.hold.mean():>8,.0f} vs {y.hold.mean():>8,.0f}  worst {x.hold.min():>10,.0f} vs {y.hold.min():>10,.0f}")
    a, b = tests[("NIFTY before 2024", "top 10")], tests[("unseen combined", "top 10")]
    pa, pb = tests[("NIFTY before 2024", "placebo 11-20")], tests[("unseen combined", "placebo 11-20")]
    passed = bool(a[1] is not None and b[1] is not None and a[1] < .05 and b[1] < .05 and a[0] > pa[0] and b[0] > pb[0])
    print(f"\nPART B PASS: {passed}")
    if passed:
        for lab, h in (("NIFTY 2024 on", n[n.e >= "2024-01-01"]), ("SENSEX", s)):
            f = flags(h, 0, 10)
            print(f"skip flagged, {lab}: total {h.hold[~f].sum():,.0f} vs hold {h.hold.sum():,.0f}; worst {h.hold[~f].min():,.0f} vs {h.hold.min():,.0f}")
    print("RELI 2026-10-30 reaction session:", sorted(d for d in react.get("RELI", ()) if d >= "2026-10-01"))
    print("top 10 now:", memo and caps("2026-10-30", sids, bs, fund, adj).sid.tolist()[:10])


def main():
    hol = ob.holidays()
    n, s = part_a(2.5, hol)
    part_a(None, hol)
    part_b(n, s, hol)


if __name__ == "__main__":
    main()
