# Research prompt 0017 — find more short-horizon quant strategies like the weekly strangle

Paste everything below the line into a new Claude Code session started in `/home/ubuntu/alpha-signal-v2`.

---

You are the research lead for a deep, evidence-first search for **new systematic short-horizon trading strategies** for one Indian retail account. Some edges have already been found and tested here, and many ideas have already failed; your job is to find what is genuinely left. Work like a careful quant: mechanism first, pre-registered tests, honest costs, out-of-sample proof, and plain-words reporting.

## 1. Who this is for and what "good" means

- **Owner:** Amit (CFA, FRM, ex-risk at Millennium / Goldman). He trades one Zerodha account, places orders through the Kite Connect API from this server (static IP registered), and must log in by hand once a day (2FA).
- **Capital:** about ₹35 L of margin today, as pledged shares plus a liquid fund, with roughly half cash-like. More can follow if something proves itself.
- **Benchmark already live:** a weekly short strangle on NIFTY and SENSEX: about 0.05 delta, entered 2 sessions before expiry, held to expiry, no stops. The two indices are rotated through one margin pot. Expect about 20 % a year after costs and tax, with rare gap weeks that can cost several months of profit.
- **What Amit wants:** 3–5 more strategies that:
  - each earn a good return after all costs and taxes;
  - are **not just more short volatility**, i.e. low correlation with the strangle, especially in its bad weeks;
  - can be run systematically from minute or daily data with Kite orders, with nobody watching the screen;
  - are simple enough to explain in a paragraph.
- **Scope:** "Intraday" is meant broadly: intraday, overnight, and holding periods up to about 2 weeks. Any instrument he can trade at Zerodha counts: cash equities, stock and index futures, index and stock options, ETFs, liquid funds / T-bills as carry, and currency or commodity derivatives if the data allows.

## 2. Read first (don't redo what's done)

- `CLAUDE.md` and `.claude/rules/*.md`: house rules (venv, read-only DB, worktrees, host door for any download, pre-registration habits, `tools/multiple_testing.py`).
- Option work:
  - `docs/studies/option-premium-feasibility-2026-10.md`;
  - `docs/studies/option-stops-wings-2026-10.md`;
  - `docs/studies/option-risk-filters-2026-10.md`;
  - `docs/plans/0022-option-premium-paper-book.md`;
  - `docs/plans/0029-options-live-automation.md`;
  - `options_live.py` (the live execution framework you can reuse).
- Intraday and short-horizon work already done:
  - `docs/research/0009-intraday-factor-menu.md`;
  - `docs/research/0010-minute-bar-uses/0010-minute-bar-uses.md`;
  - `docs/studies/day-night-factors-2026-10.md`;
  - `docs/studies/intraday-slow-factors-2026-10.md`.
- The broader research memory: `~/.claude/projects/-home-ubuntu-alpha-signal-v2/memory/MEMORY.md`, which links many verdicts (what failed and why).

**Known results:**
- Overnight momentum, tug-of-war, filing-timing drift and ASM up-flags failed.
- Momentum lives in the day half.
- `vol_of_vol_60d` and `rskew_60d` are strong cross-sectional SMALL-cap signals (monthly horizon).
- Stop-losses and wings on the strangle failed out of sample.
- No market factor predicted the strangle's worst weeks out of sample.

Don't re-test a dead idea unless you state what is materially different.

## 3. Data you have (verify coverage before relying on it)

- **Minute bars:**
  - 1,974 NSE stocks, 2015-02 → 2026-10, Kite, Parquet under `data/intraday/` (manifest table `intraday_files`);
  - a daily summary of them (`sources/intraday_daily.py`, `data/intraday/daily_1m/`).
- **Index options, 1-minute:** NIFTY weeklies 2021-05 → 2026-08 and SENSEX 2023-08 → 2026-07 (`data/intraday/options_1m/`, `sources/hf_options_1m.py`), plus 1-minute NIFTY and SENSEX index bars.
- **End-of-day F&O:** `fno_bhav`, NSE 2019 → and BSE 2024 →. Option `close` is the 15:00–15:30 VWAP, not a tradable last price. Settlement is from `underlying_price`. PCR and IV/skew tables come from it.
- **Daily prices:** `stock_prices` for the universe; survivorship-free legacy bhavcopy back to the 1990s (see memory `survivorship_universe_via_bhavcopy`); delivery %, bulk and block deals, insider trades, shareholding.
- **Market and macro:** India VIX, FII/DII cash and derivative positioning (positioning from 2022), `macro_history` (rates, FX, oil; no US VIX or S&P history yet), index history.
- **Events:** NSE announcements (live from 2026-10) and BSE announcements history (2018 → 2026-10-12); results dates; corporate actions; surveillance (ASM/GSM) flags; index inclusion/exclusion if you can source it point-in-time.
- **Live:** Kite quotes, depth, margins and orders via `options_live` / `sources/kite_quotes.py`. Read-only in this research: **never place an order**.

Missing data you may propose to add (cost it, don't buy it):
- intraday futures bars;
- stock-option intraday data;
- order-book depth history;
- US market history.

## 4. Candidate space (a starting list; add your own)

Rank by mechanism: **who pays you, and why do they keep paying?**

- **Calendar and flow:**
  - index rebalance and inclusion trades;
  - month-end and quarter-end flows;
  - F&O expiry-day effects in the cash market;
  - MF/ETF creation flows;
  - FII flow persistence;
  - dividend and record-date effects;
  - pre-holiday drift.
- **Intraday price patterns:**
  - opening-range breakout or fade;
  - the first half-hour predicting the last half-hour (intraday momentum, Gao-Han-Li-Zhou);
  - gap fade or follow-through by gap size and news;
  - VWAP reversion;
  - closing-auction imbalance (F&O stocks close by auction since 2026-08-03; see research 0010);
  - circuit-limit behaviour.
- **Event-driven, short hold:**
  - results-day reactions (announcement CAR exists as a factor);
  - block or bulk deals;
  - promoter buying;
  - pledge changes;
  - surveillance-list entry and exit;
  - corporate actions;
  - new listings in their first weeks.
- **Relative value and arbitrage:**
  - cash-futures basis and calendar spreads;
  - ETF NAV premium or discount;
  - pairs or cointegration within a sector;
  - index vs constituents (dispersion);
  - NSE vs BSE dual-listing gaps (check whether this is still feasible at retail speed).
- **Volatility, but different from the strangle:**
  - calendar spreads (weekly vs monthly);
  - term-structure carry;
  - long volatility before known events if under-priced;
  - stock-option skew;
  - a tail hedge that pays in the strangle's bad weeks and could fund itself. **This one is high-value even at a small loss**, because it raises the whole book's return per unit of drawdown.
- **Carry and cash:** the best use of idle margin (liquid fund, T-bills, cash-futures arbitrage funds) as a baseline every strategy must beat.

## 5. How to run it (pre-registered, honest)

1. **Survey, no backtests yet:** for each candidate, write one paragraph:
   - mechanism;
   - evidence (Indian studies first, then global; cite sources; use web search);
   - data you have;
   - expected edge size versus Indian costs;
   - capacity at ₹35 L–₹2 Cr;
   - how it could fail.

   Kill weak candidates here. Keep about 10–15.
2. **Pre-registration:** before any test result, write `docs/studies/short-horizon-preregistration-<date>.md` and commit it. Per candidate it fixes:
   - exact rules;
   - universe;
   - entry and exit times;
   - sizing;
   - cost model;
   - in-sample and out-of-sample split (walk-forward);
   - metrics;
   - a pass bar.

   Results are reported against it unchanged. Anything decided after seeing results is labelled exploratory.
3. **Costs, Indian and current (Zerodha, 2026):**
   - brokerage per order;
   - STT: intraday equity sell side; delivery both sides; futures and options at the post-Oct-2024 rates;
   - exchange and SEBI charges, stamp duty, GST;
   - slippage from the minute data: half-spread plus impact at your size, not a flat bp;
   - DP charges for delivery;
   - tax treatment: intraday equity is speculative income, F&O is business income, delivery is STCG/LTCG.

   Show gross and net.
4. **Tests:**
   - Point-in-time data only: no future bars, no survivorship (use the delisted-inclusive universe where it matters).
   - Fills at prices you could actually get: the next bar's open or a VWAP window, never the bar that triggered the signal.
   - Walk-forward or a held-out period.
   - Regime split: 2020 crash, 2021–22, 2023–26.
   - The multiple-testing haircut over everything tried (`tools/multiple_testing.py`).
   - Report:
     - annual return on capital used;
     - Sharpe;
     - max drawdown and worst day or week;
     - hit rate;
     - trades a year;
     - capacity (where impact eats half the edge);
     - **correlation with the strangle, overall and in the strangle's worst 10 weeks.**
5. **Portfolio view:** for the survivors, show the combined book with the strangle, at ₹35 L and at ₹1 Cr: return, drawdown and worst week.

## 6. Deliverables

- **The study:** `docs/studies/short-horizon-strategies-<date>.md` in plain words. Define every term. The verdict comes in the first lines.
  - One card per tested strategy:
    - hypothesis and mechanism;
    - rules;
    - data;
    - results table (gross and net, both windows);
    - capacity;
    - correlation with the strangle;
    - verdict: **PROMOTE TO PAPER**, **WATCH**, or **DROP**.
  - A ranked shortlist, and a list of untested ideas with what data would unlock them.
- **Code:** `tools/<strategy>_study.py` per strategy, reproducible and read-only, with small tests for the point-in-time join and the fill logic.
- **A plan doc:** for each PROMOTE TO PAPER strategy, a proposed plan (next free number in `docs/plans/`). It covers:
  - the paper book first (as plan 0022 did);
  - then how `options_live`-style automation would run it;
  - the decisions Amit has to make.

  Don't wire anything into live trading, cron or the database.

## 7. Rules of engagement

- Work in a git worktree, with `ALPHA_DB=/home/ubuntu/alpha-signal-v2/data/alpha_signal.db`, read-only (`file:...?mode=ro`). Never copy the 22 GB DB. No long DB writers.
- Any download goes through the host door (`sources/_http` + `hosts.HOSTS`), is treated as untrusted data, and is staged and validated before use.
- **No orders, no Kite writes, no cron or crontab edits, no change to live weights or picks.**
- Parallel subagents are fine for independent candidates (keep it under about 8). Each one gets the pre-registration section for its candidate and reports numbers only from its own runs.
- Every number in the report comes from a run you can point to. If the evidence is weak, say so; a clear "nothing passed" is a valid result.
- Commit with explicit paths (never `git add .` / `-A`, never `--amend`).
- Add a bullet to `docs/plans/0000-checklist.md` when you start.
- End with a short summary for Amit: what passed, what it would add to the book in rupees at ₹35 L, the risks, and the next decision he needs to make.
