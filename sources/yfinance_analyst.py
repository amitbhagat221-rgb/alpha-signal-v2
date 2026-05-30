"""
Alpha Signal v2 — Yahoo Finance Analyst Consensus

Replaces Tickertape's broken `forecastsHistory.price` feed (which mixed real
year-end snapshots with daily lastPrice contamination — see HANDOFF
2026-05-22). Two distinct writes:

  1. Daily (default): refresh `analyst_consensus` (latest aggregate per sid).
     Drives the cockpit "current PT" card. Idempotent.

  2. Monthly (--snapshot): append to `analyst_consensus_snapshots`. One row
     per stock per (snapshot_date, source). Drives backtest + pt_revision_*
     signals over proper windows.

PTs are episodic — sell-side analysts publish ~quarterly. Daily history was
phantom precision; monthly captures real material revisions while filtering
day-to-day noise.

Coverage (validated 2026-05-22 on top-50-per-tier):
    LARGE: 98%, MID: 92%, SMALL: 4%

Fields available per stock:
    targetMeanPrice         — consensus PT (mean)
    targetMedianPrice       — median (more robust to outliers)
    targetHighPrice / Low   — analyst dispersion
    numberOfAnalystOpinions — n analysts contributing
    recommendationKey       — strong_buy / buy / hold / sell / strong_sell / none
    recommendationMean      — 1=strong buy, 5=strong sell

Usage:
    python -m sources.yfinance_analyst                  # daily refresh
    python -m sources.yfinance_analyst --snapshot       # ALSO write to monthly history
    python -m sources.yfinance_analyst --ticker HALC    # smoke test one
    python -m sources.yfinance_analyst --limit 20       # smoke test
    python -m sources.yfinance_analyst --tier LARGE
"""

import argparse
import json
import sys
import time
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, upsert_df

DELAY = 0.3       # Yahoo accepts ~60 req/min; 300ms = safe
SOURCE = "yfinance"


def _first_business_day(d=None):
    """The snapshot anchor — 1st business day of the current month."""
    d = d or _date.today()
    first = d.replace(day=1)
    while first.weekday() >= 5:    # skip Sat / Sun
        first += timedelta(days=1)
    return first.isoformat()


def _fetch_one(ticker, sid_for_gate=None):
    """Return dict of analyst fields, or None if no coverage.

    Adds rating-mix counts (`n_strong_buy` ... `n_strong_sell`) from
    `.recommendations` DataFrame's most recent period — used for the
    cockpit's rating-distribution bar.

    Plan 0007 Phase 2: passes the response `info` dict through the Identity
    Gate. yfinance's `info["symbol"]` must equal what we queried; mismatches
    (rare but possible on rebrands or delisted ticker recycling) route to
    analyst_consensus_quarantine and return None to the caller.
    """
    import yfinance as yf
    try:
        tk = yf.Ticker(f"{ticker}.NS")
        info = tk.info
    except Exception:
        return None
    if not info:
        return None

    # Identity gate
    if sid_for_gate is not None:
        try:
            from validators.identity_check import verify_identity, quarantine_row, record_verdict
            v = verify_identity(sid_for_gate, info, source="yfinance",
                                expected_name=ticker)
            if v.status == "WRONG_ENTITY":
                quarantine_row(
                    source_table="analyst_consensus",
                    row={"sid": sid_for_gate, "has_analyst_data": 1,
                         "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                    sid=sid_for_gate, datum_class="analyst_pt", verdict=v,
                )
                return None
            elif v.status == "PASS":
                record_verdict(
                    sid=sid_for_gate, source_table="analyst_consensus",
                    source_key=f'{{"sid":"{sid_for_gate}"}}',
                    datum_class="analyst_pt", verdict=v,
                )
        except Exception as e:
            import sys
            print(f"  ⚠ yfinance identity_check failed for {sid_for_gate}: {e}", file=sys.stderr)

    tgt_mean = info.get("targetMeanPrice")
    if tgt_mean is None:
        return None
    rec_mix = {}
    rating_mix_history = None
    try:
        recs = tk.recommendations
        if recs is not None and len(recs) > 0:
            # Most-recent row (period '0m')
            row = recs.iloc[0]
            for col in ("strongBuy", "buy", "hold", "sell", "strongSell"):
                v = row.get(col)
                if v is not None and not pd.isna(v):
                    rec_mix[col] = int(v)
            # Serialize full 4-period history for trend rendering. Compact JSON
            # array: [[period, sb, b, h, s, ss], ...] in chronological order
            # (oldest first) so client can render left-to-right.
            # Period is '0m', '-1m', '-2m', '-3m' — parse the integer for sort.
            def _period_int(p):
                try:
                    return int(str(p).rstrip("m"))
                except (ValueError, TypeError):
                    return 0
            recs_sorted = recs.assign(_p=recs["period"].map(_period_int)).sort_values("_p")
            history = []
            for _, r in recs_sorted.iterrows():
                period = r.get("period")
                if period is None:
                    continue
                history.append([
                    str(period),
                    int(r["strongBuy"]) if not pd.isna(r.get("strongBuy")) else 0,
                    int(r["buy"])       if not pd.isna(r.get("buy"))       else 0,
                    int(r["hold"])      if not pd.isna(r.get("hold"))      else 0,
                    int(r["sell"])      if not pd.isna(r.get("sell"))      else 0,
                    int(r["strongSell"]) if not pd.isna(r.get("strongSell")) else 0,
                ])
            if history:
                rating_mix_history = json.dumps(history, separators=(",", ":"))
    except Exception:
        pass

    # Next earnings date (analysts revise PTs within ~10d of earnings → freshness proxy)
    next_earnings_date = None
    try:
        ets = info.get("earningsTimestamp")
        if ets:
            next_earnings_date = datetime.fromtimestamp(int(ets), tz=timezone.utc).date().isoformat()
    except Exception:
        pass

    return {
        "target_mean":         float(tgt_mean) if tgt_mean is not None else None,
        "target_median":       float(info["targetMedianPrice"]) if info.get("targetMedianPrice") is not None else None,
        "target_high":         float(info["targetHighPrice"])   if info.get("targetHighPrice") is not None else None,
        "target_low":          float(info["targetLowPrice"])    if info.get("targetLowPrice") is not None else None,
        # n_analysts: yfinance can return None for numberOfAnalystOpinions even
        # when per-rating counts are populated (e.g. KALYA 2026-05-24: NULL count
        # but 9 in n_buy). Fall back to sum of rating-mix counts so downstream
        # _confidence() doesn't apply low-conf shrinkage to real consensus.
        "n_analysts":          (
            int(info["numberOfAnalystOpinions"]) if info.get("numberOfAnalystOpinions")
            else (sum(v for v in (rec_mix.get("strongBuy"), rec_mix.get("buy"), rec_mix.get("hold"),
                                  rec_mix.get("sell"), rec_mix.get("strongSell")) if v) or None)
        ),
        "recommendation_key":  info.get("recommendationKey"),
        "recommendation_mean": float(info["recommendationMean"]) if info.get("recommendationMean") is not None else None,
        "n_strong_buy":        rec_mix.get("strongBuy"),
        "n_buy":               rec_mix.get("buy"),
        "n_hold":              rec_mix.get("hold"),
        "n_sell":              rec_mix.get("sell"),
        "n_strong_sell":       rec_mix.get("strongSell"),
        "next_earnings_date":  next_earnings_date,
        "rating_mix_history":  rating_mix_history,
    }


def compute(limit=None, ticker=None, tier=None, snapshot=False, dry_run=False):
    where = ["s.ticker IS NOT NULL"]
    params = []
    if ticker:
        where.append("s.ticker = ?");  params.append(ticker)
    if tier:
        where.append("s.cap_tier = ?"); params.append(tier)
    stocks = read_sql(
        f"SELECT sid, ticker, cap_tier FROM stocks s WHERE {' AND '.join(where)} ORDER BY cap_tier, ticker",
        params=params,
    )
    if limit:
        stocks = stocks.head(limit)

    mode = "daily refresh + MONTHLY SNAPSHOT" if snapshot else "daily refresh only"
    print(f"yfinance analyst pull ({mode}): {len(stocks)} stocks")
    if dry_run:
        return 0

    fetched_at  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snapshot_dt = _first_business_day()

    consensus_rows = []   # writes to analyst_consensus (current)
    snapshot_rows  = []   # writes to analyst_consensus_snapshots (monthly history)
    n_with_data    = 0
    n_no_data      = 0
    n_real_spread  = 0

    # Latest close per sid for the spread-check sanity signal
    closes = read_sql(
        "SELECT sid, close FROM stock_prices WHERE (sid, date) IN "
        "(SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)"
    )
    close_map = dict(zip(closes["sid"], closes["close"]))

    # Existing PT map for change detection — if new value differs from old
    # by >0.5%, we record the prior value and the change timestamp. This is
    # our own "PT revised <date>" badge since yfinance doesn't expose it.
    prior = read_sql(
        "SELECT sid, price_target, price_target_changed_at FROM analyst_consensus"
    )
    prior_pt_map     = dict(zip(prior["sid"], prior["price_target"]))
    prior_changed_at = dict(zip(prior["sid"], prior["price_target_changed_at"]))

    t_start = time.time()
    for i, (sid, t, cap_tier) in enumerate(stocks.itertuples(index=False), 1):
        data = _fetch_one(t, sid_for_gate=sid)
        if data is None:
            n_no_data += 1
        else:
            n_with_data += 1
            close = close_map.get(sid)
            if close and data["target_mean"] and abs(data["target_mean"] - close) / close > 0.02:
                n_real_spread += 1

            # Plan 0007 Phase 3 — Plausibility Gate on pt_upside.
            # CCAVENUE-class: yfinance returned +33,522% upside for a thin-
            # coverage SMALL cap (2026-05-28). The hard cap in PLAUSIBILITY_
            # RANGES routes that row to consensus_signals_quarantine instead
            # of the live table. Existing clip at ±50/+150 in signals/
            # consensus.py (commit 0d8d8bd) stays as a backstop.
            if close and data["target_mean"] and close > 0:
                pt_upside_pct = 100 * (data["target_mean"] / close - 1)
                try:
                    from validators.plausibility import verify_plausibility, route_on_plausibility
                    pv = verify_plausibility("pt_upside_pct", value=pt_upside_pct,
                                             segment=cap_tier or "*")
                    if pv.status == "OUT_OF_RANGE_HARD":
                        # Quarantine + skip live write for this SID's analyst row
                        route_on_plausibility(
                            pv, source_table="consensus_signals",
                            row={"sid": sid, "snapshot_date": fetched_at[:10],
                                 "pt_upside": pt_upside_pct, "fetched_at": fetched_at},
                            sid=sid, datum_class="pt_upside_pct",
                        )
                        n_no_data += 1   # treat as no_data from accounting POV
                        time.sleep(DELAY)
                        continue
                    elif pv.status in ("PASS", "EXTREME"):
                        route_on_plausibility(
                            pv, source_table="consensus_signals",
                            row={"sid": sid, "snapshot_date": fetched_at[:10],
                                 "pt_upside": pt_upside_pct, "fetched_at": fetched_at},
                            sid=sid, datum_class="pt_upside_pct",
                        )
                except Exception as e:
                    import sys
                    print(f"  ⚠ plausibility gate failed for {sid}: {e}", file=sys.stderr)

            # Narrow column set so upsert_df only updates these fields,
            # leaving Tickertape-sourced forward_eps / eps_growth_pct /
            # forward_revenue / revenue_growth_pct intact (those are real).
            # PT change detection — compare new mean PT to prior fetch
            prior_pt   = prior_pt_map.get(sid)
            changed_at = prior_changed_at.get(sid)
            new_pt     = data["target_mean"]
            pt_prev_to_save = None
            if (prior_pt is not None and not pd.isna(prior_pt) and prior_pt > 0
                    and new_pt is not None
                    and abs(new_pt - prior_pt) / prior_pt > 0.005):
                # PT moved >0.5% — record prior value + update timestamp
                pt_prev_to_save = float(prior_pt)
                changed_at = fetched_at
            consensus_rows.append({
                "sid":                       sid,
                "total_analysts":            data["n_analysts"],
                "price_target":              new_pt,
                "price_target_median":       data["target_median"],
                "price_target_high":         data["target_high"],
                "price_target_low":          data["target_low"],
                "recommendation_key":        data["recommendation_key"],
                "recommendation_mean":       data["recommendation_mean"],
                "n_strong_buy":              data["n_strong_buy"],
                "n_buy":                     data["n_buy"],
                "n_hold":                    data["n_hold"],
                "n_sell":                    data["n_sell"],
                "n_strong_sell":             data["n_strong_sell"],
                "pt_source":                 SOURCE,
                "next_earnings_date":        data["next_earnings_date"],
                "rating_mix_history":        data["rating_mix_history"],
                "price_target_prev":         pt_prev_to_save if pt_prev_to_save else prior_pt_map.get(sid),
                "price_target_changed_at":   changed_at,
                "has_analyst_data":          1,
                "fetched_at":                fetched_at,
            })
            if snapshot:
                snapshot_rows.append({
                    "sid": sid,
                    "snapshot_date":       snapshot_dt,
                    "source":              SOURCE,
                    "target_mean":         data["target_mean"],
                    "target_median":       data["target_median"],
                    "target_high":         data["target_high"],
                    "target_low":          data["target_low"],
                    "n_analysts":          data["n_analysts"],
                    "recommendation_key":  data["recommendation_key"],
                    "recommendation_mean": data["recommendation_mean"],
                    "fetched_at":          fetched_at,
                })

        if i % 200 == 0:
            elapsed = time.time() - t_start
            rate = i / elapsed
            print(f"  [{i}/{len(stocks)}] coverage={n_with_data} no_data={n_no_data} "
                  f"spread={n_real_spread} | {rate:.1f}/s")
        time.sleep(DELAY)

    if consensus_rows:
        upsert_df(pd.DataFrame(consensus_rows), "analyst_consensus")
    if snapshot_rows:
        upsert_df(pd.DataFrame(snapshot_rows), "analyst_consensus_snapshots")

    pct_have    = 100 * n_with_data / len(stocks) if len(stocks) else 0
    pct_spread  = 100 * n_real_spread / n_with_data if n_with_data else 0
    elapsed     = time.time() - t_start
    print()
    print(f"Done in {elapsed:.0f}s. {n_with_data}/{len(stocks)} have analyst data ({pct_have:.1f}%).")
    print(f"  {n_real_spread} ({pct_spread:.1f}%) have PT >2% from current close (non-degenerate).")
    if snapshot:
        print(f"  Wrote {len(snapshot_rows)} rows to analyst_consensus_snapshots @ {snapshot_dt}")
    return n_with_data


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", help="One ticker (smoke test)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--tier", choices=["LARGE", "MID", "SMALL"])
    parser.add_argument("--snapshot", action="store_true",
                        help="Also append a row to analyst_consensus_snapshots "
                             "(monthly history). Set this on the monthly cron only.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(limit=args.limit, ticker=args.ticker, tier=args.tier,
            snapshot=args.snapshot, dry_run=args.dry_run)
