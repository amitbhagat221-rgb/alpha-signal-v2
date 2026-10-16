"""
Alpha Signal v2 — how much of a name the desk can hold (plan 0026 phase 1d.8, research 0008 problem 3).

One number per name: its 20-session median traded value (₹), and the largest position that is at most
`config.MB_THESIS["max_adv_share"]` (5 %) of it. The cockpit's Candidates and Held rows and the paper books'
capacity kill both read it here, so the rule has one definition.

Read-only. `read(sql, params) -> list[dict]` is the caller's reader (the cockpit's `db.rows`, or a tool's
read-only connection), so this module owns no connection.
"""
from statistics import median

from config import MB_THESIS


def _in(n):
    return ",".join("?" * n)


def adv_inr(read, sids, asof=None):
    """{sid: 20-session median traded value in ₹}. The sessions are the market's last `adv_window` trading dates
    on or before `asof` (latest when None); a session on which a stock has no row counts as 0, so a stock that
    traded 8 days in 20 shows the median of 8 trades and 12 zeros. Traded value is the exchange's figure, else
    close × volume (the same split-safe pair of same-day raw numbers as tools.lh_costs)."""
    sids = list(dict.fromkeys(sids))
    if not sids:
        return {}
    n = MB_THESIS["adv_window"]
    dates = [r["date"] for r in read(
        "SELECT DISTINCT date FROM stock_prices WHERE date <= ? ORDER BY date DESC LIMIT ?", [asof or "9999-12-31", n])]
    if not dates:
        return {}
    got = {}
    for i in range(0, len(sids), 500):
        chunk = sids[i:i + 500]
        for r in read(
                "SELECT sid, CASE WHEN traded_value > 0 THEN traded_value ELSE close * volume END AS tv "
                f"FROM stock_prices WHERE date >= ? AND date <= ? AND sid IN ({_in(len(chunk))})",
                [dates[-1], dates[0], *chunk]):
            got.setdefault(r["sid"], []).append(r["tv"] or 0.0)
    return {s: float(median(sorted(v + [0.0] * (len(dates) - len(v))))) for s, v in got.items()}


def max_position_inr(adv):
    """The largest position, ₹: max_adv_share of one day's trading. None when the ADTV is unknown."""
    return None if adv is None else adv * MB_THESIS["max_adv_share"]


def per_name_inr(max_names, book_inr=None):
    """What one name gets at full size: the book split over `max_names` (30 candidates, 10 held)."""
    return (book_inr or MB_THESIS["book_inr"]) / max_names


def capacity(read, sids, max_names, asof=None, book_inr=None):
    """{sid: {adv_inr, max_inr, per_name_inr, too_big, share}}. too_big = the per-name amount exceeds the
    max position (so the book would be more than max_adv_share of a day's trading in that name); share = the
    per-name amount as a fraction of the ADTV (None without an ADTV)."""
    per = per_name_inr(max_names, book_inr)
    out = {}
    for sid, adv in adv_inr(read, sids, asof).items():
        cap = max_position_inr(adv)
        out[sid] = {"adv_inr": adv, "max_inr": cap, "per_name_inr": per,
                    "too_big": per > cap, "share": per / adv if adv > 0 else None}
    return out


def inr_short(x):
    """₹ in the units Indian retail reads: '₹4.2 L' (lakh) below a crore, '₹1.3 Cr' above, '₹0' for zero."""
    if x is None:
        return None
    if x >= 1e7:
        return f"₹{x / 1e7:,.1f} Cr"
    if x >= 1e5:
        return f"₹{x / 1e5:,.1f} L"
    return f"₹{x:,.0f}"
