# Research 0009 — What the Kite minute bars can feed: a pre-registered factor menu

**Status:** research complete, nothing built; extended and partly corrected by [research 0010](0010-minute-bar-uses/0010-minute-bar-uses.md) · **Written:** 2026-10-16 · **Parent:** [ADR 0072](../decisions/0072-kite-minute-bar-parquet-archive.md), checklist "Factors from the Kite minute bars"
**Method:** probe of the staged archive (1,774 stocks, read-only DuckDB), the in-house verdicts of every related factor in `factors.FACTORS`, and a literature check (sources at the end). No backtest was run, so no factor result here is ours yet.

## Headline

1. **Three products are worth more than any single factor.** A per-stock trading-cost model, a circuit / mania gate and a capacity measure. The cost model replaces the 150 bps SMALL placeholder that decides whether the SMALL books net out ([names per tier](../studies/names-per-tier-2026-10.md)).
2. **Twelve factor candidates, split fast and slow.** The strongest priors are realized skewness (fast) and the day / night split of momentum (slow). The weakest are the retests of daily proxies that already failed.
3. **Four candidates need only daily open and close, so they can be tested today.** They use the survivorship-free daily prices, which the minute archive cannot give (Kite has no delisted stocks).
4. **Expect few winners.** All six daily microstructure proxies were dropped, `max_lottery_21d` came out contrarian, low volatility failed, and LARGE has no factor with out-of-sample skill. What is new is power: about 140 monthly periods from 2015-02, against 39 for the earlier proxy tests.

## What the data actually is (probed 2026-10-16)

| Fact | Consequence |
|---|---|
| Four columns per minute: sid, ts, close (paise), volume | No high / low per minute and no trade direction; buy / sell volume must be inferred |
| First bar 09:15 IST; no pre-open auction bar | The day's open comes from `stock_prices.open` (complete since 2015, 0 missing) |
| Regular session ends at the 15:29 bar; one evening Muhurat session per year (18:00–18:59) | Drop bars after 15:30 before any summary |
| **Corrected 2026-10-16 ([research 0010](0010-minute-bar-uses/0010-minute-bar-uses.md)):** before 2026-08-03 the official close is the 15:00–15:30 VWAP for every stock. From 2026-08-03 F&O stocks close by auction: our bars stop at 15:14 for them (RELIANCE), and the auction price exists only in the daily close. Non-F&O stocks keep the VWAP close and bars to 15:29 | Closing-window candidates (S4, F4, F5) need a regime split at 2026-08-03 for F&O names; `px_last` means the last continuous bar; the auction move is a new forward-only candidate |
| Bars per day over the last year: median 370, 5th percentile 199; 16 of 1,774 stocks average under 100 | Minute-level measures are fine for most stocks; realized moments should use 5-minute returns to damp bid-ask bounce in thin names |
| Prices are split-adjusted as of the fetch day | Ratios within a day are safe; never compare minute levels with `stock_prices` without rescaling |
| Survivors only | Every minute-bar backtest is biased upward; say so in the verdict |
| Scan speed: 12 months × 1,774 stocks in 53 s on 2 threads | One full-history summary pass is minutes, not hours |

## The menu

Sign = the direction the literature expects (+ means higher value, higher future return). "Daily" in the data column means it can be built from `stock_prices` alone.

### Slow (monthly rebalance, 63–252 day horizon)

| # | Candidate | Formula | Sign | Data | Prior |
|---|---|---|---|---|---|
| S1 | `mom_intraday_12_1` | Sum of log(close / open) over months t−12 to t−2 | + | Daily | Strong. US 1926–2019: intraday-return portfolios show momentum without long-term reversal (Barardehi, Bogousslavsky, Muravyev). In-house `mom_6m` is robust, so this asks which half of the day carries it |
| S2 | `mom_overnight_12_1` | Sum of log(open / previous close) over the same window | − at long horizons | Daily | Strong in the US: overnight-return portfolios show only long-term reversal; momentum profits sit overnight (Lou, Polk, Skouras). Test S1 and S2 together as one pre-registered pair |
| S3 | `tug_of_war_3m` | Share of the last 63 days with overnight > 0 and intraday < 0 | + | Daily | Medium. US decile spread reported near 0.9 %/month gross (Akbas, Boehmer, Jiang, Koch); holds in Canada, fails in France, Germany, Italy, UK, Japan and China |
| S4 | `late_volume_share_3m` | Volume 15:00–15:30 ÷ day volume, 63-day mean | ? | Minute | Weak. Institutional and index flow concentrates at the close; a descriptor, not a known anomaly (old plan 0002 item 29) |
| S5 | `semibeta_neg_1y` | Realized beta from 5-minute returns when stock and market both fall | + | Minute + synthetic market | Medium. Negative-negative semibeta predicts higher returns (Bollerslev, Patton, Quaedvlieg 2022). Needs a market minute series: build it cap-weighted from the LARGE tier, since the archive holds no index |

### Fast (weekly rebalance, 5–21 day horizon; must clear real costs)

| # | Candidate | Formula | Sign | Data | Prior |
|---|---|---|---|---|---|
| F1 | `rskew_5m_1w` | Realized skewness of 5-minute returns over the week: √N·Σr³ / (Σr²)^1.5 | − | Minute | Strongest fast prior. Low-minus-high skew decile earned 19 bps the next week, t 3.70, not explained by FF + Carhart (Amaya, Christoffersen, Jacobs, Vasquez, US 1993–2008). Caution: our MAX lottery factor came out contrarian, so the sign may flip here |
| F2 | `signed_jump_1m` | (up semivariance − down semivariance) ÷ realized variance, 21 days | − | Minute | Medium. Good-minus-bad volatility from Bollerslev and co-authors; the published return result should be re-read before relying on it |
| F3 | `bvc_imbalance_5d` | Bulk-volume buy share: Σ V·Φ(Δp/σ) ÷ Σ V per minute, 5 days, minus 0.5 | + then − | Minute | Medium. Order imbalance predicts next-day returns, then reverses. Must be checked against `delivery_anomaly_z` (the robust in-house flow factor) before it counts as new |
| F4 | `close_pressure_5d` | (last trade at 15:29 − official close) ÷ official close, 5-day mean | − | Minute | India-specific, no direct paper. Related: mispricing factors lose at the close (Bogousslavsky 2021); early-day returns reverse in the last half-hour (Baltussen, Da, Soebhag, draft) |
| F5 | `vwap_dev_true_5d` | (official close − day VWAP) ÷ day VWAP, 5-day mean | ? | Minute | Weak. The OHLC proxy scored best |t| 0.96 SMALL and was dropped; one retest on the true VWAP, then close the file |
| F6 | `overnight_ret_1m` | Mean log(open / previous close) over 21 days | + short, − later | Daily | Medium. Overnight returns as firm-level retail sentiment; India's retail share makes it plausible |
| F7 | `rkurt_5m_1m` | Realized kurtosis of 5-minute returns, 21 days | + | Minute | Weak; same paper as F1 found it positive but not always significant. Run as a control next to F1 |

Left off the menu on purpose: realized volatility as a factor (duplicates the failed `low_vol_252d`; keep it for risk), jump share (Jiang and Yao find jumps explain the size and illiquidity effects, so it would be a size proxy), and morning-afternoon persistence (old item 32; no published support).

### Not factors, but plug-in tools

| # | Tool | What it measures | Who uses it |
|---|---|---|---|
| T1 | **Per-stock cost model** | Effective spread from minute closes (Roll / Abdi-Ranaldo style) plus impact from a true intraday Amihud or Kyle lambda (Σ\|r\| ÷ Σ value traded, 5-minute) | Replaces the flat 150 / 31 bps assumptions in every SMALL and multibagger book; also a cleaner version of `kyle_lambda`, our strongest microstructure factor (LARGE t 4.24, MID t 4.14, cost-coupled) |
| T2 | **Circuit / mania gate** | Minutes per day the price sits flat at the day's high (or low) with volume trickling in, on days the move is near a 2 / 5 / 10 / 20 % band | Multibagger mania exclusion (the daily version failed) and historical depth for the planned circuit flag ③, which otherwise starts only from forward quote snapshots |
| T3 | **Capacity** | Share of session minutes with no trade, and value traded per active minute | Sizing the multibagger book, whose edge sits in ₹0.5–1 Cr a day stocks |
| T4 | **Execution timing** | The U-shaped volume profile and same-half-hour return continuation (Heston, Korajczyk, Sadka: lasts at least 40 days, strongest in the first and last half-hour) | When in the day to place an order; an intraday signal, not a daily factor |

## One table feeds everything: `intraday_daily`

One row per stock per trading day, built in one DuckDB pass over the compacted months, regular session only (09:15–15:29 IST). Store **sums, not ratios**, so any window (5, 21, 63, 252 days) is an exact roll-up; the factor function divides.

| Column group | Columns |
|---|---|
| Counts | `n_bars`, `n_bars_5m`, `vol`, `value` (Σ close·volume) |
| Prices | `px_first` (09:15 close), `px_last` (15:29 close), `vwap_day_num` (Σ c·v), `vwap_close_num` / `vwap_close_den` (15:00–15:30) |
| Segment returns | `r_first30` (09:15→09:45), `r_mid` (09:45→15:00), `r_last30` (15:00→15:29) |
| Realized moments, 5-minute log returns | `rv` (Σr²), `rs_up`, `rs_down` (semivariances), `r3` (Σr³), `r4` (Σr⁴), `bpv` (bipower variation) |
| Flow | `bvc_buy_vol`, `abs_r_sum` (Σ\|r\|, for impact), `vol_last30`, `zero_minutes` |
| Circuit | `flat_at_high_min`, `flat_at_low_min` |
| Market (synthetic, one row per day) | Cap-weighted LARGE 5-minute returns for S5 |

Rough size: about 3.2 M stock-days × 25 columns, under 1 GB in SQLite, inside ADR 0072's budget. Overnight returns (S2, S3, F6) come from `stock_prices`, not from this table.

## Pre-registration (fix before the data is ready)

- **Formulas, signs, tiers and horizons are the tables above.** Changing one after seeing a result counts as a new hypothesis.
- **Hypothesis count:** 12 candidates × 3 tiers join the multiple-testing ledger (`tools/multiple_testing.py`, ADR 0043). The bar stays |t| ≥ 2.5 and the BY-FDR haircut.
- **Survivorship:** minute-bar candidates are judged on survivors and labelled so. S1–S3 and F6 are judged on the survivorship-free daily universe.
- **Costs:** a fast candidate passes only net of turnover at the real costs (16 / 18 / 31 bps), or at T1's per-stock costs once built.
- **Redundancy:** each survivor is checked for added value over the wired factors of its tier, and specifically against `mom_6m` (S1, S2), `max_lottery_21d` (F1), `delivery_anomaly_z` (F3) and `kyle_lambda` (T1).
- **Where fast winners go:** the SMALL tactical book (plan 0025) through walk-forward `fast_select`, never straight into live weights.

## Order of work

1. **Now, no minute data needed:** test S1, S2, S3, F6 on daily prices (the four "Daily" rows).
2. **When the backfill ends:** compaction to month files, then the `intraday_daily` builder plus its contract and a 3-stock smoke test, then the backfill of the table.
3. **Tools first:** T1 cost model, then T2 circuit gate (both pay off whatever the factor results).
4. **Factors:** F1 + F7 together, then F2, F3, F4, S5, S4, F5 last.
5. **Registration per factor:** the usual touchpoints (one compute function in `pit`, one `factors.FACTORS` entry as LIBRARY, `PIT_COLUMNS`, lineage), then `reconstruct_pit`, `backtest_pit`, multiple testing, promotion review.

## Sources

- Amaya, Christoffersen, Jacobs, Vasquez, "Does realized skewness predict the cross-section of equity returns?", JFE 118 (2015) — [CREATES working paper](https://repec.econ.au.dk/repec/creates/rp/11/rp11_44.pdf)
- Lou, Polk, Skouras, "A tug of war: overnight versus intraday expected returns", JFE 134 (2019) — [LSE](https://eprints.lse.ac.uk/87481/)
- Akbas, Boehmer, Jiang, Koch, "Overnight returns, daytime reversals, and future stock returns", JFE 145 (2022) — [summary](https://www.cxoadvisory.com/calendar-effects/tug-of-war-risk-and-future-stock-returns/); G7 replication — [IDEAS](https://ideas.repec.org/a/eee/pacfin/v74y2022ics0927538x22001044.html)
- Barardehi, Bogousslavsky, Muravyev, "What drives momentum and reversal? Evidence from day and night signals" (working paper) — [Illinois](https://experts.illinois.edu/en/publications/what-drives-momentum-and-reversal-evidence-from-day-and-night-sig/)
- Bogousslavsky, "The cross-section of intraday and overnight returns", JFE 141 (2021) — [IDEAS](https://ideas.repec.org/a/eee/jfinec/v141y2021i1p172-194.html); Baltussen, Da, Soebhag, "End-of-day reversal" (draft) — [PDF](https://www3.nd.edu/~zda/EOD.pdf)
- Heston, Korajczyk, Sadka, "Intraday patterns in the cross-section of stock returns", JF 65 (2010) — [arXiv](https://ar5iv.arxiv.org/html/1005.3535)
- Bollerslev, Patton, Quaedvlieg, "Realized semibetas", JFE (2022); Bollerslev, Li, Patton, Quaedvlieg, "Realized semicovariances", Econometrica (2020) — [Duke](https://econ.duke.edu/publications/realized-semicovariances)
- Jiang, Yao, "Stock price jumps and cross-sectional return predictability", JFQA 48 (2013) — [IDEAS](https://ideas.repec.org/a/cup/jfinqa/v48y2013i05p1519-1544_00.html)
- India: no NSE cross-sectional study of overnight or intraday-split returns was found; intraday overreaction on NSE — [Tripathi & Aggarwal, IJFM](https://publishingindia.com/archive/ijfm/prior-return-effect-in-indian-stock-market-an-intra-day-analysis)
