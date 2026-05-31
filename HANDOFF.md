# HANDOFF
Updated: 2026-05-31 | Branch: master (3 unpushed) | HEAD (pre-commit): `feat(fno): IV factors derived in-house from bhavcopy (§3.2.2 IV half, 8/8)`

## Left off
Shipped **6 of the 9 §3.2.3 microstructure factors** — the daily-derivable ones, off `stock_prices` OHLCV, no Kite. [signals/microstructure.py](signals/microstructure.py): 3 clean (`intraday_range_compression`=ATR5/ATR20, `closing_strength_1m`, `opening_gap_freq_1m`) + 3 proxies (`vwap_deviation_5d`=close-vs-typical-price since `traded_value` is ~17% NULL incl. all recent; `bidask_spread_proxy`=Corwin-Schultz; `kyle_lambda`=Amihud illiquidity). `prev_close` self-computed as lag(close), turnover=close×volume. ~99% coverage (NULLs are legit: <22d-history IPOs + circuit-frozen `high==low` untraded names). Fully wired (PIT helper `pit_microstructure` + 6 cols + BACKTEST_SIGNALS group "Microstructure" + SIGNAL_COLUMN_MAP + 6 FACTOR_LINEAGE, drift clean); monthly cadence → reconstructed over the **deep 39-month panel** (149 dates, 2022-08→2026-05) and backtested on years of price history.

**Backtest (39 monthly periods):**
- **`kyle_lambda` LARGE t=+4.24 KEEP + MID t=+4.14 KEEP** (CIs [2.33,6.86]/[2.11,6.97] strictly >0), SMALL t=+1.65 WEAK. The **Amihud illiquidity premium** — illiquid → higher forward returns. Strongest, most robust factor in the whole F&O/micro batch (39 periods).
- Other 5 DROP: `opening_gap_freq` MID t=1.31, `bidask_spread_proxy` MID t=1.30 (weak hints); `closing_strength`/`vwap_deviation`/`range_compression` no signal.

All 6 on the bench (`FACTOR_LIBRARY`); none wired. 0 CRITICAL, health green.

## Pick up here
1. **Promotion review of the 2 KEEP candidates** — `kyle_lambda` (LARGE+MID) + `iv_skew_25d` (MID, from the prior commit). Both earned it. For each: `tools/walk_forward.py` OOS + `tools/factor_correlation.py`. **`kyle_lambda` caveats**: (a) trading-cost-coupled — the illiquidity premium is literally compensation for the spread you'd pay, so net-of-cost it may shrink; (b) likely colinear with size/adtv and may already be partly captured by the pick-eligibility gate (ADR 0021). Then a deliberate `SCREEN.weight_tiers` call (signal-weights.md — never mechanical).
2. **§3.2.5 event-time / PEAD (6 factors)** — feasible now, no blocked data; post-earnings drift is a robust anomaly → best shot at more KEEPs. `signals/pead.py` off `quarterly_income` + `stock_prices`.
3. **Phase E badges deploy** (`systemctl restart alpha-cockpit`) + **Kite activation** when creds land → unblocks the 3 held intraday §3.2.3 factors (`volume_clock_concentration`, `tick_imbalance_5d`, `intraday_momentum_persistence`).

## Watch out
- **`kyle_lambda` is a long-only-portfolio trap if wired naively** — buying the illiquidity premium means buying names you can't cheaply trade. Treat the t=4.24 as real *gross* alpha that needs a net-of-cost haircut before sizing.
- **3 IV/micro factors use raw (unadjusted) prices** crossing day boundaries (opening_gap, kyle, iv_realised_spread realised leg) → rare split-day noise, bounded by clips (same stance as sector_momentum). Not adjusted by design.
- The 6 micro cols + IV cols aren't in the DuckDB mirror until tonight's `duckdb_refresh`; backtest reads SQLite (fine).
- HEAD is still the IV commit; this session's microstructure work is uncommitted until the commit below.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — §3.2.2 done (8/8); §3.2.3 6/9 (3 on hold, Kite). State: 38/50 PIT-shipped; 2 promotion candidates banked (kyle_lambda, iv_skew_25d).
