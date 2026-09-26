# Research 0004 — Regime Overlay for Exposure Scaling (plan 0011 WS7.2 · decision D9)

**Status:** research complete · **Date:** 2026-07-11 · **Type:** deep-research dive #4 of the roadmap-to-90 queue
**Gates:** plan [0011](../plans/0011-roadmap-to-90.md) WS7.2 · decision [ADR 0051](../decisions/0051-roadmap-to-90-decisions-d1-d12.md) D9
**Motivating evidence + cautionary tale:** [ADR 0039](../decisions/0039-multibagger-funnel-regime-dominated.md) (regime-dominance finding) · [ADR 0041](../decisions/0041-sector-tilt-backtest-gated-small-only.md) (macro ensemble already built)
**Source evidence:** [return-prediction-2026-07-05-report.md](../studies/return-prediction-2026-07-05-report.md) (E[1Y] ≈ 90% market beta → regime is the only honest bear-year lever)

> **The pre-committed bar (D9, non-negotiable):** adopt the overlay ONLY IF a walk-forward test on
> survivorship-free index history shows **max-drawdown reduction ≥10pp for a CAGR give-up ≤2pp**.
> If it fails, **publish the negative result and drop it.** This research is designed to *disprove*
> the overlay, not to flatter it.

The overlay scales the **invested fraction** of the whole book ({1.0, 0.8, 0.6}) on a market-regime
signal. It does **not** pick stocks and does **not** touch cross-sectional factor weights. It is the
one lever the honest-return audit identified for bear-year outcomes: with E[1Y] ~90% market beta, a
flat/down tape cannot be factor-ed around — you can only own less of it.

---

## 1. Available inputs — what regime data is already in-house

Inspected `data/alpha_signal.db` directly (2026-07-11). Depth is the binding constraint, not availability.

| Candidate signal | In-house? | Table / series | History depth | Cadence | PIT-safety |
|---|---|---|---|---|---|
| **Nifty 50 trend** (200DMA / 12-1 TSMOM) | ✅ YES | `macro_history` id=`nifty50` | **2015-06-25 → today, 2,719 daily rows (~11y)** | daily | ✅ trailing SMA/return, no look-ahead |
| Nifty 50 in `nse_index_history` | ⚠️ shallow | `nse_index_history` `NIFTY 50` | only **2023-06-01→** (770 rows) | daily | ✅ (use `macro_history` nifty50 for depth) |
| **Smallcap trend / breadth proxy** | ✅ YES | `nse_index_history` `NIFTY SMALLCAP 250` | **2016-01-01 → today (2,554 rows, ~10.5y)** | daily | ✅ trailing |
| Midcap 150 / Nifty 500 | ⚠️ shallow | `nse_index_history` | 2023-06→ only | daily | ✅ |
| **India VIX** (risk-off gauge) | ✅ YES | `vix_history` (2,706) / `macro_history` id=`india_vix` | **2015-06-25 → today (~11y)** | daily | ✅ trailing level/percentile |
| **USDINR** (risk / carry) | ✅ YES | `macro_history` id=`usdinr` | **2015-06-25 → today (2,880)** | daily | ✅ |
| **Credit spread** (`credit_excess_idx`) | ⚠️ depth-limited | `macro_history` id=`credit_excess_idx` / `aaa_psu_etf` | **2019-12-31 → today (1,616, 6.5y)** | daily | ✅ — but no free India credit index pre-2019-12 (Bharat-Bond inception; see memory `credit_beta_benched_signal_not_data`) |
| 10y G-sec proxy | ✅ YES | `macro_history` id=`gsec10_etf` | 2016-06 → today | daily | ✅ |
| India money rate (cash yield) | ✅ YES | `macro_history` id=`india_money_rate` | 2022-01→ (monthly) | monthly | ✅ (for the "parked in cash earns X" leg) |
| **FII net cash flow** (trend) | ❌ **effectively absent** | `fii_dii_cash_flow` | **only 47 days (2026-04-30→)** | daily | n/a — no usable history |
| FII/DII F&O positioning | ⚠️ partial | `fii_dii_positioning` | 2022-01 → today (1,114 days) | daily | ✅ but positioning ≠ cash flow |
| **Breadth: % stocks > 200DMA** | ⚠️ derivable, not stored | compute from `stock_prices` | `stock_prices` = **2020-01→ only (2,447 sids)**, survivor-biased | daily | ✅ if intersected with `historical_universe` |
| Advance-decline / new-highs-lows | ❌ absent | — | — | — | not harvested |

**What already exists as regime infrastructure (reuse, don't rebuild):**

- **`scoring/regime.py` + `regime_state` table + `config.VIX_REGIMES`** — a live VIX-only classifier
  (`CALM` <13 / `NORMAL` 13-25 / `CAUTION` 25-35 / `CRISIS` >35) with **3-day hysteresis**, already
  emitting **tier** allocations (alloc_large/mid/small). Current row: `CALM`, VIX 12.25. This is the
  natural spine to extend — but note it tilts *across tiers*, it does **not** scale invested fraction.
  The overlay adds a new, orthogonal output (invested %); it should reuse the VIX thresholds and the
  hysteresis machinery verbatim.
- **`macro_score` ensemble (ADR 0041, `signals/macro.py` → `macro_sector_signals`)** — despite the
  name this is a **sector-fundamental** score (IIP / core-sector / GST / credit-growth → per-sector
  0-100), monthly cadence, sector-level. It is **not a market trend/breadth/risk regime signal** and
  has limited reuse for exposure scaling. Do not mistake it for the "macro ensemble" this overlay
  needs — the reusable macro-regime asset is the VIX classifier, not this.

**Net:** the trend + risk legs (Nifty 50, smallcap, India VIX, USDINR) are all in-house at ~11y depth
and PIT-safe. The credit leg is usable but depth-limited to 6.5y (misses 2008/2011/2013 stress).
**FII cash-flow trend is not a candidate** — 47 days of history rules it out of any walk-forward.
Breadth is derivable but only 2020+ and survivor-biased. **The honest signal set is trend + VIX
(+ a cheap smallcap-relative breadth proxy back to 2016), not the full four-input ensemble.**

---

## 2. India-specific evidence — does exposure-scaling on regime work here?

**Trend / time-series-momentum on Indian indices — the premium replicates, with a fatal caveat:**

- TSMOM on Indian equities is real and significant: a BSE 1996-2020 study documents persistent
  absolute-momentum profits (~0.7-1.4%/mo, robust to FF risk factors), optimal **12-month formation**,
  1-3m holding (Jegadeesh-Titman lineage; multiple India replications). Cross-sectional and
  time-series momentum both survive in India.
- **The caveat that matters for us:** the *risk-managed TSMOM* literature (Emerald JEFAS 2022,
  emerging-economy study) finds Indian absolute-momentum strategies suffer **severe crashes precisely
  during recovery phases** — the April-May 2009 rebound cost a naive TSMOM **-56% in two months**;
  it explicitly attributes this to "sluggish information diffusion causing trading-signal delays."
  Translation: **a trend overlay whipsaws worst at V-shaped bottoms** (2009, and our own 2020 COVID V).
  That is the single biggest threat to the D9 bar and it is *stronger* in India than in the US.
- 200DMA/Faber-style timing (buy>SMA, exit<SMA) is well-documented to **reduce drawdown and volatility
  vs buy-and-hold with roughly comparable or slightly-lower CAGR** on the S&P 500 — but the published
  edge is a US result, and the same source-set notes it "faces many whipsaws and is unlikely to beat
  buy-and-hold in rising markets without recessions." **Flag as transfer risk:** most 200DMA-timing
  evidence is US-import; the India-specific version has fewer, sharper, more V-shaped drawdowns
  (2008, 2020) that are the *hardest* case for trend timing.

**Our own evidence (ADR 0039 — the motivating fact AND the trap):** Indian small/mid multibagger
capture is **regime-dominated** — the same screen's edge flips sign across the 2018-21 quality-led
bear and the 2022-26 junk rally; base-rate of a ≥3x flips 2.6% → 13.4%. This *proves* regime
determines bear-year outcomes (the motivation). But it also proves a **naive/complex regime signal
overfits** — the two known regimes calibrate to opposite extremes, so any threshold fitted on one
window is wrong on the other. **The design lesson: pre-commit thresholds from theory, never fit them
on the test window.**

**India-specific tax cost of switching (the drag US studies omit — decided in plan WS1.3):**
De-risking moves book → cash, which **realizes capital gains**. Statutory (post-2024 India):
**STCG 20%** if held <1yr, **LTCG 12.5%** if ≥1yr, plus **STT** and brokerage each round-trip.
A monthly trend overlay that flips ~4-6x/yr realizes gains on the moved slice each time, at the
*20% short-term* rate — a real, India-specific, several-hundred-bps drag that the walk-forward
**must** charge. This is the mechanism most likely to blow the ≤2pp CAGR budget.

---

## 3. Proposed signal — a low-parameter, pre-committed ensemble

Design principle (from ADR 0039): **few inputs, zero fitted parameters, thresholds from theory.**
Every parameter below is a canonical constant, not an optimized value.

**Inputs (2 orthogonal legs + 1 confirmation — all in-house, all ≥2016 depth):**

1. **TREND (spine):** Nifty 50 monthly close vs its **12-month simple moving average** (≈200 trading
   days). *Why 12m:* it is THE canonical trend/TSMOM window (Faber 2007; Moskowitz-Ooi-Pedersen
   2012; the India TSMOM studies' optimal formation) — not chosen by us. *Why monthly evaluation:*
   ties the switch cadence to the book's monthly rebalance (WS1.1) so the overlay adds **no extra
   turnover events**, and monthly sampling is the standard whipsaw-suppressant vs daily 200DMA.
2. **RISK (confirmation):** India VIX **regime state**, reusing `config.VIX_REGIMES` cutoffs verbatim
   (CALM/NORMAL vs CAUTION/CRISIS at 25). *Why reuse:* these thresholds already exist and were not
   fitted for this test → no new free parameter.
3. **BREADTH proxy (confirmation):** NIFTY SMALLCAP 250 / NIFTY 50 **ratio vs its own 12m SMA**
   (risk-on when smallcaps lead). *Why this proxy:* true % >200DMA breadth needs `stock_prices`
   (2020+, survivor-biased); the smallcap-relative-trend proxy is in-house back to **2016**, is the
   direct expression of the ADR-0039 regime axis (junk-rally vs quality-bear), and adds no new
   parameter (reuses the 12m window).

**Regime → invested fraction (deliberately shallow, 3-state):**

| Regime | Rule (evaluated monthly, at rebalance) | Invested fraction |
|---|---|---|
| **Risk-ON** | Trend UP (Nifty > 12m SMA) **and** VIX not in CAUTION/CRISIS | **1.00** |
| **Neutral** | exactly one of {trend, VIX, breadth} risk-off | **0.80** |
| **Risk-OFF** | Trend DOWN (Nifty < 12m SMA) **and** (VIX ≥25 **or** breadth risk-off) | **0.60** |

Plus the existing **hysteresis** (require the new state to persist — reuse `VIX_HYSTERESIS_DAYS`
logic, lifted to monthly confirmation) so a one-month head-fake does not trigger a switch.

*Why {1.0, 0.8, 0.6} and never 0%:* a long-only book that can only de-risk to 60% keeps most of its
beta (so it still participates in the V-recovery it would otherwise whipsaw on), caps the CAGR
give-up mechanically, and — critically — **never fully realizes gains**, holding the switching tax
down. Going to cash (0%) is market-timing; it maximizes whipsaw and the STCG drag and is exactly the
overfit ADR 0039 warns against. Shallow-and-rare beats deep-and-frequent for the D9 bar.

**Parameter count: effectively zero free parameters** — 12m window (canonical), VIX cutoffs (reused),
{1.0/0.8/0.6} (a-priori conservative choice, sensitivity-tested not fitted). This is the whole point.

---

## 4. Walk-forward test design — built as WS7.2, judged against D9

**Data window (survivorship-free INDEX history — the easy part):** indices are survivorship-free by
construction (they reconstitute), so the stock-level survivorship problem does not apply. But the
in-house `nifty50` starts 2015-06, giving only ~1 clean index-level bear (2020 COVID V) + shallow
2018/2022 dips — **too few bear regimes** (the thin-bear problem credit_beta hit). **Recommended
build step:** extend the Nifty 50 (price + TRI) back to **1999** via a free source — niftyindices.com
TRI CSV or yfinance `^NSEI` (2007+) spliced onto the in-house series — to capture **2008 GFC, 2011,
2013 taper, 2015-16, 2018-19, 2020, 2022**: ~6-7 independent drawdowns. This is read-only harvest of
one index series, not a factor build. Cross-check the splice on the 2015-2026 overlap against
in-house `nifty50`.

**Protocol (no in-sample peeking — the ADR-0039 discipline):**
1. Thresholds are **pre-committed** (§3) — nothing is optimized on the test window, so the walk-forward
   is genuinely out-of-sample by construction. The only "fit" is the a-priori exposure map, which
   gets a **sensitivity band** ({1.0/0.8/0.6} vs {1.0/0.7/0.5} vs {1.0/0.9/0.75}) reported, not tuned.
2. Each month t: compute regime from data **≤ t only** (trailing 12m SMA, trailing VIX). Apply the
   invested fraction to month t+1 index total return; the un-invested slice earns the in-house
   **`india_money_rate`** (cash yield), so parking is not free-lunch cash at 0%.
3. **Cost + tax model on the switch (mandatory):** on every *down*shift, the fraction moved to cash
   realizes the embedded gain on that slice → charge **STCG 20%** (holding <1yr — the overlay churns
   faster than a year) plus **STT + ~10-20bps** round-trip; *up*shift charges STT+brokerage on the
   re-entry. Track realized-gain basis per slice. Report switch count/yr — the tax is ∝ switch
   frequency, so this is where whipsaw shows up as rupees.
4. Compare against the **buy-and-hold baseline** (fraction ≡ 1.0, same tax treatment of the terminal
   position). Two metrics only:
   - **Max-drawdown reduction (pp)** = DD(baseline) − DD(overlay).
   - **CAGR give-up (pp)** = CAGR(baseline) − CAGR(overlay), **net of switching cost + tax**.
5. **D9 verdict:** PASS iff DD-reduction ≥ 10pp **and** CAGR give-up ≤ 2pp, robust across the exposure
   sensitivity band and across at least the 1999-2026 and 2007-2026 sub-windows. Otherwise
   **publish the negative result in an ADR and drop** (D9 is explicit about this).

**Tables / tools it would touch (as a WS7.2 build):**
- **Reads:** `macro_history` (nifty50, india_vix, usdinr, india_money_rate), `nse_index_history`
  (NIFTY SMALLCAP 250), + the harvested 1999-2015 Nifty extension.
- **New tool:** `tools/regime_overlay_sim.py` — the walk-forward engine (mirrors `tools/backtest_pit.py`
  cost-model conventions and `tools/rebalance_sim.py` net-of-cost accounting; add the STCG/LTCG/STT
  tax layer from WS1.3).
- **Producer extension:** `scoring/regime.py` gains an `invested_fraction` output alongside the tier
  allocations; `regime_state` gains a column (production wiring only *after* D9 passes).
- **Applied at:** book level in `rebalance_sim` / `portfolio_nav` — scales gross exposure, leaves the
  cross-sectional ranker untouched.
- Writes **nothing** to production during research (read-only, per this dive's constraints).

---

## 5. Honest prior — will it clear the −10pp-DD-for-≤2pp-CAGR bar?

**Best guess: it FAILS the bar as a monthly 3-input ensemble — I put ~30-40% on a clear PASS, and the
pass is fragile.** A shallow, *trend-only, quarterly-evaluated* variant has the best (roughly
coin-flip) shot; anything richer or faster almost certainly fails on cost.

**Single most likely failure mode — whipsaw tax × thin bear sample (the exact ADR-0039 / credit_beta
trap):**
1. **Whipsaw + STCG-20% eats the CAGR budget.** India's drawdowns are sharp V's (2009, 2020). A
   monthly trend overlay sells into the bottom and rebuys higher, and each de-risk realizes gains at
   the 20% short-term rate — the Emerald study's own finding that Indian TSM "performs worst during
   recovery phases" is precisely this. The CAGR give-up blows past 2pp not from missed upside alone
   but from taxed round-trips. This is the tax drag US 200DMA studies never model.
2. **The DD-reduction number is high-variance because the bear sample is thin.** Whether the overlay
   clears −10pp DD is dominated by whether it dodged 2008 and 2020 — two events. With ~6 independent
   drawdowns even in the 1999-2026 extension, the DD-reduction estimate has wide error bars, so a
   headline "−12pp" could be one lucky crash-dodge, not a robust property (same failure that killed
   credit_beta: no signal, just too few stress regimes to tell).

**Why I don't put it near zero:** trend-timing genuinely reduces DD in the raw (untaxed) series, and
the shallow 0.6 floor + never-cash design + monthly-cadence-aligned-to-rebalance are specifically
built to suppress the two failure channels. If the tax/whipsaw drag comes in under ~2pp, the DD
reduction from dodging even *part* of 2008/2020 could clear +10pp.

**Recommendation for WS7.2:** build `regime_overlay_sim.py`, run it honestly with the tax layer and
the 1999-extended index, and **let the number decide** — the design's whole value is that D9 pre-commits
to publishing the negative result. My prior is a lean-fail, so the most valuable outcome is likely a
clean, cited negative that closes the "should we time the market?" question permanently, exactly as
ADR 0039 closed the naive-regime-gate question for multibaggers.

---

## Appendix — reuse ledger (what this dive did NOT re-derive)
- VIX regime classifier, thresholds, hysteresis: reused from `scoring/regime.py` + `config.VIX_REGIMES`.
- Macro ensemble: inspected `signals/macro.py`/ADR 0041, judged **not** a market-regime signal → not reused as such.
- credit_beta: honored as a dead stock-level factor (memory `credit_beta_benched_signal_not_data`); the
  index-level `credit_excess_idx` is a *different* object and remains a candidate regime leg — but
  depth-limited to 2019-12, so demoted to optional confirmation, not core.
- FII flow: ruled out on 47-day depth, not re-probed.
- Regime-dominance motivation + no-peeking discipline: taken wholesale from ADR 0039.
