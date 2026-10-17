"""Sectors › Industry Detail: the explainer pane's computed parts (plan 0016 P5).

The written story (the `explainer` block of sector_metadata, tools/sector_explainer.py)
has no numbers in its prose. Everything numeric on the page comes from here:
  - geometry for the inline SVGs (P&L waterfall, cycle clock, five-forces radar,
    lead-time dots), so the template only loops
  - industry financial medians for the cheat sheet (fundamentals_screener, annual)
  - dial readings (macro_history latest value for a mapped indicator)
  - regulatory events filtered to the industry by the story's keywords

Plain functions, no state (ADR 0004). Medians are cached per industry per day.
"""

import math
import re
from datetime import date
from functools import lru_cache
from statistics import median

import db

# ── SVG geometry ──────────────────────────────────────────────────────────────

WATERFALL_W, WATERFALL_H = 440, 230
_WF_BASE, _WF_SCALE = 190, 1.7          # y of ₹0, px per rupee
_WF_X0, _WF_STEP, _WF_BW = 48, 56, 44    # first bar x, bar pitch, bar width


def waterfall(walk_side, input_label, opex_label):
    """Bars for one ₹100 → profit walk. walk_side = {name, input, opex, dep_int}."""
    inp = float(walk_side.get("input", 0))
    opx = float(walk_side.get("opex", 0))
    di = float(walk_side.get("dep_int", 0))
    gross = 100 - inp
    ebitda = gross - opx
    profit = ebitda - di

    def y(v):
        return round(_WF_BASE - v * _WF_SCALE, 1)

    bars = []
    x = _WF_X0

    def add(label, top, bottom, kind, value_label, tip):
        nonlocal x
        bars.append({"x": x, "y": y(top), "h": round((top - bottom) * _WF_SCALE, 1), "w": _WF_BW,
                     "kind": kind, "label": label, "value": value_label, "tip": tip,
                     "cx": x + _WF_BW // 2, "label_y": y(top) - 6})
        x += _WF_STEP

    add("Sales", 100, 0, "keep", "100", "Sales ₹100")
    add("Input", 100, gross, "cut", f"−{inp:.0f}", f"{input_label} ₹{inp:.0f}")
    add("Gross", gross, 0, "keep", f"{gross:.0f}", f"Gross margin ₹{gross:.0f}")
    add("Opex", gross, ebitda, "cut", f"−{opx:.0f}", f"{opex_label} ₹{opx:.0f}")
    add("EBITDA", ebitda, 0, "keep", f"{ebitda:.0f}", f"EBITDA ₹{ebitda:.0f}")
    add("Dep+int", ebitda, profit, "cut", f"−{di:.0f}", f"Depreciation and interest ₹{di:.0f}")
    add("Profit", profit, 0, "keep", f"{profit:.0f}", f"Profit ₹{profit:.0f}")
    return {"name": walk_side.get("name", ""), "bars": bars, "w": WATERFALL_W, "h": WATERFALL_H,
            "gross": gross, "ebitda": ebitda, "profit": profit,
            "input_label": input_label, "opex_label": opex_label}


# clock positions → hand angle (degrees, 0 = 12 o'clock, clockwise) and phase ring
_CLOCK_ANGLE = {"bottom": -45, "early_up": -15, "boom": 45, "peak": 135, "early_down": 165, "bust": 225}


def clock(position):
    """Hand endpoint for the cycle clock (centre 150,150, radius 120)."""
    ang = math.radians(_CLOCK_ANGLE.get(position, -15))
    r = 98
    return {"x2": round(150 + r * math.sin(ang), 1), "y2": round(150 - r * math.cos(ang), 1)}


_FORCES = [("rivalry", "Rivalry"), ("supplier", "Supplier power"), ("buyer", "Buyer power"),
           ("entrants", "New entrants"), ("substitutes", "Substitutes")]


def radar(scores):
    """Pentagon polygons for the five forces. scores = {force: [a, b]} on 0..3.
    Centre (170,150), radius 110; axis 0 at the top, clockwise."""
    cx, cy, R = 170, 150, 110

    def pt(i, v):
        ang = math.radians(-90 + i * 72)
        rr = R * max(0.0, min(3.0, float(v))) / 3.0
        return round(cx + rr * math.cos(ang), 1), round(cy + rr * math.sin(ang), 1)

    def ring(frac):
        return " ".join(f"{round(cx + R * frac * math.cos(math.radians(-90 + i * 72)), 1)},"
                        f"{round(cy + R * frac * math.sin(math.radians(-90 + i * 72)), 1)}" for i in range(5))

    axes, a_pts, b_pts, labels = [], [], [], []
    for i, (key, label) in enumerate(_FORCES):
        a, b = (scores.get(key) or [0, 0])[:2]
        a_pts.append(pt(i, a))
        b_pts.append(pt(i, b))
        ex, ey = pt(i, 3)
        axes.append((ex, ey))
        anchor = "middle" if i in (0, 2, 3) else ("start" if i == 1 else "end")
        lx = ex + (8 if i == 1 else -8 if i == 4 else 0)
        ly = ey + (-10 if i == 0 else 19 if i in (2, 3) else 4)
        labels.append({"x": round(lx, 1), "y": round(ly, 1), "anchor": anchor, "text": label})
    return {"rings": [ring(1.0), ring(2 / 3), ring(1 / 3)], "axes": axes,
            "a": " ".join(f"{x},{y}" for x, y in a_pts), "a_pts": a_pts,
            "b": " ".join(f"{x},{y}" for x, y in b_pts), "b_pts": b_pts,
            "labels": labels}


def lead_dots(indicators):
    """Dot positions for the lead-time chart: x by lead_quarters (0..3), one row each."""
    xs = {0: 60, 1: 280, 2: 500, 3: 700}
    out = []
    for i, it in enumerate(sorted(indicators, key=lambda d: (int(d.get("lead_quarters", 0)), d.get("name", "")))):
        q = max(0, min(3, int(it.get("lead_quarters", 0))))
        out.append({"x": xs[q], "y": 40 + i * 28, "name": it.get("name", ""), "channel": it.get("channel", ""), "q": q})
    return {"dots": out, "h": 40 + len(out) * 28 + 40}


# ── industry financial medians (cheat sheet) ──────────────────────────────────

_LINES = ["Sales", "Raw Material Cost", "Operating Profit", "Net profit", "Inventory", "Inventories",
          "Receivables", "Trade receivables", "Gross Block", "Depreciation", "Net Block",
          "Capital Work in Progress", "Profit before tax", "Interest", "Equity Share Capital",
          "Reserves", "Borrowings", "Power and Fuel", "Employee Cost"]

METRIC_LABELS = {
    "gross_margin_pct": ("Gross margin", "%"), "ebitda_margin_pct": ("EBITDA margin", "%"),
    "net_margin_pct": ("Net margin", "%"), "inventory_days": ("Inventory days", "d"),
    "receivable_days": ("Receivable days", "d"), "capex_to_dep": ("Capex ÷ depreciation", "×"),
    "asset_turn": ("Asset turn", "×"), "cwip_to_gross_block": ("CWIP ÷ gross block", "%"),
    "roce_pct": ("ROCE", "%"), "debt_to_ebitda": ("Debt ÷ EBITDA", "×"),
    "power_fuel_pct": ("Power & fuel ÷ sales", "%"), "employee_cost_pct": ("Employee cost ÷ sales", "%"),
    "interest_to_ebitda_pct": ("Interest ÷ EBITDA", "%"), "sales_growth_pct": ("Sales growth", "%"),
}


def _per_stock_metrics(latest, prior):
    """Metrics for one stock from its latest and prior annual line items."""
    g = latest.get
    sales = g("Sales")
    m = {}

    def safe_div(a, b, scale=1.0):
        if a is None or b in (None, 0):
            return None
        return a / b * scale

    if sales and sales > 0:
        rm = g("Raw Material Cost")
        if rm is not None:
            m["gross_margin_pct"] = (sales - rm) / sales * 100
        m["ebitda_margin_pct"] = safe_div(g("Operating Profit"), sales, 100)
        m["net_margin_pct"] = safe_div(g("Net profit"), sales, 100)
        inv = g("Inventories") if g("Inventories") is not None else g("Inventory")
        m["inventory_days"] = safe_div(inv, sales, 365)
        rec = g("Receivables") if g("Receivables") is not None else g("Trade receivables")
        m["receivable_days"] = safe_div(rec, sales, 365)
        m["asset_turn"] = safe_div(sales, g("Net Block"))
        m["power_fuel_pct"] = safe_div(g("Power and Fuel"), sales, 100)
        m["employee_cost_pct"] = safe_div(g("Employee Cost"), sales, 100)
        ps = prior.get("Sales")
        if ps and ps > 0:
            m["sales_growth_pct"] = (sales / ps - 1) * 100
    dep = g("Depreciation")
    gb, pgb = g("Gross Block"), prior.get("Gross Block")
    if dep and dep > 0 and gb is not None and pgb is not None:
        m["capex_to_dep"] = (gb - pgb) / dep
    m["cwip_to_gross_block"] = safe_div(g("Capital Work in Progress"), gb, 100)
    cap = sum(v for v in (g("Equity Share Capital"), g("Reserves"), g("Borrowings")) if v is not None)
    if cap > 0 and g("Profit before tax") is not None:
        m["roce_pct"] = ((g("Profit before tax") or 0) + (g("Interest") or 0)) / cap * 100
    m["debt_to_ebitda"] = safe_div(g("Borrowings"), g("Operating Profit"))
    m["interest_to_ebitda_pct"] = safe_div(g("Interest"), g("Operating Profit"), 100)
    return {k: v for k, v in m.items() if v is not None and math.isfinite(v)}


@lru_cache(maxsize=256)
def _medians_cached(industry, day):
    sids = [r["sid"] for r in db.rows("SELECT sid FROM stocks WHERE industry = ?", [industry])]
    if not sids:
        return {}
    q = ",".join("?" * len(sids))
    rows = db.rows(
        f"SELECT sid, period_end, line_item, value FROM fundamentals_screener "
        f"WHERE period_type = 'annual' AND sid IN ({q}) AND line_item IN ({','.join('?' * len(_LINES))}) "
        f"AND period_end >= date('now', '-30 months')",
        sids + _LINES)
    by = {}
    for r in rows:
        by.setdefault(r["sid"], {}).setdefault(r["period_end"], {})[r["line_item"]] = r["value"]
    per_metric = {}
    as_of = None
    for sid, periods in by.items():
        ends = sorted(periods)
        latest = periods[ends[-1]]
        if ends[-1] < str(date.today().year - 2):
            continue
        prior = periods[ends[-2]] if len(ends) > 1 else {}
        as_of = max(as_of or "", ends[-1])
        for k, v in _per_stock_metrics(latest, prior).items():
            # drop absurd values so one broken filing cannot drag a median
            if abs(v) > 1e4:
                continue
            per_metric.setdefault(k, []).append(v)
    out = {}
    for k, vals in per_metric.items():
        if len(vals) >= 5:
            out[k] = {"median": median(vals), "n": len(vals)}
    if out:
        out["_as_of"] = as_of
        out["_stocks"] = len(by)
    return out


def industry_financial_medians(industry):
    """{metric_key: {median, n}, _as_of, _stocks} from the latest annual filings of
    the industry's stocks; a metric needs at least five stocks. {} when no data."""
    return _medians_cached(industry, date.today().isoformat())


def fmt_metric(key, value):
    label, unit = METRIC_LABELS.get(key, (key, ""))
    if value is None:
        return "—"
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "d":
        return f"{value:.0f} days"
    return f"{value:.2f}×"


# ── dial readings and industry-filtered regulatory ────────────────────────────

def dial_readings(dials):
    """Attach the latest macro_history value to each dial that names an indicator."""
    ids = [d.get("indicator_id") for d in dials if d.get("indicator_id")]
    latest = {}
    if ids:
        q = ",".join("?" * len(ids))
        for r in db.rows(
                f"SELECT indicator_id, value, date FROM ("
                f"  SELECT indicator_id, value, date, ROW_NUMBER() OVER (PARTITION BY indicator_id ORDER BY date DESC) r "
                f"  FROM macro_history WHERE indicator_id IN ({q})) WHERE r = 1", ids):
            latest[r["indicator_id"]] = r
    out = []
    for d in dials:
        d = dict(d)
        r = latest.get(d.get("indicator_id"))
        d["latest_value"] = r["value"] if r else None
        d["latest_date"] = r["date"] if r else None
        out.append(d)
    return out


def filter_regulatory(events, keywords):
    """Keep the parent sector's events whose title or reasoning mentions an industry keyword."""
    kws = [k.lower().strip() for k in (keywords or []) if k and k.strip()]
    if not kws:
        return []
    out = []
    for e in events:
        hay = f"{e.get('title') or ''} {e.get('ai_reasoning') or ''}".lower()
        if any(re.search(r"\b" + re.escape(k), hay) for k in kws):
            out.append(e)
    return out


def cheat_rows(cheat_sheet, medians):
    """The cheat-sheet rows with the industry median filled in where a metric_key maps."""
    rows = []
    for c in cheat_sheet or []:
        k = c.get("metric_key")
        m = (medians or {}).get(k) if k else None
        rows.append({**c, "today": fmt_metric(k, m["median"]) if m else None,
                     "n": m["n"] if m else None,
                     "label": METRIC_LABELS.get(k, (None, None))[0] if k else None})
    return rows


def view(explainer):
    """Everything the template needs beyond the story itself."""
    if not explainer:
        return None
    walk = (explainer.get("pnl") or {}).get("walk") or {}
    il = walk.get("input_label") or "Input cost"
    ol = walk.get("opex_label") or "Running costs"
    return {
        "waterfall_a": waterfall(walk.get("a") or {}, il, ol),
        "waterfall_b": waterfall(walk.get("b") or {}, il, ol),
        "clock": clock((explainer.get("clock") or {}).get("position")),
        "radar": radar((explainer.get("forces") or {}).get("scores") or {}),
        "lead": lead_dots(explainer.get("lead_indicators") or []),
        "forces": _FORCES,
    }
