"""
Alpha Signal Cockpit - page data for /model (Health, Evidence, Library, Rules).

One question: is the model working, and should I change anything? Everything is
derived: the factor list and weights from the registry (`factors.FACTORS`), the
evidence from the same rows /system reads (`cockpit_ops.api.get_validation_evidence`),
decay from the FACTOR_DECAY check's own source (`tools.factor_decay`), tier verdicts
from the same outcomes as /book (`cockpit.book.tier_verdicts`).

  get_model()         the whole page: health, evidence, library, rules
  factor_count_text() "11 factors / 16 weights", the one wording everywhere
  do_this_week()      the (at most 3) lines on top of Health (pure, tested)
"""

import re

import config
import factors
import views
from cockpit import api, book, playbooks
from formatting import tier_word
from cockpit._shared import _persisted_cache, _ttl_cache

PROMOTION_BAR = 2.5          # |t| a factor needs to be considered (promotion review)
MULTIPLE_TEST_BAR = 4.2      # |t| after allowing for ~270 hypotheses tried (Bonferroni; the 2.5 bar alone is not enough)
LOW_DATA_PCT = 80            # a pick with less of its weight backed by real values than this is flagged
MAX_ACTIONS = 3
# Tiers with no factor that has out-of-sample skill: the list lives in views (one source for every page).
NO_OOS_SKILL = views.NO_OOS_SKILL

BENCH_WORDS = {
    "PROPOSED": "Proposed: waiting on a human decision to wire it.",
    "LIBRARY": "Benched: computed and tested, below the bar to rank stocks.",
    "BLOCKED": "Blocked: the data or method has a problem.",
    "SUPERSEDED": "Replaced by another factor.",
    "CONTROL": "Control: a structural covariate, not a signal.",
}
STATE_ORDER = {"WIRED": 0, "PROPOSED": 1, "LIBRARY": 2, "BLOCKED": 3, "SUPERSEDED": 4, "CONTROL": 5}


def short_label(signal_id):
    f = factors.FACTORS.get(signal_id) or {}
    return (f.get("label") or signal_id).split(" (")[0]


def factor_count_text():
    """'11 factors / 16 weights': factors wired in any tier / (factor, tier) weights."""
    n_weights = sum(1 for tw in factors.weights().values() for _ in tw)
    return f"{len(factors.wired_signal_ids())} factors / {n_weights} weights"


def bar_width(weight, tier_weights):
    """|w| as a share of the tier's total |w| (percent), for the bar. A negative
    weight is a bar of its own size, drawn red, never a negative width."""
    total = sum(abs(w) for w in tier_weights) or 1
    return round(100 * abs(weight) / total, 1)


def t_verdict(t, weight):
    """(key, words) for a long-run t against the two bars, in the wired direction."""
    if t is None:
        return "none", "no test yet"
    if (t > 0) != (weight > 0):
        return "wrong", f"sign is opposite to the weight"
    a = abs(t)
    if a >= MULTIPLE_TEST_BAR:
        return "proven", f"clears the {MULTIPLE_TEST_BAR:g} bar"
    if a >= PROMOTION_BAR:
        return "passes", f"above {PROMOTION_BAR:g}, below {MULTIPLE_TEST_BAR:g}"
    return "weak", f"below {PROMOTION_BAR:g}"


@_persisted_cache(3600, name="model_decay")
def _decay():
    """{(signal id, tier): decay row} from the FACTOR_DECAY check's own analysis (about 10 s)."""
    from tools.factor_decay import analyze
    return {(r["signal_id"], r["tier"]): r for r in analyze()}


def _streak():
    """Days in a row the FACTOR_DECAY check has fired, counting today (0 if it has not)."""
    try:
        from checks import history
        return history.read()["streaks"].get("FACTOR_DECAY", 0)
    except Exception:  # noqa: BLE001 - a missing history must not take the page down
        return 0


def evidence_rows():
    """One row per wired (factor, tier), grouped by tier, biggest weight first."""
    from cockpit_ops.api import get_validation_evidence
    ev = get_validation_evidence()
    decay = _decay()
    rows = []
    wts = factors.weights()
    for tier in [t for t in views.display_tiers() if t in wts] + [t for t in wts if t not in views.display_tiers()]:
        tw = wts[tier]
        tier_ws = list(tw.values())
        for key, w in sorted(tw.items(), key=lambda kv: -abs(kv[1])):
            sid = factors.signal_for(key, tier)
            e = next((r for r in ev["rows"] if r["signal"] == sid and r["cap_tier"] == tier), None) or {}
            d = decay.get((sid, tier)) or {}
            vkey, vwords = t_verdict(e.get("t_stat"), w)
            rows.append({
                "tier": tier, "signal": sid, "label": short_label(sid), "weight": w,
                "bar_pct": bar_width(w, tier_ws), "inverted": w < 0,
                "t": e.get("t_stat"), "n_periods": e.get("n_periods"), "verdict": vkey, "verdict_words": vwords,
                "ic_recent": d.get("ic_recent"), "ic_all": d.get("ic_all"),
                "decayed": bool(d.get("decayed")), "gap_se": d.get("gap_se"),
                "thin": bool(e.get("thin")) or bool(d.get("note")),
            })
    return rows, ev["meta"]


def tier_evidence(rows):
    """{tier: {n_weights, best_t, n_proven, n_pass}}: how strong the wired factors are, per tier."""
    out = {}
    for r in rows:
        o = out.setdefault(r["tier"], {"n_weights": 0, "best_t": 0.0, "n_proven": 0, "n_pass": 0})
        o["n_weights"] += 1
        aligned = r["t"] is not None and (r["t"] > 0) == (r["weight"] > 0)
        if aligned:
            o["best_t"] = max(o["best_t"], abs(r["t"]))
            o["n_proven"] += abs(r["t"]) >= MULTIPLE_TEST_BAR
            o["n_pass"] += abs(r["t"]) >= PROMOTION_BAR
    return out


def allocation_flag(tier, alloc, regime_name, ev):
    """The one-line warning when a tier gets capital in the regime split but no wired factor
    clears the multiple-testing bar; None when one does."""
    if ev["n_proven"]:
        return None
    msg = (f"{tier_word(tier)} gets {alloc * 100:.0f}% in a {regime_name} market but none of its factors clears the "
           f"{MULTIPLE_TEST_BAR:g} bar (best |t| {ev['best_t']:.1f})")
    bad = views.unproven_tiers()
    return msg + (f"; {bad[tier]}." if tier in bad else ".")


def low_data_picks():
    """Today's top picks whose real-value share is below LOW_DATA_PCT, and which factors are missing."""
    pick_date = api.latest_pick_date()
    top = views.picks(pick_date, per_tier="book")
    labels = api.get_factor_labels()
    low = []
    for r in top.to_dict("records"):
        d = views.pick_data(r, r["sid"], pick_date)
        if d and d["score"] < LOW_DATA_PCT:
            low.append({"ticker": r["ticker"], "tier": r["cap_tier"], "score": d["score"],
                        "missing": [labels.get(k, k) for k in d["missing"]]})
    return {"pick_date": pick_date, "n": len(top), "n_low": len(low), "low": low, "threshold": LOW_DATA_PCT}


def do_this_week(decayed, streak, coverage, tiers, max_lines=MAX_ACTIONS):
    """The lines on top of Health, at most `max_lines`, most urgent first. Each is
    {kind: review | data | decide, text, link}. decayed = evidence rows flagged decayed."""
    out = []
    for r in decayed:
        days = f", flagged {streak + 1} days running" if streak else ""
        out.append({"kind": "review", "link": "evidence",
                    "text": f"Review {r['label']} in {tier_word(r['tier'])}: its last-year IC is {r['ic_recent']:+.3f} "
                            f"against {r['ic_all']:+.3f} long-run{days}."})
    if coverage["n_low"]:
        first = coverage["low"][0]
        miss = ", ".join(first["missing"][:2]) or "some factors"
        more = f" (+{coverage['n_low'] - 1} more)" if coverage["n_low"] > 1 else ""
        out.append({"kind": "data", "link": "",
                    "text": f"{coverage['n_low']} of {coverage['n']} top picks have under {coverage['threshold']}% of their "
                            f"weight backed by real values: {first['ticker']} is missing {miss}{more}."})
    for t in tiers:
        if t["flag"]:
            out.append({"kind": "decide", "link": "rules", "text": t["flag"]})
    for t in tiers:
        if t["verdict"]["verdict"] == "lagged":
            out.append({"kind": "decide", "link": "evidence",
                        "text": f"{tier_word(t['tier'])} picks lagged their tier ({t['verdict']['spread_pp']:+.1f} percentage points "
                                f"at {t['verdict']['window']} trading days). Check its factors before adding capital."})
    return out[:max_lines]


def get_health(rows):
    regime = views.regime() or {}
    ev = tier_evidence(rows)
    outcomes = book.get_track_record()
    verdicts = {v["tier"]: v for v in outcomes["verdicts"]}
    sb = api.get_sized_book() or {}
    tiers = []
    for tier in views.display_tiers():
        key = f"alloc_{tier.lower()}"
        alloc = regime.get(key)
        e = ev.get(tier, {"n_weights": 0, "best_t": 0.0, "n_proven": 0, "n_pass": 0})
        tiers.append({
            "tier": tier, "unproven": views.is_unproven(tier), "alloc_pct": None if alloc is None else round(alloc * 100),
            "split": {name: round(spec["alloc"][tier] * 100) for name, spec in config.REGIMES.items()},
            "book_pct": (sb.get("tier_weights") or {}).get(tier),
            "verdict": verdicts.get(tier) or {"verdict": "none", "text": f"{tier_word(tier)}: no outcomes yet.", "spread_pp": None, "window": None},
            "evidence": e,
            "flag": None if alloc is None else allocation_flag(tier, alloc, regime.get("regime", "current"), e),
        })
    coverage = low_data_picks()
    decayed = [r for r in rows if r["decayed"]]
    return {"tiers": tiers, "regime": regime.get("regime"), "coverage": coverage,
            "actions": do_this_week(decayed, _streak(), coverage, tiers),
            "outcomes_note": outcomes, "n_decayed": len(decayed)}


# ── Library ─────────────────────────────────────────────────────────────────────────

def _first_sentence(text, limit=170):
    text = " ".join((text or "").split())
    cut = text.find(". ")
    text = text[: cut + 1] if 0 < cut < limit else text
    text = text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "..."
    return text if text.endswith((".", "...")) or not text else text + "."


# Registry descriptions name tables and columns; the page says them in words.
_PLAIN_WORDS = (
    ("macro_sector_signals_pit.macro_score", "sector macro score"),
    ("macro_sector_signals_pit", "sector macro signals"),
    ("fno_bhav settle prices", "F&O settlement prices"),
    ("fno_bhav", "F&O settlement prices"),
    ("forecast_history.price snapshots", "analyst forecast history"),
    ("forecast_history", "analyst forecast history"),
)


def plain_note(text):
    """A registry note in words: table names swapped for what they hold, a module reference in
    brackets dropped, any other snake_case identifier spaced out."""
    for raw, words in _PLAIN_WORDS:
        text = text.replace(raw, words)
    text = re.sub(r"\s*\((?:signals|pit)\.[a-z_]+\)", "", text)
    return re.sub(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", lambda m: m.group(0).replace("_", " "), text)


def bench_note(state, best_t, data_status="READY"):
    """The Library sentence for a benched factor, worded from its own evidence. A PROPOSED factor is
    only 'strong' when its best tested t clears the promotion bar; one whose data is dropped or
    contaminated is Blocked whatever its t says."""
    if state == "PROPOSED":
        if data_status in ("DROPPED", "BLOCKED"):
            return "Blocked: data contaminated, cannot be promoted."
        if best_t is None:
            return "Proposed: no test result yet."
        if abs(best_t) >= PROMOTION_BAR:
            return (f"Proposed: best t {best_t:+.2f}, clears the {PROMOTION_BAR:g} bar; waiting on a human "
                    f"decision to wire it.")
        return f"Proposed: best t {best_t:+.2f}, below the {PROMOTION_BAR:g} bar."
    return BENCH_WORDS.get(state, state)


def library_rows(ev_rows):
    """Every registry factor: wired first, then candidates, benched, the rest; the note is
    built from the registry (description, computed state, weights), never typed by hand."""
    best = {}
    for r in ev_rows:
        if r["thin"] or r["t_stat"] is None:
            continue
        b = best.get(r["signal"])
        if b is None or abs(r["t_stat"]) > abs(b["t"]):
            best[r["signal"]] = {"t": r["t_stat"], "tier": r["cap_tier"], "n": r["n_periods"]}
    wired = {}
    for tier, tw in factors.weights().items():
        for key, w in tw.items():
            wired.setdefault(factors.signal_for(key, tier), []).append((tier, w))
    rows = []
    for sid, f in factors.FACTORS.items():
        state = factors.status(sid)
        b = best.get(sid)
        note = [_first_sentence(f.get("description"))]
        if state == "WIRED":
            note.append("Weights: " + ", ".join(f"{tier_word(t)} {w:+.2f}" for t, w in wired[sid]) + ".")
        else:
            note.append(bench_note(state, b["t"] if b else None, f.get("status", "READY")))
        if f.get("status", "READY") not in ("READY", state):
            note.append(f"Data {f['status'].lower()}: " + _first_sentence(f.get("status_reason"), 110))
        rows.append({
            "id": sid, "label": short_label(sid), "group": f.get("group") or f.get("family"),
            "state": state, "wired_in": [t for t, _ in wired.get(sid, [])],
            "best_t": b["t"] if b else None, "best_tier": b["tier"] if b else None,
            "cadence": f.get("cadence", "monthly"), "note": plain_note(" ".join(n for n in note if n)),
        })
    rows.sort(key=lambda r: (STATE_ORDER.get(r["state"], 9), -abs(r["best_t"] or 0)))
    return rows


# ── Rules ───────────────────────────────────────────────────────────────────────────

def get_rules():
    p, hrp = config.PORTFOLIO, config.PORTFOLIO["hrp"]
    regime = views.regime() or {}
    tier_picks = {t: config.TIERS[t]["picks"] for t in views.display_tiers()}
    same = len(set(tier_picks.values())) == 1
    return {
        "regimes": [{"name": n, "vix_lo": s["vix"][0], "vix_hi": s["vix"][1],
                     "alloc": {t: round(a * 100) for t, a in s["alloc"].items()}, "active": n == regime.get("regime")}
                   for n, s in config.REGIMES.items()],
        "regime": regime.get("regime"), "vix": regime.get("vix_latest"), "vix_asof": (regime.get("updated_at") or "")[:10],
        "pick_line": (f"Top {next(iter(tier_picks.values()))} per tier ({sum(tier_picks.values())} names in all)" if same
                      else "Top picks per tier: " + ", ".join(f"{tier_word(t)} {n}" for t, n in tier_picks.items())),
        "evidence": playbooks.evidence(), "unproven": views.unproven_tiers(),
        "limits": [
            ("Stocks per sector", f"at most {p['max_stocks_per_sector']}"),
            ("One stock in the sized book", f"at most {hrp['max_stock_weight'] * 100:.0f}% of the book"),
            ("One sector in the sized book", f"at most {hrp['max_sector_weight'] * 100:.0f}% of the book"),
            ("Liquidity floor", f"traded value at least {hrp['min_adtv_inr'] / 1e7:.0f} crore rupees a day"),
            ("Trading cost used in tests", ", ".join(f"{tier_word(t)} {config.TRANSACTION_COSTS_BPS[t]} bps" for t in tier_picks
                                                  if t in config.TRANSACTION_COSTS_BPS) + " each way"),
        ],
        "band": book.band_line(),
        "limits_note": [
            f"A factor with no value for a stock counts as the middle of its tier ({config.MISSING_FACTOR_SCORE * 100:.0f} of 100), not zero.",
            f"A pick needs {config.PICK_GATE['min_eligible_coverage'] * 100:.0f}% of the factor weight that applies to it backed by real values.",
        ],
    }


@_ttl_cache(300)
def get_model():
    rows, meta = evidence_rows()
    from cockpit_ops.api import get_validation_evidence
    return {
        "counts": factor_count_text(), "health": get_health(rows),
        "evidence": rows, "evidence_meta": meta, "tier_evidence": tier_evidence(rows),
        "library": library_rows(get_validation_evidence()["rows"]), "rules": get_rules(),
        "multiple_test_bar": MULTIPLE_TEST_BAR, "promotion_bar": PROMOTION_BAR,
    }
