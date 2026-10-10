# Playbooks: ideas from outside the model

Screens in the style of well-known investors, shown on the cockpit `/ideas` page (Screens, Avoid, Track record).
None feeds `daily_picks`. Rules are constants in `sleeves.py` (shared with `tools/playbook_backtest.py`, so the page
and the backtest test the same rule); the data layer is `cockpit/playbooks.py`. Every screen row shows the stock's rank
in its tier from `daily_picks`, so agreement and conflict with the model are visible.

Honest status (backtest 2026-10): every sleeve lost to its tier average after costs; the red-flag veto did not lag
(t 0.45, unproven). Treat all of it as a reason to look, never as a signal.

## All approaches (moved from the retired "All approaches" tab; brainstorm of 2026-10-04)

| Approach | Who | Status | Where |
|---|---|---|---|
| Avoid list / checklist | Munger, Pabrai | live | Avoid tab; the flag count also shows beside every screen |
| Promoter and insider buying | Event-driven | live | Screens, Insider buying |
| Compounders, bought when cheap | Buffett, Munger | live | Screens, Compounders (quality rule, then price against the stock's own history); the strict toggle is the multibagger gates |
| Cloning superinvestors | Pabrai | partial | Screens, Superinvestors; changes fill in as earlier filings load, BSE-listed stocks only |
| Earnings + delivery breakouts | O'Neil, Minervini | live | Screens, Breakouts |
| Net-nets / deep value | Graham | live | Screens, Deep value, with red flags beside each name |
| Category rules | Lynch | live | chip on the stock page (`playbooks.stock_chips`) |
| Market-cycle readings | Marks, Druckenmiller | removed from Ideas | the regime lives on Today / Model; history was one cycle |
| Downside / upside card | Pabrai | partial | Deep value shows price against book and net cash; no per-stock card |
| Management says vs does | Fisher | partial | chip on the stock page; verdicts come from the `say_do` LLM kind (`output/say_do.py`) |
| Portfolios and backtest | n/a | live | Track record tab: each screen held monthly after costs, plus the forward record |
| Position sizing overlay | Thorp | not built | applies to the other engines, not an idea source |

## Multibagger (merged into Compounders)

The weekly multibagger funnel (`signals/multibagger.py`) is the strict version of Compounders: universe, then safety
gates (Beneish clean, pledge <= 10%, debt/equity <= 0.5), then quality hurdles (ROIC >= 18%, Piotroski F >= 6, 3-year
profit growth >= 20%, promoter >= 35%, market cap Rs 1-20k crore). Its HOLD / WATCH / REVIEW conviction is a holding
monitor reviewed every 3-6 months, not a stop-loss: most eventual 3x winners fall 30%+ on the way. The ordering has no
reliable edge, weakest in small-cap uptrends; the regime itself is read on Today, not recomputed here.
