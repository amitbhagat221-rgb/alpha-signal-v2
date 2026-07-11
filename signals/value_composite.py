"""
Alpha Signal v2 — value_composite, live producer (plan 0012 C2; WS2.1b).

`value_composite` validated on the clean re-baselined panel (SMALL t=3.32) but
had no live producer. This is a computed, ZERO-WEIGHT signal (pending human
promotion review); it does NOT change `config.SIGNAL_WEIGHTS`.

40% earnings_yield + 35% book_to_price + 25% position_52w, within-cap_tier
percentile-rank composite — mirrors `tools.reconstruct_pit.pit_value_composite`
/ `_within_tier_rank_composite` EXACTLY: a NaN-TOLERANT weighted average of
whichever component ranks exist for a sid (renormalized over the present
components), not a strict all-or-nothing NULL. This intentionally diverges
from plan 0012 C2's STEPS gloss ("NULL if any component missing") because the
whole point of this task is comparability against the ALREADY-VALIDATED PIT
composite (clean t=3.32 SMALL) — building a stricter composite here would
silently change what "value_composite" even means relative to the backtest
evidence it's supposed to represent.

position_52w = (close - 52w_low) / (52w_high - 52w_low) over the last 252
trading days (min 60 obs), mirroring `tools.reconstruct_pit.pit_position_52w`.

Reads:  stock_prices (position_52w only — earnings_yield/book_to_price are
        passed in by the caller to avoid recomputation, see `_load_signals`)
Returns: DataFrame[sid, value_composite]

Usage:
    python -m signals.value_composite     # live compute + print stats (recomputes EY/BP itself)
"""

import numpy as np
import pandas as pd

from db import read_sql

COMPONENTS = [("earnings_yield", 0.40), ("book_to_price", 0.35), ("position_52w", 0.25)]
POSITION_52W_LOOKBACK = 252
POSITION_52W_MIN_OBS = 60


def compute_position_52w():
    px = read_sql(
        "SELECT sid, date, close FROM stock_prices WHERE close > 0 ORDER BY sid, date"
    )
    rows = []
    for sid, g in px.groupby("sid", sort=False):
        recent = g.tail(POSITION_52W_LOOKBACK)
        if len(recent) < POSITION_52W_MIN_OBS:
            continue
        closes = recent["close"].to_numpy()
        last = closes[-1]
        lo, hi = closes.min(), closes.max()
        if hi <= lo or hi <= 0:
            continue
        rows.append({"sid": sid, "position_52w": round(float((last - lo) / (hi - lo)), 4)})
    return pd.DataFrame(rows, columns=["sid", "position_52w"]) if rows else pd.DataFrame(columns=["sid", "position_52w"])


def compute_value_composite(earnings_yield, book_to_price, cap_tier_df, position_52w=None):
    """`cap_tier_df` = DataFrame[sid, cap_tier] (the ranking universe). `earnings_yield`/
    `book_to_price` are the caller's already-computed live frames (avoid recomputation).
    `position_52w` computed inline unless injected (testing)."""
    if position_52w is None:
        position_52w = compute_position_52w()

    df = cap_tier_df[["sid", "cap_tier"]].merge(earnings_yield, on="sid", how="left")
    df = df.merge(book_to_price, on="sid", how="left")
    df = df.merge(position_52w, on="sid", how="left")

    for col, _ in COMPONENTS:
        df[f"_r_{col}"] = df.groupby("cap_tier")[col].rank(pct=True)

    weighted_score = pd.Series(0.0, index=df.index)
    weight_sum = pd.Series(0.0, index=df.index)
    for col, w in COMPONENTS:
        rank_col = df[f"_r_{col}"]
        has = rank_col.notna()
        weighted_score[has] += w * rank_col[has]
        weight_sum[has] += w

    df["value_composite"] = (weighted_score / weight_sum.replace(0, np.nan)).round(4)
    return df[["sid", "value_composite"]]


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
