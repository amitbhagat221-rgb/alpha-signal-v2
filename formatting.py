"""
Alpha Signal v2 — number formatting shared by the cockpit templates (as Jinja
filters, registered in cockpit/_shared.make_templates) and the email digest.

Missing values (None / NaN / non-numeric) render as DASH. Anything float()
accepts is formatted — including the cockpit's SilentUndefined, which floats to
0.0 exactly as the old `"%.1f"|format(x)` template code did.
"""

import math

DASH = "—"


def _num(x):
    """float(x), or None for None / NaN / ±Inf / non-numeric."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def signed(x, decimals=2):
    """+1.23 / -0.40 — explicit sign (`"%+.2f"|format(x)`)."""
    v = _num(x)
    return DASH if v is None else f"{v:+.{decimals}f}"


def pct(x, decimals=1, signed=False, scale=1):
    """12.3% (`"%.1f%%"|format(x)`); signed=True → +12.3%; scale=100 for a
    fraction (0.123 → 12.3%)."""
    v = _num(x)
    if v is None:
        return DASH
    out = f"{v * scale:{'+' if signed else ''}.{decimals}f}"
    if float(out) == 0:                      # rounds to zero: "0%", never "-0%"
        out = out.lstrip("+-")
    return out + "%"


def inr(x, decimals=0, group=True):
    """₹43,155 (thousands grouped by default; group=False → ₹43155 for JSON/CSV)."""
    v = _num(x)
    if v is None:
        return DASH
    body = f"{abs(v):{',' if group else ''}.{decimals}f}"
    return f"-₹{body}" if v < 0 and float(body.replace(",", "")) != 0 else f"₹{body}"


def crore(cr):
    """A ₹-crore amount: ₹1.2L Cr at/above a lakh crore, else ₹12,345 Cr."""
    v = _num(cr)
    if v is None:
        return DASH
    if v >= 100_000:
        return f"₹{v / 100_000:.1f}L Cr"
    return f"₹{v:,.0f} Cr"


def tone(x, pos="score-green", neg="score-red", zero=""):
    """Sign → CSS class (or colour): `pos` above zero, `neg` below, `zero` at
    zero; "" when missing. Pass zero=neg for the binary green/red form."""
    v = _num(x)
    if v is None:
        return ""
    return pos if v > 0 else neg if v < 0 else zero


def short_date(x):
    """'2026-10-05' (or an ISO timestamp) -> '5 Oct'; missing / not a date -> DASH."""
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return DASH
    return f"{d.day} {d:%b}"


def long_date(x):
    """'2026-10-05' -> '5 Oct 2026'; missing / not a date -> DASH."""
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return DASH
    return f"{d.day} {d:%b %Y}"


def month_text(ym):
    """'2026-09' (or a full ISO date) -> 'Sep 2026'; not a month -> the text as given."""
    import datetime as _dt
    try:
        return f"{_dt.date.fromisoformat(str(ym)[:7] + '-01'):%b %Y}"
    except ValueError:
        return DASH if ym in (None, "") else str(ym)


def count(x):
    """A whole-number count with thousands grouped ("3,254"); a float count (rows_affected
    arrives as 3254.0) is rounded, never printed with a decimal. Missing -> "—"."""
    v = _num(x)
    return DASH if v is None else f"{round(v):,}"


FILTERS = {"count": count, "signed": signed, "pct": pct, "inr": inr, "crore": crore, "tone": tone, "short_date": short_date, "long_date": long_date, "month_text": month_text}


# VIX regime → colour name. One map for cockpit, change feed and email; the
# regime vocabulary itself is config.REGIMES (CALM/NORMAL/CAUTION/CRISIS).
REGIME_COLORS = {"CALM": "green", "NORMAL": "blue", "CAUTION": "amber", "CRISIS": "red"}


# Cap tier → (label, CSS colour). One map for every cockpit/ops page and the email;
# the tier list itself is config.TIERS (views.tiers / views.pickable_tiers). A tier
# missing here (a new config.TIERS entry) still renders: "<Name> Cap", muted.
TIER_STYLES = {
    "LARGE": ("Large Cap", "var(--blue)"),
    "MID":   ("Mid Cap",   "var(--accent)"),
    "SMALL": ("Small Cap", "var(--green)"),
    "MICRO": ("Micro",     "#e74c3c"),
}


def tier_label(tier):
    return TIER_STYLES.get(tier, (f"{str(tier).title()} Cap", ""))[0]


def tier_color(tier):
    return TIER_STYLES.get(tier, ("", "var(--text-muted)"))[1]


def tier_word(tier):
    """The tier as one word for prose and pills on the main cockpit: Large / Mid / Small / Micro."""
    return str(tier).title() if tier else DASH


def rank_text(rank, n=None, tier=None):
    """The one way a rank reads: "#1 of 100 in Large" ("#1 of 100" without a tier, "#1" without a
    count). `n` is the number ranked in the tier (views.tier_sizes). Missing rank -> "not ranked"."""
    r = _num(rank)
    if r is None:
        return "not ranked"
    out = f"#{int(r)}"
    if _num(n):
        out += f" of {int(_num(n)):,}"
    if tier:
        out += f" in {tier_word(tier)}"
    return out


FILTERS.update({"tier_label": tier_label, "tier_color": tier_color, "tier_word": tier_word, "rank_text": rank_text})


_MACRO_WORDS = {"iip": "IIP", "nondurables": "non-durables", "usdinr": "USD/INR", "vix": "VIX",
                "us": "US", "10y": "10Y", "nifty": "Nifty", "psubank": "PSU bank", "fmcg": "FMCG",
                "it": "IT", "gdp": "GDP", "cpi": "CPI", "wpi": "WPI"}


def macro_label(ident):
    """A macro series id in plain words: iip_consumer_nondurables -> "IIP consumer
    non-durables", core_cement -> "Cement", usdinr -> "USD/INR". Text that is
    already words (has a space or capital) is returned unchanged."""
    s = "" if ident is None else str(ident)
    if not s or " " in s or s != s.lower():
        return s
    parts = s.split("_")
    if parts[0] == "core" and len(parts) > 1:
        parts = parts[1:]
    out = " ".join(_MACRO_WORDS.get(p, p) for p in parts)
    return out if out[:1].isupper() else out[:1].upper() + out[1:]


def macro_text(text):
    """A stored driver summary ("iip_consumer_durables +11.1% · usdinr 88.2") with each
    leading series id put in words; sentences are returned unchanged."""
    def one(part):
        head, _, rest = part.partition(" ")
        if head and head == head.lower() and ("_" in head or head in ("usdinr", "vix")):
            return (macro_label(head) + " " + rest).strip()
        return part
    return " · ".join(one(p) for p in str(text or "").split(" · "))


FILTERS["macro_label"] = macro_label
FILTERS["macro_text"] = macro_text
