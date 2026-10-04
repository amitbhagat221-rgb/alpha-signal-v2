"""
Alpha Signal v2 — Parse corporate_actions (SPLIT, BONUS, DIVIDEND) into per-event factors
and write a unified `corporate_adjustments` table.

A factor < 1 represents the multiplier applied to PRE-event prices to make them
comparable to post-event prices:
  - SPLIT From Rs A To Rs B → factor = B/A
  - BONUS N free per M held  → factor = M/(M+N)
  - DIVIDEND Rs D, close_pre  → factor = (close_pre - D)/close_pre

Same-day events on the same sid are *multiplied* into a single combined factor
(solves the same-day SPLIT+BONUS PK collision in the older split_adjustments table).

This script is the upstream half of PIT-strict adjustment. The downstream half lives
in pit.py — it composes these per-event factors at signal-compute
time, only including events with ex_date <= snapshot_date (no forward leakage).

Run:
    python -m tools.compute_corporate_adjustments
    python -m tools.compute_corporate_adjustments --dry-run
"""
import argparse
import re
from datetime import datetime

import pandas as pd

from db import get_db, read_sql, upsert_df


# ────────────────────── Parsers ──────────────────────

_RS_NUM = r"r[se]\.?\s*(\d+(?:\.\d+)?)"  # "Rs 10", "Re 1", "Rs.5", "Re.0.50"
_NUM_RS = r"(\d+(?:\.\d+)?)\s*r[se]\.?"  # "10 Rs", "1 Re"


def parse_split_factor(subject):
    """Returns the multiplier applied to PRE-split prices (always < 1)."""
    if not subject:
        return None
    s = subject.lower()
    # "From Rs X ... To Rs/Re Y" — segment by from/to so the right number lands in each capture
    from_idx = s.find("from")
    to_idx = s.find("to", from_idx) if from_idx >= 0 else -1
    if from_idx >= 0 and to_idx > from_idx:
        from_nums = re.findall(_RS_NUM, s[from_idx:to_idx])
        to_nums = re.findall(_RS_NUM, s[to_idx:])
        if from_nums and to_nums:
            old_fv, new_fv = float(from_nums[0]), float(to_nums[0])
            if old_fv > 0 and new_fv > 0:
                return new_fv / old_fv
    # Fallback: "1:N" or "N:1" colon form
    m = re.search(r"(\d+)\s*:\s*(\d+)", s)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a == 1 and b > 1:
            return 1.0 / b
        if b == 1 and a > 1:
            return 1.0 / a
    return None


def parse_bonus_factor(subject):
    """Bonus N:M → N free per M held → factor = M/(M+N). None for a bonus of anything
    but equity shares: preference shares (NCRPS) or debentures leave the share count,
    and so the price basis, unchanged (TVSM "Bonus Ncrps 4:1" was cutting its whole
    price history to a fifth)."""
    if not subject or re.search(r"ncrps|preference|debenture|\bncd", subject.lower()):
        return None
    m = re.search(r"(\d+)\s*:\s*(\d+)", subject.lower())
    if not m:
        return None
    free, held = int(m.group(1)), int(m.group(2))
    if held <= 0:
        return None
    return held / (held + free)


DEMERGER_MIN_DROP = 0.8     # an ex-day close below this share of the previous close is the demerger, not the market


def parse_dividend_amount(subject):
    """Returns the per-share dividend amount in Rs, or None."""
    if not subject:
        return None
    s = subject.lower()
    # Try "Rs/Re X" first (most common)
    m = re.search(_RS_NUM, s)
    if m:
        return float(m.group(1))
    # Fallback "X Rs/Re"
    m = re.search(_NUM_RS, s)
    if m:
        return float(m.group(1))
    return None


# ────────────────────── Builder ──────────────────────

def _ensure_table():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS corporate_adjustments (
                sid TEXT NOT NULL,
                ex_date TEXT NOT NULL,
                factor REAL NOT NULL,         -- combined multiplier for PRE-ex_date prices (< 1)
                n_events INTEGER NOT NULL,    -- number of events composed (1 typical, 2 same-day)
                inds TEXT NOT NULL,           -- comma-joined event types: SPLIT,BONUS,DIVIDEND
                subjects TEXT,                -- concatenated raw subjects (truncated)
                fetched_at TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (sid, ex_date)
            );
        """)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    return compute(dry_run=parser.parse_args().dry_run)


def compute(dry_run=False):
    """Pipeline step `compute_corporate_adjustments` (daily, after fetch_corp_actions).
    Until 2026-09-27 this ran only by hand and froze at 2026-04-30 — 30 splits/bonuses
    (LIC, Trent, …) went unadjusted for five months."""
    _ensure_table()

    actions = read_sql(
        "SELECT sid, ex_date, CASE WHEN ind = 'OTHER' THEN 'DEMERGER' ELSE ind END AS ind, subject "
        "FROM corporate_actions "
        "WHERE (ind IN ('SPLIT','BONUS','DIVIDEND') OR (ind = 'OTHER' AND lower(subject) LIKE '%demerger%')) "
        "AND sid IS NOT NULL ORDER BY sid, ex_date, ind"
    )
    prices = read_sql("SELECT sid, date, close FROM stock_prices WHERE close > 0")
    # Close on the last trading day BEFORE each dividend's ex_date, in one as-of join.
    # (Was a full-table boolean scan per dividend: O(dividends × price rows), which
    # ran for hours once stock_prices grew — corporate_adjustments froze at 2026-04-30.)
    divs = actions.loc[actions["ind"].isin(["DIVIDEND", "DEMERGER"]), ["sid", "ex_date"]].drop_duplicates()
    divs = divs.assign(_t=pd.to_datetime(divs["ex_date"], errors="coerce")).dropna(subset=["_t"])
    px = prices.assign(_t=pd.to_datetime(prices["date"])).sort_values("_t")
    pre = pd.merge_asof(divs.sort_values("_t"), px[["sid", "_t", "close"]], on="_t", by="sid",
                        direction="backward", allow_exact_matches=False)
    close_before = {(r.sid, r.ex_date): r.close for r in pre.itertuples() if pd.notna(r.close)}
    close_on = {(r.sid, r.date): r.close for r in prices.itertuples()}

    parsed = []  # (sid, ex_date, ind, factor, subject)
    skipped = {"SPLIT": 0, "BONUS": 0, "DIVIDEND_NO_AMOUNT": 0, "DIVIDEND_NO_PRE_CLOSE": 0,
               "INVALID_FACTOR": 0}

    for _, r in actions.iterrows():
        sid = r["sid"]
        ex_date = r["ex_date"]
        ind = r["ind"]
        subj = r.get("subject") or ""
        factor = None

        if ind == "SPLIT":
            factor = parse_split_factor(subj)
            if factor is None:
                skipped["SPLIT"] += 1
        elif ind == "BONUS":
            factor = parse_bonus_factor(subj)
            if factor is None:
                skipped["BONUS"] += 1
        elif ind == "DIVIDEND":
            amount = parse_dividend_amount(subj)
            if amount is None:
                skipped["DIVIDEND_NO_AMOUNT"] += 1
                continue
            close_pre = close_before.get((sid, ex_date))
            if close_pre is None:
                skipped["DIVIDEND_NO_PRE_CLOSE"] += 1
                continue
            close_pre = float(close_pre)
            if close_pre <= 0 or amount >= close_pre:
                skipped["INVALID_FACTOR"] += 1
                continue
            factor = (close_pre - amount) / close_pre

        elif ind == "DEMERGER":
            # The parent trades ex the demerged business from ex_date: the share of value that
            # stays is that day's close over the close before (HEG 2026-09-07: 0.37). Smaller
            # moves are left alone (a demerger of a minor unit is within a normal day's range).
            before, on = close_before.get((sid, ex_date)), close_on.get((sid, ex_date))
            if before and on and on / float(before) < DEMERGER_MIN_DROP:
                factor = on / float(before)
            else:
                continue

        if factor is None or factor <= 0 or factor >= 1.0:
            skipped["INVALID_FACTOR"] += 1
            continue
        parsed.append({"sid": sid, "ex_date": ex_date, "ind": ind,
                       "factor": factor, "subject": subj[:200]})

    print(f"Parsed events: {len(parsed)}")
    print(f"Skipped: {skipped}")

    if not parsed:
        print("Nothing to write.")
        return

    df = pd.DataFrame(parsed)
    # Combine same-day events per (sid, ex_date)
    grouped = df.groupby(["sid", "ex_date"], as_index=False).agg(
        factor=("factor", "prod"),
        n_events=("ind", "count"),
        inds=("ind", lambda s: ",".join(sorted(set(s)))),
        subjects=("subject", lambda s: " || ".join(s)[:500]),
    )

    print(f"\nUnique (sid, ex_date) rows: {len(grouped)}  (after combining same-day events)")
    print(f"  SPLIT-only:         {(grouped['inds'] == 'SPLIT').sum()}")
    print(f"  BONUS-only:         {(grouped['inds'] == 'BONUS').sum()}")
    print(f"  DIVIDEND-only:      {(grouped['inds'] == 'DIVIDEND').sum()}")
    print(f"  multi-event:        {(grouped['n_events'] > 1).sum()}")
    print(f"\nFactor distribution:")
    print(grouped["factor"].describe().to_string())

    if dry_run:
        print(f"\n[dry-run] would write {len(grouped)} rows to corporate_adjustments")
        return len(grouped)

    # Wipe and rewrite (idempotent rebuild) in ONE transaction — a failed write must
    # never leave the screener with no split/bonus adjustments at all.
    with get_db() as conn:
        conn.execute("DELETE FROM corporate_adjustments")
        n = upsert_df(grouped[["sid", "ex_date", "factor", "n_events", "inds", "subjects"]],
                      "corporate_adjustments", conn=conn)
    print(f"\n→ wrote {n} rows to corporate_adjustments")
    return n


if __name__ == "__main__":
    main()
