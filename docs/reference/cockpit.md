# ALPHA SIGNAL COCKPIT — Design Blueprint

> Bloomberg-inspired stock intelligence dashboard for Indian retail investors.
> FastAPI + Jinja2 + Tailwind CSS + Alpine.js + Chart.js
> Dark theme, 7 screens, SQLite backend (236 MB, 33 tables)

---

## Tech Stack (Implemented)

| Layer | Technology | Why |
|-------|-----------|-----|
| **Backend** | FastAPI | Async, fast, auto-docs at /docs |
| **Templates** | Jinja2 | Server-rendered, no JS build step |
| **Styling** | Tailwind CSS CDN + custom CSS vars | Utility-first + dark theme tokens |
| **Interactivity** | Alpine.js 3.x | Lightweight reactivity for tabs, tooltips, toggles |
| **Charts** | Chart.js 4 | Responsive, animated, multiple chart types |
| **Data** | SQLite (WAL mode) via `db.read_sql()` | Single file, concurrent reads, no ORM |
| **Fonts** | Plus Jakarta Sans + JetBrains Mono | Display + monospace numbers |

**Deployment:** `uvicorn cockpit.app:app --host 0.0.0.0 --port 3000 --reload` on Oracle Cloud VM.

---

## Color System

```css
--bg-primary:       #0a0a0f       /* near-black canvas */
--bg-card:          #12121a       /* elevated card surfaces */
--bg-card-hover:    #1a1a28       /* interactive hover */
--border:           #1e1e2e       /* subtle separation */
--border-accent:    #2a2a3e       /* visible borders */

--text-primary:     #e8e8ed       /* main text (not pure white) */
--text-secondary:   #8888a0       /* labels, captions */
--text-muted:       #555570       /* timestamps, metadata */

--green:            #22c55e       /* opportunity, bullish */
--amber:            #f59e0b       /* watch, caution */
--red:              #ef4444       /* risk, bearish */
--blue:             #3b82f6       /* informational, neutral */
--accent:           #8b5cf6       /* purple — system/regime status */
```

**Rules:** Green/red = financial direction only. Every color must answer "what does this mean?" Cards with actions get 4px left-border accent.

---

## Screen Architecture (7 Screens)

### Navigation: Left rail (desktop) / Bottom tabs (mobile)

| Icon | Screen | URL | Purpose |
|------|--------|-----|---------|
| Brief | Morning Brief | `/` | Landing page — regime, changes, top picks |
| Signals | Signals | `/signals` | What fired today, by signal type |
| Actions | Action Queue | `/actions` | Buy/Watch/Exit recommendations |
| Explorer | Explorer | `/explorer` | Heat map + table of all stocks |
| Detail | Stock Detail | `/explorer/{sid}` | **Complete investment briefing** (6 tabs) |
| Portfolio | Portfolio | `/portfolio` | Model portfolio with analytics |
| Sectors | Sectors | `/sectors` | Sector rotation + macro |
| System | System | `/system` | Pipeline health, data freshness |

---

## Stock Detail Page — The Most Important Screen

### Design: 6-Tab Layout (Alpine.js)

```
[Overview] [Financials] [Ownership] [Consensus] [Forensic] [Price & Technicals]
```

#### Header (always visible, above tabs)
- Ticker: 36px, 800 weight
- Price: 36px monospace, with date
- Cap tier badge, action badge (BUY/AVOID), conviction badge
- 52W range inline bar (visual position indicator)
- Price metrics bar: 1M/3M/6M/1Y returns + RSI

#### Tab 1: Overview
- AI Dossier card (thesis, bull/bear, target/stop)
- Conviction score (0-100 with gradient bar)
- Signal cards — each with: name, description, progress bar, sub-component grid, tooltip
- Analyst consensus summary
- News & Sentiment headlines
- Regulatory events for sector

#### Tab 2: Financials
- 12-metric grid (3x4): Market Cap, P/E, EY, D/E, ROE, EBITDA Margin, PAT Margin, Book Value, FCF Yield, Revenue Growth, Current Ratio, Piotroski F
- Each metric card: value + sector average comparison + tooltip
- Quarterly results table (10 quarters): Revenue, PAT, EBITDA, EPS, margins, YoY%
- Revenue + PAT bar chart (Chart.js)
- Annual balance sheet summary (5 years)

#### Tab 3: Ownership
- Shareholding stacked area chart (6 quarters: Promoter/FII/MF/DII)
- QoQ change arrows per category
- Pledge % warning
- Insider trades table (10 trades, enhanced)
- Insider buy/sell monthly timeline chart
- Bulk deals table

#### Tab 4: Consensus
- Price target range bar (low → current → target → high)
- Forecast revision chart (PT/EPS/Revenue trends from forecast_history)
- Analyst breakdown: count, buy %, EPS growth, revenue growth
- Forward P/E from forward_eps

#### Tab 5: Forensic
- Piotroski 9-factor grid (3x3): each factor pass/fail with description
- Beneish M-Score card with zone explanation
- Altman Z-Score card with zone explanation
- Accruals quality breakdown (CF accruals, BS accruals, persistence)

#### Tab 6: Price & Technicals
- Multi-timeframe price chart (1M/3M/6M/1Y/3Y selector)
- Volume overlay on secondary Y-axis
- Delivery % trend line (90 days)
- 52W high/low annotation lines
- Momentum: 6M/12M returns, RSI value

### Tooltip System
- 20px circular button (not 10px icon)
- Alpine.js popover: hover AND click activated
- 280px styled card with description text
- Every metric and signal has a tooltip explaining what it is, why it matters

### Data Sources Per Tab

| Tab | Tables Used | API Functions |
|-----|------------|---------------|
| Overview | daily_picks, daily_snapshots, all signal tables, news_articles, regulatory_signals | get_stock_detail, get_dossier, get_stock_news, get_regulatory_for_sector |
| Financials | quarterly_income, annual_balance_sheet, annual_cash_flow | get_quarterly_financials, get_annual_financials, get_sector_comparison |
| Ownership | shareholding, insider_trades, insider_signals, bulk_deals | get_shareholding_history, get_insider_activity, get_insider_timeline, get_bulk_deals |
| Consensus | analyst_consensus, forecast_history | get_analyst_consensus, get_forecast_trend |
| Forensic | piotroski_scores, forensic_scores, accruals_scores | get_stock_detail (already loads sub-factors) |
| Price | stock_prices | get_price_series_extended |

---

## Other Screens (Summary)

### Morning Brief (`/`)
- Regime banner (VIX, allocation, date)
- What Changed cards (from diff engine)
- Earnings This Week
- Top 5 picks per tier with price → target, returns, thesis snippet

### Signals (`/signals`)
- Tab-filtered by signal type (Promoter, Consensus, Forensic, Insider, Smart Money, Regulatory)
- Each card: stock, signal explanation in English, strength bar

### Action Queue (`/actions`)
- Three sections: Consider Buying (green) / Watch (amber) / Consider Exiting (red)
- Each card enriched with price, target, upside%, RSI, thesis

### Explorer (`/explorer`)
- Heat map view (color-coded score grid per tier)
- Table view toggle (rank, ticker, sector, score, price, 1M%)
- Search bar with type-ahead

### Portfolio (`/portfolio`)
- Analytics card: expected return, score premium, sector allocation bars
- Allocation donut (Large/Mid/Small with VIX)
- Model portfolio tables with Price, Target, Upside%, 1M% columns

### Sectors (`/sectors`)
- Sector cards with avg score, stock count, macro signal
- Full macro_detail text, regulatory event count

### System (`/system`)
- Pipeline log (last 7 days, pass/fail per step)
- Data freshness badges per table

---

## Key Files

| File | Purpose |
|------|---------|
| `cockpit/api.py` | ALL data queries — no ORM, just `read_sql()` |
| `cockpit/app.py` | FastAPI routes + Jinja2 template rendering |
| `cockpit/templates/base.html` | Layout shell (nav, search, mobile tabs) |
| `cockpit/templates/stock_detail.html` | Stock detail (6 tabs, ~950 lines) |
| `cockpit/templates/morning_brief.html` | Landing page |
| `cockpit/templates/portfolio.html` | Model portfolio + analytics |
| `cockpit/templates/signals.html` | Signal feed |
| `cockpit/templates/action_queue.html` | Buy/Watch/Exit queue |
| `cockpit/templates/explorer.html` | Heat map + table |
| `cockpit/templates/sectors.html` | Sector overview |
| `cockpit/templates/system.html` | Pipeline health |
| `cockpit/static/cockpit.css` | Dark theme + component styles |
| `cockpit/static/cockpit.js` | Conviction bar animation + chart factories |

---

## Verification (5-Second Test)

| Screen | Question answered in 5 seconds |
|--------|-------------------------------|
| Stock Detail — Overview | Should I buy? What's the conviction? What do signals say? |
| Stock Detail — Financials | Is revenue growing? What are margins? How leveraged? |
| Stock Detail — Ownership | Who owns this? Are promoters buying or selling? |
| Stock Detail — Consensus | What do analysts think? Revising up or down? |
| Stock Detail — Forensic | Earnings manipulation risk? Bankruptcy risk? |
| Stock Detail — Price | What's the trend? Is volume confirming? |
| Morning Brief | What happened? What are today's best opportunities? |
| Action Queue | What trades to consider with entry/exit levels? |
| Portfolio | Expected return? Sector concentration? |
| Signals | What signals fired and why should I care? |
| Sectors | Which sectors have policy tailwinds? |
