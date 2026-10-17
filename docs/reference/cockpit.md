# Cockpit

Bloomberg-inspired ops + intelligence dashboard. FastAPI + Jinja2 + Tailwind CDN + Alpine.js + Chart.js. Dark theme, 7 screens, served from `uvicorn cockpit.app:app --port 3000` on the Oracle VM.

## Stack

| Layer | Choice |
|---|---|
| Backend | FastAPI |
| Templates | Jinja2 (server-rendered, no JS build) |
| Style | Tailwind CDN + CSS vars |
| Interactivity | Alpine.js 3.x |
| Charts | Chart.js 4 |
| Data | SQLite WAL via `db.read_sql()`, no ORM |
| Fonts | Plus Jakarta Sans + JetBrains Mono |

## Color tokens

```
--bg-primary: #0a0a0f   --bg-card: #12121a   --bg-card-hover: #1a1a28
--border: #1e1e2e       --border-accent: #2a2a3e
--text-primary: #e8e8ed --text-secondary: #8888a0 --text-muted: #555570
--green: #22c55e (bull) --amber: #f59e0b (watch) --red: #ef4444 (bear)
--blue: #3b82f6 (info)  --accent: #8b5cf6 (regime)
```

Green/red = financial direction only. Cards with actions get 4px left-border accent.

## Screens

| URL | Purpose |
|---|---|
| `/` | Morning Brief — regime, changes, top picks per tier |
| `/signals` | What fired today, filtered by signal type |
| `/actions` | Buy / Watch / Exit queue with thesis |
| `/explorer` | Heat map + table of all stocks |
| `/explorer/{sid}` | **Stock Detail — 6 tabs (the main screen)** |
| `/portfolio` | Model portfolio + analytics |
| `/ideas` | Ideas, three tabs: Screens (chips: insider buying, compounders with a strict multibagger-gates toggle, superinvestors, breakouts, deep value; each with its backtest result line and the model rank in tier), Avoid (veto unproven), Track record (sleeve backtest + forward record). `/playbooks` and `/multibagger` redirect here. Data: `cockpit/playbooks.py`; Lynch category / say-vs-do / playbook chips for the stock page come from `playbooks.stock_chips(sid)`; the retired tabs and roadmap are in [playbooks.md](playbooks.md) |
| `/sectors?industry=X` | Industry deep-dive (drill from 38 industries; sectors are visual grouping only — [ADR 0013](../decisions/0013-industry-not-sector-as-drill-unit.md)). Four tabs: **Understand** (the twelve-card explainer — tea-stall version, kitchen, who buys, rupee to profit, clock, wiring, bottlenecks, rulebook, five forces, tell a friend, glossary; [ADR 0078](../decisions/0078-industry-explainer-no-numbers-in-prose.md)), **Numbers** (results-call cheat sheet with live industry medians from `fundamentals_screener` + the story's segments and KPIs), **Players** (true share incl. private, listed market-cap share), **Picks & signals** (top picks, avoid, lead indicators + the call, industry dials with macro readings, regulatory events filtered to the industry). The explainer lives in `sector_metadata.payload.explainer`, written per industry by a Claude Code session via `tools/sector_explainer.py --print-prompt` / `--ingest`; the computed parts are `cockpit/explainer.py` |
| `/macro` | Macro (plan 0028, [ADR 0079](../decisions/0079-macro-page-from-dated-desk-archive.md)): Start, the India framework (8 chapters), the global and geopolitical framework (9), synthesis (3), today's brief, the archive and the Deeper shelf, with an **As of** filter that opens the whole page as it read on any archived date. `/macro` frames `/macro/frame?as_of=` (its own stylesheet `static/macro.css` and router `static/macro.js`); `cockpit/macro.page(as_of)` assembles every part from `desk_snapshots`. The brief is computed daily by `run.sh macro_desk` (05:45 UTC, `output/macro_desk.py`); then `macro_desk write` runs the desk kinds `macro_note` (daily written note, no figures) and `macro_hotspots` (weekly) on the subscription worker; the RBI stance (`macro_desk rbi COLOUR "TEXT"`) is set by hand, and `macro_desk note FILE.json` saves a hand-written note; chapters and the shelf are versioned rows refreshed monthly. Phones: the frame is sized to the visible height in script (Android's 100vh ignores the address bar) |
| `/system` | Pipeline health, freshness, rerun buttons |
| `/flow` | Pipeline DAG view with rerun ([ADR 0008](../decisions/0008-cockpit-write-surface.md)) |

## News (plan 0021)

`/news` is written top-down by an editor (`sources/news_editor.py`), not a feed: Today (the newest daily edition, 3 items with source links), the world in 7 fixed themes (compact cards), On the radar and Sectors to watch (the weekly edition: early signs, sectors the news helps / to be careful with), and a collapsed sector-flow table. `/news/theme/{theme_id}` is the theme page (note, what could happen next, stocks, timeline, sources; retired themes render, unknown id is 404). `/news/all` is the old searchable feed. Data: `api.get_news_today()`, `get_news_themes()`, `get_news_theme(id)`, `get_news_week()`, `get_sector_radar()`. Stocks on a theme are counted from its headlines; the LLM names none. Shared bits in `_news_theme.html`. Each block has an empty state.

## Stock Detail (6 tabs)

Header (always visible): ticker, price, date, cap tier + action + conviction badges, 52W range bar, 1M/3M/6M/1Y returns + RSI.

| Tab | Cards | Source tables |
|---|---|---|
| **Overview** | AI dossier (thesis/bull/bear/target/stop), conviction 0-100, signal cards with progress bars + tooltips, analyst summary, news + sentiment, sector regulatory events | daily_picks, daily_snapshots, all signal tables, news_articles, regulatory_signals |
| **Financials** | 12-metric grid (Mcap, P/E, EY, D/E, ROE, EBITDA margin, PAT margin, BV, FCF Yield, Rev growth, CR, Piotroski F) with sector-avg comparison; quarterly results (10q); Revenue+PAT bar chart; 5-year balance sheet | quarterly_income, annual_balance_sheet, annual_cash_flow |
| **Ownership** | Shareholding stacked area (6q: Promoter/FII/MF/DII) + QoQ arrows; pledge warning; insider trades + monthly timeline; bulk deals | shareholding, insider_trades, insider_signals, bulk_deals |
| **Consensus** | PT range bar (low→current→target→high); forecast revision chart; analyst breakdown (count, buy%, EPS+rev growth); forward P/E | analyst_consensus (yfinance daily), analyst_consensus_snapshots (monthly history), forecast_history (Tickertape year-end) |
| **Forensic** | Piotroski 9-factor grid (pass/fail per factor); Beneish M-Score zone card; Altman Z zone card; accruals quality (CF, BS, persistence) | piotroski_scores, forensic_scores, accruals_scores |
| **Price & Tech** | Multi-timeframe price chart (1M/3M/6M/1Y/3Y) + volume + 90d delivery%; 52W annotations; momentum 6M/12M + RSI | stock_prices |

Tooltip system: 20px button (not 10px icon), Alpine popover (hover + click), 280px card. Every metric and signal has one.

## Files

| File | Purpose |
|---|---|
| `cockpit/api.py` | All data queries via `read_sql()` |
| `cockpit/app.py` | Routes + Jinja rendering + rerun endpoint |
| `cockpit/templates/base.html` | Layout shell |
| `cockpit/templates/stock_detail.html` | 6-tab detail (~950 lines) |
| `cockpit/templates/{morning_brief,signals,action_queue,explorer,portfolio,sectors,system,flow}.html` | One per screen |
| `cockpit/templates/_components.html` | Macros (slide_row, etc.) |
| `cockpit/static/cockpit.css` | Theme + components |
| `cockpit/static/cockpit.js` | Conviction bar, chart factories |

## 5-second test (per screen, the question it must answer immediately)

| Screen | Question |
|---|---|
| Detail / Overview | Should I buy? What's the conviction? |
| Detail / Financials | Growing? Margins? Leverage? |
| Detail / Ownership | Who owns it? Promoters buying or selling? |
| Detail / Consensus | What do analysts think? Revising which way? |
| Detail / Forensic | Manipulation risk? Bankruptcy risk? |
| Detail / Price | Trend? Volume confirming? |
| Morning Brief | What happened? Today's best opportunities? |
| Action Queue | What trades, with entry/exit levels? |
| Sectors | Which industries have policy tailwinds? |
| System | Did the pipeline run? Anything stale? |
