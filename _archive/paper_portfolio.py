"""
Alpha Signal v2 — Paper portfolio (realized-return loop)

Bridges "we publish daily picks" → "did this make money?". Reads `daily_picks`,
applies portfolio construction rules, simulates trades at next-day open,
marks-to-market daily, and persists everything (paper_positions, paper_trades,
paper_nav_history) so we can attribute realized P&L back to signals.

Pure functions wherever possible — the I/O wrapper lives in
`tools/paper_trade_backfill.py` (replay historical) and
`tools/paper_trade_daily.py` (forward, wired into PIPELINE_STEPS).

Portfolio rules (v0 — deliberately simple, will A/B against tier-weight + VIX later):
  - Top 5 per tier (LARGE/MID/SMALL) = 15 positions total
  - Equal-weight ~6.67% per name (fully invested, no cash drag)
  - Sector cap: ≤ 5 positions per sector (across the 15-stock portfolio)
  - Weekly rebalance: Friday close picks → Monday open execution
  - Costs: TRANSACTION_COSTS_BPS by tier (LARGE 30 / MID 50 / SMALL 150 bps per side)

Starting NAV: ₹10L (one-person-fund realistic).

See docs/decisions/0028-paper-portfolio-realized-return-loop.md.
"""

from datetime import date as _date, datetime, timedelta
from typing import Optional

import pandas as pd

from db import read_sql, get_db
from config import PORTFOLIO, TRANSACTION_COSTS_BPS


INITIAL_NAV = 1_000_000.0   # ₹10L
PICKS_PER_TIER = PORTFOLIO["picks_per_tier"]   # {LARGE:5, MID:5, SMALL:5}
TOTAL_PICKS = sum(PICKS_PER_TIER.values())     # 15
MAX_PER_SECTOR = PORTFOLIO["max_stocks_per_sector"]


# ─────────────────────── Portfolio construction (pure functions) ───────────────────────


def build_target_portfolio(picks_df: pd.DataFrame) -> pd.DataFrame:
    """Given a single date's `daily_picks`, return the target portfolio.

    Steps:
      1. Pick top 5 by rank within each cap_tier.
      2. Apply sector cap: if any sector has >MAX_PER_SECTOR, swap the
         lowest-rank one(s) for the next-eligible same-tier candidate.
      3. Assign equal weights (1 / TOTAL_PICKS each).

    Returns a DataFrame with columns:
      [sid, cap_tier, sector, rank, final_score, target_weight_pct]
    """
    # Filter to picks with required fields
    df = picks_df[picks_df["cap_tier"].isin(PICKS_PER_TIER.keys())].copy()
    df = df.dropna(subset=["sid", "cap_tier", "rank", "final_score"])
    df["rank"] = df["rank"].astype(int)

    # Step 1: top-N per tier
    chosen = []
    for tier, n in PICKS_PER_TIER.items():
        tier_df = df[df["cap_tier"] == tier].sort_values("rank")
        chosen.append(tier_df.head(n))
    portfolio = pd.concat(chosen).reset_index(drop=True)

    # Step 2: enforce sector cap (across whole portfolio, not per-tier)
    if MAX_PER_SECTOR and "sector" in portfolio.columns:
        portfolio = _enforce_sector_cap(portfolio, df)

    # Step 3: equal weights
    n_actual = len(portfolio)
    if n_actual == 0:
        return portfolio
    portfolio["target_weight_pct"] = 100.0 / n_actual

    return portfolio[["sid", "cap_tier", "sector", "rank", "final_score",
                      "target_weight_pct"]].reset_index(drop=True)


def _enforce_sector_cap(portfolio: pd.DataFrame, full_picks: pd.DataFrame) -> pd.DataFrame:
    """If any sector exceeds MAX_PER_SECTOR, drop the lowest-ranked over-cap
    names and replace with the next-eligible candidate from the same tier."""
    # We iterate until no sector is over cap. Bounded by len(full_picks).
    for _ in range(50):
        counts = portfolio["sector"].value_counts()
        over = counts[counts > MAX_PER_SECTOR]
        if over.empty:
            return portfolio

        offending_sector = over.index[0]
        # Find the lowest-ranked stock in this offending sector
        bad_rows = portfolio[portfolio["sector"] == offending_sector].sort_values("rank")
        drop_row = bad_rows.iloc[-1]
        # Replace with the next-eligible candidate from the SAME tier,
        # excluding already-picked sids and the offending sector.
        chosen_sids = set(portfolio["sid"])
        candidates = full_picks[
            (full_picks["cap_tier"] == drop_row["cap_tier"])
            & (~full_picks["sid"].isin(chosen_sids))
            & (full_picks["sector"] != offending_sector)
        ].sort_values("rank")

        if candidates.empty:
            # Can't fix — give up and accept over-cap (will surface as warning)
            return portfolio

        portfolio = portfolio[portfolio["sid"] != drop_row["sid"]]
        portfolio = pd.concat([portfolio, candidates.head(1)], ignore_index=True)

    return portfolio


# ─────────────────────── Rebalance + trade logic ───────────────────────


def is_friday(d: str) -> bool:
    return datetime.fromisoformat(d).weekday() == 4


def next_trading_day(d: str, available_dates: list[str]) -> Optional[str]:
    """Return the first date in available_dates strictly after d, or None."""
    after = [x for x in available_dates if x > d]
    return after[0] if after else None


def compute_rebalance(
    target: pd.DataFrame,
    current_positions: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compare target portfolio vs current open positions.

    Returns (to_buy, to_sell, to_hold) DataFrames.
      - to_sell: positions in current but NOT in target
      - to_buy:  positions in target but NOT in current
      - to_hold: positions in both (no action this rebalance)
    """
    current_sids = set(current_positions["sid"]) if not current_positions.empty else set()
    target_sids = set(target["sid"])

    to_sell = current_positions[current_positions["sid"].isin(current_sids - target_sids)].copy()
    to_buy = target[target["sid"].isin(target_sids - current_sids)].copy()
    to_hold = current_positions[current_positions["sid"].isin(current_sids & target_sids)].copy()

    return to_buy, to_sell, to_hold


def cost_bps_for_tier(tier: str) -> float:
    return float(TRANSACTION_COSTS_BPS.get(tier, 50))


# ─────────────────────── NAV computation ───────────────────────


def mark_to_market(positions: pd.DataFrame, date_iso: str) -> tuple[float, int]:
    """Mark all OPEN positions to close-price on `date_iso`.

    Returns (positions_mv, n_positions). If a stock has no price for that
    date, falls back to the most recent price ≤ date_iso. Missing prices
    are valued at entry_price (conservative — no carry).
    """
    if positions.empty:
        return 0.0, 0
    sids = positions["sid"].tolist()
    placeholders = ",".join("?" * len(sids))
    prices = read_sql(
        f"""
        WITH px AS (
            SELECT sid, close, date,
                   ROW_NUMBER() OVER (PARTITION BY sid ORDER BY date DESC) AS rn
            FROM stock_prices
            WHERE sid IN ({placeholders}) AND date <= ?
        )
        SELECT sid, close FROM px WHERE rn = 1
        """,
        params=sids + [date_iso],
    )
    price_map = dict(zip(prices["sid"], prices["close"]))

    mv = 0.0
    for _, p in positions.iterrows():
        px = price_map.get(p["sid"], p["entry_price"])
        mv += p["qty"] * px
    return mv, len(positions)


# ─────────────────────── State persistence ───────────────────────


def get_open_positions() -> pd.DataFrame:
    return read_sql("SELECT * FROM paper_positions WHERE status='OPEN'")


def get_latest_nav() -> Optional[float]:
    """Most recent NAV from history; None if empty."""
    df = read_sql(
        "SELECT nav FROM paper_nav_history ORDER BY nav_date DESC LIMIT 1"
    )
    return float(df.iloc[0]["nav"]) if not df.empty else None


def get_latest_cash() -> float:
    df = read_sql(
        "SELECT cash FROM paper_nav_history ORDER BY nav_date DESC LIMIT 1"
    )
    return float(df.iloc[0]["cash"]) if not df.empty else INITIAL_NAV


def write_nav(
    nav_date: str, nav: float, cash: float, n_positions: int,
    prev_nav: Optional[float], peak_nav: float,
    benchmark_nav: Optional[float] = None,
) -> None:
    daily_ret = ((nav / prev_nav) - 1) * 100 if prev_nav else None
    cumret = ((nav / INITIAL_NAV) - 1) * 100
    drawdown = ((nav / peak_nav) - 1) * 100 if peak_nav > 0 else 0.0
    bench_cumret = ((benchmark_nav / INITIAL_NAV) - 1) * 100 if benchmark_nav else None
    spread = (cumret - bench_cumret) if bench_cumret is not None else None

    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO paper_nav_history
               (nav_date, nav, cash, n_positions, daily_return_pct,
                cumulative_return_pct, drawdown_pct,
                benchmark_nav, benchmark_cumret, spread_vs_benchmark)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (nav_date, nav, cash, n_positions,
             round(daily_ret, 4) if daily_ret is not None else None,
             round(cumret, 4), round(drawdown, 4),
             benchmark_nav,
             round(bench_cumret, 4) if bench_cumret is not None else None,
             round(spread, 4) if spread is not None else None),
        )


def execute_trade(
    trade_date: str, sid: str, side: str, qty: float, price: float,
    tier: str, reason: str, rebalance_date: str,
    position_id: Optional[int] = None,
) -> tuple[int, float]:
    """Persist a trade. Returns (trade_id, net_cash_impact).

    net_cash_impact is NEGATIVE for BUY (cash leaves), POSITIVE for SELL.
    Cost is always subtracted from the side's economics.
    """
    gross = qty * price
    cost_bps = cost_bps_for_tier(tier)
    cost_amount = gross * cost_bps / 10_000.0
    if side == "BUY":
        net = gross + cost_amount      # we pay gross + cost
        cash_impact = -net
    else:  # SELL
        net = gross - cost_amount      # we receive gross - cost
        cash_impact = net

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO paper_trades
               (trade_date, sid, side, qty, price, gross_value,
                cost_bps, cost_amount, net_value, reason,
                position_id, rebalance_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (trade_date, sid, side, qty, price, gross,
             cost_bps, cost_amount, net, reason,
             position_id, rebalance_date),
        )
        return cur.lastrowid, cash_impact


def open_position(
    sid: str, cap_tier: str, sector: Optional[str],
    entry_date: str, entry_price: float,
    target_weight_pct: float, qty: float,
    rank: Optional[int], score: Optional[float],
) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO paper_positions
               (sid, cap_tier, sector, entry_date, entry_price,
                entry_weight_pct, qty, rank_at_entry, score_at_entry, status)
               VALUES (?,?,?,?,?,?,?,?,?,'OPEN')""",
            (sid, cap_tier, sector, entry_date, entry_price,
             target_weight_pct, qty, rank, score),
        )
        return cur.lastrowid


def close_position(position_id: int, exit_date: str, exit_price: float) -> None:
    with get_db() as conn:
        conn.execute(
            """UPDATE paper_positions
               SET status='CLOSED', exit_date=?, exit_price=?
               WHERE position_id=?""",
            (exit_date, exit_price, position_id),
        )


# ─────────────────────── Resetting (for backfill) ───────────────────────


def reset_paper_state() -> None:
    """Wipe all paper_* tables. Used by backfill before replaying."""
    with get_db() as conn:
        conn.execute("DELETE FROM paper_trades")
        conn.execute("DELETE FROM paper_positions")
        conn.execute("DELETE FROM paper_nav_history")
        # Reset autoincrement counters
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('paper_trades','paper_positions')")
