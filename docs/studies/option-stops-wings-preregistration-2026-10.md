# Pre-registration: stops, wings and sizing for the option paper book (2026-10-21)

Written before any intraday result was seen (Amit 2026-10-21: "yes go ahead"). The study that follows reports against these rules; nothing here changes after the first run.

## Question
Can the live rule (plan 0022: sell ~0.05-delta NIFTY / SENSEX weekly call + put at the close 2 sessions before expiry, hold to expiry) cap its worst trade without giving up most of its return?

## Data
- Prices: Hugging Face `thetrademarkk/india-index-options-1m`, 1-minute, in `data/intraday/options_1m/` (NIFTY weeklies 2021-05-27 →, SENSEX 2023-08-11 →). Files flagged `suspect` in the manifest (VWAP match vs fno_bhav < 90 %) are excluded; their count is reported.
- Settlement, lot sizes, costs: `option_book` (one source with the paper book).
- 2019 – 2021-05 has no intraday data: those years stay on the daily-close study; the stress model (2015–2026) is re-run for the winner only.

## Entry (all variants)
- Same strikes as the paper book (0.05 delta from that day's chain), entered at the **15:20–15:29 average of 1-minute closes**, not the official 15:00–15:30 VWAP close. The baseline is reported both ways so the entry-price effect is visible on its own.
- Costs: `option_book.leg_cost` (1 % slippage per leg per side), four legs when wings are bought; a stop exit pays exit costs.

## Variants (fixed list)
1. **Baseline**: naked strangle, held to expiry.
2. **Premium stop** k × entry credit per leg, k ∈ {2, 3}: exit that leg at the first 1-minute close ≥ k × its entry price; if a session opens above the stop, exit at that open (gap-through).
3. **Index stop**: exit both legs at the first 1-minute index close within 0.5 % of either short strike (gap-through as above).
4. **Wings** w ∈ {2 %, 3 %, 4 %} of the index beyond each short strike (nearest listed strike at or beyond), bought at entry, held to expiry.
5. **Wings 3 % + premium stop 3×** (one combination only).

## Margin
- Naked: Kite quote where captured, else 12 % of notional (as the paper book).
- Hedged: max loss per lot (wing width − credit) + exposure margin 2 % of notional on the short legs. Checked against one live Kite basket quote on the next entry day; if off by > 25 %, re-scale and say so.

## Sizing (on ₹35 L)
- **A, by margin**: lots = floor(35 L / margin per lot).
- **B, by worst case**: lots = floor(3.5 L / max loss per lot) (10 % of capital), for wing variants; for unhedged variants max loss per lot = the 2021–26 worst observed loss per lot.
- NIFTY and SENSEX are reported separately and combined at half capital each (they overlap at the Tuesday close).

## Reported per variant × sizing
Trades, win rate, mean P&L per trade (₹ and % of margin), annual P&L on ₹35 L, Sharpe (weekly), worst trade (₹, % of capital), max drawdown, losing years, how often a stop or wing was triggered, and stop exits that would have expired worthless (whipsaw cost).

## Decision rule
A variant **replaces** the naked rule in the paper book only if, against the baseline on the same trades:
1. its worst trade (sizing B) is at most **half** the baseline's worst, and
2. it keeps at least **70 %** of the baseline's annual P&L (sizing B vs baseline at the same worst-case budget), and
3. its mean per trade stays > 0 in each of 2021–23 and 2024–26.

If several pass, the one with the higher annual P&L wins; ties go to the simpler variant. If none passes, the paper rule stays naked and the sizing is set by worst case (B). The winner is then run once through the 2015–2026 stress model (`tools/option_premium_backtest`), and its worst stress trade is reported before any real-money decision.
