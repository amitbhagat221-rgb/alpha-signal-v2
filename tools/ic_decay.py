"""
Alpha Signal v2 — IC term-structure / decay diagnostic  (READ-ONLY).

Answers "is the single-horizon (20d) t-stat the right lens?" — it isn't for
every factor. Short-term-reversal / microstructure / event factors peak in
days-weeks then decay or flip; value / quality / forensic factors build over
months. Judging all of them at one horizon conflates "wrong horizon" with
"no alpha" (Qian-Hua-Sorensen IC decay; Grinold-Kahn IR = IC·√breadth).

For each (signal, cap_tier) this computes Spearman IC vs forward return at a
GRID of horizons {5, 20, 63, 126, 252} trading days, aggregates each with the
same Newey-West correction used by backtest_pit (scaled up for the longer
fwd-return overlap at each horizon), and reports:
  - the IC term structure (mean IC + t at each horizon)
  - the NATURAL HORIZON = horizon of peak |mean IC|
  - a FAST / MEDIUM / SLOW bucket (≤20d / 21–63d / >63d)
  - a sign-flip flag (reversal across horizons)

This changes NOTHING in the model — no weights, no promotion. It is the
evidence you look at before deciding whether to evaluate/weight factors at
their own horizon. Honest limit: longer horizons need more non-overlapping
history; the v1 archive (2023→2026) carries the long end, but n_periods
shrinks as the horizon grows — read the long end with the CIs in mind.

Outputs (no DB schema change):
  output/ic_decay_report.txt   — human-readable term-structure table
  data/ic_decay.json           — machine-readable {signal,tier,horizon,...}

Usage:
    python -m tools.ic_decay                 # all signals × all tiers
    python -m tools.ic_decay --signal roe    # one signal
    python -m tools.ic_decay --min-periods 6 # stricter eligibility for the peak
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, get_backtest_cadence
from tools.backtest_pit import (
    SIGNAL_COLUMN_MAP,
    _compute_ic,
    _aggregate,
    _nw_lag_for,
)

HORIZONS = [5, 20, 63, 126, 252]  # trading days ≈ 1w / 1mo / 3mo / 6mo / 1yr
# Trading days between consecutive eval dates, by cadence — used to size the
# Newey-West lag for the fwd-return overlap at each horizon.
_GAP_TRADING_DAYS = {"weekly": 5, "monthly": 21}


def _price_series():
    """sid -> date-indexed close Series (sorted, NaN-free). Built once so each
    (sid, eval_date, horizon) forward return is a positional lookup."""
    df = read_sql("SELECT sid, date, close FROM stock_prices WHERE close IS NOT NULL")
    if df.empty:
        raise RuntimeError("stock_prices empty — cannot compute forward returns")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["sid", "date"])
    return {sid: g.set_index("date")["close"] for sid, g in df.groupby("sid")}


def _fwd_panel(panel, price_series):
    """Long frame [snapshot_date, sid, fwd_5 … fwd_252] for the (date, sid)
    pairs present in `panel`. fwd_H = close H trading days after the first
    trading day on/after snapshot_date (matches pit_fwd_return_20d's
    anchor_idx + H), NaN where the horizon hasn't matured."""
    pairs = panel[["snapshot_date", "sid"]].drop_duplicates()
    rows = []
    for snapshot_date, sid in pairs.itertuples(index=False):
        s = price_series.get(sid)
        if s is None or s.empty:
            continue
        pos = int(s.index.searchsorted(pd.Timestamp(snapshot_date), side="left"))
        if pos >= len(s):
            continue
        p0 = float(s.iloc[pos])
        if not (p0 > 0):
            continue
        rec = {"snapshot_date": snapshot_date, "sid": sid}
        for h in HORIZONS:
            tgt = pos + h
            if tgt < len(s):
                p1 = float(s.iloc[tgt])
                if p1 > 0:
                    rec[f"fwd_{h}"] = p1 / p0 - 1.0
        rows.append(rec)
    return pd.DataFrame(rows)


def _horizon_lag(signal, cadence, horizon):
    """Newey-West lag = max(the signal's registered lag, the fwd-return overlap
    at THIS horizon). Longer horizons overlap more consecutive eval windows."""
    gap = _GAP_TRADING_DAYS.get(cadence, 21)
    overlap = max(0, round(horizon / gap) - 1)
    return max(_nw_lag_for(signal, cadence), overlap)


def _classify(by_h, min_periods):
    """Pick the natural horizon (peak |mean IC| among horizons with enough
    periods) and bucket it. Returns (bucket, peak_horizon, sign_flip)."""
    cand = {h: r for h, r in by_h.items()
            if r and r.get("mean_ic") is not None and r["n_periods"] >= min_periods}
    if not cand:
        return "INSUFFICIENT", None, False
    peak = max(cand, key=lambda h: abs(cand[h]["mean_ic"]))
    bucket = "FAST" if peak <= 20 else ("MEDIUM" if peak <= 63 else "SLOW")
    signs = {np.sign(r["mean_ic"]) for r in cand.values() if r["mean_ic"]}
    return bucket, peak, len(signs) > 1


def compute(only_signal=None, min_periods=5):
    print("Loading PIT panels + price history…")
    v1_df = read_sql("SELECT * FROM daily_snapshots_pit_v1")
    v2_df = read_sql("SELECT * FROM daily_snapshots_pit")
    print(f"  v1: {len(v1_df):,} rows / {v1_df['snapshot_date'].nunique()} dates · "
          f"v2: {len(v2_df):,} rows / {v2_df['snapshot_date'].nunique()} dates")
    price_series = _price_series()
    px_dates = pd.concat([s.index.to_series() for s in price_series.values()])
    print(f"  stock_prices spans {px_dates.min().date()} → {px_dates.max().date()} "
          f"across {len(price_series):,} sids")

    # Attach the multi-horizon forward returns to each panel.
    for name, df in (("v1", v1_df), ("v2", v2_df)):
        if df.empty:
            continue
        fwd = _fwd_panel(df, price_series)
        df.drop(columns=[c for c in df.columns if c.startswith("fwd_")
                         and c != "fwd_return_20d"], errors="ignore", inplace=True)
        merged = df.merge(fwd, on=["snapshot_date", "sid"], how="left")
        if name == "v1":
            v1_df = merged
        else:
            v2_df = merged

    # Sanity: recomputed fwd_20 should track the stored fwd_return_20d closely.
    if "fwd_20" in v1_df.columns and "fwd_return_20d" in v1_df.columns:
        chk = v1_df[["fwd_20", "fwd_return_20d"]].dropna()
        if len(chk) > 50:
            corr = chk["fwd_20"].corr(chk["fwd_return_20d"])
            print(f"  sanity: recomputed fwd_20 vs stored fwd_return_20d ρ={corr:.3f} "
                  f"(n={len(chk):,})")

    v2_dates_all = pd.to_datetime(v2_df["snapshot_date"]).dt.date.unique() if not v2_df.empty else []
    weekly_dates = {d.isoformat() for d in v2_dates_all if pd.Timestamp(d).weekday() == 4}

    targets = [(s, c) for s, c in SIGNAL_COLUMN_MAP.items() if s != "_response"]
    if only_signal:
        targets = [(s, c) for s, c in targets if s == only_signal]
        if not targets:
            print(f"No signal '{only_signal}' in registry")
            return []

    results = []  # one dict per (signal, tier, horizon)
    summary = []  # one dict per (signal, tier) with natural-horizon classification

    for signal, (v1_col, v2_col) in targets:
        cadence = get_backtest_cadence(signal)
        # Source pick mirrors backtest_pit: monthly prefers the v1 archive
        # (it carries the long horizons), weekly uses the live v2 panel.
        sources = [("v2_recompute", v2_df, v2_col)]
        if cadence == "monthly":
            sources.insert(0, ("v1_archive", v1_df, v1_col))

        for src_name, src_df, signal_col in sources:
            if signal_col is None or signal_col not in src_df.columns:
                continue
            if src_df[signal_col].notna().sum() == 0:
                continue
            if cadence == "weekly" and src_name == "v2_recompute":
                df_use = src_df[src_df["snapshot_date"].isin(weekly_dates)]
            elif cadence == "monthly" and src_name == "v2_recompute" and weekly_dates:
                df_use = src_df[~src_df["snapshot_date"].isin(weekly_dates)]
            else:
                df_use = src_df
            if df_use.empty:
                continue

            for tier in ["LARGE", "MID", "SMALL"]:
                tier_df = df_use[df_use["cap_tier"] == tier]
                if tier_df.empty:
                    continue
                by_h = {}
                for h in HORIZONS:
                    fwd_col = f"fwd_{h}"
                    if fwd_col not in tier_df.columns or tier_df[fwd_col].notna().sum() == 0:
                        by_h[h] = None
                        continue
                    ic_rows = _compute_ic(tier_df, signal_col, fwd_col)
                    res = _aggregate(ic_rows, signal, tier, src_name,
                                     cadence=cadence, nw_lag=_horizon_lag(signal, cadence, h))
                    by_h[h] = res
                    if res:
                        results.append({**res, "horizon_days": h, "source": src_name})
                bucket, peak, flip = _classify(by_h, min_periods)
                if bucket != "INSUFFICIENT" or any(by_h.values()):
                    summary.append({
                        "signal": signal, "cap_tier": tier, "source": src_name,
                        "cadence": cadence, "natural_horizon": peak,
                        "bucket": bucket, "sign_flip": flip,
                        "ic_by_h": {h: (round(by_h[h]["mean_ic"], 4) if by_h[h] and by_h[h]["mean_ic"] is not None else None)
                                    for h in HORIZONS},
                        "t_by_h": {h: (by_h[h]["t_stat"] if by_h[h] else None) for h in HORIZONS},
                        "n_by_h": {h: (by_h[h]["n_periods"] if by_h[h] else 0) for h in HORIZONS},
                    })
            # one source is enough per signal once it produced data
            if any(s["signal"] == signal for s in summary):
                break

    return summary, results


def _fmt_report(summary):
    lines = []
    lines.append("IC TERM STRUCTURE — mean Spearman IC by forward horizon (trading days)")
    lines.append("natural horizon = peak |IC|.  ⚠ = sign flips across horizons (reversal).")
    lines.append("")
    hdr = f"{'signal':28} {'tier':6}" + "".join(f"{str(h)+'d':>10}" for h in HORIZONS) + \
          f"{'peak':>7} {'bucket':>8}"
    for bucket in ("FAST", "MEDIUM", "SLOW", "INSUFFICIENT"):
        rows = [s for s in summary if s["bucket"] == bucket]
        if not rows:
            continue
        lines.append(f"\n── {bucket} ({len(rows)}) ──")
        lines.append(hdr)
        rows.sort(key=lambda s: (s["signal"], s["cap_tier"]))
        for s in rows:
            ic_cells = ""
            for h in HORIZONS:
                ic = s["ic_by_h"][h]
                n = s["n_by_h"][h]
                cell = "—" if ic is None or n < 3 else f"{ic:+.3f}"
                ic_cells += f"{cell:>10}"
            flag = " ⚠" if s["sign_flip"] else ""
            peak = f"{s['natural_horizon']}d" if s["natural_horizon"] else "—"
            lines.append(f"{s['signal'][:28]:28} {s['cap_tier']:6}{ic_cells}"
                         f"{peak:>7} {s['bucket']:>8}{flag}")
    return "\n".join(lines)


_BUCKET_COLOR = {"FAST": "#e74c3c", "MEDIUM": "#4d8eff", "SLOW": "#2ecc71"}


def _plot(summary, live_keys):
    """IC term-structure curves: one panel per cap_tier, one line per factor,
    coloured by bucket. Wired-into-production factors are drawn bold + labelled
    so you can SEE whether a live factor is being judged at its peak horizon.
    Saves output/ic_decay_curves.png. Returns the path or None if matplotlib
    isn't available."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"⚠ matplotlib unavailable — skipping graphs ({e})")
        return None

    tiers = ["LARGE", "MID", "SMALL"]
    x = list(range(len(HORIZONS)))
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.5), sharey=True)
    fig.patch.set_facecolor("#0f1115")

    for ax, tier in zip(axes, tiers):
        ax.set_facecolor("#0f1115")
        ax.axhline(0, color="#555", lw=0.8, zorder=1)
        rows = [s for s in summary if s["cap_tier"] == tier and s["bucket"] != "INSUFFICIENT"]
        for s in rows:
            ys = [s["ic_by_h"][h] if (s["ic_by_h"][h] is not None and s["n_by_h"][h] >= 3)
                  else np.nan for h in HORIZONS]
            if np.all(np.isnan(ys)):
                continue
            is_live = (s["signal"] in live_keys)
            color = _BUCKET_COLOR.get(s["bucket"], "#888")
            ax.plot(x, ys, color=color, marker="o", ms=3,
                    lw=2.4 if is_live else 0.8,
                    alpha=0.95 if is_live else 0.30, zorder=3 if is_live else 2)
            if is_live:
                # label at the peak horizon
                pk = HORIZONS.index(s["natural_horizon"]) if s["natural_horizon"] else int(np.nanargmax(np.abs(ys)))
                ax.annotate(s["signal"][:16], (x[pk], ys[pk]), fontsize=6.5,
                            color="#e8e8e8", xytext=(2, 3), textcoords="offset points")
        # Clip the y-axis: a few artifacts (e.g. pt_upside, survivorship-
        # inflated at 252d) reach |IC|>0.5 and would squash every other curve.
        ax.set_ylim(-0.20, 0.20)
        ax.set_title(tier, color="#e8e8e8", fontsize=12)
        ax.set_xticks(x)
        ax.set_xticklabels([f"{h}d" for h in HORIZONS], color="#aaa", fontsize=9)
        ax.tick_params(colors="#aaa")
        for sp in ax.spines.values():
            sp.set_color("#333")
        ax.grid(True, color="#1c1f26", lw=0.6)
    axes[0].set_ylabel("mean Spearman IC", color="#aaa")
    from matplotlib.lines import Line2D
    legend = [Line2D([0], [0], color=c, lw=2.4, label=b) for b, c in _BUCKET_COLOR.items()]
    legend.append(Line2D([0], [0], color="#888", lw=2.4, label="bold = live (wired)"))
    axes[2].legend(handles=legend, facecolor="#16181d", edgecolor="#333",
                   labelcolor="#e8e8e8", fontsize=8, loc="upper right")
    fig.suptitle("IC term structure by forward horizon — bold = production-wired factor",
                 color="#e8e8e8", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out_png = PROJECT_ROOT / "output" / "ic_decay_curves.png"
    fig.savefig(out_png, dpi=130, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_png


def _live_keys():
    """Signal ids currently carrying production weight (config.SIGNAL_WEIGHTS*)."""
    try:
        import config
        keys = set()
        for attr in ("SIGNAL_WEIGHTS",):
            w = getattr(config, attr, {})
            for tier_w in w.values():
                if isinstance(tier_w, dict):
                    keys.update(tier_w.keys())
        return keys
    except Exception:
        return set()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signal", help="single signal (default: all)")
    ap.add_argument("--min-periods", type=int, default=5,
                    help="min non-overlapping periods for a horizon to be the peak")
    ap.add_argument("--plot-only", action="store_true",
                    help="skip the 3-min recompute; redraw graphs from data/ic_decay.json")
    args = ap.parse_args()

    if args.plot_only:
        summary = json.loads((PROJECT_ROOT / "data" / "ic_decay.json").read_text())["summary"]
        # JSON keys are strings; normalise the by-horizon dicts back to int keys
        for s in summary:
            for k in ("ic_by_h", "t_by_h", "n_by_h"):
                s[k] = {int(h): v for h, v in s[k].items()}
        png = _plot(summary, _live_keys())
        print(f"→ {png.relative_to(PROJECT_ROOT)}" if png else "no graph")
        return

    summary, results = compute(only_signal=args.signal, min_periods=args.min_periods)
    if not summary:
        print("No IC computed.")
        return

    report = _fmt_report(summary)
    print("\n" + report)

    out_txt = PROJECT_ROOT / "output" / "ic_decay_report.txt"
    out_txt.parent.mkdir(parents=True, exist_ok=True)
    out_txt.write_text(report + "\n")
    out_json = PROJECT_ROOT / "data" / "ic_decay.json"
    out_json.write_text(json.dumps({"summary": summary, "rows": results}, indent=2))
    png = _plot(summary, _live_keys())
    arts = [out_txt, out_json] + ([png] if png else [])
    print(f"\n→ " + " · ".join(str(a.relative_to(PROJECT_ROOT)) for a in arts))

    # Headline counts
    n_fast = sum(1 for s in summary if s["bucket"] == "FAST")
    n_med = sum(1 for s in summary if s["bucket"] == "MEDIUM")
    n_slow = sum(1 for s in summary if s["bucket"] == "SLOW")
    n_flip = sum(1 for s in summary if s["sign_flip"])
    print(f"\n{len(summary)} (signal,tier) classified · "
          f"FAST {n_fast} · MEDIUM {n_med} · SLOW {n_slow} · {n_flip} sign-flippers")


if __name__ == "__main__":
    main()
