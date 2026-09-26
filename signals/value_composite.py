"""
Alpha Signal v2 — value_composite, live producer (plan 0012 C2; WS2.1b).

`value_composite` validated on the clean re-baselined panel (SMALL t=3.32) but
had no live producer. This is a computed, ZERO-WEIGHT signal (pending human
promotion review); it does NOT change `config.SIGNAL_WEIGHTS`.

40% earnings_yield + 35% book_to_price + 25% position_52w, within-cap_tier
percentile-rank composite — `within_tier_rank_composite` below IS the one
tools.reconstruct_pit's composites call: a NaN-TOLERANT weighted average of
whichever component ranks exist for a sid (renormalized over the present
components), not a strict all-or-nothing NULL. This intentionally diverges
from plan 0012 C2's STEPS gloss ("NULL if any component missing") because the
whole point of this task is comparability against the ALREADY-VALIDATED PIT
composite (clean t=3.32 SMALL) — building a stricter composite here would
silently change what "value_composite" even means relative to the backtest
evidence it's supposed to represent.

position_52w = (close - 52w_low) / (52w_high - 52w_low) over the last 252
trading days (min 60 obs) on split/bonus-adjusted closes — the same function
tools.reconstruct_pit.pit_position_52w calls.

Reads:  stock_prices + corporate_adjustments (position_52w only — earnings_yield/book_to_price are
        passed in by the caller to avoid recomputation, see `_load_signals`)
Returns: DataFrame[sid, value_composite]

Usage:
    python -m signals.value_composite     # live compute + print stats (recomputes EY/BP itself)
"""

import numpy as np
import pandas as pd

from db import read_sql
from signals._prices import load_prices

COMPONENTS = [("earnings_yield", 0.40), ("book_to_price", 0.35), ("position_52w", 0.25)]
POSITION_52W_LOOKBACK = 252
POSITION_52W_MIN_OBS = 60


def position_52w(prices):
    """(close − 52w_low) / (52w_high − 52w_low) over each sid's last 252 trading days
    (min 60 obs), on adj_close when present so a split inside the window doesn't
    stretch the range. Shared by the live path and tools/reconstruct_pit:pit_position_52w.
    Returns DataFrame[sid, position_52w] (sids without a value omitted)."""
    price_col = "adj_close" if "adj_close" in prices.columns else "close"
    rows = []
    for sid, g in prices.sort_values(["sid", "date"]).groupby("sid", sort=False):
        recent = g.tail(POSITION_52W_LOOKBACK)
        if len(recent) < POSITION_52W_MIN_OBS:
            continue
        closes = recent[price_col].to_numpy()
        last = closes[-1]
        lo, hi = closes.min(), closes.max()
        if hi <= lo or hi <= 0:
            continue
        rows.append({"sid": sid, "position_52w": round(float((last - lo) / (hi - lo)), 4)})
    return pd.DataFrame(rows, columns=["sid", "position_52w"])


def compute_position_52w(prices=None):
    """Live position_52w on split/bonus-adjusted closes (a signals._prices frame)."""
    return position_52w(load_prices() if prices is None else prices)


def within_tier_rank_composite(df, components, name):
    """NaN-tolerant within-cap_tier rank composite.

    components: list of (column_name, weight); `df` has sid, cap_tier + those columns.
    Each component is percentile-ranked within its tier; a sid's composite is the
    weighted average of whichever component ranks exist (renormalized), NaN if none.
    Returns DataFrame[sid, name]. Shared with tools/reconstruct_pit's composites.
    """
    cols = [c for c, _ in components]
    out = df[["sid", "cap_tier"] + cols].copy()
    for col in cols:
        out[f"_r_{col}"] = out.groupby("cap_tier")[col].rank(pct=True)

    weighted_score = pd.Series(0.0, index=out.index)
    weight_sum = pd.Series(0.0, index=out.index)
    for col, w in components:
        rank_col = out[f"_r_{col}"]
        has = rank_col.notna()
        weighted_score[has] += w * rank_col[has]
        weight_sum[has] += w

    out[name] = (weighted_score / weight_sum.replace(0, np.nan)).round(4)
    return out[["sid", name]]


def compute_value_composite(earnings_yield, book_to_price, cap_tier_df, position_52w=None):
    """`cap_tier_df` = DataFrame[sid, cap_tier] (the ranking universe). `earnings_yield`/
    `book_to_price` are the caller's already-computed live frames (avoid recomputation).
    `position_52w` computed inline unless passed (the screener passes its own)."""
    if position_52w is None:
        position_52w = compute_position_52w()

    df = cap_tier_df[["sid", "cap_tier"]].merge(earnings_yield, on="sid", how="left")
    df = df.merge(book_to_price, on="sid", how="left")
    df = df.merge(position_52w, on="sid", how="left")
    return within_tier_rank_composite(df, COMPONENTS, "value_composite")


if __name__ == "__main__":
    from signals.earnings_yield import compute_earnings_yield

    stocks = read_sql("SELECT sid, cap_tier FROM stocks")
    ey = compute_earnings_yield()
    from scoring.screener import _compute_book_to_price
    bp = _compute_book_to_price()
    res = compute_value_composite(ey, bp, stocks)
    s = res["value_composite"].dropna()
    print(f"value_composite — {len(s):,} stocks with a usable composite")
    if len(s):
        print(f"  mean={s.mean():.4f}  median={s.median():.4f}  "
              f"p25={s.quantile(0.25):.4f}  p75={s.quantile(0.75):.4f}")
